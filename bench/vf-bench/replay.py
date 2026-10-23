#!/usr/bin/env python3
"""replay.py — VF-Bench in one command, at a pinned revision, in a clean environment (#601).

`vfbench.py` scores the corpus in whatever checkout and shell runs it: the host's git, gh,
gitleaks, global git config and PATH all reach the verifier, so the score half-measures the host.
This runner pins the revision instead of trusting the checkout:

  run        export the pinned commit into a fresh temporary repository (`git init` + a LOCAL
             fetch of that one commit — never the network), run every case N times there under a
             built (not inherited) environment, one process per case with a timeout, and write
             one JSON report plus a short text summary.
  compare    diff two reports. Anything outside the host facts (`environment`), the raw refusal
             text (`diagnostics`) and wall time (`*wall_seconds`) must match, or it fails.
  reproduce  replay the revision and protocol a published report pins, then compare against it:
             the second-environment check CI runs (#601).
  drill      the deliberate negative controls: a revision with a corpus case deleted, one edited,
             a pinned fixture file deleted and one edited must each FAIL the replay, for that
             reason. A replay that cannot see a missing fixture would score a different corpus.

Each configuration is reported on its own, never as a pass rate: false acceptance (a trap
passed), false rejection (a valid control refused), RED for the wrong reason, coverage of the
README's verifier-check inventory, wall time, and the run-to-run spread with every case whose
verdict moved. The naive self-scorer is the SYNTHETIC BASELINE and is labelled so, never a
product score. External verifiers plug in through the adapter contract (README, "External
adapter contract"); when none was run, the report says UNMEASURED with a null score.

Stdlib only. Exit 0: a complete measurement (or, for compare/reproduce/drill, the check held).
Exit 1: it ran and failed — preflight, a skip, a timeout, an unscored case, a mismatch. Exit 2:
usage (unknown revision, unreadable report, unknown case).
"""
import argparse
import hashlib
import importlib.util
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SCHEMA = "vf-bench-replay@1"
ADAPTER_CONTRACT = "vf-bench-adapter@1"
BENCH = "bench/vf-bench"
SOUND = "open-fleet verify.py (sound)"
NAIVE = "self-scoring (naive)"
# The built-in gates' honesty labels. The naive gate grades the worker's own self-report: it is a
# synthetic baseline that shows what the traps do to a self-scorer, never a score for any product.
BUILTIN = {
    SOUND: ("measured", "open-fleet verify.py (sound)"),
    NAIVE: ("synthetic-baseline", "synthetic baseline (naive self-scorer), never a product score"),
}
PINNED_BLOBS = ("bench/vf-bench/VERSION", "bench/vf-bench/CANARY", "bench/vf-bench/gate.py",
                "bench/vf-bench/vfbench.py", "runtime/scripts/verify.py",
                "bench/vf-bench/heldout-protocol.json")
PINNED_TREES = ("bench/vf-bench/traps", "bench/vf-bench/fixtures", "runtime/scripts")
FIXTURE_PREFIX = "bench/vf-bench/fixtures/"
# Never compared: what varies by host, the raw refusal text (fixture SHAs and temp paths move
# every run), and wall time. Everything else in two reports of one revision must be equal.
COMPARE_EXCLUDED = ("environment", "diagnostics")
UNSCORED = ("timeout", "crash", "malformed", "error", "not-run")
DEFAULT_RUNS = 3
DEFAULT_CASE_TIMEOUT = 300
DEFAULT_ADAPTER_TIMEOUT = 60
UNMEASURED = {
    "name": None, "state": "unmeasured", "score": None,
    "reason": ("no real external verifier has been run through the adapter contract at this "
               "revision; an unmeasured verifier has no score, not a zero"),
}


class ReplayError(Exception):
    """A usage-level failure: the replay could not start, so nothing was measured."""


# ---------------------------------------------------------------------------------------------
# The clean environment
# ---------------------------------------------------------------------------------------------

def scrubbed_env(run_dir):
    """The WHOLE environment a replayed case sees, built rather than inherited (#601).

    PATH is one directory holding exactly `git`, `python3` and `python` — no host gh, gitleaks or
    tool shims — so a trap's verdict cannot depend on what this host happens to have installed.
    HOME and XDG_CONFIG_HOME are empty directories (no global git config: no signing, hooks or
    aliases), and the system git config is off. Nothing else crosses: no tokens, no PYTHONPATH,
    no ORCA_* or OPEN_FLEET_* variables. The one exception is the dynamic loader's
    LD_LIBRARY_PATH, kept when set: a shared-library Python (actions/setup-python on Linux)
    cannot start without it, and it names no tool."""
    env = {
        "PATH": str(run_dir / "bin"),
        "HOME": str(run_dir / "home"),
        "XDG_CONFIG_HOME": str(run_dir / "home" / ".config"),
        "TMPDIR": str(run_dir / "tmp"),
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "NO_COLOR": "1",
        "PYTHONUTF8": "1", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1",
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0",
    }
    if os.environ.get("LD_LIBRARY_PATH"):
        env["LD_LIBRARY_PATH"] = os.environ["LD_LIBRARY_PATH"]
    return env


def choose_git(explicit=None):
    """The git the replay links into its PATH. The system-owned one first (/usr/bin/git on macOS
    and on the GitHub runners): verify.py fails closed on a worker-writable git on a lane that
    claims soundness (h409 R2), and the same binary on every host keeps the export identical."""
    if explicit:
        if not (os.path.isfile(explicit) and os.access(explicit, os.X_OK)):
            raise ReplayError(f"--git {explicit} is not an executable file")
        return explicit
    for candidate in ("/usr/bin/git", "/bin/git"):
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    found = shutil.which("git")
    if not found:
        raise ReplayError("no git on this host")
    return found


def _home_relative(path):
    home = os.path.expanduser("~")
    path = str(path)
    return "~" + path[len(home):] if home not in ("", "/") and path.startswith(home) else path


def _git(args, cwd=None, env=None, git="git"):
    r = subprocess.run([git, *args], cwd=cwd, env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise ReplayError(f"git {' '.join(args)} failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def resolve_revision(source, rev):
    """(commit, tree) for `rev` in the source repository, or ReplayError."""
    try:
        commit = _git(["rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}"], cwd=source)
    except ReplayError:
        raise ReplayError(f"{rev!r} is not a commit in {source}") from None
    return commit, _git(["rev-parse", f"{commit}^{{tree}}"], cwd=source)


def export_revision(source, commit, dest, env, git):
    """A fresh repository holding the pinned commit and only the history it reaches.

    `git fetch` from a local path is the local transport (no network). Both refs/heads/main and
    refs/remotes/origin/main name the pinned commit, so the ancestry leg and every trap that pins
    a real commit read the same refs on every host — never whatever branches the source had."""
    dest.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], cwd=dest, env=env, git=git)
    _git(["fetch", "--no-tags", "--quiet", str(source), commit], cwd=dest, env=env, git=git)
    _git(["update-ref", "refs/heads/main", commit], cwd=dest, env=env, git=git)
    _git(["update-ref", "refs/remotes/origin/main", commit], cwd=dest, env=env, git=git)
    _git(["reset", "--quiet", "--hard", commit], cwd=dest, env=env, git=git)


