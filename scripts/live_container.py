#!/usr/bin/env python3
"""live_container.py — the container-based live harness: ONE paid live arm in a fresh, disposable
Linux container beside a credential broker in its own, both destroyed after (PR #668;
docs/guides/live-harness.md is the operator's guide).

  build   build the harness image from scripts/live_container.Dockerfile: the base pinned by
          digest, git, and Claude Code pinned to one version by its official installer, installed
          as the non-root user every arm runs as (the only step that downloads anything)
  run     run one arm in a fresh container of that image and destroy it:
              wip_curve     scripts/wip_curve.py ARGS
              ablation      scripts/ablation.py ARGS
              hint_replay   scripts/hint_replay.py ARGS
              trajectories  scripts/eval.py run --suite trajectories ARGS
              first_run     runtime/scripts/first_run.py ARGS
          ARGS follow `--`; inside the container the repository is /repo (read-only) and the
          results directory is /results, the working directory, where every output must go: an
          arm's output flag (OUTPUTS) must name a path under it, and an arm whose ledger defaults
          to a temp dir must name one (REQUIRED)

Why a container. Process containment (runtime/scripts/containment.py) finds every process of a
paid call by the OF_CALL_ID marker in its environment. On macOS no sweep can see every
descendant: an Apple system binary's environment is hidden from `ps -E`. So every paid live path
refuses on a plain host, and lifts only inside a container this launcher started (containment.
harness_problem): a container marker, the launcher's attestation whose nonce is the container's
own hostname, and the strong probe passing, which it does on Linux. Destroying the container is
the final backstop for anything in-process containment misses, a process that clears its own
environment included.

The token never enters the arm's container (Codex at 47e0616eac: its uid runs the agents and the
tests they write, so any of them could read a token mounted there). It is mounted read-only
(SECRET) into a second container that runs scripts/live_broker.py alone, the credential broker.
The arm's container joins the broker's network namespace and nothing else; its `claude`
(scripts/live_container_bin/claude, first on PATH) sends every model call to the broker, which
puts the token in place of a placeholder and refuses any call that would pass --cap-usd. The
broker's ledger is written beside the receipt, out of the arm's reach, and summarised in it.

What the arm's container gets: the image's non-root user, --rm, a pids/memory/CPU limit, no
capability, no-new-privileges, no privileged flag, no host namespace, and the broker's network
alone; a clean export of the checkout's HEAD, read-only (the launcher refuses a dirty tree, and
nothing the container writes reaches the checkout, its .git or its ignored files); one read-write
results directory, so the arm's own ledger and evidence outlive the container; and the
attestation, read-only. The broker's container gets the same user, hardening and export, limits
of its own, the token file read-only, and its ledger directory. One launch at a time holds LOCK,
from the leftover check to the receipt. A wall-clock limit ends it: the launcher kills and removes
both containers, then verifies with `docker ps -a --filter label=LABEL=<nonce>` that neither
exists. A teardown step that fails or times out is recorded, never raised, so the receipt,
written outside every mount, is always written. The container's output is saved through a
redactor to a 0600 file: no byte of the token reaches the disk.

The limit, honestly: this guards against accidents on the host, never against an operator who
deliberately fakes a container (as root: a /.dockerenv, an attestation, a hostname). The
attestation proves which launch a container came from to the receipt, not to an adversary.

Exit: the arm's exit status, once both containers are verified destroyed · 2 usage or a refused
start (whatever was created is destroyed first) · 3 a container could not be verified destroyed
(fail closed) · 124 the wall-clock limit ended it (verified destroyed) · 128+N on signal N
(verified destroyed).
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import importlib.util
import json
import os
import posixpath
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT  # the checkout whose HEAD runs (a Python-level seam for the launcher's own tests)
DOCKERFILE = ROOT / "scripts" / "live_container.Dockerfile"
CLAUDE_CODE = "2.1.304"
IMAGE = f"open-fleet-live:claude-{CLAUDE_CODE}"
LABEL = "org.open-fleet.live-harness"  # every harness container carries it: its value is the nonce
ROLE_LABEL = "org.open-fleet.role"  # broker or arm
DOCKERFILE_LABEL = "org.open-fleet.dockerfile-sha256"
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"  # never in any environment the launcher sets: the broker holds the token
TOKEN_FILE = "~/of-live/oauth-token"
RECEIPTS = "~/of-live/receipts"
LOCK = "~/of-live/live-harness.lock"  # held by one launch from its leftover check to its receipt
USER = "10001:10001"  # the image's `runner`, never root
REPO_IN, RESULTS_IN, LEDGER_IN = "/repo", "/results", "/ledger"
SECRET = "/run/secrets/claude_token"  # the token: a read-only file mount in the broker's container alone
BROKER_SCRIPT, BROKER_PORT = "scripts/live_broker.py", 8787
BROKER_LIMITS = {"pids": 64, "memory": "512m", "cpus": "1"}
WRAPPER_DIR = "scripts/live_container_bin"  # its `claude` sends every model call to the broker
# The container's whole PATH: the wrapper first, and never ~/.local/bin, where the raw binary lies.
CONTAINER_PATH = f"{REPO_IN}/{WRAPPER_DIR}:/usr/local/bin:/usr/bin:/bin"
ARMS = {
    "wip_curve": ("scripts/wip_curve.py",),
    "ablation": ("scripts/ablation.py",),
    "hint_replay": ("scripts/hint_replay.py",),
    "trajectories": ("scripts/eval.py", "run", "--suite", "trajectories"),
    "first_run": ("runtime/scripts/first_run.py",),
}
# Each arm's flags that name where its ledger and evidence go: each must be under /results, and an
# arm whose ledger defaults to a temp dir must name one (Codex at 47e0616eac: destroying the
# container erased it).
OUTPUTS = {"wip_curve": ("--results", "--out"), "ablation": ("--out",), "hint_replay": ("--out",),
           "trajectories": ("--out",), "first_run": ("--workdir",)}
REQUIRED = {"ablation": "--out", "hint_replay": "--out", "trajectories": "--out", "first_run": "--workdir"}
LIMITS = {"pids": 4096, "memory": "8g", "cpus": "4"}
BACKSTOP_S = 120  # the in-container `timeout`, past the launcher's limit: a dead launcher still ends it
DESTROY_WAIT_S = 30
BROKER_READY_S = 60  # the arm starts only once the broker answers /health inside its own container
TEARDOWN_TIMEOUT_S = 60  # each docker call of a teardown
REDACTED = b"[REDACTED]"
RECEIPT_SCHEMA = "open-fleet.live-container-receipt/2"
EXIT_USAGE, EXIT_NOT_DESTROYED, EXIT_TIMED_OUT = 2, 3, 124


def _load(name, path):
    """A runtime module by path, writing no bytecode beside it."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    prior, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = prior
    return mod


