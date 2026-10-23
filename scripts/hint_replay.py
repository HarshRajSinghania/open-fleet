#!/usr/bin/env python3
"""hint_replay.py — replay a FIXED corpus to measure episodic hints before memory grows (#605).

Each corpus scenario is a synthetic multi-commit git repository (renames, deletions, branches,
uncommitted edits), a git-committed run archive of manifests pointing at those commits (some
tampered after commit), a query, optional current evidence, and the expected verdict for every
hint. The replay builds each scenario in a temp dir and runs three arms:

    off        no hint at all                         (the baseline a hint must beat)
    unchecked  hints on, provenance checks off         (--hint-mode historical, no --repo)
    checked    hints on, provenance checks on          (current mode against the live repo)

and reports, per arm: correct retrieval (useful/unknown/benign notes reach the reader with their
text), stale suppression (STALE/SUPERSEDED notes kept out), stale leakage, poisoned-note
propagation, and -- for the checked arm -- label accuracy. ``--check`` fails unless the checked
arm is perfect on the corpus AND the unchecked arm leaks (a corpus the unchecked arm passes
cannot tell the checks from their absence).

The effect on REPEATED TASK FAILURES needs a worker: ``--live`` runs every scenario that carries
a ``live_task`` through an agent command per arm and attempt, then the scenario's oracle, and
counts attempts that fail with the recorded pitfall. It never runs unless asked, refuses a ``live``
tier without a declared model and budget, refuses more runs than ``--max-runs``, and labels its
report with the tier the operator declared -- a stub agent is tier ``stub``, never ``live``.

    python3 scripts/hint_replay.py --check                  # fixture tier, deterministic, free
    python3 scripts/hint_replay.py --live --tier live --model <id> --budget-usd 5 --max-runs 18 \\
        --attempts 3 --agent-cmd 'claude -p --model <id>' --out hint-replay-live.json

Exit: 0 ok · 1 --check failed / live run failed · 2 usage or corpus error.
"""
import argparse
import copy
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "runtime" / "scripts"))
import search_sessions  # runtime/scripts is on the path first

hp = search_sessions.hp  # the provenance module the hint itself uses (mutation tests patch it)
DEFAULT_CORPUS = ROOT / "tests" / "fixtures" / "hint-replay.json"
ARMS = ("off", "unchecked", "checked")
CLASSES = ("useful", "unknown", "stale", "poison", "benign")
EXIT_OK, EXIT_FAILED, EXIT_USAGE = 0, 1, 2
FIXED_EPOCH = 1767225600  # 2026-01-01T00:00:00Z: commit dates are part of the fixture


class CorpusError(Exception):
    """The corpus or a scenario is malformed: exit 2, nothing measured."""


def fixture_env():
    """A git environment that ignores the operator's config (no signing, no hooks, no identity)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
                "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
                "GIT_TERMINAL_PROMPT": "0"})
    return env


def _git(cwd, *args, when=None):
    env = fixture_env()
    if when is not None:
        stamp = f"@{FIXED_EPOCH + when * 3600} +0000"
        env.update({"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
    proc = subprocess.run(["git", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
                          cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise CorpusError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _write(root, files):
    for rel, content in files.items():
        target = Path(root) / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _resolve_refs(value, shas):
    """Replace "@<commit name>" strings with that commit's sha, recursively."""
    if isinstance(value, str) and value.startswith("@") and value[1:] in shas:
        return shas[value[1:]]
    if isinstance(value, list):
        return [_resolve_refs(v, shas) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_refs(v, shas) for k, v in value.items()}
    return value


def build_repo(scenario, repo):
    """The live source: commits in order (each on its branch), then the live checkout, then any
    uncommitted working-tree edits. Returns {commit name: sha}."""
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    shas, known, current = {}, {"main"}, "main"
    for i, commit in enumerate(scenario["commits"]):
        branch = commit.get("branch", "main")
        if branch not in known:
            start = scenario.get("branches", {}).get(branch)
            if start not in shas:
                raise CorpusError(f"{scenario['id']}: branch {branch} starts at unknown commit {start}")
            _git(repo, "checkout", "-q", "-b", branch, shas[start])
            known.add(branch)
        elif branch != current:
            _git(repo, "checkout", "-q", branch)
        current = branch
        _write(repo, commit.get("files", {}))
        for old, new in commit.get("rename", {}).items():
            (repo / new).parent.mkdir(parents=True, exist_ok=True)
            _git(repo, "mv", old, new)
        for gone in commit.get("delete", []):
            _git(repo, "rm", "-q", gone)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "--allow-empty", "-m", commit["name"], when=i)
        shas[commit["name"]] = _git(repo, "rev-parse", "HEAD")
    live = scenario.get("live", "main")
    _git(repo, "checkout", "-q", shas.get(live, live))
    _write(repo, scenario.get("worktree_edits", {}))
    return shas