def _object(export, env, git, path):
    r = subprocess.run([git, "rev-parse", "--verify", "--quiet", f"HEAD:{path}"], cwd=export,
                       env=env, capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


# ---------------------------------------------------------------------------------------------
# The driver: runs INSIDE the export, under the scrubbed environment, with the pinned bench
# ---------------------------------------------------------------------------------------------

def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def driver_probe(bench):
    """Everything the replay needs to know about the pinned bench before it scores anything: the
    corpus, each case's skip reason, the gates, the revision's own corpus pin and the git its
    signed-dispatch cases will run under (the bench's own custody probe, never a reimplementation)."""
    vf = _load(bench / "vfbench.py", "vfbench_replayed")
    out = {"gates": list(vf.GATES), "fixtures": sorted(getattr(vf, "FIXTURES", {}) or {})}
    version = (bench / "VERSION").read_text(encoding="utf-8") if (bench / "VERSION").exists() else ""
    canary = (bench / "CANARY").read_text(encoding="utf-8") if (bench / "CANARY").exists() else ""
    out["version"] = version.strip()
    out["canary_guids"] = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                                     canary)
    if (bench / "gate.py").exists():
        gate = _load(bench / "gate.py", "vfbench_gate_replayed")
        digest = gate.corpus_digest()
        out["corpus_sha256"] = digest
        out["corpus_pin"] = {"version": gate.EXPECTED_VERSION,
                             "canary_guid": gate.EXPECTED_CANARY_GUID,
                             "corpus_sha256": gate.EXPECTED_CORPUS_SHA256}
        out["corpus_errors"] = gate.check_corpus(version, canary, digest)
    else:
        out["corpus_sha256"] = out["corpus_pin"] = None
        out["corpus_errors"] = ["this revision has no bench/vf-bench/gate.py, so no corpus pin"]
    probe = getattr(vf, "_system_git_dir", None)
    out["system_custody_git_dir"] = probe() if probe else None
    out["cases"] = [{"id": t["id"], "class": t["class"], "sound_expected": t["sound_expected"],
                     "expect_reason": t.get("expect_reason"), "fixture": t.get("fixture"),
                     "skip": vf.skip_reason(t)} for t in vf.load_traps()]
    _emit(out)


def case_token(case_id):
    """The opaque handle an adapter gets for a case: stable across runs, never the id, the class
    or the expected verdict (#601)."""
    return hashlib.sha256(f"{ADAPTER_CONTRACT}\0{case_id}".encode("utf-8")).hexdigest()[:16]


_BOOLEAN_FLAGS = ("--no-gh", "--execute-nc")


def coordinator_inputs(argv):
    """verify.py's flag list → {name: value}. These are the coordinator's OUT-OF-BAND inputs —
    the contract, the class, the lighting, the lane, the proof command, the review repository and
    the signed dispatch record — which is exactly what an external verifier must receive too."""
    out, tokens = {}, iter(argv)
    for tok in tokens:
        if not tok.startswith("--"):
            raise ValueError(f"unexpected positional verifier argument {tok!r}")
        out[tok[2:].replace("-", "_")] = True if tok in _BOOLEAN_FLAGS else next(tokens)
    return out


def adapter_request(vf, trap, holder):
    """(request, cwd, env) for one case: what an external verifier receives (README, "External
    adapter contract"). A fixture-backed case is built fresh by the pinned bench and prepared by
    the SAME builder the sound gate uses (`fixture_command`), so the adapter sees what verify.py
    sees; a static case gets the coordinator fields the sound gate passes."""
    if trap.get("fixture") in vf.FIXTURES:
        repo = holder / "repo"
        facts = vf.FIXTURES[trap["fixture"]](repo)
        cmd, env = vf.fixture_command(trap, facts, repo, holder)
        coordinator = coordinator_inputs(cmd[2:])
        cwd = repo
    else:
        mpath = holder / "vf-manifest.json"
        mpath.write_text(json.dumps(trap["manifest"]), encoding="utf-8")
        coordinator = {"manifest": str(mpath)}
        for key in ("contract_source", "contract_digest", "unit_class", "base", "repo"):
            if trap.get(key):
                coordinator[key] = trap[key]
        if trap.get("execute_nc"):
            coordinator["execute_nc"] = True
            if trap.get("nc_command"):
                coordinator["nc_command"] = trap["nc_command"]
        cwd, env = vf.ROOT, dict(os.environ)
    manifest_path = coordinator.pop("manifest")
    request = {"contract": ADAPTER_CONTRACT, "case": {"token": case_token(trap["id"])},
               "workdir": str(cwd), "manifest_path": manifest_path,
               "manifest": json.loads(Path(manifest_path).read_text(encoding="utf-8")),
               "coordinator": coordinator}
    return request, cwd, env


def _kill_group(proc):
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        return


def parse_adapter_response(stdout):
    """A conforming answer, or a MALFORMED record. Anything but exactly one JSON object of the
    contract's shape is malformed — never a RED: a verifier that did not answer refused nothing."""
    def malformed(why):
        return {"status": "malformed", "error": why}
    try:
        obj = json.loads(stdout)
    except ValueError:
        return malformed("stdout is not exactly one JSON object")
    if not isinstance(obj, dict):
        return malformed("stdout is JSON but not an object")
    extra = sorted(set(obj) - {"contract", "verdict", "reasons", "verifier"})
    if extra:
        return malformed(f"unknown field(s) {extra}")
    if obj.get("contract") != ADAPTER_CONTRACT:
        return malformed(f"contract is {obj.get('contract')!r}, not {ADAPTER_CONTRACT!r}")
    verdict = obj.get("verdict")
    if verdict not in ("GREEN", "RED", "UNSUPPORTED"):
        return malformed(f"verdict is {verdict!r}, not GREEN, RED or UNSUPPORTED")
    reasons = obj.get("reasons", [])
    if not (isinstance(reasons, list) and all(isinstance(r, str) for r in reasons)):
        return malformed("reasons is not a list of strings")
    if verdict == "UNSUPPORTED" and not any(r.strip() for r in reasons):
        return malformed("UNSUPPORTED without a reason")
    who = obj.get("verifier")
    if not (isinstance(who, dict) and set(who) == {"name", "version"}
            and all(isinstance(v, str) and v.strip() for v in who.values())):
        return malformed("verifier is not {name, version}, both non-empty strings")
    if verdict == "UNSUPPORTED":
        return {"status": "unsupported", "reasons": reasons, "verifier": who}
    return {"status": "scored", "verdict": verdict, "reasons": reasons, "verifier": who}


