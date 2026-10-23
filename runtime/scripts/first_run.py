#!/usr/bin/env python3
"""first_run.py — a reproducible first run of the POSIX route, inert or live (#596).

One review unit is driven through the PUBLIC wrappers an operator types, never the provider
classes underneath them:

  preflight  preflight.py --mission review-it --runtime posix --mode readonly
  create     task_ops.py create --spec <frozen spec>
  dispatch   spawn_worker.sh <task> new-child <title> <agent>   (OPEN_FLEET_RUNTIME=posix, setsid)
  guard      deny-hook.sh --verify-settings on the registration the provider installed
  delivery   the launch the provider recorded carries the spec nonce, and the worker echoes it
  result     worker_ops.py show/read + check_reply.py: the worker's exit and its report
  verify     verify.py --unit-class report-only on a SHA-bound manifest, run in a checkout the
             coordinator cuts from git at the evidence head (never the worker's own tree)
  release    worker_ops.py retain, then release; the evidence commit survives both

and the run ends in a SHA-bound verdict line, `FIRST_RUN=GO` or `FIRST_RUN=NO-GO step=<s>`.

ONE code path, two kinds of worker:

  --worker inert (default)  an inert stand-in answers to the harness name from a private bin
      directory first on PATH, behind tripwires for every other harness name. It reads the
      spec and the change file it names, and answers in the harness's own result shape. No model
      is called and nothing is spent. A GO here is a FIXTURE result: it proves the fleet's
      route, never the harness.
  --worker live             the operator's real harness on PATH does the review. The receipt
      is labelled `live-unreviewed`: it becomes certification evidence only once a maintainer
      binds it into docs/runs/ (runtime/providers/certification.json says which cells hold).

Profiles: `ro` (default; the review-it shape — the worker prints its report and has no tool to
send mail, so posix records its clean exit as `worker_died (exit=0)` and the coordinator commits
the report it read from the transcript) and `rw` (the worker commits the report itself and sends
`worker_done`; its HEAD is re-read from git, never taken from the claim).

The reviewed target is a two-commit repository the run synthesizes, or `--target <repo>`
(cloned into the sandbox, never modified) with `--base/--head`. Every artifact lives in one
sandbox directory: the state store, the clone, the worker worktree, the verifier checkout and
`receipt.json` (per-step argv, exit, elapsed seconds, failure and recovery hint). The sandbox
is removed after a GO unless `--keep`; it is always kept after a NO-GO.

`probes` runs the negative probes instead: unsupported profile, privilege escalation, unarmed
deny hook, malformed runtime response and missing capability, each through the same wrapper,
each required to refuse BEFORE a launch (the stand-in never runs, no dispatch is recorded).

Usage:
  first_run.py [run] [--profile ro|rw] [--agent <harness>] [--worker inert|live]
               [--target <repo> [--base <rev>] [--head <rev>]] [--workdir <dir>] [--keep]
               [--timeout <s>] [--json]
  first_run.py probes [--workdir <dir>] [--keep] [--json]

Exit: 0 GO · 1 NO-GO (receipt names the step) · 2 usage · 143/129 SIGTERM/SIGHUP (workers stopped).
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "runtime" / "scripts"
CAPABILITIES = ROOT / "runtime" / "providers" / "capabilities.json"
SCHEMA = "open-fleet-first-run/v1"
# The launch names a harness by its binary; every one gets a tripwire in inert mode.
HARNESS_BINARIES = {"antigravity": "agy"}
LIVE_STATES = ("ready", "running", "retained")
REPORT_HEAD = "FIRST-RUN-REPORT "
READ_HEAD = "FIRST-RUN-READ "
# Where each posix launch (base.build_harness_command) prints its final answer on stdout, which
# posix records line by line as the transcript. A Claude-only reader discarded every other
# harness's report and turned a finished paid run into NO-GO (#596 review).
REPORT_FORMATS = {
    "claude": "claude-stream-json",  # -p --output-format stream-json: {"type":"result","result":...}
    "codex": "codex-exec-json",      # exec --json: item.completed {"item":{"type":"agent_message","text":...}}
    "opencode": "opencode-json",     # run --format json: {"type":"text","part":{"text":...}}; step_start resets
    "omp": "pi-json",                # -p --mode json: message_end {"message":{"role":"assistant","content":[...]}}
    "pi": "pi-json",
    "goose": "goose-stream-json",    # {"type":"message","message":{"id":...,"role":"assistant","content":[...]}}
    "jcode": "jcode-ndjson",         # run --ndjson: {"type":"done","text":<every text delta of the run>}
    "hermes": "text",                # chat --oneshot -Q: plain text
    "crush": "text",                 # run -q: plain text
    "gemini": "text",                # -p with no --output-format: plain text
}
# These carry every turn's text, not only the last answer: the report starts at its own header.
ANCHORED_FORMATS = ("jcode-ndjson", "text")
# Lines the posix monitor itself writes into the transcript, around the worker's own output.
MONITOR_EVENTS = ("turn_started", "launch_refused", "sandbox_git_synced", "sandbox_git_sync_failed", "injected_prompt")


class StepFailed(Exception):
    """A lifecycle step did not hold; `recovery` is the operator's next move."""

    def __init__(self, message: str, recovery: str = ""):
        super().__init__(message)
        self.recovery = recovery


def text_of(data: bytes | str | None) -> str:
    """Captured output as text for display and checks only (#596 review): a reviewed file in an
    older encoding must never raise. Bytes that are evidence (the diff) stay bytes."""
    if isinstance(data, str):
        return data
    return (data or b"").decode("utf-8", "replace")