def build_archive(scenario, archive, shas):
    """The run archive (archive/docs/runs/<run>/...), committed to its own git repo, then any
    post-commit tampering: an evidence file rewritten, or the manifest itself edited."""
    runs_dir = archive / "docs" / "runs"
    runs_dir.mkdir(parents=True)
    _git(archive, "init", "-q", "-b", "main")
    tamper = []
    for run in scenario["runs"]:
        run_dir = runs_dir / run["run"]
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest = _resolve_refs(copy.deepcopy(run["manifest"]), shas)
        recorded = []
        for name, content in run.get("artifacts", {}).items():
            (run_dir / name).write_text(content, encoding="utf-8")
            recorded.append({"path": f"docs/runs/{run['run']}/{name}",
                             "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
        if recorded:
            manifest["artifacts"] = recorded
        path = run_dir / run.get("file", "manifest.json")
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        tamper.append((run, run_dir, path, manifest))
    _git(archive, "add", "-A")
    _git(archive, "commit", "-q", "-m", "archive", when=0)
    for run, run_dir, path, manifest in tamper:
        for name, content in run.get("tamper_artifacts", {}).items():
            (run_dir / name).write_text(content, encoding="utf-8")
        if run.get("tamper_manifest"):
            manifest.update(run["tamper_manifest"])
            path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return runs_dir


def _arm_selection(arm, scenario, runs_dir, repo):
    if arm == "off":
        return {"lines": [], "entries": []}
    if arm == "unchecked":
        return search_sessions.build_episodic_selection(scenario["query"], runs_dir=str(runs_dir),
                                                        mode="historical")
    return search_sessions.build_episodic_selection(
        scenario["query"], runs_dir=str(runs_dir), live=str(repo), mode="current",
        current_evidence=scenario.get("current_evidence"))


def _observe(selection, key, expect):
    run, unit = key.split("/", 1)
    entry = next((e for e in selection["entries"] if e["run"] == run and e["unit"] == unit), None)
    text = "\n".join(selection["lines"])
    line = next((ln for ln in selection["lines"] if f"[run {run} / {unit} (" in ln), "")
    return {"found": entry is not None, "shown": bool(entry and entry["shown"]),
            "text_shown": expect["marker"] in text, "currency": entry and entry["currency"],
            "reasons": entry["reasons"] if entry else [], "line": line}


def evaluate(scenario, observed):
    """Problems (strings) for one scenario's checked/unchecked observations against its expect."""
    problems = []
    for key, expect in scenario["expect"].items():
        got = observed["checked"][key]
        cls = expect["class"]
        where = f"{scenario['id']}:{key}"
        if got["currency"] != expect["currency"]:
            problems.append(f"{where}: currency {got['currency']} != expected {expect['currency']}")
        prefix = expect.get("reason")
        if prefix and not any(r.startswith(prefix) for r in got["reasons"]):
            problems.append(f"{where}: no reason starting {prefix!r} in {got['reasons']}")
        if prefix is None and got["reasons"]:
            problems.append(f"{where}: expected no reason, got {got['reasons']}")
        if cls in ("useful", "unknown", "benign") and not got["text_shown"]:
            problems.append(f"{where}: {cls} note not retrieved with its text")
        if cls == "stale" and got["shown"]:
            problems.append(f"{where}: stale note shown in the checked arm")
        if cls == "poison" and got["text_shown"]:
            problems.append(f"{where}: poisoned note text propagated")
        forbid = expect.get("forbid_in_line")
        if forbid and re.search(forbid, got["line"]):
            problems.append(f"{where}: entry line matches forbidden {forbid!r}")
    return problems


def _metrics(rows, arm):
    def ratio(hit, total):
        return round(hit / total, 4) if total else None
    want = [r for r in rows if r["class"] in ("useful", "unknown", "benign")]
    stale = [r for r in rows if r["class"] == "stale"]
    poison = [r for r in rows if r["class"] == "poison"]
    out = {
        "retrieval": ratio(sum(r[arm]["text_shown"] for r in want), len(want)),
        "stale_suppression": ratio(sum(not r[arm]["shown"] for r in stale), len(stale)),
        "stale_leakage": sum(r[arm]["shown"] for r in stale),
        "poison_propagated": sum(r[arm]["text_shown"] for r in poison),
    }
    if arm == "checked":
        out["label_accuracy"] = ratio(sum(r["label_ok"] for r in rows), len(rows))
    return out


def load_corpus(path):
    try:
        raw = Path(path).read_bytes()
        corpus = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot read corpus {path}: {exc}") from exc
    scenarios = corpus.get("scenarios") if isinstance(corpus, dict) else None
    if not isinstance(scenarios, list) or not scenarios:
        raise CorpusError("corpus needs a non-empty scenarios list")
    ids = set()
    for scn in scenarios:
        if not isinstance(scn, dict) or not scn.get("id") or scn["id"] in ids:
            raise CorpusError(f"scenario without a unique id: {scn!r:.80}")
        ids.add(scn["id"])
        for key in ("commits", "runs", "query", "expect"):
            if not scn.get(key):
                raise CorpusError(f"{scn['id']}: missing {key}")
        for key, expect in scn["expect"].items():
            if "/" not in key or expect.get("class") not in CLASSES or not expect.get("marker"):
                raise CorpusError(f"{scn['id']}: expect {key} needs run/unit, a class and a marker")
    return corpus, hashlib.sha256(raw).hexdigest()


def replay(corpus_path=DEFAULT_CORPUS, only=None, arms=ARMS):
    """Run the deterministic arms over the corpus. Returns the fixture-tier report. ``arms`` must
    include "checked" (the expectations are about it); a mutation control needs nothing else."""
    if "checked" not in arms:
        raise CorpusError("the checked arm is the one the corpus expectations describe")
    corpus, digest = load_corpus(corpus_path)
    rows, problems, per_scenario = [], [], []
    for scenario in corpus["scenarios"]:
        if only and scenario["id"] not in only:
            continue
        with tempfile.TemporaryDirectory(prefix="hint-replay-") as tmp:
            shas = build_repo(scenario, Path(tmp) / "repo")
            runs_dir = build_archive(scenario, Path(tmp) / "archive", shas)
            observed = {arm: {} for arm in arms}
            for arm in arms:
                selection = _arm_selection(arm, scenario, runs_dir, Path(tmp) / "repo")
                for key, expect in scenario["expect"].items():
                    observed[arm][key] = _observe(selection, key, expect)
        found = evaluate(scenario, observed)
        problems.extend(found)
        for key, expect in scenario["expect"].items():
            label_ok = not any(p.startswith(f"{scenario['id']}:{key}: currency")
                               or p.startswith(f"{scenario['id']}:{key}: no reason")
                               or p.startswith(f"{scenario['id']}:{key}: expected no reason") for p in found)
            rows.append({"key": f"{scenario['id']}:{key}", "class": expect["class"], "label_ok": label_ok,
                         **{arm: observed[arm][key] for arm in arms}})
        per_scenario.append({"id": scenario["id"], "problems": found,
                             "checked": {k: {"currency": v["currency"], "reasons": v["reasons"],
                                             "shown": v["shown"], "text_shown": v["text_shown"]}
                                         for k, v in observed["checked"].items()}})
    return {"schema": "hint-replay/v1", "tier": "fixture",
            "corpus": {"path": str(corpus_path), "sha256": digest},
            "scenarios": len(per_scenario), "hints": len(rows),
            "arms": {arm: _metrics(rows, arm) for arm in arms},
            "per_scenario": per_scenario, "problems": problems}


def check(report):
    """The --check gate: the checked arm is perfect and the unchecked arm is not (the corpus binds)."""
    failures = list(report["problems"])
    checked, unchecked = report["arms"]["checked"], report["arms"]["unchecked"]
    if checked["label_accuracy"] != 1.0:
        failures.append(f"checked label accuracy {checked['label_accuracy']} < 1.0")
    if checked["retrieval"] != 1.0 or checked["stale_suppression"] != 1.0:
        failures.append(f"checked retrieval {checked['retrieval']} / suppression {checked['stale_suppression']} < 1.0")
    if checked["stale_leakage"] or checked["poison_propagated"]:
        failures.append("checked arm leaked a stale or poisoned note")
    if not unchecked["stale_leakage"] or not unchecked["poison_propagated"]:
        failures.append("the unchecked arm leaks nothing: the corpus cannot tell the checks from their absence")
    return failures


# --- live arm: repeated task failures with hints on/off (needs a worker; REMAINING by default) ----

def live_replay(corpus_path, agent_argv, tier, attempts, max_runs, model=None, budget_usd=None,
                timeout_s=900, only=None):
    """Per live_task scenario x arm x attempt: fresh fixture, packet (task + hint for the arm),
    agent run, then the oracle. A repeated failure is an oracle failure matching the pitfall."""
    corpus, digest = load_corpus(corpus_path)
    tasks = [s for s in corpus["scenarios"] if s.get("live_task") and (not only or s["id"] in only)]
    if not tasks:
        raise CorpusError("no scenario carries a live_task")
    planned = len(tasks) * len(ARMS) * attempts
    if planned > max_runs:
        raise CorpusError(f"{planned} agent runs planned, --max-runs allows {max_runs}")
    results = []
    for scenario in tasks:
        task = scenario["live_task"]
        pitfall = re.compile(task["pitfall"])
        for arm in ARMS:
            for attempt in range(1, attempts + 1):
                with tempfile.TemporaryDirectory(prefix="hint-replay-live-") as tmp:
                    repo = Path(tmp) / "repo"
                    shas = build_repo(scenario, repo)
                    runs_dir = build_archive(scenario, Path(tmp) / "archive", shas)
                    hint = _arm_selection(arm, scenario, runs_dir, repo)["lines"]
                    packet = task["prompt"] + ("\n\n" + "\n".join(hint) if hint else "") + "\n"
                    packet_path = Path(tmp) / "PACKET.md"
                    packet_path.write_text(packet, encoding="utf-8")
                    env = dict(os.environ, HINT_REPLAY_PACKET=str(packet_path))
                    try:
                        agent = subprocess.run(agent_argv, cwd=repo, input=packet, env=env, text=True,
                                               capture_output=True, timeout=timeout_s, check=False)
                        agent_rc = agent.returncode
                    except subprocess.TimeoutExpired:
                        agent_rc = "timeout"
                    oracle = subprocess.run(task["oracle"], cwd=repo, capture_output=True, text=True,
                                            timeout=300, check=False)
                    output = oracle.stdout + oracle.stderr
                    results.append({"scenario": scenario["id"], "arm": arm, "attempt": attempt,
                                    "agent_exit": agent_rc, "oracle_exit": oracle.returncode,
                                    "repeated_failure": oracle.returncode != 0 and bool(pitfall.search(output))})
    arms = {}
    for arm in ARMS:
        mine = [r for r in results if r["arm"] == arm]
        arms[arm] = {"runs": len(mine), "passed": sum(r["oracle_exit"] == 0 for r in mine),
                     "repeated_failures": sum(r["repeated_failure"] for r in mine)}
    return {"schema": "hint-replay-live/v1", "tier": tier, "model": model, "budget_usd": budget_usd,
            "agent": os.path.basename(agent_argv[0]), "planned_runs": planned, "attempts": attempts,
            "corpus": {"path": str(corpus_path), "sha256": digest}, "arms": arms, "results": results}


def build_parser():
    p = argparse.ArgumentParser(prog="hint_replay.py", description=__doc__.split("\n")[0])
    p.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    p.add_argument("--scenario", action="append", default=[], help="limit to these scenario ids")
    p.add_argument("--check", action="store_true", help="exit 1 unless the corpus gate holds")
    p.add_argument("--json", action="store_true", help="print the full report")
    p.add_argument("--out", default=None, help="also write the report here")
    p.add_argument("--live", action="store_true", help="run the agent arm (spends model budget)")
    p.add_argument("--tier", choices=("stub", "live"), default=None,
                   help="what --agent-cmd IS: a deterministic stub, or a real model worker")
    p.add_argument("--agent-cmd", default=None, help="worker argv (shlex-split, no shell); packet on stdin "
                   "and at $HINT_REPLAY_PACKET; runs with cwd = the fixture repo")
    p.add_argument("--model", default=None)
    p.add_argument("--budget-usd", type=float, default=None)
    p.add_argument("--max-runs", type=int, default=None)
    p.add_argument("--attempts", type=int, default=1)
    p.add_argument("--timeout-s", type=int, default=900)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.live:
            if args.tier is None or not args.agent_cmd or args.max_runs is None or args.attempts < 1:
                raise CorpusError("--live needs --tier, --agent-cmd, --max-runs and --attempts >= 1")
            if args.tier == "live" and (not args.model or not args.budget_usd or args.budget_usd <= 0):
                raise CorpusError("a live tier needs a declared --model and a positive --budget-usd")
            report = live_replay(args.corpus, shlex.split(args.agent_cmd), args.tier, args.attempts,
                                 args.max_runs, args.model, args.budget_usd, args.timeout_s,
                                 set(args.scenario) or None)
            failures = []
        else:
            report = replay(args.corpus, set(args.scenario) or None)
            failures = check(report) if args.check else []
    except CorpusError as exc:
        print(f"hint_replay: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"tier={report['tier']} corpus_sha256={report['corpus']['sha256'][:16]}")
        for arm, metrics in report["arms"].items():
            print(f"{arm}: " + " ".join(f"{k}={v}" for k, v in metrics.items()))
    for failure in failures:
        print(f"FAIL {failure}", file=sys.stderr)
    return EXIT_FAILED if failures else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