# The process groups of the adapters this driver has running (PR #645 review). Each adapter gets
# its own group, so a kill of the driver's group never reaches it; the groups are therefore also
# written to --pgid-file, and the replay kills every group listed there whenever a case process
# ends, timed out or not. The driver's own exit path kills them too (see driver_main).
_ADAPTER_GROUPS = set()
_PGID_FILE = None


def _publish_groups():
    if _PGID_FILE:
        Path(_PGID_FILE).write_text("".join(f"{g}\n" for g in sorted(_ADAPTER_GROUPS)),
                                    encoding="utf-8")


def kill_groups(pgids):
    """SIGKILL each process group; one already gone is skipped."""
    for pgid in pgids:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue


def run_adapter(vf, trap, adapter, timeout):
    """One case through one external adapter, with the four outcomes kept apart: a conforming
    verdict (scored), a declared UNSUPPORTED, and three failures that are NEVER scored — a timeout
    (process group killed), a crash (non-zero exit) and a malformed answer.

    The adapter's stdio are files, not pipes: a process it leaves behind cannot hold a pipe open
    and turn a finished answer into a timeout. Whatever it leaves behind in its process group is
    killed once it has answered (PR #645 review)."""
    holder = Path(tempfile.mkdtemp(prefix="vfbench-adapter-"))
    try:
        request, cwd, env = adapter_request(vf, trap, holder)
        stdin, stdout, stderr = (holder / n for n in ("request.json", "stdout", "stderr"))
        stdin.write_text(json.dumps(request), encoding="utf-8")
        with open(stdin, "rb") as fin, open(stdout, "wb") as fout, open(stderr, "wb") as ferr:
            try:
                proc = subprocess.Popen(adapter["argv"], cwd=cwd, env=env, stdin=fin,
                                        stdout=fout, stderr=ferr, start_new_session=True)
            except OSError as exc:
                return {"status": "crash", "error": f"the adapter could not start: {exc}"}
            _ADAPTER_GROUPS.add(proc.pid)
            _publish_groups()
            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            finally:
                kill_groups([proc.pid])
                proc.wait()
                _ADAPTER_GROUPS.discard(proc.pid)
                _publish_groups()
        if timed_out:
            return {"status": "timeout", "error": f"no answer within {timeout} s; process group killed"}
        err = stderr.read_text(encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            return {"status": "crash", "error": f"the adapter exited {proc.returncode}",
                    "stderr": err.strip()[-400:]}
        return parse_adapter_response(stdout.read_text(encoding="utf-8", errors="replace"))
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def driver_case(bench, case_id, adapters, adapter_timeout):
    """Every configuration for ONE case, in order, one JSON line as each starts and finishes — so
    when the replay kills a case that ran out of time, it knows which configuration was running."""
    vf = _load(bench / "vfbench.py", "vfbench_replayed")
    trap = next(t for t in vf.load_traps() if t["id"] == case_id)
    for name, gate in vf.GATES.items():
        _emit({"start": name})
        t0, detail = time.monotonic(), {}
        try:
            passed = gate(trap, detail)
            rec = {"status": "scored", "verdict": "GREEN" if passed else "RED",
                   "reasons": detail.get("fails"), "gives_reasons": "fails" in detail}
        except Exception as exc:  # vfbench raises on a broken verifier run: not a verdict (#257)
            rec = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:600]}
        rec.update(done=name, wall_seconds=round(time.monotonic() - t0, 3))
        _emit(rec)
    for adapter in adapters:
        _emit({"start": adapter["name"]})
        t0 = time.monotonic()
        rec = run_adapter(vf, trap, adapter, adapter_timeout)
        rec.update(done=adapter["name"], wall_seconds=round(time.monotonic() - t0, 3))
        _emit(rec)


def driver_main(args):
    """The case driver's entry: whichever way it ends — a return, an exception, or a TERM, HUP or
    INT turned into an exit — no adapter process group it started outlives it. A SIGKILL skips
    this; the replay then kills the groups listed in --pgid-file instead."""
    global _PGID_FILE
    _PGID_FILE = args.pgid_file

    def _exit(signum, frame):
        raise SystemExit(128 + signum)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _exit)
    try:
        driver_case(Path(args.bench), args.case, json.loads(args.adapters), args.adapter_timeout)
    finally:
        kill_groups(list(_ADAPTER_GROUPS))
        _ADAPTER_GROUPS.clear()
        _publish_groups()
    return 0


# ---------------------------------------------------------------------------------------------
# Preflight: the replay refuses to score a corpus it cannot identify
# ---------------------------------------------------------------------------------------------

def _named_fixture_paths(obj):
    if isinstance(obj, str):
        return [obj] if obj.startswith(FIXTURE_PREFIX) else []
    if isinstance(obj, list):
        return [p for x in obj for p in _named_fixture_paths(x)]
    if isinstance(obj, dict):
        return [p for x in obj.values() for p in _named_fixture_paths(x)]
    return []


def fixture_failures(export, traps, builders):
    """Every committed fixture a case names must be in the export, and every one it PINS must
    still hash to the pin: the coordinator's contract digest and the manifest's artifacts[]. The
    corpus digest covers traps/*.json only, so without this a deleted or edited fixture file
    would replay as a different corpus under the same pin. Run-time fixtures must name a builder
    the pinned vfbench.py defines."""
    failures = []
    for t in traps:
        if t.get("fixture") is not None:
            if t["fixture"] not in builders:
                failures.append({"kind": "fixture-builder-missing", "case": t["id"],
                                 "detail": f"names run-time fixture {t['fixture']!r}, which "
                                           f"vfbench.py at this revision does not build"})
            continue
        pins = {p: None for p in _named_fixture_paths(t)}
        if t.get("contract_source"):
            pins[t["contract_source"]] = t.get("contract_digest")
        for art in (t.get("manifest") or {}).get("artifacts") or []:
            if art.get("path") and art.get("sha256"):
                pins[art["path"]] = "sha256:" + art["sha256"]
        for path, digest in sorted(pins.items()):
            f = export / path
            if not f.is_file():
                failures.append({"kind": "fixture-missing", "case": t["id"],
                                 "detail": f"names {path}, which the exported revision lacks"})
                continue
            got = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
            if digest and got != digest:
                failures.append({"kind": "fixture-changed", "case": t["id"],
                                 "detail": f"pins {path} at {digest[:23]}…, the exported file "
                                           f"hashes to {got[:23]}…"})
    return failures