# The attestation contract (its path, schema and hostname) is containment.py's: one definition,
# read by the check inside the container and written here. Git runs hardened (#629).
containment = _load("live_container_containment", ROOT / "runtime" / "scripts" / "containment.py")
gitexec = _load("live_container_gitexec", ROOT / "runtime" / "scripts" / "gitexec.py")


class Refused(Exception):
    """A refused start: exit 2, after whatever was created is destroyed."""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def docker_env():
    """The launcher's environment for a docker client, without a token it may have inherited."""
    return {k: v for k, v in os.environ.items() if k != TOKEN_ENV}


def docker(*args, timeout=120):
    """`docker ARGS` (whatever `docker` PATH names), captured; never raises on a nonzero exit."""
    exe = shutil.which("docker")
    if not exe:
        raise Refused("no `docker` on PATH (OrbStack or Docker Engine)")
    return subprocess.run([exe, *args], env=docker_env(), stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, errors="replace", timeout=timeout)


def git(repo, *args, timeout=300):
    proc = subprocess.run(gitexec.argv("-C", str(repo), *args), env=gitexec.env(), stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise Refused(f"git {' '.join(args[:3])} in {repo}: {proc.stderr.strip()[:300]}")
    return proc.stdout


def read_token(path):
    """The subscription token from the operator's file: a regular file (never a link) only its
    owner can read. Every refusal names the file, never a byte of it."""
    path = Path(path).expanduser()
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as err:
        raise Refused(f"the token file {path} cannot be opened ({err.strerror}); write the token from "
                      "`claude setup-token` there, mode 0600") from None
    with os.fdopen(fd, "rb") as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise Refused(f"the token file {path} is not a regular file")
        if st.st_mode & 0o077:
            raise Refused(f"the token file {path} is readable by others (mode {st.st_mode & 0o777:o}): chmod 600")
        raw = fh.read()
    try:
        token = raw.decode("ascii").strip()
    except UnicodeDecodeError:
        raise Refused(f"the token file {path} is not one ASCII line") from None
    if not token or any(c.isspace() for c in token):
        raise Refused(f"the token file {path} must hold the token alone, on one line")
    return token


def pinned_commit(repo):
    """The checkout's HEAD, or Refused when its tree is dirty: what runs is what was committed."""
    dirty = git(repo, "status", "--porcelain", "--untracked-files=all").splitlines()
    if dirty:
        shown = ", ".join(line[3:] for line in dirty[:5]) + (" …" if len(dirty) > 5 else "")
        raise Refused(f"the checkout {repo} is dirty ({shown}): commit or remove it, so the container runs a commit")
    return git(repo, "rev-parse", "--verify", "HEAD^{commit}").strip()


def export_checkout(repo, commit, dest):
    """A self-contained, shallow clone of `commit` at `dest`: git works inside the container (a
    worktree's .git names a host path), and no host .git, untracked or ignored file is mounted."""
    git(dest.parent, "init", "-q", str(dest))
    git(dest, "fetch", "-q", "--depth=1", "--no-tags", f"file://{Path(repo).resolve()}", commit)
    git(dest, "-c", "advice.detachedHead=false", "checkout", "-q", "--detach", "FETCH_HEAD")
    head = git(dest, "rev-parse", "HEAD").strip()
    if head != commit:
        raise Refused(f"the export is at {head}, not the pinned {commit}")


def image_facts(image):
    """The image's id, digests and labels; Refused when it is not built."""
    proc = docker("image", "inspect", "--format", "{{json .}}", image)
    if proc.returncode != 0:
        raise Refused(f"no image {image}: build it first (live_container.py build): {proc.stderr.strip()[:200]}")
    doc = json.loads(proc.stdout)
    labels = (doc.get("Config") or {}).get("Labels") or {}
    committed = sha256_file(DOCKERFILE) if DOCKERFILE.is_file() else None
    return {"ref": image, "id": doc.get("Id"), "repo_digests": doc.get("RepoDigests") or [], "labels": labels,
            "dockerfile_sha256": labels.get(DOCKERFILE_LABEL), "committed_dockerfile_sha256": committed,
            "from_committed_dockerfile": bool(committed) and labels.get(DOCKERFILE_LABEL) == committed}


def leftovers():
    """Every harness container that still exists: one arm at a time, and a leftover is looked at."""
    proc = docker("ps", "-a", "--filter", f"label={LABEL}", "--format", "{{.ID}}")
    if proc.returncode != 0:
        raise Refused(f"docker ps failed: {proc.stderr.strip()[:200]}")
    return proc.stdout.split()


def output_problem(arm, arm_args):
    """Why the arm's arguments would leave its ledger or evidence outside /results, or None. An
    abbreviation argparse would accept (`--ou`) counts as the flag it abbreviates."""
    flags, named, i = OUTPUTS.get(arm, ()), set(), 0
    while i < len(arm_args):
        opt, eq, value = arm_args[i].partition("=")
        flag = next((f for f in flags if opt.startswith("--") and len(opt) > 2 and f.startswith(opt)), None)
        if flag:
            if not eq:
                if i + 1 >= len(arm_args):
                    return f"{opt} names no path"
                i, value = i + 1, arm_args[i + 1]
            path = posixpath.normpath(posixpath.join(RESULTS_IN, value))
            if path != RESULTS_IN and not path.startswith(RESULTS_IN + "/"):
                return f"{flag} {value} is outside {RESULTS_IN}: destroying the container would erase it"
            named.add(flag)
        i += 1
    need = REQUIRED.get(arm)
    if need and need not in named:
        return (f"the {arm} arm needs {need} under {RESULTS_IN}: its default is a temp dir that destroying the "
                "container erases")
    return None


def hardened(nonce, role, limits):
    """What both containers share: the non-root user, --rm, limits, no capability, no privilege."""
    mem = str(limits["memory"])
    return ["create", "--rm", "--init", "--user", USER, "--label", f"{LABEL}={nonce}", "--label", f"{ROLE_LABEL}={role}",
            "--pids-limit", str(limits["pids"]), "--memory", mem, "--memory-swap", mem, "--cpus", str(limits["cpus"]),
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--log-driver", "none"]


def broker_argv(image_id, nonce, export, token_file, ledger_dir, cap_usd, timeout):
    """`docker create` for the broker: the one container the token is mounted in, read-only. It
    carries the harness hostname, which the arm's container inherits with its network namespace."""
    return [*hardened(nonce, "broker", BROKER_LIMITS), "--hostname", containment.HARNESS_HOSTNAME + nonce,
            "--env", "PATH=/usr/local/bin:/usr/bin:/bin",
            "--mount", f"type=bind,src={export},dst={REPO_IN},readonly",
            "--mount", f"type=bind,src={token_file},dst={SECRET},readonly",
            "--mount", f"type=bind,src={ledger_dir},dst={LEDGER_IN}",
            "--workdir", LEDGER_IN, image_id,
            "timeout", "--kill-after=30", str(int(timeout) + 2 * BACKSTOP_S),
            "python3", "-I", f"{REPO_IN}/{BROKER_SCRIPT}", "--token-file", SECRET,
            "--ledger", f"{LEDGER_IN}/spend.jsonl", "--cap-usd", repr(float(cap_usd)), "--port", str(BROKER_PORT)]


def arm_argv(image_id, nonce, arm, broker_id, cmd, export, results, attestation, limits):
    """`docker create` for the arm: the broker's network namespace and nothing else of it, and no
    credential: its environment is the image's and PATH alone. No privileged flag, no host
    namespace, no capability, no device."""
    return [*hardened(nonce, "arm", limits), "--label", f"org.open-fleet.arm={arm}",
            "--network", f"container:{broker_id}",
            "--env", f"PATH={CONTAINER_PATH}",
            "--mount", f"type=bind,src={export},dst={REPO_IN},readonly",
            "--mount", f"type=bind,src={results},dst={RESULTS_IN}",
            "--mount", f"type=bind,src={attestation},dst={containment.ATTESTATION},readonly",
            "--workdir", RESULTS_IN, image_id, *cmd]


def await_broker(broker_id, ledger_dir):
    """Return once the broker answers /health inside its own container, or Refused: the arm never
    starts beside a broker that could not open the token or its ledger (`docker exec`, the
    container's own user, no credential on its command line)."""
    probe = ["exec", broker_id, "python3", "-I", "-c",
             f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{BROKER_PORT}/health', timeout=2)"]
    deadline = time.monotonic() + BROKER_READY_S
    while True:
        try:
            if docker(*probe, timeout=30).returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        if time.monotonic() > deadline:
            raise Refused(f"the broker never answered within {BROKER_READY_S:g} s. On Docker Engine on Linux, uid "
                          f"10001 must be able to read the token file and write {ledger_dir}")
        time.sleep(0.5)


def destroy(ids, nonce):
    """Kill and remove every container of this launch, then verify that none exists (`docker ps -a
    --filter label=LABEL=<nonce>`, which also finds one whose id the launcher never learned). A
    docker call that fails or times out is recorded and the rest still run: this never raises, so
    the receipt is always written (Codex and Greptile at 47e0616eac)."""
    errors = []

    def attempt(*args):
        try:
            return docker(*args, timeout=TEARDOWN_TIMEOUT_S)
        except (subprocess.TimeoutExpired, OSError, Refused) as err:
            errors.append(f"docker {' '.join(args[:2])}: {type(err).__name__}")
            return None
    for cid in reversed(ids):  # the arm first: the broker settles what it left in flight, then goes
        attempt("kill", cid)
    for cid in reversed(ids):
        attempt("rm", "-f", cid)
    check = ["ps", "-a", "--filter", f"label={LABEL}={nonce}", "--format", "{{.ID}}"]
    deadline = time.monotonic() + DESTROY_WAIT_S
    while True:
        proc = attempt(*check)
        listed = proc.stdout.split() if proc is not None and proc.returncode == 0 else None
        if listed == []:
            return {"verified": True, "check": ["docker", *check], "output": "", "errors": errors}
        if time.monotonic() > deadline:
            output = (proc.stdout + proc.stderr).strip()[:300] if proc is not None else "; ".join(errors)[-300:]
            return {"verified": False, "check": ["docker", *check], "output": output, "errors": errors}
        for cid in dict.fromkeys([*ids, *(listed or [])]):  # --rm removes asynchronously; ask again
            attempt("rm", "-f", cid)
        time.sleep(0.5)


class Redactor:
    """Writes a byte stream with every occurrence of `secret` replaced, holding back only the
    longest tail that could begin it, so a secret split across two reads is caught too."""

    def __init__(self, fh, secret):
        self.fh, self.secret, self.tail, self.count = fh, secret, b"", 0

    def write(self, data):
        buf = self.tail + data
        self.count += buf.count(self.secret)
        buf = buf.replace(self.secret, REDACTED)
        keep = next((k for k in range(min(len(self.secret) - 1, len(buf)), 0, -1) if buf.endswith(self.secret[:k])), 0)
        self.fh.write(buf[:len(buf) - keep])
        self.tail = buf[len(buf) - keep:]

    def close(self):
        self.fh.write(self.tail)
        self.tail = b""
        self.fh.close()


def pump(stream, redactor):
    """Copy the container's output through the redactor until it ends."""
    while chunk := stream.read1(65536):
        redactor.write(chunk)


@contextlib.contextmanager
def launch_lock(path):
    """Hold the launch lock, or Refused: two launchers can never both pass the leftover check
    (Greptile at 47e0616eac). The lock ends with this process, however it ends."""
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Refused(f"another launch holds {path}: one arm runs at a time") from None
        yield
    finally:
        os.close(fd)


def spend(ledger):
    """The broker's ledger, summarised for the receipt: what the arm spent, by the broker's count."""
    try:
        lines = Path(ledger).read_text(encoding="utf-8").splitlines()
    except OSError as err:
        return {"ledger": str(ledger), "read": False, "error": type(err).__name__}
    events = []
    for line in lines:
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    starts = {e.get("call"): e for e in events if e.get("event") == "start"}
    settles = {e.get("call"): e for e in events if e.get("event") == "settle"}
    opened = next((e for e in events if e.get("event") == "open"), {})
    unsettled = [c for c in starts if c not in settles]
    return {"ledger": str(ledger), "read": True, "cap_usd": opened.get("cap_usd"), "calls": len(starts),
            "refused": sum(1 for e in events if e.get("event") == "refuse"),
            "settled_usd": round(sum(e.get("cost_usd") or 0 for e in settles.values()), 6),
            "unsettled_calls": len(unsettled),
            "unsettled_reserved_usd": round(sum(starts[c].get("reserved_usd") or 0 for c in unsettled), 6)}


def write_new(path, data, mode=0o600):
    """A new file, never through a link or over an existing one."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def inside(path, other):
    return path == other or other in path.parents


def run(args):
    """Check the request, then launch under the lock. Returns the exit code."""
    if args.arm not in ARMS:
        raise Refused(f"unknown arm {args.arm!r}: one of {', '.join(ARMS)}")
    if args.timeout <= 0:
        raise Refused("--timeout must be a positive number of seconds")
    if not args.cap_usd > 0:
        raise Refused("--cap-usd must be a positive number of dollars: the broker refuses every call past it")
    if why := output_problem(args.arm, args.arm_args):
        raise Refused(why)
    results = Path(args.results).expanduser().resolve()
    receipts = Path(args.receipts).expanduser().resolve()
    token_file = Path(args.token_file).expanduser().absolute()
    repo = Path(REPO).resolve()
    for what, path in (("--results", results), ("--receipts", receipts)):
        if inside(path, repo) or inside(repo, path):
            raise Refused(f"{what} {path} overlaps the checkout {repo}")
    for what, path in (("--results", results), ("--receipts", receipts), ("--token-file", token_file)):
        if "," in str(path):
            raise Refused(f"{what} {path} holds a comma, which a docker --mount cannot carry")
    if inside(receipts, results) or inside(results, receipts):
        raise Refused(f"--receipts {receipts} overlaps --results {results}: the container writes to the "
                      "results, and the receipt must be out of its reach")
    for what, mount in (("--results", results), ("the checkout", repo)):  # the arm sees both (Codex at 8585b35789)
        if inside(Path(os.path.realpath(token_file)), mount) or inside(token_file, mount):
            raise Refused(f"--token-file {token_file} is inside {what} {mount}, which the arm's container mounts: "
                          "keep the token outside both")
    token = read_token(token_file)  # its value only to check the file and to redact the output
    commit = pinned_commit(repo)
    image = image_facts(args.image)
    with launch_lock(args.lock):
        if leftovers():
            raise Refused(f"a harness container already exists (docker ps -a --filter label={LABEL}): one arm runs "
                          "at a time; inspect it, then `docker rm -f` it")
        return launch(args, results, receipts, token_file, token, repo, commit, image)


def launch(args, results, receipts, token_file, token, repo, commit, image):
    """Create the broker's container and the arm's, run the arm, destroy both, write the receipt
    (always, once anything was created). Returns the exit code."""
    nonce = secrets.token_hex(16)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = receipts / f"{stamp}-{args.arm}-{nonce[:8]}"
    log_path, ledger_dir = base.with_suffix(".log"), base.with_suffix(".broker")
    staging = Path(tempfile.mkdtemp(prefix="of-live-"))
    limits = {"pids": args.pids_limit, "memory": args.memory, "cpus": args.cpus}
    script, *prefix = ARMS[args.arm]
    cmd = ["timeout", "--kill-after=30", str(int(args.timeout) + BACKSTOP_S),
           "python3", f"{REPO_IN}/{script}", *prefix, *args.arm_args]
    receipt = {"schema": RECEIPT_SCHEMA, "arm": args.arm, "arm_args": args.arm_args, "argv": cmd,
               "commit": commit, "repo": str(repo), "image": image, "nonce": nonce,
               "hostname": containment.HARNESS_HOSTNAME + nonce,
               "token": {"file": str(token_file), "mounted_at": SECRET,
                         "passed": "a read-only file mount in the broker's container alone; the arm's container "
                                   "holds no credential"},
               "container": {"id": None, "user": USER, "limits": limits, "network": "the broker's namespace",
                             "mounts": {REPO_IN: "the export of the commit, read-only", RESULTS_IN: str(results),
                                        containment.ATTESTATION: "the attestation, read-only"}, "path": CONTAINER_PATH},
               "broker": {"id": None, "user": USER, "limits": BROKER_LIMITS, "port": BROKER_PORT,
                          "cap_usd": args.cap_usd, "spend": None,
                          "mounts": {REPO_IN: "the export of the commit, read-only", SECRET: "the token file, read-only",
                                     LEDGER_IN: str(ledger_dir)}},
               "wall_clock_limit_s": args.timeout, "started_at": None, "ended_at": None, "elapsed_s": None,
               "timed_out": False, "interrupted": None, "refused": None, "exit_status": None,
               "destroyed": {"verified": False, "check": None, "output": "no container was created", "errors": []},
               "log": str(log_path), "token_redactions": 0}
    ids, refused, redactor = [], None, None
    try:
        export = staging / "repo"
        export_checkout(repo, commit, export)
        for need in (script, f"{WRAPPER_DIR}/claude", BROKER_SCRIPT):
            if not (export / need).is_file():
                raise Refused(f"{need} is not in commit {commit[:12]}")
        attestation = staging / "attestation.json"
        doc = {"schema": containment.ATTESTATION_SCHEMA, "nonce": nonce, "commit": commit, "arm": args.arm,
               "image": image["id"], "created_at": now()}
        write_new(attestation, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode(), mode=0o644)
        results.mkdir(parents=True, exist_ok=True)
        receipts.mkdir(parents=True, exist_ok=True, mode=0o700)
        ledger_dir.mkdir(mode=0o700)
        for role in ("broker", "arm"):
            argv = (broker_argv(image["id"], nonce, export, token_file, ledger_dir, args.cap_usd, args.timeout)
                    if role == "broker" else
                    arm_argv(image["id"], nonce, args.arm, ids[0], cmd, export, results, attestation, limits))
            proc = docker(*argv)
            if proc.returncode != 0:
                raise Refused(f"docker create of the {role} failed: {proc.stderr.strip()[:300]}")
            ids.append(proc.stdout.strip().splitlines()[-1])
            receipt["broker" if role == "broker" else "container"]["id"] = ids[-1]
        proc = docker("start", ids[0])
        if proc.returncode != 0:
            raise Refused(f"docker start of the broker failed: {proc.stderr.strip()[:300]}")
        await_broker(ids[0], ledger_dir)
        receipt["started_at"], started = now(), time.monotonic()
        fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        redactor = Redactor(os.fdopen(fd, "wb"), token.encode())
        attach = subprocess.Popen([shutil.which("docker"), "start", "--attach", ids[1]], env=docker_env(),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        pumper = threading.Thread(target=pump, args=(attach.stdout, redactor), daemon=True)
        pumper.start()
        try:
            receipt["exit_status"] = attach.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            receipt["timed_out"] = True
        finally:
            receipt["ended_at"], receipt["elapsed_s"] = now(), round(time.monotonic() - started, 1)
            if attach.poll() is None:
                receipt["destroyed"] = destroy(ids, nonce)
                attach.kill()
                attach.wait()
            pumper.join(timeout=30)
            attach.stdout.close()
    except Refused as err:
        if not ids:
            raise
        receipt["refused"], refused = str(err), err
    except (KeyboardInterrupt, SystemExit) as err:
        receipt["interrupted"] = getattr(err, "code", None) or 128 + signal.SIGINT
        raise
    finally:
        if ids and not receipt["destroyed"]["verified"]:
            receipt["destroyed"] = destroy(ids, nonce)
        shutil.rmtree(staging, ignore_errors=True)
        if redactor is not None:
            with contextlib.suppress(OSError, ValueError):
                redactor.close()
            receipt["token_redactions"] = redactor.count
        if ids:
            receipt["broker"]["spend"] = spend(ledger_dir / "spend.jsonl")
            text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
            if token in text:  # never: nothing above holds it
                raise RuntimeError("the receipt would carry the token")
            write_new(base.with_suffix(".json"), text.encode())
            print(f"live_container: receipt {base.with_suffix('.json')}", file=sys.stderr)
    if not receipt["destroyed"]["verified"]:
        print(f"live_container: FAIL-CLOSED: launch {nonce}'s containers could not be verified destroyed: "
              f"{receipt['destroyed']['output']}", file=sys.stderr)
        return EXIT_NOT_DESTROYED
    if refused:
        raise refused
    if receipt["timed_out"]:
        return EXIT_TIMED_OUT
    code = receipt["exit_status"]
    return code if code >= 0 else 128 - code  # the attach client died of signal -code


def build(args):
    """docker build of the committed Dockerfile, from an empty context, labelled with its digest."""
    dockerfile = Path(args.dockerfile).resolve()
    if not dockerfile.is_file():
        raise Refused(f"no Dockerfile at {dockerfile}")
    with tempfile.TemporaryDirectory(prefix="of-live-build-") as ctx:
        context = Path(args.context).resolve() if args.context else Path(ctx)
        argv = ["build", "-f", str(dockerfile), "-t", args.image,
                "--label", f"{DOCKERFILE_LABEL}={sha256_file(dockerfile)}", str(context)]
        exe = shutil.which("docker")
        if not exe:
            raise Refused("no `docker` on PATH (OrbStack or Docker Engine)")
        return subprocess.run([exe, *argv], stdin=subprocess.DEVNULL).returncode


def parser():
    p = argparse.ArgumentParser(prog="live_container.py", description=__doc__.split("\n", 1)[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="exit: the arm's status · 2 refused · 3 not verified destroyed · 124 timed out")
    sub = p.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="build the harness image (downloads the base and Claude Code)")
    b.add_argument("--image", default=IMAGE)
    b.add_argument("--dockerfile", default=str(DOCKERFILE), help=argparse.SUPPRESS)
    b.add_argument("--context", default=None, help=argparse.SUPPRESS)
    r = sub.add_parser("run", help="run one arm in a fresh container, then destroy it")
    r.add_argument("--arm", required=True, choices=sorted(ARMS))
    r.add_argument("--results", required=True, help="the host results directory, /results inside")
    r.add_argument("--timeout", type=float, required=True, help="wall-clock limit, seconds")
    r.add_argument("--cap-usd", type=float, required=True, dest="cap_usd",
                   help="the spend cap the broker enforces on every model call: the arm's authorised cap")
    r.add_argument("--token-file", default=TOKEN_FILE, dest="token_file",
                   help=f"the subscription token, mode 0600 (default {TOKEN_FILE})")
    r.add_argument("--receipts", default=RECEIPTS, help=f"where the receipt goes (default {RECEIPTS})")
    r.add_argument("--image", default=IMAGE)
    r.add_argument("--lock", default=LOCK, help=argparse.SUPPRESS)
    r.add_argument("--pids-limit", type=int, default=LIMITS["pids"], dest="pids_limit")
    r.add_argument("--memory", default=LIMITS["memory"])
    r.add_argument("--cpus", default=LIMITS["cpus"])
    r.add_argument("arm_args", nargs=argparse.REMAINDER, help="-- then the arm's own arguments")
    return p


def _signalled(signum, _frame):
    raise SystemExit(128 + signum)


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == "run":
        args.arm_args = args.arm_args[1:] if args.arm_args[:1] == ["--"] else args.arm_args
    previous = {s: signal.signal(s, _signalled) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        return build(args) if args.command == "build" else run(args)
    except Refused as err:
        print(f"live_container: refused: {err}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:  # the containers are already destroyed and the receipt written
        return 128 + signal.SIGINT
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)


if __name__ == "__main__":
    sys.exit(main())