def run_text(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run capturing BYTES, with stdout/stderr decoded by text_of; `.raw` keeps stdout."""
    proc = subprocess.run(argv, capture_output=True, **kwargs)
    out = subprocess.CompletedProcess(argv, proc.returncode, text_of(proc.stdout), text_of(proc.stderr))
    out.raw = proc.stdout or b""
    return out


def posix_harnesses() -> list[str]:
    caps = json.loads(CAPABILITIES.read_text(encoding="utf-8"))
    return list(caps["providers"]["posix"]["supported_harnesses"])


def _text_blocks(content) -> str:
    """The text blocks of a pi- or goose-style message content (a list, or pi's bare string)."""
    if isinstance(content, str):
        return content
    blocks = content if isinstance(content, list) else []
    return "".join(b["text"] for b in blocks
                   if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str))


def harness_report(agent: str, lines: list[str]) -> str:
    """The worker's final answer, read from its transcript lines in its harness's own format."""
    fmt = REPORT_FORMATS[agent]
    answer, kept = "", []
    parts: dict = {}  # opencode: the text parts of the current step
    run_id, run = None, ""  # goose: the chunks of the message being streamed
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            event = None
        if not isinstance(event, dict):
            kept.append(line)
            continue
        kind = event.get("type")
        if kind in MONITOR_EVENTS:
            continue
        kept.append(line)
        item, message, part = event.get("item"), event.get("message"), event.get("part")
        if fmt == "claude-stream-json" and kind == "result" and isinstance(event.get("result"), str):
            answer = event["result"]
        elif (fmt == "codex-exec-json" and kind == "item.completed" and isinstance(item, dict)
              and item.get("type") == "agent_message" and isinstance(item.get("text"), str)):
            answer = item["text"]
        elif fmt == "opencode-json" and kind == "step_start":
            parts = {}
        elif fmt == "opencode-json" and kind == "text" and isinstance(part, dict) and isinstance(part.get("text"), str):
            parts[part.get("id") or f"anon-{len(parts)}"] = part["text"]
            answer = "\n".join(parts.values())
        elif fmt == "jcode-ndjson" and kind == "done" and isinstance(event.get("text"), str):
            answer = event["text"]
        elif not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        elif fmt == "pi-json" and kind == "message_end":
            answer = _text_blocks(message.get("content")) or answer
        elif fmt == "goose-stream-json" and kind == "message":
            # goose emits one message as chunks sharing its id; a new id starts a new message.
            if message.get("id") is None or message.get("id") != run_id:
                run_id, run = message.get("id"), ""
            run += _text_blocks(message.get("content"))
            answer = run or answer
    if fmt == "text":
        answer = "\n".join(kept)
    if fmt in ANCHORED_FORMATS:
        heads = [i for i, ln in enumerate(answer.splitlines()) if ln.startswith(REPORT_HEAD)]
        if heads:
            answer = "\n".join(answer.splitlines()[heads[-1]:]) + "\n"
    return answer


def all_harness_binaries() -> list[str]:
    """Every harness name and binary base.py knows: each gets a tripwire in inert mode."""
    spec = importlib.util.spec_from_file_location("of_first_run_base", ROOT / "runtime" / "providers" / "base.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    names = {HARNESS_BINARIES.get(h, h) for h in mod.SUPPORTED_HARNESSES}
    return sorted(names | set(mod.SUPPORTED_HARNESSES))


INERT_WORKER = r'''
"""Inert stand-in for a coding-agent harness (first_run.py, #596). Calls no model."""
import json, os, re, subprocess, sys
from pathlib import Path

harness, argv = sys.argv[1], sys.argv[2:]
log_dir = Path(sys.argv[0]).resolve().parent
dispatch = os.environ.get("OPEN_FLEET_DISPATCH_ID", "")
with open(log_dir / "runs.log", "a", encoding="utf-8") as fh:
    fh.write(json.dumps({"harness": harness, "dispatch": dispatch}) + "\n")
(log_dir / f"{dispatch or 'unknown'}.argv.json").write_text(json.dumps(argv), encoding="utf-8")
spec = next((a for a in argv if "FR-NONCE:" in a), "")
m = re.search(r"FIRST-RUN-REPORT (FR-NONCE:[0-9a-f]{16}) ([0-9a-f]{40})", spec)
inp = re.search(r"diff is written to (\S+) in your working tree", spec)
if not m or not inp:
    print("no first-run spec in argv", file=sys.stderr)
    sys.exit(3)


def answer(text):
    """Print the final answer the way this harness's launch prints it (first_run.REPORT_FORMATS)."""
    note = "Reading the diff.\n"  # formats that keep every turn's text carry the earlier ones too
    msg = {"role": "assistant", "content": [{"type": "text", "text": text}]}
    head, _, rest = text.partition("\n")
    events = {
        "claude": [{"type": "system", "subtype": "init"},
                   {"type": "result", "subtype": "success", "is_error": False, "result": text}],
        "codex": [{"type": "thread.started", "thread_id": "inert"}, {"type": "turn.started"},
                  {"type": "item.completed", "item": {"id": "item_0", "type": "agent_message", "text": text}},
                  {"type": "turn.completed", "usage": {"input_tokens": 0, "cached_input_tokens": 0,
                                                       "output_tokens": 0}}],
        "opencode": [{"type": "step_start", "part": {"id": "prt_0", "type": "step-start"}},
                     {"type": "text", "part": {"id": "prt_1", "type": "text", "text": text}},
                     {"type": "step_finish", "part": {"id": "prt_2", "type": "step-finish", "reason": "stop"}}],
        "pi": [{"type": "agent_start"}, {"type": "message_end", "message": msg},
               {"type": "agent_end", "messages": [msg]}],
        "goose": [{"type": "message", "message": {"id": "msg_0", "role": "assistant",
                                                  "content": [{"type": "text", "text": chunk}]}}
                  for chunk in (head + "\n", rest)] + [{"type": "complete", "total_tokens": 0}],
        "jcode": [{"type": "start"}, {"type": "text_delta", "text": note}, {"type": "text_delta", "text": text},
                  {"type": "done", "text": note + text}],
    }
    events["omp"] = events["pi"]
    if harness in events:
        for event in events[harness]:
            print(json.dumps(event))
    else:  # hermes, crush, gemini print plain text
        print(note + text, end="")
# Like an ro harness with no shell, it learns the change only by reading the file it was given:
# the bytes git wrote, any encoding; it reads them as text the way a model would (#596 review).
raw = Path(inp.group(1)).read_bytes()
change = raw.decode("utf-8", "replace")
lines = change.splitlines()
stat = subprocess.run(["git", "apply", "--stat", "-"], input=raw, capture_output=True).stdout.decode("utf-8", "replace").strip()
stat = re.sub(r" [|] +", " | ", stat)
paths = [d.group(1) for d in map(re.compile(r"^diff --git a/.* b/(.*)$").match, lines) if d]
read = [ln for ln in lines if ln.startswith("FIRST-RUN-READ ")][-1:]
report = f"FIRST-RUN-REPORT {m.group(1)} {m.group(2)}\n" + (stat or "(empty diff)") + "\n" + "".join(
    f"changed: {p}\n" for p in paths) + "".join(f"{ln}\n" for ln in read)
rc = 0
if os.environ.get("OPEN_FLEET_SANDBOX_PROFILE") == "rw":
    rel = re.search(r"write the report to (\S+)", spec).group(1)
    Path(rel).parent.mkdir(parents=True, exist_ok=True)
    Path(rel).write_text(report, encoding="utf-8")
    subprocess.run(["git", "add", "-f", "--", rel], check=True)  # the target may ignore it
    subprocess.run(["git", "commit", "-q", "-m", "first-run report", "--", rel], check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.decode("ascii", "replace").strip()
    rc = subprocess.run([sys.executable, "-I", os.path.join(os.environ["OPEN_FLEET_ROOT"], "runtime",
                         "scripts", "send_msg.py"), "--type", "worker_done", "--outcome", "succeeded",
                         "--subject", f"worker_done:{dispatch}",
                         "--payload", json.dumps({"head": head, "report": rel})]).returncode
answer(report)
sys.exit(rc)
'''


class Sandbox:
    """Every path one run touches, plus the environment its wrappers run under."""

    def __init__(self, workdir: Path, worker: str, agent: str):
        self.dir = workdir
        self.worker = worker
        self.agent = agent
        self.inert = workdir / "inert"
        self.tripwire = workdir / "tripwire"
        self.state_db = workdir / "state" / "runtime.db"
        self.target = workdir / "target"
        self.scratch = workdir / "sp"
        self.home = workdir / "home"
        for d in (self.scratch, self.home, self.state_db.parent):
            d.mkdir(parents=True, exist_ok=True)
        path = [os.path.dirname(sys.executable), os.environ.get("PATH", os.defpath)]
        if worker == "inert":
            self._install_inert()
            path = [str(self.inert), str(self.tripwire)] + path
        self.env = {
            **os.environ,
            "PATH": os.pathsep.join(path),
            # setsid only: tmux would start a server whose login shell can reorder PATH; and no
            # rc file of a login shell (zsh reads ~/.zshenv even for `-c`) may run at all.
            "SHELL": "/bin/sh",
            "OPEN_FLEET_RUNTIME": "posix",
            "OPEN_FLEET_POSIX_BACKEND": "setsid",
            "OPEN_FLEET_STATE_DB": str(self.state_db),
            "OPEN_FLEET_CLI_CWD": str(self.target),
            "SP": str(self.scratch),
            "PYTHON": sys.executable,
        }
        # An inherited CLI override or Orca session would route the wrappers somewhere else.
        for var in ("ORCA_CLI_COMMAND", "OPEN_FLEET_CLI_COMMAND", "ORCA_FLEET_RUNTIME", "OPEN_FLEET_REPO_ROOT",
                    "OPEN_FLEET_SANDBOX_PROFILE", "ORCA_SANDBOX_PROFILE", "OPEN_FLEET_PARENT_PROFILE",
                    "ORCA_PARENT_PROFILE", "OPEN_FLEET_DENY_HOOK_SETTINGS", "ORCA_DENY_HOOK_SETTINGS",
                    "WORKER_CMD", "CLAUDE_CMD", "CODEX_CMD", "ORCA_TERMINAL_HANDLE", "OPEN_FLEET_TERMINAL_HANDLE"):
            self.env.pop(var, None)
        if worker == "inert":
            # The stand-in needs no credentials; a private HOME keeps every user config out.
            self.env["HOME"] = str(self.home)

    def _install_inert(self) -> None:
        self.inert.mkdir(parents=True, exist_ok=True)
        self.tripwire.mkdir(parents=True, exist_ok=True)
        (self.inert / "worker.py").write_text(INERT_WORKER, encoding="utf-8")
        for name in all_harness_binaries():
            trip = self.tripwire / name
            trip.write_text(f'#!/bin/sh\necho "{name} $*" >> {shlex.quote(str(self.tripwire / "hits.log"))}\nexit 97\n',
                            encoding="utf-8")
            trip.chmod(0o755)
        stand_in = self.inert / HARNESS_BINARIES.get(self.agent, self.agent)
        stand_in.write_text(
            "#!/bin/sh\n# first_run.py inert stand-in: no model is called.\n"
            f"exec {shlex.quote(sys.executable)} -I {shlex.quote(str(self.inert / 'worker.py'))} "
            f"{shlex.quote(self.agent)} \"$@\"\n",
            encoding="utf-8",
        )
        stand_in.chmod(0o755)

    def inert_runs(self) -> list[dict]:
        log = self.inert / "runs.log"
        if not log.is_file():
            return []
        return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]

    def tripwire_hits(self) -> str:
        log = self.tripwire / "hits.log"
        return log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""


class Recorder:
    """Runs each command, times it, and keeps the receipt's step list."""

    def __init__(self, sandbox: Sandbox):
        self.sb = sandbox
        self.steps: list[dict] = []
        self.commands: list[dict] = []

    def run(self, argv: list[str], *, cwd: Path | None = None, env: dict | None = None,
            timeout: int = 300, record: bool = True) -> subprocess.CompletedProcess:
        start = time.monotonic()
        full_env = {**self.sb.env, **(env or {})}
        try:
            proc = run_text(argv, cwd=str(cwd or self.sb.target), env=full_env, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc = subprocess.CompletedProcess(argv, 124, text_of(exc.stdout), f"timed out after {timeout}s")
            proc.raw = exc.stdout if isinstance(exc.stdout, bytes) else b""
        if record:  # polling reads are not receipts
            self.commands.append({"argv": [str(a) for a in argv], "env": sorted((env or {}).keys()),
                                  "rc": proc.returncode, "elapsed_s": round(time.monotonic() - start, 3)})
        return proc

    def step(self, name: str, fn, *args, **kwargs):
        start = time.monotonic()
        record: dict = {"step": name}
        try:
            detail = fn(*args, **kwargs)
            record.update(ok=True, detail=detail)
            return detail
        except StepFailed as exc:
            record.update(ok=False, detail=str(exc), recovery=exc.recovery)
            raise
        except Exception as exc:
            # A defect here must still end in a receipt, not a traceback with none (#596 review).
            # KeyboardInterrupt and the signal exits are BaseException and still unwind.
            where = traceback.extract_tb(exc.__traceback__)[-1]
            detail = f"unexpected {type(exc).__name__}: {exc}"[:1000]
            recovery = (f"a first_run.py defect at {Path(where.filename).name}:{where.lineno}; the sandbox is "
                        "kept: report it with receipt.json")
            record.update(ok=False, detail=detail, recovery=recovery)
            raise StepFailed(detail, recovery) from exc
        finally:
            record["elapsed_s"] = round(time.monotonic() - start, 3)
            self.steps.append(record)


def py(script: str, *args: str) -> list[str]:
    return [sys.executable, str(SCRIPTS / script), *args]


def field(out: str, key: str) -> str:
    m = re.search(rf"(?m)(?:^|\s){re.escape(key)}=(\S+)", out)
    return m.group(1) if m else ""


def git(rec: Recorder, *args: str, cwd: Path | None = None) -> str:
    proc = rec.run(["git", *args], cwd=cwd)
    if proc.returncode != 0:
        raise StepFailed(f"git {' '.join(args)} failed: {(proc.stderr or proc.stdout).strip()[:300]}")
    return proc.stdout.strip()


def harness_version(binary: str, env: dict) -> str:
    try:
        proc = run_text([binary, "--version"], timeout=30, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unreadable: {exc}"
    return (proc.stdout or proc.stderr).strip().splitlines()[0][:200] if (proc.stdout or proc.stderr).strip() else ""


def host_facts() -> dict:
    def version(argv):
        try:
            out = run_text(argv, timeout=30)
            return (out.stdout or out.stderr).strip().splitlines()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            return None

    catalog = run_text(["git", "-C", str(ROOT), "rev-parse", "HEAD"])
    dirty = run_text(["git", "-C", str(ROOT), "status", "--porcelain"])
    return {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "git": version(["git", "--version"]),
        "bash": version(["bash", "--version"]),
        "catalog_commit": catalog.stdout.strip() if catalog.returncode == 0 else None,
        "catalog_dirty": bool(dirty.stdout.strip()) if dirty.returncode == 0 else None,
    }


# --- lifecycle ------------------------------------------------------------------------------

class FirstRun:
    def __init__(self, args: argparse.Namespace, sandbox: Sandbox):
        self.args = args
        self.sb = sandbox
        self.rec = Recorder(sandbox)
        self.run_id = f"fr-{secrets.token_hex(3)}"
        self.nonce = f"FR-NONCE:{secrets.token_hex(8)}"
        self.unit_dir = f".first-run/{self.run_id}"
        self.change_rel = f"{self.unit_dir}/change.diff"
        # Only the change file carries this: quoting it shows the worker read that file (FR-4).
        self.read_receipt = f"{READ_HEAD}{secrets.token_hex(8)}"
        self.facts: dict = {"run_id": self.run_id, "nonce": self.nonce}

    # Each method is one step; it returns its detail string or raises StepFailed.
    def prereqs(self) -> str:
        if sys.version_info < (3, 11):
            raise StepFailed(f"python {platform.python_version()} < 3.11", "run with Python 3.11-3.13")
        missing = [t for t in ("git", "bash", "sh") if not shutil.which(t, path=self.sb.env["PATH"])]
        if missing:
            raise StepFailed(f"not on PATH: {', '.join(missing)}", "install the missing tools")
        binary = HARNESS_BINARIES.get(self.args.agent, self.args.agent)
        found = shutil.which(binary, path=self.sb.env["PATH"])
        if not found:
            raise StepFailed(f"`{binary}` is not on PATH", f"install {self.args.agent} and sign it in, or use --worker inert")
        if self.args.worker == "live" and Path(found).resolve().is_relative_to(self.sb.dir.resolve()):
            raise StepFailed("live mode resolved the harness inside the sandbox", "remove the stand-in from PATH")
        self.facts["harness"] = {
            "name": self.args.agent,
            "path": found,
            "version": "inert stand-in (no model)" if self.args.worker == "inert" else harness_version(found, self.sb.env),
        }
        return f"{binary} -> {found}"

    def target(self) -> str:
        t = self.sb.target
        if self.args.target:
            src = Path(self.args.target).resolve()
            proc = self.rec.run(["git", "clone", "-q", "--no-hardlinks", str(src), str(t)], cwd=self.sb.dir)
            if proc.returncode != 0:
                raise StepFailed(f"cannot clone {src}: {proc.stderr.strip()[:300]}", "--target must be a git repository")
        else:
            t.mkdir(parents=True)
            git(self.rec, "init", "-q", "-b", "main", cwd=t)
        for key, val in (("user.email", "first-run@open-fleet.invalid"), ("user.name", "open-fleet first run"),
                         ("commit.gpgsign", "false"), ("tag.gpgsign", "false"), ("core.hooksPath", "/dev/null")):
            git(self.rec, "config", key, val, cwd=t)
        if not self.args.target:
            (t / "README.md").write_text("# first-run target\n", encoding="utf-8")
            git(self.rec, "add", "-f", "--", "README.md", cwd=t)
            git(self.rec, "commit", "-q", "-m", "seed", cwd=t)
            (t / "app.py").write_text("def greet(name):\n    return f'hello {name}'\n", encoding="utf-8")
            git(self.rec, "add", "-f", "--", "app.py", cwd=t)
            git(self.rec, "commit", "-q", "-m", "add greet()", cwd=t)
        base = git(self.rec, "rev-parse", "--verify", f"{self.args.base}^{{commit}}", cwd=t)
        head = git(self.rec, "rev-parse", "--verify", f"{self.args.head}^{{commit}}", cwd=t)
        if base == head:
            raise StepFailed("--base and --head name the same commit", "review a range with at least one commit")
        self.facts["reviewed"] = {"base_sha": base, "head_sha": head}
        # The coordinator's evidence branch starts at the reviewed head; its first commit is the
        # frozen contract, so the contract exists in git BEFORE any worker is dispatched.
        git(self.rec, "checkout", "-q", "-b", f"first-run/{self.run_id}", head, cwd=t)
        # The change reaches the worker as a FILE in its tree: most ro launches have no shell to
        # run `git diff` (omp, pi, opencode, jcode, goose, hermes, crush, gemini; claude in plan
        # mode), and the spec alone let a worker that never saw the change copy the header to a
        # GO (#596 review). It is frozen with the contract, so it is the evidence range's BASE and
        # never part of the result; its last line is the read receipt no other channel carries.
        diff = self.rec.run(["git", "-c", "core.quotePath=false", "diff", base, head], cwd=t)
        names = self.rec.run(["git", "-c", "core.quotePath=false", "diff", "--name-only", base, head], cwd=t)
        if diff.returncode != 0 or names.returncode != 0:
            raise StepFailed(f"git diff {base} {head} failed: {(diff.stderr or names.stderr).strip()[:300]}")
        # Byte-exact: a reviewed file in an older encoding reaches the worker as git wrote it.
        body = diff.raw if not diff.raw or diff.raw.endswith(b"\n") else diff.raw + b"\n"
        change = (f"# first-run {self.run_id}: the change under review, `git diff {base} {head}`.\n"
                  "# Written before dispatch. Read it to the end: its last line is the read receipt.\n").encode()
        change += body + f"{self.read_receipt}\n".encode()
        (t / self.unit_dir).mkdir(parents=True)
        (t / self.change_rel).write_bytes(change)
        self.facts["change"] = {"input": self.change_rel, "paths": names.stdout.splitlines()}
        contract = (
            f"# First-run contract {self.run_id}\n\n"
            f"Frozen by first_run.py before dispatch. Reviewed change: `{base}..{head}`.\n\n"
            f"- FR-1: the worker receives this unit's frozen spec ({self.nonce}) through the posix route.\n"
            f"- FR-2: the worker's report opens with `FIRST-RUN-REPORT {self.nonce} {head}`.\n"
            "- FR-3: the report is bound to a commit the coordinator reads from git and verify.py re-derives.\n"
            f"- FR-4: the report quotes the read receipt that ends `{self.change_rel}` and names every changed path.\n"
        )
        path = t / self.unit_dir / "contract.md"
        path.write_text(contract, encoding="utf-8")
        # Force-add exactly the files this run owns: a target's ignore rules (`*.diff`,
        # `.first-run/`) must not block them, and no glob may sweep in anything else (#596 review).
        git(self.rec, "add", "-f", "--", f"{self.unit_dir}/contract.md", self.change_rel, cwd=t)
        git(self.rec, "commit", "-q", "-m", f"first-run {self.run_id}: freeze contract", cwd=t)
        self.facts["contract"] = {
            "source": f"{self.unit_dir}/contract.md@{git(self.rec, 'rev-parse', 'HEAD', cwd=t)}",
            "digest": "sha256:" + hashlib.sha256(contract.encode("utf-8")).hexdigest(),
            "criterion_ids": ["FR-1", "FR-2", "FR-3", "FR-4"],
            "text": contract,
        }
        return f"reviewed {base[:12]}..{head[:12]}; contract frozen"

    def preflight(self) -> str:
        proc = self.rec.run(py("preflight.py", "--mission", "review-it", "--runtime", "posix", "--mode", "readonly"))
        if proc.returncode != 0:
            raise StepFailed(f"preflight refused: {(proc.stderr or proc.stdout).strip()[:300]}",
                             "read the preflight line; docs/troubleshooting.md")
        return proc.stdout.strip().splitlines()[-1]

    def spec(self) -> str:
        r = self.facts["reviewed"]
        lines = [
            f"open-fleet first-run review unit {self.run_id} ({self.nonce}).",
            f"Review the change {r['base_sha']}..{r['head_sha']}. Its diff is written to {self.change_rel} in your "
            "working tree: read that file to its end. You need no shell for this, and must not change it.",
            "Report what the change does and any problem you see, one line each, naming every changed path.",
            f"Your report MUST start with this exact line: FIRST-RUN-REPORT {self.nonce} {r['head_sha']}",
            "The file's last line is a read receipt: copy that line, verbatim, into your report.",
        ]
        if self.args.profile == "rw":
            lines += [
                f"Modify nothing except: write the report to {self.unit_dir}/report.md and commit only that file, "
                f"adding it with `git add -f -- {self.unit_dir}/report.md` (the repository may ignore it).",
                "Then report completion with:",
                '  python3 "$OPEN_FLEET_ROOT/runtime/scripts/send_msg.py" --type worker_done --outcome succeeded'
                ' --subject "worker_done:$OPEN_FLEET_DISPATCH_ID" --payload \'{"head": "<the report commit sha>"}\'',
            ]
        else:
            lines.append("Modify nothing. Print the report as your final answer.")
        lines.append(f"Frozen contract: {self.facts['contract']['source']} ({self.facts['contract']['digest']}).")
        return "\n".join(lines)

    def create(self) -> str:
        proc = self.rec.run(py("task_ops.py", "create", "--spec", self.spec()))
        task = field(proc.stdout, "CREATED")
        if proc.returncode != 0 or not task:
            raise StepFailed(f"task_ops.py create: rc={proc.returncode} {(proc.stderr or proc.stdout).strip()[:300]}",
                             "run task_ops.py create in the sandbox target to see the refusal")
        self.facts["task"] = task
        return task

    def dispatch(self) -> str:
        env = {"PROFILE": self.args.profile}
        if self.args.profile == "rw":
            env["ORCA_COORD_ALLOW_AUTONOMOUS_WRITE"] = "1"
        proc = self.rec.run(["bash", str(SCRIPTS / "spawn_worker.sh"), self.facts["task"], "new-child",
                             self.run_id, self.args.agent], env=env)
        disp, handle = field(proc.stdout, "DISPATCH"), field(proc.stdout, "HANDLE")
        launch = next((ln.split("=", 1)[1] for ln in proc.stdout.splitlines() if ln.startswith("LAUNCH_EFFECTIVE=")), "")
        if proc.returncode != 0 or not disp:
            raise StepFailed(f"spawn_worker.sh rc={proc.returncode}: {(proc.stderr or proc.stdout).strip()[-400:]}",
                             "read the SPAWN= line; docs/troubleshooting.md")
        self.facts.update(dispatch=disp, handle=handle)
        try:
            self.facts["launch_effective"] = json.loads(launch)
        except json.JSONDecodeError:
            raise StepFailed(f"spawn_worker.sh printed no readable LAUNCH_EFFECTIVE: {launch[:200]!r}") from None
        return f"{disp} on {handle}"

    def worker_show(self) -> dict:
        proc = self.rec.run(py("orca_cli.py", "orchestration", "worker-show", "--dispatch", self.facts["dispatch"], "--json"))
        try:
            return json.loads(proc.stdout)["result"]["worker"]
        except (ValueError, KeyError, TypeError):
            raise StepFailed(f"worker-show unreadable: {proc.stdout[:200]!r}") from None

    def guard(self) -> str:
        wt = Path(self.worker_show()["worktree"])
        self.facts["worktree"] = str(wt)
        settings = wt / ".claude" / "settings.local.json"
        proc = self.rec.run(["sh", str(SCRIPTS / "deny-hook.sh"), "--verify-settings", str(settings)])
        if proc.returncode != 0:
            raise StepFailed(f"the installed guard is not armed: {proc.stderr.strip()[:300]}",
                             f"deny-hook.sh --verify-settings {settings}")
        return proc.stdout.strip()

    def delivery(self) -> str:
        command = str((self.facts.get("launch_effective") or {}).get("command", ""))
        if self.nonce not in command:
            raise StepFailed("the launch the provider recorded does not carry the task spec",
                             "the worker would start without its assignment; compare LAUNCH_EFFECTIVE to the task")
        if self.sb.worker == "inert":
            if not self.wait_for(lambda: (self.sb.inert / f"{self.facts['dispatch']}.argv.json").is_file()):
                raise StepFailed("the stand-in never ran for this dispatch", "worker_ops.py read --dispatch <d>")
            argv = json.loads((self.sb.inert / f"{self.facts['dispatch']}.argv.json").read_text(encoding="utf-8"))
            if not any(self.nonce in a for a in argv):
                raise StepFailed("the stand-in ran without the task spec in its argv")
            return "spec in the recorded launch and in the worker's argv"
        return "spec in the recorded launch (the live worker's echo is checked at result)"

    def wait_for(self, pred, timeout: float | None = None) -> bool:
        deadline = time.monotonic() + (timeout or self.args.timeout)
        while time.monotonic() < deadline:
            if pred():
                return True
            time.sleep(0.25)
        return False

    def result(self) -> str:
        disp = self.facts["dispatch"]
        state = {"v": ""}

        def settled():
            out = self.rec.run(py("worker_ops.py", "show", "--dispatch", disp), record=False).stdout
            state["v"] = field(out, "STATE")
            return state["v"] not in ("",) + LIVE_STATES

        if not self.wait_for(settled):
            raise StepFailed(f"worker still {state['v'] or 'unknown'} after {self.args.timeout}s",
                             f"worker_ops.py read --dispatch {disp} --source transcript; raise --timeout")
        mail = self.rec.run(py("check_reply.py", "check", "--terminal", "coordinator"))
        msgs = parse_mail(mail.stdout)
        mine = [m for m in msgs if disp in m["subject"]]
        expected = "completed" if self.args.profile == "rw" else "died"
        if state["v"] != expected:
            raise StepFailed(f"dispatch settled {state['v']!r}, expected {expected!r}: {mine}",
                             f"worker_ops.py read --dispatch {disp} --source transcript")
        if self.args.profile == "rw":
            done = [m for m in mine if m["type"] == "worker_done"]
            if not done:
                raise StepFailed("no worker_done from this dispatch", "the worker never reported; read its transcript")
            self.facts["worker_claim"] = done[0]["payload"]
        else:
            # A ro worker has no tool to send mail: posix records its CLEAN exit as worker_died.
            died = [m for m in mine if m["type"] == "escalation" and m["subject"].startswith("worker_died:")]
            if not died or (died[0]["payload"] or {}).get("exitCode") != 0:
                raise StepFailed(f"ro worker did not exit cleanly: {died}", f"worker_ops.py read --dispatch {disp}")
        read = self.rec.run(py("worker_ops.py", "read", "--dispatch", disp, "--source", "transcript"))
        if read.returncode != 0 or "SOURCE=transcript" not in read.stdout:
            raise StepFailed(f"transcript read not certified: {(read.stderr or read.stdout).strip()[:200]}")
        report = self.transcript_report()
        first = report.splitlines()[0] if report else ""
        want = self.report_header()
        if first.strip() != want:
            raise StepFailed(f"report does not open with {want!r}: {first[:200]!r}",
                             "the worker did not follow the spec; read its transcript")
        self.check_read(report, "report")
        self.facts["report"] = report
        return f"settled {state['v']}; report names the reviewed head"

    def report_header(self) -> str:
        """FR-2: the exact line every report opens with, printed and committed alike."""
        return f"{REPORT_HEAD}{self.nonce} {self.facts['reviewed']['head_sha']}"

    def check_read(self, report: str, what: str) -> None:
        """FR-4: the report shows its worker read the change file, not only the spec (#596 review).

        The receipt is the file's LAST line and appears nowhere else the worker sees, and the
        changed paths come from the diff itself: a worker that copied the header, read no file,
        or read only one end of it cannot meet both.
        """
        missing = [] if self.read_receipt in report else ["the read receipt"]
        missing += [p for p in self.facts["change"]["paths"]
                    if not re.search(rf"(?<![\w.-]){re.escape(p)}(?![\w/-])", report)]  # `b/<path>` counts
        if missing:
            raise StepFailed(f"the {what} does not show the worker read {self.change_rel}: missing {missing}",
                             f"the worker must read {self.change_rel} to its end; read its transcript")

    def transcript_report(self) -> str:
        proc = self.rec.run(py("orca_cli.py", "orchestration", "worker-read", "--dispatch", self.facts["dispatch"],
                               "--limit", "100000", "--json"))
        try:
            messages = json.loads(proc.stdout)["result"]["transcript"]["messages"]
        except (ValueError, KeyError, TypeError):
            raise StepFailed(f"worker-read unreadable: {proc.stdout[:200]!r}") from None
        lines = [str(block.get("text") or "") for msg in messages for block in (msg.get("blocks") or [])]
        return harness_report(self.args.agent, lines)

    def evidence(self) -> str:
        t, rel = self.sb.target, f"{self.unit_dir}/report.md"
        if self.args.profile == "rw":
            head = git(self.rec, "rev-parse", "HEAD", cwd=Path(self.facts["worktree"]))
            claim = (self.facts.get("worker_claim") or {}).get("head")
            if claim != head:
                raise StepFailed(f"worker_done claims head {claim!r}; git says {head}", "the claim is not evidence")
        else:
            path = t / rel
            path.write_text(self.facts["report"], encoding="utf-8", errors="replace")
            git(self.rec, "add", "-f", "--", rel, cwd=t)
            git(self.rec, "commit", "-q", "-m", f"first-run {self.run_id}: report from the worker transcript", cwd=t)
            head = git(self.rec, "rev-parse", "HEAD", cwd=t)
        contract_sha = self.facts["contract"]["source"].rsplit("@", 1)[1]
        changed = git(self.rec, "diff", "--name-only", contract_sha, head, cwd=t).splitlines()
        if changed != [rel]:
            raise StepFailed(f"the evidence range changes more than the report: {changed}",
                             "a review unit may not change code")
        # verify.py binds the COMMITTED bytes, so they are what must meet FR-2: an rw worker could
        # print the right report and commit another (#596 review). Read from git, never the tree.
        committed = self.rec.run(["git", "show", f"{head}:{rel}"], cwd=t)
        first, want = (committed.stdout.splitlines() or [""])[0], self.report_header()
        if committed.returncode != 0 or first.strip() != want:
            raise StepFailed(f"the committed report does not open with {want!r}: {first[:200]!r}",
                             f"git show {head}:{rel}; the report the worker printed is not the one it committed")
        self.check_read(committed.stdout, "committed report")
        self.facts["evidence"] = {"base_sha": contract_sha, "head_sha": head}
        return f"{contract_sha[:12]}..{head[:12]} carries only {rel}"

    def verify(self) -> str:
        ev, contract = self.facts["evidence"], self.facts["contract"]
        checkout = self.sb.dir / "verify"
        git(self.rec, "worktree", "add", "-q", "--detach", str(checkout), ev["head_sha"], cwd=self.sb.target)
        rel = f"{self.unit_dir}/report.md"
        report = (checkout / rel).read_bytes()
        manifest = {
            "unit": f"first-run-{self.run_id}",
            "claim": f"first-run review of {self.facts['reviewed']['head_sha']} on the posix route "
                     f"({self.args.worker} {self.args.agent}, PROFILE={self.args.profile})",
            "base_sha": ev["base_sha"],
            "head_sha": ev["head_sha"],
            "base_branch": f"first-run/{self.run_id}",
            "contract": {k: contract[k] for k in ("source", "digest", "criterion_ids")},
            "criteria": [{"id": cid, "text": cid, "addressed": True} for cid in contract["criterion_ids"]],
            "artifacts": [{"path": rel, "sha256": hashlib.sha256(report).hexdigest()}],
        }
        mpath = checkout / self.unit_dir / "manifest.json"
        write_manifest(mpath, manifest)
        argv = py("verify.py", "--manifest", f"{self.unit_dir}/manifest.json", "--contract-source", contract["source"],
                  "--contract-digest", contract["digest"], "--unit-class", "report-only")
        proc = self.rec.run(argv, cwd=checkout)
        self.facts["verify"] = {"argv": argv[1:], "cwd": str(checkout), "rc": proc.returncode,
                                "out": (proc.stdout + proc.stderr).strip().splitlines()[-6:]}
        if proc.returncode != 0 or "verify: OK" not in proc.stdout:
            fails = [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.startswith("FAIL")]
            why = "; ".join(fails)[:1500] or (proc.stderr or proc.stdout).strip()[-400:]
            raise StepFailed(f"verify.py rc={proc.returncode}: {why}",
                             f"re-run in {checkout}: {' '.join(shlex.quote(a) for a in argv)}")
        return "verify: OK (report-only, SHA-bound)"

    def release(self) -> str:
        disp, head = self.facts["dispatch"], self.facts["evidence"]["head_sha"]
        for verb, want in (("retain", "retained"), ("release", "released")):
            proc = self.rec.run(py("worker_ops.py", verb, "--dispatch", disp))
            got = field(self.rec.run(py("worker_ops.py", "show", "--dispatch", disp)).stdout, "STATE")
            if proc.returncode != 0 or got != want:
                raise StepFailed(f"worker_ops.py {verb}: rc={proc.returncode} state={got!r}",
                                 f"worker_ops.py show --dispatch {disp}")
            if self.rec.run(["git", "cat-file", "-e", f"{head}^{{commit}}"]).returncode != 0:
                raise StepFailed(f"the evidence commit {head} is gone after {verb}")
        return "retained, then released; the evidence commit survives"

    def execute(self) -> dict:
        order = ["prereqs", "target", "preflight", "create", "dispatch", "guard", "delivery", "result",
                 "evidence", "verify", "release"]
        failed = None
        start = time.monotonic()
        try:
            for name in order:
                self.rec.step(name, getattr(self, name))
            if self.sb.worker == "inert":
                self.rec.step("isolation", self.isolation)
        except StepFailed:
            failed = self.rec.steps[-1]
        return self.receipt(failed, round(time.monotonic() - start, 3))

    def isolation(self) -> str:
        hits = self.sb.tripwire_hits()
        if hits:
            raise StepFailed(f"a harness resolved past the stand-in to a tripwire: {hits[:200]!r}")
        runs = [r["dispatch"] for r in self.sb.inert_runs()]
        if runs != [self.facts["dispatch"]]:
            raise StepFailed(f"the stand-in ran for {runs}, expected exactly this dispatch")
        return "only the stand-in ran, once, for this dispatch"

    def receipt(self, failed: dict | None, elapsed: float) -> dict:
        facts = {k: v for k, v in self.facts.items() if k not in ("report", "contract")}
        if "contract" in self.facts:
            facts["contract"] = {k: self.facts["contract"][k] for k in ("source", "digest", "criterion_ids")}
        return {
            "schema": SCHEMA,
            "verdict": "NO-GO" if failed else "GO",
            "tier": "fixture-tested" if self.sb.worker == "inert" else "live-unreviewed",
            "route": {"provider": "posix", "backend": "setsid", "profile": self.args.profile,
                      "harness": self.args.agent, "worker": self.sb.worker},
            "host": host_facts(),
            "facts": facts,
            "steps": self.rec.steps,
            "commands": self.rec.commands,
            "failure": failed,
            "elapsed_s": elapsed,
            "sandbox": str(self.sb.dir),
        }


def write_manifest(path: Path, manifest: dict) -> None:
    """The coordinator's manifest; a separate function so a test can mutate what gets bound."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


MAIL_HEAD = re.compile(r"^--- (\S+) \((\S+)\) from (\S+)$")


def parse_mail(text: str) -> list[dict]:
    """check_reply.py's printed messages: header, SUBJ line, then the payload line."""
    out: list[dict] = []
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = MAIL_HEAD.match(line)
        if not m:
            continue
        subj = lines[i + 1][len("SUBJ: "):] if i + 1 < len(lines) and lines[i + 1].startswith("SUBJ: ") else ""
        payload = None
        if i + 2 < len(lines):
            try:
                payload = json.loads(lines[i + 2])
            except ValueError:
                payload = None
        out.append({"id": m.group(1), "type": m.group(2), "from": m.group(3), "subject": subj, "payload": payload})
    return out


# --- negative probes ------------------------------------------------------------------------

def probe_table(sb: Sandbox, unarmed: Path, garbage: Path) -> list[tuple]:
    """(name, why, argv, env, expected exit, refusal text) — `{task}` is a fresh ready task."""
    rw = {"PROFILE": "rw", "ORCA_COORD_ALLOW_AUTONOMOUS_WRITE": "1"}
    spawn = ["bash", str(SCRIPTS / "spawn_worker.sh")]
    return [
        ("unsupported-profile", "PROFILE=ro for a harness with no verified read-only launch (cursor)",
         spawn + ["{task}", "new-child", "probe", "cursor"], {"PROFILE": "ro"}, 2,
         "no verified PROFILE=ro launch flag"),
        ("privilege-escalation", "a ro parent asks for an rw child",
         spawn + ["{task}", "new-child", "probe", "claude"], {**rw, "OPEN_FLEET_PARENT_PROFILE": "ro"}, 2,
         "monotonic privilege narrowing violation"),
        ("unarmed-deny-hook", "the named hook registration never denies",
         spawn + ["{task}", "new-child", "probe", "claude"], {**rw, "OPEN_FLEET_DENY_HOOK_SETTINGS": str(unarmed)}, 2,
         "deny-hook not armed"),
        ("malformed-upstream-response", "the runtime CLI answers with non-JSON",
         spawn + ["{task}", "new-child", "probe", "claude"], {"PROFILE": "ro", "ORCA_CLI_COMMAND": str(garbage)}, 1,
         "SPAWN=FAILED"),
        ("missing-capability", "pin-it needs cap:orca-self-audit, which posix lacks",
         py("preflight.py", "--mission", "pin-it", "--runtime", "posix", "--mode", "readonly"), {}, 2,
         "missing_capability: cap:orca-self-audit"),
    ]


def probes(sb: Sandbox) -> dict:
    """Each probe must REFUSE before a launch: the stand-in never runs, no dispatch is recorded."""
    rec = Recorder(sb)
    sb.target.mkdir(parents=True, exist_ok=True)
    git(rec, "init", "-q", "-b", "main", cwd=sb.target)
    for key, val in (("user.email", "probe@open-fleet.invalid"), ("user.name", "probe"), ("commit.gpgsign", "false")):
        git(rec, "config", key, val, cwd=sb.target)
    git(rec, "commit", "-q", "--allow-empty", "-m", "seed", cwd=sb.target)

    unarmed = sb.dir / "unarmed-settings.json"
    block = run_text(["sh", str(SCRIPTS / "deny-hook.sh"), "--settings", str(sb.target)], check=True).stdout
    doc = json.loads(block)
    for entry in doc["hooks"]["PreToolUse"]:
        for hook in entry["hooks"]:
            hook["command"] = "true # deny-hook.sh registered but never denies"
    unarmed.write_text(json.dumps(doc), encoding="utf-8")
    garbage = sb.dir / "garbage-cli"
    garbage_log = sb.dir / "garbage-cli.log"
    garbage.write_text(f'#!/bin/sh\necho "$*" >> {shlex.quote(str(garbage_log))}\necho "<html>502 Bad Gateway</html>"\n',
                       encoding="utf-8")
    garbage.chmod(0o755)

    results = []
    for name, why, argv, env, want_rc, want_text in probe_table(sb, unarmed, garbage):
        created = rec.run(py("task_ops.py", "create", "--spec", f"probe {name}"))
        task = field(created.stdout, "CREATED")
        before = len(sb.inert_runs())
        proc = rec.run([a.replace("{task}", task) for a in argv], env=env)
        text = proc.stdout + proc.stderr
        workers = rec.run(py("orca_cli.py", "orchestration", "worker-list", "--json")).stdout
        try:
            dispatched = [w for w in json.loads(workers)["result"]["workers"] if w.get("taskId") == task]
        except (ValueError, KeyError, TypeError):
            dispatched = [{"unreadable": workers[:200]}]
        if dispatched:
            # A probe that did NOT refuse launched asynchronously: give the worker time to show.
            deadline = time.monotonic() + 15
            while len(sb.inert_runs()) == before and time.monotonic() < deadline:
                time.sleep(0.2)
        problems = []
        if proc.returncode != want_rc:
            problems.append(f"exit {proc.returncode}, expected {want_rc}")
        if want_text not in text:
            problems.append(f"no {want_text!r} in the output")
        if len(sb.inert_runs()) != before or sb.tripwire_hits():
            problems.append("a worker launched")
        if dispatched:
            problems.append(f"a dispatch was recorded: {dispatched}")
        if name == "malformed-upstream-response" and garbage_log.is_file() and "worker-start" in garbage_log.read_text(errors="replace"):
            problems.append("worker-start was called after an unreadable response")
        results.append({"probe": name, "why": why, "rc": proc.returncode, "refused": not problems,
                        "problems": problems, "evidence": [ln for ln in text.splitlines() if want_text in ln][:2]})
    return {"schema": SCHEMA, "verdict": "GO" if all(r["refused"] for r in results) else "NO-GO",
            "probes": results, "host": host_facts(), "sandbox": str(sb.dir)}


# --- entry point ----------------------------------------------------------------------------

def parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="first_run.py", description="Reproducible first run of the posix route (#596).")
    ap.add_argument("mode", nargs="?", default="run", choices=("run", "probes"))
    ap.add_argument("--profile", default="ro", choices=("ro", "rw"))
    ap.add_argument("--agent", default="claude")
    ap.add_argument("--worker", default="inert", choices=("inert", "live"))
    ap.add_argument("--target", default=None, help="git repository to review (cloned; never modified)")
    ap.add_argument("--base", default="HEAD~1")
    ap.add_argument("--head", default="HEAD")
    ap.add_argument("--workdir", default=None, help="sandbox directory (created; default a new temp dir)")
    ap.add_argument("--keep", action="store_true", help="keep the sandbox after a GO")
    ap.add_argument("--timeout", type=int, default=None, help="seconds to wait for the worker (inert 60, live 1800)")
    ap.add_argument("--json", action="store_true", help="print the receipt JSON instead of lines")
    ns = ap.parse_args(argv)
    if ns.agent not in posix_harnesses():
        ap.error(f"--agent {ns.agent!r} is not a posix harness (want {'|'.join(posix_harnesses())})")
    if ns.timeout is None:
        ns.timeout = 60 if ns.worker == "inert" else 1800
    if ns.timeout < 1:
        ap.error("--timeout must be positive")
    return ns


def make_workdir(arg: str | None) -> Path:
    if arg:
        path = Path(arg).resolve()
        if path.exists() and any(path.iterdir()):
            raise SystemExit(f"first_run.py: --workdir {path} is not empty")
        path.mkdir(parents=True, exist_ok=True)
        return path
    return Path(tempfile.mkdtemp(prefix="open-fleet-first-run-")).resolve()


def emit(receipt: dict, path: Path, as_json: bool) -> None:
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if as_json:
        print(json.dumps(receipt, indent=2))
        return
    if "probes" in receipt:
        for p in receipt["probes"]:
            state = "REFUSED" if p["refused"] else "NOT-REFUSED"
            print(f"PROBE={p['probe']} {state} rc={p['rc']}" + (f" problems={p['problems']}" if p["problems"] else ""))
        print(f"PROBES={receipt['verdict']}")
    else:
        f = receipt["facts"]
        route = receipt["route"]
        failed = receipt["failure"]
        print(f"FIRST_RUN={receipt['verdict']}" + (f" step={failed['step']}" if failed else ""))
        print(f"ROUTE=posix/setsid PROFILE={route['profile']} HARNESS={route['harness']} "
              f"WORKER={route['worker']} TIER={receipt['tier']}")
        if "reviewed" in f:
            print(f"REVIEWED={f['reviewed']['base_sha']}..{f['reviewed']['head_sha']}")
        if "evidence" in f:
            verdict = "OK" if not failed or failed["step"] not in ("verify",) else "FAILED"
            print(f"EVIDENCE={f['evidence']['base_sha']}..{f['evidence']['head_sha']} VERIFY={verdict}")
        if "dispatch" in f:
            print(f"DISPATCH={f['dispatch']} TASK={f.get('task', '')}")
        if failed:
            print(f"FAILURE={failed['detail']}")
            if failed.get("recovery"):
                print(f"RECOVERY={failed['recovery']}")
        print(f"ELAPSED_S={receipt['elapsed_s']}")
    print(f"RECEIPT={path}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    workdir = make_workdir(args.workdir)
    agent = "claude" if args.mode == "probes" else args.agent
    sb = Sandbox(workdir, "inert" if args.mode == "probes" else args.worker, agent)
    previous = trap_termination()
    try:
        receipt = probes(sb) if args.mode == "probes" else FirstRun(args, sb).execute()
    finally:
        # Ctrl-C, `kill`, a closed terminal or any error mid-run too: setsid puts the worker in
        # its own session, out of reach of the signal that ended the run, so it would keep
        # running and spending (#596 review). A second signal is held off until it is stopped:
        # the run is ending either way.
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        try:
            stop_workers(sb)
        finally:
            restore_signals(previous)
    if receipt["verdict"] == "GO" and not args.keep:
        # Everything but the receipt goes: state store, clone, worktrees, verifier checkout.
        for child in workdir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink()
        receipt["sandbox_pruned"] = True
    emit(receipt, workdir / "receipt.json", args.json)
    return 0 if receipt["verdict"] == "GO" else 1


TRAPPED_SIGNALS = (signal.SIGTERM, signal.SIGHUP)


def _terminated(signum, _frame):
    """SIGTERM/SIGHUP unwind like Ctrl-C does, so main()'s `finally` stops the workers."""
    raise SystemExit(128 + signum)


def trap_termination() -> dict:
    """Install _terminated for TRAPPED_SIGNALS; return the handlers it replaced, to restore."""
    if threading.current_thread() is not threading.main_thread():
        return {}  # signal.signal works only on the main thread; nothing to restore
    return {sig: signal.signal(sig, _terminated) for sig in TRAPPED_SIGNALS}


def restore_signals(previous: dict) -> None:
    for sig, handler in previous.items():
        signal.signal(sig, signal.SIG_DFL if handler is None else handler)


def stop_workers(sb: Sandbox) -> None:
    """Fence anything still live in this sandbox's store before its directory goes away."""
    proc = run_text(py("orca_cli.py", "orchestration", "worker-list", "--json"),
                    cwd=str(sb.target) if sb.target.is_dir() else str(sb.dir), env=sb.env)
    try:
        workers = json.loads(proc.stdout)["result"]["workers"]
    except (ValueError, KeyError, TypeError):
        return
    for w in workers:
        if w.get("state") in LIVE_STATES:
            run_text(py("worker_ops.py", "stop", "--dispatch", w["dispatchId"]), env=sb.env, cwd=str(sb.dir))


if __name__ == "__main__":
    sys.exit(main())