def inventory_rows(readme):
    """The README's verifier-check inventory (#600) as [{checks, status, cases}], or None when
    the revision has none. Coverage is measured against it: rows are the invariants."""
    if "## Verifier check inventory" not in readme:
        return None
    section = readme.split("## Verifier check inventory", 1)[1].split("\n## ", 1)[0]
    rows = []
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 4:
            continue
        rows.append({"checks": re.findall(r"`([\w.]+)`", cells[0]), "status": cells[2],
                     "cases": re.findall(r"`([^`]+)`", cells[3]) if cells[2] == "trap" else []})
    return rows


# ---------------------------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------------------------

def _ratio(count, of):
    return {"count": count, "of": of, "rate": round(count / of, 4) if of else None}


def _coverage(rows, scored_classes):
    if rows is None:
        return {"state": "this revision carries no verifier-check inventory", "rate": None}
    by_status = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    sampled = [r for r in rows if r["status"] == "trap" and set(r["cases"]) & scored_classes]
    checks = {c for r in rows for c in r["checks"]}
    return {"inventory_rows": len(rows), "by_status": by_status, "sampled_rows": len(sampled),
            "rate": round(len(sampled) / len(rows), 4) if rows else None,
            "checks": len(checks), "checks_sampled": len({c for r in sampled for c in r["checks"]})}


def score_run(cases, results, rows):
    """One configuration's metrics for one run. Only SCORED cases count; every other status is
    listed by kind, so a configuration that answered fewer cases cannot look the same."""
    scored = [c for c in cases if results[c["id"]]["status"] == "scored"]
    traps = [c for c in scored if c["sound_expected"] == "RED"]
    controls = [c for c in scored if c["sound_expected"] == "GREEN"]
    fa = sum(1 for c in traps if results[c["id"]]["verdict"] == "GREEN")
    fr = sum(1 for c in controls if results[c["id"]]["verdict"] == "RED")
    judged = [c for c in traps if results[c["id"]].get("reason_matched") is not None]
    wrong = sum(1 for c in judged if results[c["id"]]["reason_matched"] is False)
    statuses = {}
    for c in cases:
        s = results[c["id"]]["status"]
        if s != "scored":
            statuses[s] = statuses.get(s, 0) + 1
    return {"false_acceptance": _ratio(fa, len(traps)),
            "false_rejection": _ratio(fr, len(controls)),
            "wrong_reason": _ratio(wrong, len(judged)) if judged else None,
            "not_scored": statuses,
            "coverage": _coverage(rows, {c["class"] for c in scored}),
            "wall_seconds": round(sum(results[c["id"]].get("wall_seconds", 0.0) for c in cases), 3)}


def _spread(values):
    return {"per_run": values, "min": min(values), "max": max(values),
            "spread": max(values) - min(values)}


def aggregate(per_run):
    """The repeated-run view: each count per run with its spread, never one run's number alone."""
    out = {}
    for key in ("false_acceptance", "false_rejection", "wrong_reason"):
        counts = [r[key]["count"] if r[key] else None for r in per_run]
        out[key] = None if None in counts else {**_spread(counts), "of": per_run[0][key]["of"]}
    rates = [r["coverage"].get("rate") for r in per_run]
    out["coverage_rate"] = None if None in rates else _spread(rates)
    walls = [r["wall_seconds"] for r in per_run]
    out["wall_seconds"] = {"per_run": walls, "mean": round(sum(walls) / len(walls), 3),
                           "min": min(walls), "max": max(walls)}
    return out


# ---------------------------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------------------------

def _run_driver(python, args, cwd, env, timeout, pgid_file=None):
    """Run one driver process; kill its process group if it outlives `timeout`, and then kill
    every adapter process group it recorded in `pgid_file` — those are separate groups, which the
    first kill cannot reach (PR #645 review)."""
    argv = [python, "-I", "-B", "-X", "utf8", str(Path(__file__).resolve()), "_driver", *args]
    if pgid_file:
        argv += ["--pgid-file", str(pgid_file)]
    proc = subprocess.Popen(argv, cwd=cwd, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        out, err = proc.communicate()
        timed_out = True
    finally:
        if pgid_file and Path(pgid_file).exists():
            kill_groups(int(g) for g in Path(pgid_file).read_text(encoding="utf-8").split())
            Path(pgid_file).unlink()
    records = []
    for line in (out or "").splitlines():
        if line.startswith("{"):
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
    return records, timed_out, proc.returncode, (err or "").strip()


def parse_adapter_spec(spec, tier):
    name, sep, command = spec.partition("=")
    name = name.strip()  # stripped FIRST: a padded built-in name is still that name (PR #645)
    if not (sep and name and command.strip()):
        raise ReplayError(f"adapter spec {spec!r} is not NAME=COMMAND")
    check_adapter_names([{"name": name}], BUILTIN)
    argv = shlex.split(command)
    # The adapter runs from the case's workdir, so a program given as a path is made absolute.
    if os.sep in argv[0] or Path(argv[0]).exists():
        argv[0] = str(Path(argv[0]).resolve())
    argv = [str(Path(a).resolve()) if (os.sep in a and Path(a).exists()) else a for a in argv]
    return {"name": name.strip(), "tier": tier, "argv": argv}


def check_adapter_names(adapters, gates):
    """Refuse any adapter name that is not unique among the configurations (PR #645 review).
    Answers and results are keyed by configuration name, so a name shared with a gate or another
    adapter would overwrite that configuration's results — an adapter's answers scored as the
    sound gate's. Checked against the built-in names before anything runs, and again against the
    gates the pinned revision actually loads before any case is scored."""
    taken = {g: "a gate" for g in gates}
    for a in adapters:
        name = a["name"]
        if not name or name != name.strip():
            raise ReplayError(f"adapter name {name!r} is empty or padded with whitespace")
        if name in taken:
            raise ReplayError(f"adapter name {name!r} is already {taken[name]}: results are "
                              f"keyed by name, so it would overwrite that configuration's answers")
        taken[name] = "another adapter"


def replay(source, rev, runs=DEFAULT_RUNS, case_timeout=DEFAULT_CASE_TIMEOUT,
           adapter_timeout=DEFAULT_ADAPTER_TIMEOUT, adapters=(), selection=None, git=None,
           python=None, keep=None):
    """Run the replay and return the report (a dict). Raises ReplayError on usage problems."""
    if runs < 1:
        raise ReplayError("--runs must be at least 1")
    check_adapter_names(adapters, BUILTIN)
    source = Path(source).resolve()
    commit, tree = resolve_revision(source, rev)
    git = choose_git(git)
    python = python or sys.executable
    started = time.monotonic()
    run_dir = Path(tempfile.mkdtemp(prefix="vfbench-replay-")).resolve()
    try:
        for sub in ("home/.config", "tmp", "bin"):
            (run_dir / sub).mkdir(parents=True)
        for name, target in (("git", git), ("python3", python), ("python", python)):
            (run_dir / "bin" / name).symlink_to(target)
        env = scrubbed_env(run_dir)
        gitbin = str(run_dir / "bin" / "git")
        export = run_dir / "export"
        export_revision(source, commit, export, env, gitbin)
        report = _measure(export, env, gitbin, python, commit, tree, rev, runs, case_timeout,
                          adapter_timeout, list(adapters), selection)
        report["environment"].update({
            "git": _home_relative(git),
            "git_version": _git(["--version"], env=env, git=gitbin),
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_executable": _home_relative(python),
            "platform": platform.platform(),
            "env_keys": sorted(env),
            "path": {n: _home_relative(os.readlink(run_dir / "bin" / n))
                     for n in sorted(os.listdir(run_dir / "bin"))},
            "tool": {"path": "bench/vf-bench/replay.py",
                     "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
            "adapter_commands": {a["name"]: " ".join(_home_relative(x) for x in a["argv"])
                                 for a in adapters},
        })
        report["wall_seconds"] = round(time.monotonic() - started, 3)
        return report
    finally:
        if keep:
            shutil.copytree(run_dir / "export", keep, symlinks=True, dirs_exist_ok=True)
        shutil.rmtree(run_dir, ignore_errors=True)


def _measure(export, env, gitbin, python, commit, tree, rev, runs, case_timeout, adapter_timeout,
             adapters, selection):
    bench = export / BENCH
    report = {
        "schema": SCHEMA,
        "revision": {"commit": commit, "tree": tree},
        "versions": {"blobs": {p: _object(export, env, gitbin, p) for p in PINNED_BLOBS},
                     "trees": {p: _object(export, env, gitbin, p) for p in PINNED_TREES}},
        "protocol": {"runs": runs, "case_timeout_seconds": case_timeout,
                     "adapter_timeout_seconds": adapter_timeout,
                     "selection": sorted(selection) if selection else None,
                     "order": "corpus file order, the same in every run; one process per case",
                     "export": "git init + local fetch of the pinned commit (no network); "
                               "refs/heads/main and refs/remotes/origin/main both name it",
                     "environment": "built, not inherited: PATH holds only git and python"},
        "preflight": {"ok": True, "failures": []},
        "corpus": None, "skipped": [], "configurations": {}, "unsupported": [], "timeouts": [],
        "unscored": [], "external_verifiers": [], "heldout": None,
        "verdict": {"ok": False, "failures": []},
        # How the operator NAMED the revision is an input, not a result: `HEAD` here and a SHA
        # in the reproducing environment pin the same commit.
        "environment": {"requested_revision": rev}, "diagnostics": {},
    }
    if not (bench / "vfbench.py").is_file():
        report["preflight"] = {"ok": False, "failures": [
            {"kind": "not-a-vf-bench-revision", "case": None,
             "detail": "the exported revision has no bench/vf-bench/vfbench.py"}]}
        return _finish(report)
    records, timed_out, code, err = _run_driver(python, ["probe", "--bench", str(bench)],
                                                export, env, case_timeout)
    if timed_out or code != 0 or not records:
        report["preflight"] = {"ok": False, "failures": [
            {"kind": "probe-failed", "case": None,
             "detail": "the pinned bench could not be loaded: "
                       + ("timed out" if timed_out else err[-600:] or f"exit {code}")}]}
        return _finish(report)
    probe = records[-1]
    gates = probe["gates"]
    check_adapter_names(adapters, gates)
    configs = [{"name": n, "tier": BUILTIN.get(n, ("unlabelled-gate", ""))[0],
                "label": BUILTIN.get(n, ("", f"{n} (a gate this runner has no label for)"))[1]}
               for n in gates]
    kinds = {"fixture-adapter": "fixture adapter, never a product score",
             "external-adapter": "external verifier, operator-declared"}
    configs += [{"name": a["name"], "tier": a["tier"], "label": f"{a['name']} ({kinds[a['tier']]})"}
                for a in adapters]
    report["protocol"]["configurations"] = [{"name": c["name"], "tier": c["tier"]} for c in configs]
    report["versions"].update({
        "vf_bench": probe["version"], "canary_guids": probe["canary_guids"],
        "corpus_sha256": probe["corpus_sha256"], "corpus_pin": probe["corpus_pin"]})
    report["environment"]["system_custody_git_dir"] = probe["system_custody_git_dir"]
    report["environment"]["signed_dispatch_git"] = (
        f"signed-dispatch cases run under {probe['system_custody_git_dir']}/git, the first git "
        f"verify.py's own custody probe classes 'system' (h409 R2)"
        if probe["system_custody_git_dir"] else
        "no system-custody git on this host: the signed-dispatch cases are skipped by name")
    all_cases = probe["cases"]
    if selection:
        unknown = sorted(set(selection) - {c["id"] for c in all_cases})
        if unknown:
            raise ReplayError(f"--cases names no corpus case: {', '.join(unknown)}")
    cases = [c for c in all_cases if not selection or c["id"] in selection]
    report["corpus"] = {
        "total": len(all_cases),
        "traps": sum(1 for c in all_cases if c["sound_expected"] == "RED"),
        "valid_controls": sum(1 for c in all_cases if c["sound_expected"] == "GREEN"),
        "selected": len(cases),
        "cases": [{k: c[k] for k in ("id", "class", "sound_expected", "expect_reason")}
                  for c in cases]}
    traps = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((bench / "traps").glob("*.json"))]
    failures = [{"kind": "corpus-drift", "case": None, "detail": e} for e in probe["corpus_errors"]]
    failures += fixture_failures(export, [t for t in traps if not selection or t["id"] in selection],
                                 set(probe["fixtures"]))
    protocol_file = bench / "heldout-protocol.json"
    if protocol_file.is_file():
        try:
            held = json.loads(protocol_file.read_text(encoding="utf-8"))
            report["heldout"] = {"protocol": held.get("protocol"), "status": held.get("status"),
                                 "holder": (held.get("holder") or {}).get("state")}
        except ValueError:
            failures.append({"kind": "heldout-protocol-unreadable", "case": None,
                             "detail": "bench/vf-bench/heldout-protocol.json is not JSON"})
    else:
        report["heldout"] = {"protocol": None, "status": "no held-out protocol at this revision",
                             "holder": None}
    if failures:
        report["preflight"] = {"ok": False, "failures": failures}
        return _finish(report)

    report["skipped"] = [{"id": c["id"], "class": c["class"], "reason": c["skip"]}
                         for c in cases if c["skip"]]
    live = [c for c in cases if not c["skip"]]
    names = [c["name"] for c in configs]
    spec = json.dumps([{"name": a["name"], "argv": a["argv"]} for a in adapters])
    budget = case_timeout + len(adapters) * (adapter_timeout + 5)
    results = {n: {c["id"]: [] for c in live} for n in names}
    for _ in range(runs):
        for c in live:
            records, timed_out, code, err = _run_driver(
                python, ["case", "--bench", str(bench), "--case", c["id"], "--adapters", spec,
                         "--adapter-timeout", str(adapter_timeout)], export, env, budget,
                pgid_file=export.parent / "adapter-groups")
            started = {r["start"] for r in records if "start" in r}
            done = {r["done"]: r for r in records if "done" in r}
            for n in names:
                rec = done.get(n)
                if rec is None:
                    if timed_out and n in started:
                        rec = {"status": "timeout",
                               "error": f"the case ran past {budget} s; process group killed"}
                    elif timed_out:
                        rec = {"status": "not-run",
                               "error": "the case process timed out before this configuration ran"}
                    else:
                        rec = {"status": "error",
                               "error": f"the case process exited {code} with no result: {err[-400:]}"}
                if (rec["status"] == "scored" and rec.get("gives_reasons")
                        and c["sound_expected"] == "RED" and rec["verdict"] == "RED"
                        and c.get("expect_reason")):
                    rec["reason_matched"] = any(c["expect_reason"] in r
                                                for r in rec.get("reasons") or [])
                results[n][c["id"]].append(rec)

    rows = inventory_rows((bench / "README.md").read_text(encoding="utf-8")
                          if (bench / "README.md").is_file() else "")
    for cfg in configs:
        n = cfg["name"]
        per_run = [score_run(live, {cid: results[n][cid][i] for cid in results[n]}, rows)
                   for i in range(runs)]
        case_view, unstable = {}, []
        for c in live:
            recs = results[n][c["id"]]
            view = {"statuses": [r["status"] for r in recs],
                    "verdicts": [r.get("verdict") for r in recs]}
            if any("reason_matched" in r for r in recs):
                view["reason_matched"] = [r.get("reason_matched") for r in recs]
            case_view[c["id"]] = view
            if len({(r["status"], r.get("verdict"), r.get("reason_matched")) for r in recs}) > 1:
                unstable.append({"id": c["id"], "statuses": view["statuses"],
                                 "verdicts": view["verdicts"]})
            first = recs[0]
            interesting = (first["status"] != "scored" or first.get("reason_matched") is False
                           or (first.get("verdict") == "GREEN") == (c["sound_expected"] == "RED"))
            note = {"reasons": [r[:240] for r in (first.get("reasons") or [])[:3]],
                    **{k: first[k] for k in ("error", "stderr") if first.get(k)}}
            if (interesting or cfg["tier"] in ("fixture-adapter", "external-adapter")) and (
                    note["reasons"] or len(note) > 1):
                report["diagnostics"].setdefault(n, {})[c["id"]] = note
            for status, bucket in (("unsupported", "unsupported"), ("timeout", "timeouts")):
                hit = [i + 1 for i, r in enumerate(recs) if r["status"] == status]
                if hit:
                    entry = {"configuration": n, "id": c["id"], "runs": hit}
                    if status == "unsupported":
                        entry["reasons"] = recs[hit[0] - 1].get("reasons")
                    report[bucket].append(entry)
            for status in ("crash", "malformed", "error", "not-run"):
                hit = [i + 1 for i, r in enumerate(recs) if r["status"] == status]
                if hit:
                    report["unscored"].append({"configuration": n, "id": c["id"],
                                               "status": status, "runs": hit})
        entry = {"tier": cfg["tier"], "label": cfg["label"],
                 "metrics": aggregate(per_run), "runs": per_run, "cases": case_view,
                 "unstable_cases": unstable}
        if cfg["tier"] in ("fixture-adapter", "external-adapter"):
            seen = sorted({json.dumps(r["verifier"], sort_keys=True)
                           for cid in results[n] for r in results[n][cid] if r.get("verifier")})
            entry["verifier_versions"] = [json.loads(s) for s in seen]
            entry["wrong_reason_note"] = ("an external verifier's reasons are recorded, never "
                                          "matched against verify.py's wording")
        report["configurations"][n] = entry
    external = [a for a in adapters if a["tier"] == "external-adapter"]
    report["external_verifiers"] = (
        [{"name": a["name"], "state": "measured (operator-declared external verifier)",
          "verifier_versions": report["configurations"][a["name"]]["verifier_versions"]}
         for a in external] or [dict(UNMEASURED)])
    return _finish(report)


def _finish(report):
    failures = [f"preflight {f['kind']}: {f['case'] + ': ' if f.get('case') else ''}{f['detail']}"
                for f in report["preflight"]["failures"]]
    failures += [f"skipped {s['id']}: {s['reason']}" for s in report["skipped"]]
    def runs(item):
        return ", ".join(map(str, item["runs"]))
    failures += [f"timeout {t['configuration']} / {t['id']} (run {runs(t)})"
                 for t in report["timeouts"]]
    failures += [f"{u['status']} {u['configuration']} / {u['id']} (run {runs(u)})"
                 for u in report["unscored"]]
    for name, cfg in report["configurations"].items():
        if len(cfg.get("verifier_versions") or []) > 1:
            failures.append(f"{name} reported more than one verifier version in one replay — "
                            "not a pinned measurement")
    report["verdict"] = {"ok": not failures, "failures": failures}
    return report


# ---------------------------------------------------------------------------------------------
# Summary, compare, reproduce, drill
# ---------------------------------------------------------------------------------------------

def _fmt_ratio(m):
    if not m:
        return "n/a"
    lo, hi, of = m["min"], m["max"], m["of"]
    count = f"{lo}" if lo == hi else f"{lo}-{hi}"
    rate = f"{100 * hi / of:.1f}%" if of else "-"
    return f"{count}/{of} {rate}"


def render_summary(report):
    rev, ver, proto = report["revision"], report["versions"], report["protocol"]
    env = report.get("environment") or {}
    pin = ver.get("corpus_pin") or {}
    pinned = bool(pin) and pin.get("corpus_sha256") == ver.get("corpus_sha256")
    lines = [f"VF-Bench replay ({report['schema']}) at {rev['commit'][:12]}"
             f" (requested {env.get('requested_revision')!r})"]
    blobs = ver.get("blobs") or {}
    lines.append("versions: " + " · ".join(
        [f"{ver.get('vf_bench') or '?'}", f"corpus {str(ver.get('corpus_sha256'))[:12]}… "
         f"({'= pin' if pinned else 'NOT the pin'})"]
        + [f"{Path(p).name} {(b or 'absent')[:10]}" for p, b in blobs.items()
           if p.endswith((".py",))]))
    corpus = report.get("corpus") or {}
    scope = ("full corpus" if not proto.get("selection") else
             f"SUBSET of {len(proto['selection'])} case(s) — not a full-corpus replay")
    lines.append(f"protocol: {proto['runs']} run(s) · case timeout {proto['case_timeout_seconds']} s · "
                 f"{scope} ({corpus.get('total', '?')} cases: {corpus.get('traps', '?')} traps, "
                 f"{corpus.get('valid_controls', '?')} valid controls) · clean export, built env")
    if env:
        lines.append(f"environment: {env.get('platform')} · Python {env.get('python')} · "
                     f"{env.get('git_version')} ({env.get('git')}) · {env.get('signed_dispatch_git')}")
    if not report["preflight"]["ok"]:
        lines.append("PREFLIGHT FAILED — nothing was scored:")
        lines += [f"  {f['kind']}: {(f['case'] + ': ') if f.get('case') else ''}{f['detail']}"
                  for f in report["preflight"]["failures"]]
    else:
        lines.append("")
        lines.append(f"{'configuration':<62} {'false accept':<14} {'false reject':<14} "
                     f"{'wrong reason':<13} {'coverage':<10} {'wall mean':<10} stable")
        for name, cfg in report["configurations"].items():
            m = cfg["metrics"]
            cov = m.get("coverage_rate")
            covs = "n/a" if not cov else (f"{100 * cov['min']:.0f}%" if cov["spread"] == 0
                                          else f"{100 * cov['min']:.0f}-{100 * cov['max']:.0f}%")
            wall = m["wall_seconds"]["mean"]
            stable = "yes" if not cfg["unstable_cases"] else f"NO ({len(cfg['unstable_cases'])} moved)"
            lines.append(f"{cfg['label'][:62]:<62} {_fmt_ratio(m['false_acceptance']):<14} "
                         f"{_fmt_ratio(m['false_rejection']):<14} {_fmt_ratio(m['wrong_reason']):<13} "
                         f"{covs:<10} {wall:>7.1f} s  {stable}")
        lines.append("")
    ext = report.get("external_verifiers") or []
    for e in ext:
        if e.get("state") == "unmeasured":
            lines.append("external verifiers: UNMEASURED — " + e["reason"] + ".")
        else:
            lines.append(f"external verifier {e['name']}: {e['state']}")
    held = report.get("heldout") or {}
    if held:
        lines.append(f"held-out split: {held.get('status')}"
                     + (f" (holder: {held['holder']})" if held.get("holder") else ""))
    for key, label in (("skipped", "skipped"), ("unsupported", "unsupported"),
                       ("timeouts", "timeouts"), ("unscored", "unscored")):
        items = report.get(key) or []
        names = ", ".join(i["id"] if "configuration" not in i else f"{i['configuration']}/{i['id']}"
                          for i in items[:6])
        more = ", …" if len(items) > 6 else ""
        lines.append(f"{label}: {len(items)}" + (f" ({names}{more})" if items else ""))
    v = report["verdict"]
    lines.append("verdict: " + (
        "OK — a complete measurement of the pinned revision" if v["ok"] else
        f"FAILED ({len(v['failures'])} problem(s)): " + "; ".join(v["failures"][:4])))
    return "\n".join(lines) + "\n"


def comparable(obj):
    """The report minus what may differ between environments (COMPARE_EXCLUDED and wall time)."""
    if isinstance(obj, dict):
        return {k: comparable(v) for k, v in obj.items()
                if k not in COMPARE_EXCLUDED and not k.endswith("wall_seconds")}
    if isinstance(obj, list):
        return [comparable(v) for v in obj]
    return obj


def diff(a, b, path="$"):
    """Every difference between two JSON values, as `path: a != b` lines."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: absent in the first report")
            elif k not in b:
                out.append(f"{path}.{k}: absent in the second report")
            else:
                out += diff(a[k], b[k], f"{path}.{k}")
        return out
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            shown = f" ({json.dumps(a)[:160]} != {json.dumps(b)[:160]})" if len(a) + len(b) < 12 else ""
            return [f"{path}: {len(a)} item(s) != {len(b)} item(s){shown}"]
        return [d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in diff(x, y, f"{path}[{i}]")]
    if a != b:
        return [f"{path}: {json.dumps(a)[:160]} != {json.dumps(b)[:160]}"]
    return []


def load_report(path):
    try:
        report = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReplayError(f"cannot read report {path}: {exc}") from None
    if not isinstance(report, dict) or report.get("schema") != SCHEMA:
        raise ReplayError(f"{path} is not a {SCHEMA} report")
    return report


def compare(a, b):
    return diff(comparable(a), comparable(b))


def _write(report, out, summary):
    text = render_summary(report)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    if summary:
        Path(summary).parent.mkdir(parents=True, exist_ok=True)
        Path(summary).write_text(text, encoding="utf-8")
    sys.stdout.write(text)


DRILLS = (
    ("missing-case", "corpus-drift", "a corpus case file deleted"),
    ("changed-case", "corpus-drift", "a corpus case file edited (a trap's verdict flipped)"),
    ("missing-fixture", "fixture-missing", "the contract file a case pins, deleted"),
    ("changed-fixture", "fixture-changed", "the contract file a case pins, edited"),
)


def _mutate(repo, drill):
    traps = sorted((repo / BENCH / "traps").glob("*.json"))
    if not traps:
        raise ReplayError("the revision has no corpus to mutate")
    if drill in ("missing-case", "changed-case"):
        target = traps[0]
        if drill == "missing-case":
            target.unlink()
        else:
            t = json.loads(target.read_text(encoding="utf-8"))
            t["sound_expected"] = "GREEN" if t["sound_expected"] == "RED" else "RED"
            target.write_text(json.dumps(t, indent=2) + "\n", encoding="utf-8")
        return target.relative_to(repo).as_posix()
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in traps]
    pinned = [t["contract_source"] for t in cases
              if not t.get("fixture") and t.get("contract_digest")
              and str(t.get("contract_source") or "").startswith(FIXTURE_PREFIX)]
    if not pinned:
        raise ReplayError("no corpus case pins a committed fixture file at this revision")
    target = repo / sorted(pinned)[0]
    if drill == "missing-fixture":
        target.unlink()
    else:
        target.write_text(target.read_text(encoding="utf-8") + "- AC-9: added by the drill\n",
                          encoding="utf-8")
    return target.relative_to(repo).as_posix()


def drill(source, rev, git=None, python=None):
    """Each deliberate mutation must FAIL the replay with the named preflight kind. Mutations are
    commits in a throwaway copy of the revision; the source repository is never written."""
    source = Path(source).resolve()
    commit, _ = resolve_revision(source, rev)
    gitpath = choose_git(git)
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="vfbench-drill-") as tmp:
        tmp = Path(tmp).resolve()
        for sub in ("home/.config", "tmp", "bin"):
            (tmp / sub).mkdir(parents=True)
        (tmp / "bin" / "git").symlink_to(gitpath)
        env = scrubbed_env(tmp)
        copy = tmp / "copy"
        export_revision(source, commit, copy, env, gitpath)
        for name, kind, what in DRILLS:
            _git(["reset", "--quiet", "--hard", commit], cwd=copy, env=env, git=gitpath)
            path = _mutate(copy, name)
            _git(["add", "-A"], cwd=copy, env=env, git=gitpath)
            _git(["-c", "user.name=vf-drill", "-c", "user.email=drill@vf-bench.invalid",
                  "-c", "commit.gpgsign=false", "commit", "--quiet", "--no-verify", "-m",
                  f"drill: {name}"], cwd=copy, env=env, git=gitpath)
            mutated = _git(["rev-parse", "HEAD"], cwd=copy, env=env, git=gitpath)
            report = replay(copy, mutated, runs=1, git=git, python=python)
            kinds = [f["kind"] for f in report["preflight"]["failures"]]
            held = (not report["verdict"]["ok"]) and kind in kinds
            outcomes.append({"drill": name, "what": what, "path": path, "expected": kind,
                             "replay_failed": not report["verdict"]["ok"], "kinds": kinds,
                             "held": held, "first_failure": (report["verdict"]["failures"] or [""])[0]})
    return outcomes


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["_driver"]:
        ap = argparse.ArgumentParser(prog="replay.py _driver")
        ap.add_argument("mode", choices=("probe", "case"))
        ap.add_argument("--bench", required=True)
        ap.add_argument("--case")
        ap.add_argument("--adapters", default="[]")
        ap.add_argument("--adapter-timeout", type=float, default=DEFAULT_ADAPTER_TIMEOUT)
        ap.add_argument("--pgid-file")
        a = ap.parse_args(argv[1:])
        if a.mode == "probe":
            driver_probe(Path(a.bench))
            return 0
        return driver_main(a)

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--repo", default=str(ROOT), help="source repository (default: this one)")
        p.add_argument("--git", help="the git to link into the replay's PATH (default: /usr/bin/git)")
        p.add_argument("--python", help="interpreter for the replay (default: this one)")
        p.add_argument("--out", help="write the JSON report here")
        p.add_argument("--summary", help="write the text summary here")
        p.add_argument("--adapter", action="append", default=[], metavar="NAME=COMMAND",
                       help="an external verifier behind the adapter contract (operator-declared)")
        p.add_argument("--fixture-adapter", action="append", default=[], metavar="NAME=COMMAND",
                       help="a fake or reference adapter; scored, labelled never a product score")
    p_run = sub.add_parser("run", help="replay a pinned revision in a clean environment")
    p_run.add_argument("--rev", default="HEAD", help="the revision to pin (default: HEAD)")
    p_run.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    p_run.add_argument("--case-timeout", type=int, default=DEFAULT_CASE_TIMEOUT)
    p_run.add_argument("--adapter-timeout", type=int, default=DEFAULT_ADAPTER_TIMEOUT)
    p_run.add_argument("--cases", help="comma-separated case ids (a SUBSET, labelled as one)")
    p_run.add_argument("--keep", help="copy the export here before cleaning up (debugging)")
    common(p_run)
    p_cmp = sub.add_parser("compare", help="diff two reports; fail on any non-wall-time mismatch")
    p_cmp.add_argument("first")
    p_cmp.add_argument("second")
    p_rep = sub.add_parser("reproduce", help="replay what a report pins, then compare against it")
    p_rep.add_argument("reference")
    common(p_rep)
    p_dr = sub.add_parser("drill", help="missing/changed corpus and fixture files must fail the replay")
    p_dr.add_argument("--rev", default="HEAD")
    p_dr.add_argument("--repo", default=str(ROOT))
    p_dr.add_argument("--git")
    p_dr.add_argument("--python")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "compare":
            mismatches = compare(load_report(a.first), load_report(a.second))
            for m in mismatches[:60]:
                print(f"MISMATCH {m}")
            if mismatches:
                print(f"{len(mismatches)} mismatch(es) outside environment, diagnostics and wall time")
                return 1
            print("reports match (environment, diagnostics and wall time excluded)")
            return 0
        if a.cmd == "drill":
            outcomes = drill(a.repo, a.rev, git=a.git, python=a.python)
            for o in outcomes:
                state = "FAILED the replay, as required" if o["held"] else "DID NOT fail as required"
                print(f"[{'ok' if o['held'] else 'BROKEN'}] {o['drill']}: {o['what']} ({o['path']}) — "
                      f"{state}; wanted {o['expected']}, got {o['kinds'] or 'no preflight failure'}")
            return 0 if all(o["held"] for o in outcomes) else 1
        adapters = ([parse_adapter_spec(s, "external-adapter") for s in a.adapter]
                    + [parse_adapter_spec(s, "fixture-adapter") for s in a.fixture_adapter])
        if a.cmd == "run":
            selection = [c for c in (a.cases or "").split(",") if c] or None
            report = replay(a.repo, a.rev, runs=a.runs, case_timeout=a.case_timeout,
                            adapter_timeout=a.adapter_timeout, adapters=adapters,
                            selection=selection, git=a.git, python=a.python, keep=a.keep)
            _write(report, a.out, a.summary)
            return 0 if report["verdict"]["ok"] else 1
        reference = load_report(a.reference)
        proto = reference["protocol"]
        wanted = [c["name"] for c in proto.get("configurations", [])
                  if c["tier"] in ("fixture-adapter", "external-adapter")]
        if sorted(wanted) != sorted(x["name"] for x in adapters):
            raise ReplayError(f"the reference was measured with adapter(s) {wanted}; pass the same "
                              f"names with --adapter/--fixture-adapter to reproduce it")
        report = replay(a.repo, reference["revision"]["commit"], runs=proto["runs"],
                        case_timeout=proto["case_timeout_seconds"],
                        adapter_timeout=proto["adapter_timeout_seconds"], adapters=adapters,
                        selection=proto.get("selection"), git=a.git, python=a.python)
        _write(report, a.out, a.summary)
        mismatches = compare(reference, report)
        for m in mismatches[:60]:
            print(f"MISMATCH {m}")
        if mismatches:
            print(f"NOT REPRODUCED: {len(mismatches)} mismatch(es) against {a.reference}")
            return 1
        if not report["verdict"]["ok"]:
            print("NOT REPRODUCED: the replay itself did not complete")
            return 1
        print(f"REPRODUCED: this environment matches {a.reference} "
              "(environment, diagnostics and wall time excluded)")
        return 0
    except ReplayError as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
