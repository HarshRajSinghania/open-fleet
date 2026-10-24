#!/usr/bin/env python3
"""Contract tests for scripts/wip_curve.py, the pre-registered WIP-curve experiment (#604).

What is pinned here is what a hand-run experiment silently gets wrong: a design changed after the
data came in, a task whose oracle measures nothing, a spend nobody authorised, a run that did not
start from the same state as the others, a report that cannot be recomputed from what was kept, a
metric row edited after the fact, and a CLOSED unit that git or review authority does not back.

No test calls a model. Two tests drive whole runs through the posix provider with the runner's
INERT stand-in (first_run.py's pattern, #596): every subprocess runs with SHELL=/bin/sh and a
tripwire for every harness name first on PATH, and the tripwire log must stay empty.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import importlib.util
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "scripts" / "wip_curve.py"
EVENTS = ROOT / "runtime" / "scripts" / "events.py"
PREREG = ROOT / "docs" / "experiments" / "wip-curve-prereg.json"
TASKSET = ROOT / "docs" / "experiments" / "wip-curve-taskset.json"
_spec = importlib.util.spec_from_file_location("wip_curve_under_test", RUNNER)
wip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wip)

LEAKY = ("ORCA_CLI_COMMAND", "OPEN_FLEET_CLI_COMMAND", "OPEN_FLEET_RUNTIME", "ORCA_FLEET_RUNTIME",
         "OPEN_FLEET_STATE_DB", "OPEN_FLEET_STATE_DIR", "OPEN_FLEET_SANDBOX_PROFILE", "ORCA_SANDBOX_PROFILE",
         "OPEN_FLEET_PARENT_PROFILE", "ORCA_PARENT_PROFILE", "WORKER_CMD", "CLAUDE_CMD", "CODEX_CMD",
         "ORCA_TERMINAL_HANDLE", "OPEN_FLEET_TERMINAL_HANDLE", "OPEN_FLEET_DENY_HOOK_SETTINGS",
         "ORCA_DENY_HOOK_SETTINGS", "OPEN_FLEET_POSIX_BACKEND", "ORCA_POSIX_BACKEND",
         "OPEN_FLEET_MERGE_QUEUE_DB", "OPEN_FLEET_EVENTS_LOG", "ORCA_EVENTS_LOG")


def tripwired_env(tmp: Path) -> tuple[dict, Path]:
    """SHELL=/bin/sh and a tripwire for every harness name first on PATH (test_certification.py)."""
    trip = tmp / "tripwire"
    trip.mkdir(parents=True, exist_ok=True)
    log = tmp / "tripwire.log"
    for name in wip.first_run.all_harness_binaries():
        path = trip / name
        path.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\nexit 97\n', encoding="utf-8")
        path.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k not in LEAKY}
    env["PATH"] = os.pathsep.join([str(trip), os.path.dirname(sys.executable), env.get("PATH", "")])
    env["SHELL"] = "/bin/sh"
    return env, log


class _Hung(Exception):
    """An in-process run outlived its test timeout (SIGALRM)."""


def run_in_process(argv, env, cwd=None, timeout=600):
    """wip_curve.main() in this process, so coverage traces the runner itself, under `env` (a
    tripwired PATH and SHELL=/bin/sh), with its output captured. An alarm stands in for the
    subprocess timeout: it unwinds the run, which still settles and stops its workers."""
    out, err = io.StringIO(), io.StringIO()
    old_cwd = os.getcwd()

    def hung(_signum, _frame):
        raise _Hung(f"wip_curve.main{tuple(argv)[:4]} ran past {timeout}s")

    previous = signal.signal(signal.SIGALRM, hung)
    signal.alarm(int(timeout))
    try:
        with mock.patch.dict(os.environ, {k: v for k, v in (env or os.environ).items()}, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                if cwd is not None:
                    os.chdir(cwd)
                try:
                    rc = wip.main([str(a) for a in argv])
                except SystemExit as exc:  # argparse, or a trapped signal
                    rc = exc.code
            finally:
                os.chdir(old_cwd)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)
    return subprocess.CompletedProcess(argv, rc, out.getvalue(), err.getvalue())


def runner(*args, env=None, timeout=600, cwd=None):
    """The runner's CLI, in-process (see run_in_process)."""
    return run_in_process(args, env, cwd=cwd, timeout=timeout)


def rebind(run_dir: Path) -> None:
    """Forge run.json's source digests after an edit: what a careful tamperer would do."""
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rec["sources"] = {str(p.relative_to(run_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(run_dir.rglob("*")) if p.is_file() and p.name != "run.json"}
    (run_dir / "run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def synthetic_run(run_id, cond, throughput, *, compliant=True, review_in=100, review_out=20, tier="live-unreviewed",
                  model="m-1", harness="h-1", inputs="i" * 64, started="2026-10-24T10:00:00+00:00",
                  machine="host-a", agent="claude"):
    """A run summary in summarize_run()'s shape, for report logic that needs no real run."""
    builders, reviewers = {"b1r1": (1, 1), "b3r1": (3, 1), "b6r1": (6, 1), "b6r2": (6, 2)}[cond]
    tp = Fraction(str(throughput))
    metrics = {
        "throughput": {"value": f"{throughput}/h", "exact": str(tp), "verified_closed": 6, "wall_clock_s": "3600"},
        "latency": {"median_min": "1.00", "max_min": "2.00", "units": 6, "median_exact_s": "60", "max_exact_s": "120"},
        "rework": {"bounced": 1, "units": 6}, "freshness": 0, "retries": 1, "conflicts": 0, "gate_failures": 0,
        "usage": {"input_tokens": 1000, "output_tokens": 200, "cache_read_input_tokens": 0,
                  "cache_creation_input_tokens": 0, "cost_usd": "1.00"},
        "review_usage": {"reviews": 6, "observed": 6, "input_tokens": review_in, "output_tokens": review_out},
        "review_queue": {"median_min": "0.50", "max_min": "1.00", "median_exact_s": "30", "max_exact_s": "60"},
        "cost_per_verified_closed_usd": "0.1667", "parked": {}, "tasks": {}, "models": [model],
        "derivable": True,
    }
    finished = (datetime.fromisoformat(started) + timedelta(hours=1)).isoformat()
    run = {"run_id": run_id, "condition": cond, "builders": builders, "reviewers": reviewers, "tier": tier,
           "status": "complete", "started_at": started, "finished_at": finished,
           "inputs_sha256": inputs, "model_pin": model, "harness_version": harness, "attempt": 1,
           "agent": agent, "machine": {"clock": machine, "platform": "p", "machine": "m", "cpu_count": 8},
           "repetition": int(re.search(r"-rep(\d+)", run_id).group(1)) if "-rep" in run_id else None,
           "task_order": wip.task_order(*wip.load_prereg(PREREG)[:2], run_id),
           "timeout_scale": 1.0, "compliant": compliant,
           "noncompliance": [] if compliant else ["excluded by the protocol"], "binding_problems": [],
           "metrics": metrics}
    run["registered"] = wip.registered_run(run)
    return run


class Tmp(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="wip-curve-test-")
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)


# ---------------------------------------------------------------------------- pre-registration

class TestPreregistration(Tmp):
    def mutated(self, prereg_fn=None, taskset_fn=None, rehash=True):
        """A copy of the pre-registration and task set with one defect, digests kept consistent
        unless `rehash` is False, so each test sees only the defect it plants."""
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
        if taskset_fn:
            taskset_fn(taskset)
        tpath = self.tmp / "taskset.json"
        tpath.write_text(json.dumps(taskset, indent=2), encoding="utf-8")
        prereg["taskset"]["path"] = str(tpath)
        if rehash:
            prereg["taskset"]["sha256"] = hashlib.sha256(tpath.read_bytes()).hexdigest()
        if prereg_fn:
            prereg_fn(prereg)
        ppath = self.tmp / "prereg.json"
        ppath.write_text(json.dumps(prereg, indent=2), encoding="utf-8")
        p, t, _path, _sha, tp = wip.load_prereg(ppath)
        return wip.check_prereg(p, t, tp)

    def test_the_committed_pre_registration_checks_clean(self):
        p = runner("check-prereg")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("pre-registration OK", p.stdout)
        self.assertIn(wip.PENDING, p.stdout)

    def test_the_spend_is_left_to_the_owner(self):
        cost = json.loads(PREREG.read_text(encoding="utf-8"))["cost"]
        self.assertEqual(cost["cap_usd"], wip.PENDING, "the runner's author must not pick the spend")
        self.assertEqual(cost["reservation_status"], wip.PENDING)
        self.assertGreater(wip.money(cost["proposed_cap_usd"]), 0)

    def test_the_design_records_every_registered_field(self):
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        self.assertIn(1, [c["builders"] for c in prereg["conditions"]])
        self.assertGreaterEqual(prereg["repetitions"], 3)
        for key in ("machine", "provider", "model", "harness"):
            self.assertIn(key, prereg["runtime"])
        for key in ("cache_warmup", "task_difficulty", "model_changes", "reviewer_effort"):
            self.assertTrue(prereg["confounds"][key])
        for key in ("reviewer_availability", "isolation", "stopping_rule", "generalization_limits"):
            self.assertTrue(prereg[key])

    def test_a_design_without_the_serial_point_is_refused(self):
        errors = self.mutated(lambda p: p["conditions"].__setitem__(0, {**p["conditions"][0], "builders": 2}))
        self.assertTrue(any("builders=1" in e for e in errors), errors)

    def test_fewer_than_three_wip_settings_is_refused(self):
        def two(p):
            p["conditions"] = p["conditions"][:2]
            p["order"]["rows"] = [r for r in ([["b1r1", "b3r1"]] * 3)]
        errors = self.mutated(two)
        self.assertTrue(any("three differing WIP settings" in e for e in errors), errors)

    def test_fewer_than_three_repetitions_is_refused(self):
        errors = self.mutated(lambda p: p.__setitem__("repetitions", 2))
        self.assertTrue(any("repetitions" in e for e in errors), errors)

    def test_an_order_row_that_is_not_a_permutation_is_refused(self):
        errors = self.mutated(lambda p: p["order"]["rows"][1].__setitem__(0, "b1r1"))
        self.assertTrue(any("not a permutation" in e for e in errors), errors)

    def test_an_unstated_confound_is_refused(self):
        errors = self.mutated(lambda p: p["confounds"].pop("model_changes"))
        self.assertTrue(any("confounds.model_changes" in e for e in errors), errors)

    def test_an_unstated_stopping_rule_is_refused(self):
        errors = self.mutated(lambda p: p["stopping_rule"].pop("cost"))
        self.assertTrue(any("stopping_rule.cost" in e for e in errors), errors)

    def test_a_registered_metric_the_report_cannot_emit_is_refused(self):
        errors = self.mutated(lambda p: p["metrics"]["report_fields"]["run"].append("vibes_per_hour"))
        self.assertTrue(any("vibes_per_hour" in e for e in errors), errors)

    def test_a_cap_that_is_neither_pending_nor_an_amount_is_refused(self):
        errors = self.mutated(lambda p: p["cost"].__setitem__("cap_usd", "plenty"))
        self.assertTrue(any("cost.cap_usd" in e for e in errors), errors)

    def test_editing_the_task_set_voids_the_registration(self):
        errors = self.mutated(taskset_fn=lambda t: t["tasks"][0].__setitem__("title", "easier"), rehash=False)
        self.assertTrue(any("taskset.sha256" in e for e in errors), errors)

    def test_a_seed_that_builds_another_commit_is_refused(self):
        errors = self.mutated(taskset_fn=lambda t: t["seed"].__setitem__("date", "2026-10-25T00:00:00+00:00"))
        self.assertTrue(any("seed_commit" in e for e in errors), errors)

    def test_an_oracle_that_passes_on_the_seed_is_refused(self):
        lazy = ("import unittest\n\n\nclass Oracle(unittest.TestCase):\n"
                "    def test_nothing(self):\n        self.assertTrue(True)\n")
        errors = self.mutated(taskset_fn=lambda t: t["tasks"][2].__setitem__("oracle", lazy))
        self.assertTrue(any("T3: the oracle passes on the seed" in e for e in errors), errors)

    def test_the_worker_contracts_are_registered_not_coded(self):
        contracts = json.loads(PREREG.read_text(encoding="utf-8"))["contracts"]
        prereg, taskset, *_ = wip.load_prereg(PREREG)
        run = wip.Run.__new__(wip.Run)
        run.prereg, run.tasks = prereg, wip.task_by_id(taskset)
        builder = run.builder_spec("T1", "WIP-NONCE:" + "0" * 16)
        self.assertIn("WIP-BUILD WIP-NONCE:" + "0" * 16 + " task=T1", builder)
        self.assertIn(contracts["builder"][-1].split("{")[0], builder)
        review = run.review_spec("T1", "WIP-NONCE:" + "0" * 16, "a" * 40, "b" * 40, "t.md", "c.diff")
        self.assertIn("WIP-REVIEW-REQUEST WIP-NONCE:" + "0" * 16 + " task=T1 head=" + "b" * 40 + " diff=c.diff", review)

    def test_a_contract_that_loses_a_placeholder_is_refused(self):
        errors = self.mutated(lambda p: p["contracts"]["reviewer"].__setitem__(
            0, p["contracts"]["reviewer"][0].replace(" head={head}", "")))
        self.assertTrue(any("contracts.reviewer" in e and "{head}" in e for e in errors), errors)

    def test_a_verdict_line_the_parser_cannot_read_is_refused(self):
        errors = self.mutated(lambda p: p["contracts"].__setitem__("verdict_line", "VERDICT: {verdict} for {head}"))
        self.assertTrue(any("verdict_line" in e for e in errors), errors)

    def test_editing_a_worker_contract_changes_the_registration(self):
        before = hashlib.sha256(PREREG.read_bytes()).hexdigest()
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        prereg["contracts"]["reviewer"][1] += " Be lenient."
        self.assertNotEqual(hashlib.sha256(json.dumps(prereg, indent=2).encode()).hexdigest(), before)

    def test_a_reference_edit_that_does_not_apply_is_refused(self):
        def drift(t):
            t["tasks"][0]["reference"][0]["replace"] = "import regex"
        errors = self.mutated(taskset_fn=drift)
        self.assertTrue(any("T1: the reference edit does not apply" in e for e in errors), errors)

    def test_an_ambiguous_anchor_is_refused_not_guessed(self):
        tree = self.tmp / "tree"
        tree.mkdir()
        (tree / "f.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            wip.apply_edits(tree, [{"file": "f.py", "replace": "x = 1", "with": ["x = 2"]}])
        self.assertEqual((tree / "f.py").read_text(encoding="utf-8"), "x = 1\nx = 1\n")

    def test_the_seed_commit_is_the_same_on_any_host(self):
        taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
        hostile = {**os.environ, "GIT_AUTHOR_NAME": "someone", "GIT_COMMITTER_DATE": "2001-01-01T00:00:00Z"}
        seed = wip.build_seed(taskset, self.tmp / "seed", hostile)
        self.assertEqual(seed, json.loads(PREREG.read_text(encoding="utf-8"))["taskset"]["seed_commit"])


# ---------------------------------------------------------------------------- schedule

class TestSchedule(unittest.TestCase):
    def setUp(self):
        self.prereg, self.taskset, *_ = wip.load_prereg(PREREG)
        self.sched = wip.schedule(self.prereg, self.taskset)

    def test_every_repetition_runs_every_condition_once_in_its_row(self):
        conds = sorted(c["id"] for c in self.prereg["conditions"])
        self.assertEqual(len(self.sched), len(conds) * self.prereg["repetitions"])
        for rep in range(1, self.prereg["repetitions"] + 1):
            row = [e["condition"]["id"] for e in self.sched if e["repetition"] == rep]
            self.assertEqual(row, self.prereg["order"]["rows"][rep - 1])
            self.assertEqual(sorted(row), conds)

    def test_no_condition_holds_one_position_twice(self):
        rows = self.prereg["order"]["rows"][: self.prereg["repetitions"]]
        for col in range(len(rows[0])):
            column = [row[col] for row in rows]
            self.assertEqual(len(set(column)), len(column), f"position {col + 1}: {column}")

    def test_the_task_order_is_recomputable_from_the_registration_alone(self):
        seed = self.prereg["order"]["seed"]
        for entry in self.sched:
            want = sorted((t["id"] for t in self.taskset["tasks"]),
                          key=lambda t: hashlib.sha256(f"{seed}:{entry['run_id']}:{t}".encode()).hexdigest())
            self.assertEqual(entry["task_order"], want)
        self.assertGreater(len({tuple(e["task_order"]) for e in self.sched}), 1, "the order never varies")

    def test_a_re_run_keeps_its_runs_task_order(self):
        rid = self.sched[0]["run_id"]
        self.assertEqual(wip.task_order(self.prereg, self.taskset, f"{rid}-a2"), self.sched[0]["task_order"])


# ---------------------------------------------------------------------------- statistics + rule

class TestUncertainty(unittest.TestCase):
    def test_mean_sd_and_t_interval_match_a_hand_calculation(self):
        # 1, 2, 3: mean 2, sd 1, t(2) = 4.303, half-width 4.303 / sqrt(3) = 2.4843... -> [-0.48, 4.48]
        got = wip.describe([Fraction(1), Fraction(2), Fraction(3)])
        self.assertEqual((got["mean"], got["sd"], got["ci95"]), ("2.00", "1.00", ["-0.48", "4.48"]))
        self.assertEqual(got["values"], ["1.00", "2.00", "3.00"])

    def test_one_run_has_no_spread_and_no_run_has_no_mean(self):
        self.assertIsNone(wip.describe([Fraction(5)])["ci95"])
        self.assertIsNone(wip.describe([])["mean"], "no run is not a mean of 0")

    def test_the_wilson_interval_matches_the_formula(self):
        k, n, z = 4, 9, 1.959963984540054
        p = k / n
        center = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / (1 + z * z / n)
        got = wip.wilson(k, n)
        self.assertEqual(got["ci95"], [f"{center - half:.3f}", f"{center + half:.3f}"])
        self.assertEqual(wip.wilson(0, 0)["p"], None)


class TestPartialUsage(unittest.TestCase):
    """A usage observation may report input tokens and not output tokens (or the reverse): the
    reviewer-effort metric is then unavailable, never a TypeError and never a partial sum."""

    def test_a_run_missing_one_token_count_reports_review_tokens_unavailable(self):
        for review_in, review_out in ((100, None), (None, 20)):
            run = synthetic_run("r1", "b3r1", "1.0", review_in=review_in, review_out=review_out)
            self.assertIsNone(run["registered"]["review_tokens_per_review"])
            block = wip.condition_block({"id": "b3r1", "builders": 3, "reviewers": 1, "role": "x"}, [run])
            self.assertIn("unavailable", block["review_tokens_per_review"])

    def test_complete_counts_still_give_tokens_per_review(self):
        run = synthetic_run("r1", "b3r1", "1.0")
        self.assertEqual(run["registered"]["review_tokens_per_review"], "20.00")


class ReportOver(unittest.TestCase):
    """build_report() over synthetic run summaries: report logic without a real run."""

    def report(self, runs, basis="compliant"):
        by_name = {r["run_id"]: r for r in runs}
        with mock.patch.object(wip, "runs_in", return_value=[Path(r) for r in by_name]), \
                mock.patch.object(wip, "summarize_run", side_effect=lambda d, *a: copy.deepcopy(by_name[Path(d).name])):
            return wip.build_report(Path("/nonexistent"), basis=basis)


class TestIncomparableRunsAreNeverPooled(ReportOver):
    """PR #653 review: a run under another model pin or harness version than the first live run
    is not compliant, whatever its own checks say, so it never enters the curve."""

    def test_another_harness_version_or_model_pin_is_excluded(self):
        runs = [synthetic_run("wip1-b1r1-rep1", "b1r1", "1.0", started="2026-10-24T10:00:00+00:00"),
                synthetic_run("wip1-b3r1-rep1", "b3r1", "1.0", harness="h-2", started="2026-10-24T12:00:00+00:00"),
                synthetic_run("wip1-b6r1-rep1", "b6r1", "1.0", model="m-2", started="2026-10-24T14:00:00+00:00")]
        out = {r["run_id"]: r for r in self.report(runs)["runs"]}
        self.assertTrue(out["wip1-b1r1-rep1"]["compliant"])
        self.assertTrue(any("harness version" in w for w in out["wip1-b3r1-rep1"]["noncompliance"]),
                        out["wip1-b3r1-rep1"]["noncompliance"])
        self.assertTrue(any("model pin" in w for w in out["wip1-b6r1-rep1"]["noncompliance"]),
                        out["wip1-b6r1-rep1"]["noncompliance"])
        self.assertEqual(self.report(runs)["compliant_runs"], ["wip1-b1r1-rep1"])

    def test_another_machine_or_harness_name_is_excluded(self):
        runs = [synthetic_run("wip1-b1r1-rep1", "b1r1", "1.0", started="2026-10-24T10:00:00+00:00"),
                synthetic_run("wip1-b3r1-rep1", "b3r1", "1.0", machine="host-b", started="2026-10-24T12:00:00+00:00"),
                synthetic_run("wip1-b6r1-rep1", "b6r1", "1.0", agent="codex", started="2026-10-24T14:00:00+00:00")]
        out = {r["run_id"]: r for r in self.report(runs)["runs"]}
        self.assertTrue(any("machine" in w for w in out["wip1-b3r1-rep1"]["noncompliance"]),
                        out["wip1-b3r1-rep1"]["noncompliance"])
        self.assertTrue(any("harness" in w for w in out["wip1-b6r1-rep1"]["noncompliance"]),
                        out["wip1-b6r1-rep1"]["noncompliance"])


def series(cond, values, start_hour, **kw):
    """Synthetic runs of one condition, two hours apart (the cooldown always kept)."""
    base = datetime.fromisoformat("2026-10-24T00:00:00+00:00")
    return [synthetic_run(f"wip1-{cond}-rep{i + 1}", cond, v,
                          started=(base + timedelta(hours=start_hour + 2 * i)).isoformat(), **kw)
            for i, v in enumerate(values)]


class TestOnlyCompliantRunsDecide(ReportOver):
    """PR #653 review: whatever --basis shows, the recommendation is computed from compliant runs
    alone. Six fast b6r1 fixture runs must not turn a 'keep' into a 'raise'."""

    def runs(self):
        compliant = (series("b1r1", ["1.00", "1.02"], 0) + series("b3r1", ["1.00", "1.02"], 4)
                     + series("b6r1", ["1.00", "1.02"], 8))
        excluded = [synthetic_run(f"wip1-b6r1-rep{i}", "b6r1", "3.00", compliant=False, tier="fixture-tested",
                                  started=f"2026-10-25T{10 + i:02d}:00:00+00:00") for i in range(3, 9)]
        return compliant + excluded

    def test_the_basis_never_moves_the_recommendation(self):
        shown_all = self.report(self.runs(), basis="all")
        compliant_only = self.report(self.runs(), basis="compliant")
        self.assertEqual(compliant_only["recommendation"]["status"], "keep")
        self.assertEqual(shown_all["recommendation"]["status"], "keep",
                         "excluded runs swayed the recommendation")
        b6 = next(c for c in shown_all["conditions"] if c["condition"] == "b6r1")
        self.assertEqual(b6["throughput_per_h"]["n"], 8, "--basis all still shows every run's row")


class TestOnlyOneRetryAfterAFailure(ReportOver):
    """PR #653 review: the registration allows one re-run, and only of a run that failed for an
    infrastructure reason. A repeat of a run that did not fail, or a third attempt, never counts."""

    def attempt(self, n, status="complete", hour=10, **kw):
        run = synthetic_run("wip1-b1r1-rep1" + (f"-a{n}" if n > 1 else ""), "b1r1", "1.0",
                            started=f"2026-10-24T{hour:02d}:00:00+00:00", **kw)
        run.update(attempt=n, status=status)
        if status != "complete":
            run.update(compliant=False, noncompliance=[f"the run ended {status}"])
        return run

    def test_a_repeat_of_a_run_that_did_not_fail_is_excluded(self):
        out = {r["run_id"]: r for r in self.report([self.attempt(1), self.attempt(2, hour=12)])["runs"]}
        self.assertFalse(out["wip1-b1r1-rep1-a2"]["compliant"])
        self.assertTrue(any("attempt 2" in w for w in out["wip1-b1r1-rep1-a2"]["noncompliance"]))

    def test_one_retry_after_a_failure_counts_and_a_third_attempt_never_does(self):
        out = {r["run_id"]: r for r in self.report([self.attempt(1, status="failed"), self.attempt(2, hour=12),
                                                   self.attempt(3, hour=14)])["runs"]}
        self.assertTrue(out["wip1-b1r1-rep1-a2"]["compliant"], out["wip1-b1r1-rep1-a2"]["noncompliance"])
        self.assertFalse(out["wip1-b1r1-rep1-a3"]["compliant"])


class TestChangedDeadlinesNeverCount(ReportOver):
    """PR #653 review: a run whose dispatch deadlines were scaled away from the registered 30 and
    15 minutes is reported, never pooled; and every run records the scale it ran under."""

    def test_a_scaled_run_is_excluded(self):
        scaled = synthetic_run("wip1-b1r1-rep1", "b1r1", "1.0")
        scaled["timeout_scale"] = 0.5
        run = self.report([scaled])["runs"][0]
        self.assertFalse(run["compliant"])
        self.assertTrue(any("deadlines" in w for w in run["noncompliance"]), run["noncompliance"])

    def test_every_run_records_its_timeout_scale(self):
        record = json.loads((Path(dry_run(*B1_BOUNDARY)[0].name) / "results" / "runs" / B1_BOUNDARY[0]
                             / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["timeout_scale"], 1.0)


class TestOnlyTheScheduledRunCounts(ReportOver):
    """Adversarial pass (pooling incomparable runs; extra runs swaying the curve): a run must be a
    scheduled run, under its scheduled condition, repetition and task order."""

    def test_an_unscheduled_run_is_excluded(self):
        run = self.report([synthetic_run("wip1-b6r1-rep4", "b6r1", "9.0")])["runs"][0]
        self.assertFalse(run["compliant"])
        self.assertTrue(any("not a scheduled run" in w for w in run["noncompliance"]), run["noncompliance"])

    def test_a_run_under_another_condition_than_scheduled_is_excluded(self):
        mislabelled = synthetic_run("wip1-b3r1-rep1", "b6r1", "9.0")
        run = self.report([mislabelled])["runs"][0]
        self.assertFalse(run["compliant"])
        self.assertTrue(any("scheduled" in w and "b3r1" in w for w in run["noncompliance"]), run["noncompliance"])

    def test_a_run_whose_waves_ran_another_wip_is_excluded(self):
        src = Path(dry_run(*B1_BOUNDARY)[0].name) / "results" / "runs" / B1_BOUNDARY[0]
        results = Path(tempfile.mkdtemp(prefix="wip-curve-wip-"))
        self.addCleanup(shutil.rmtree, results, True)
        shutil.copytree(src, results / "runs" / src.name)
        rec_path = results / "runs" / src.name / "run.json"
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        rec["condition"] = {**rec["condition"], "builders": 3}  # the label says 3; the record ran 1
        rec_path.write_text(json.dumps(rec), encoding="utf-8")
        run = wip.build_report(results, basis="all")["runs"][0]
        self.assertTrue(any("builders=1" in w for w in run["noncompliance"]), run["noncompliance"])


class TestDecisionRule(unittest.TestCase):
    def setUp(self):
        self.prereg = json.loads(PREREG.read_text(encoding="utf-8"))

    def block(self, ci, rework="0.100", fresh=0):
        return {"throughput_per_h": {"ci95": ci}, "rework": {"p": rework},
                "freshness": {"values": [fresh, fresh, fresh], "total": 3 * fresh}}

    def compliant(self):
        return [{"builders": b, "reviewers": 1} for b in (1, 3, 6)]

    def test_too_few_compliant_runs_issue_nothing(self):
        got = wip.recommend(self.prereg, {}, self.compliant()[:2])
        self.assertEqual(got["status"], "not-issued")

    def test_overlapping_intervals_keep_the_caps(self):
        blocks = {"b1r1": self.block(["1.0", "2.0"]), "b3r1": self.block(["1.5", "3.0"]),
                  "b6r1": self.block(["2.5", "4.0"]), "b6r2": self.block(["2.0", "3.5"])}
        self.assertEqual(wip.recommend(self.prereg, blocks, self.compliant())["status"], "keep")

    def test_a_clear_gain_above_the_cap_is_a_raise_candidate(self):
        blocks = {"b1r1": self.block(["1.0", "2.0"]), "b3r1": self.block(["1.5", "3.0"]),
                  "b6r1": self.block(["3.5", "5.0"]), "b6r2": self.block(["2.0", "3.5"])}
        got = wip.recommend(self.prereg, blocks, self.compliant())
        self.assertEqual(got["status"], "raise")
        self.assertIn("human-reviewed policy change", got["authority"])

    def test_a_gain_bought_with_rework_is_not_a_raise(self):
        blocks = {"b1r1": self.block(["1.0", "2.0"]), "b3r1": self.block(["1.5", "3.0"]),
                  "b6r1": self.block(["3.5", "5.0"], rework="0.300"), "b6r2": self.block(["2.0", "3.5"])}
        self.assertEqual(wip.recommend(self.prereg, blocks, self.compliant())["status"], "keep")

    def test_a_serial_run_beating_the_cap_is_a_lower_candidate(self):
        blocks = {"b1r1": self.block(["3.1", "4.0"]), "b3r1": self.block(["1.5", "3.0"]),
                  "b6r1": self.block(["1.0", "2.0"]), "b6r2": self.block(["1.0", "2.0"])}
        self.assertEqual(wip.recommend(self.prereg, blocks, self.compliant())["status"], "lower")


# ---------------------------------------------------------------------------- refusals + gate

class TestRunRefusals(Tmp):
    """Refusals happen before anything launches: no run directory, no tripwire hit."""

    def setUp(self):
        super().setUp()
        self.env, self.trip_log = tripwired_env(self.tmp)
        self.results = self.tmp / "results"

    def refused(self, *args, rc=2, text=""):
        p = runner("run", "--results", str(self.results), "--workdir", str(self.tmp / "wd"), *args, env=self.env)
        self.assertEqual(p.returncode, rc, p.stdout + p.stderr)
        self.assertIn(text, p.stderr)
        self.assertFalse((self.results / "runs").exists() and any((self.results / "runs").iterdir()),
                         "a refused run left a run directory")
        self.assertFalse(self.trip_log.exists(), "a refused run reached a harness")

    def test_no_run_starts_without_an_explicit_cost_cap(self):
        self.refused(text="--cost-cap-usd is required")

    def test_a_live_run_refuses_a_zero_cap(self):
        self.refused("--worker", "live", "--cost-cap-usd", "0", "--model", "m", text="above zero")

    def test_a_live_run_refuses_without_a_model_pin(self):
        self.refused("--worker", "live", "--cost-cap-usd", "5", text="--model")

    def test_a_live_run_on_another_harness_is_not_refused_as_the_stand_in(self):
        # The stand-in's claude-only rule is not a live run's: codex is refused for the reason that
        # applies to it, that no model pin can reach it (PR #653 review).
        self.refused("--worker", "live", "--agent", "codex", "--cost-cap-usd", "5", "--model", "m",
                     "--reservation-usd", "1", "--runs", "wip1-b9r9-rep1", text="cannot enforce the model pin")

    def test_a_live_run_refuses_changed_dispatch_deadlines(self):
        self.refused("--worker", "live", "--model", "m", "--cost-cap-usd", "5", "--reservation-usd", "1",
                     "--timeout-scale", "0.5", text="--timeout-scale")

    def test_a_retry_with_no_failed_first_attempt_is_refused(self):
        self.refused("--cost-cap-usd", "0", "--runs", "wip1-b1r1-rep1-a2", text="infrastructure failure")

    def test_a_third_attempt_is_refused(self):
        self.refused("--cost-cap-usd", "0", "--runs", "wip1-b1r1-rep1-a3", text="one re-run")

    def test_a_retry_of_a_run_that_did_not_fail_is_refused(self):
        src = Path(dry_run(*B3)[0].name) / "results" / "runs" / B3[0]
        shutil.copytree(src, self.results / "runs" / src.name)
        p = runner("run", "--results", str(self.results), "--workdir", str(self.tmp / "wd"), "--runs",
                   f"{B3[0]}-a2", "--cost-cap-usd", "0", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("infrastructure failure", p.stderr)
        self.assertEqual([d.name for d in (self.results / "runs").iterdir()], [B3[0]])

    def test_a_live_run_refuses_without_an_authorised_reservation(self):
        # The per-dispatch reservation is PENDING OWNER AUTHORISATION too: never taken as given.
        self.refused("--worker", "live", "--cost-cap-usd", "5", "--model", "m", text="--reservation-usd")

    def test_a_cap_must_be_an_amount(self):
        self.refused("--cost-cap-usd", "lots", text="not a decimal amount")

    def test_the_stand_in_refuses_a_harness_it_cannot_imitate(self):
        self.refused("--cost-cap-usd", "0", "--agent", "codex", text="needs --worker live")

    def test_an_unscheduled_run_is_refused(self):
        self.refused("--cost-cap-usd", "0", "--runs", "wip1-b9r9-rep1", text="not a scheduled run")

    def test_a_cap_below_the_first_waves_worst_case_starts_nothing(self):
        self.refused("--cost-cap-usd", "1.00", "--inert-cost-usd", "0.25", "--runs", "wip1-b6r2-rep1",
                     rc=1, text="not started")


class TestWorkerCodeRunsWithoutTheCoordinatorsEnvironment(Tmp):
    """Adversarial pass (every subprocess): the oracle and the merge gate execute worker-written
    code on the coordinator. They hand it a minimal environment and a private HOME and TMPDIR,
    never the coordinator's own (where a harness API key lives)."""

    def test_the_oracle_sees_no_coordinator_secret_and_no_real_home(self):
        taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
        checkout = self.tmp / "ck"
        wip.build_seed(taskset, checkout)
        probe = {"id": "TX", "oracle": (
            "import os, tempfile, unittest\n\n\nclass Oracle(unittest.TestCase):\n"
            "    def test_environment(self):\n"
            # booleans only: a failure must never print the environment it is guarding
            "        self.assertFalse('WIP_CURVE_TEST_SECRET' in os.environ, 'a coordinator variable reached it')\n"
            f"        self.assertFalse(os.environ.get('HOME') == {os.environ.get('HOME', '')!r}, 'the real HOME')\n"
            "        self.assertTrue(tempfile.gettempdir().startswith(os.environ['HOME']), 'a private TMPDIR')\n"
            "        self.assertFalse(len(os.environ) > 12, 'more than the minimal environment')\n")}
        with mock.patch.dict(os.environ, {"WIP_CURVE_TEST_SECRET": "s3cret"}):
            result = wip.run_oracle(checkout, [probe], taskset, self.tmp)
        self.assertEqual(result["exit"], 0, result["tail"])


class TestHostFactsUseTheHardenedGit(Tmp):
    """Adversarial pass (every git call): the host facts every run records read the catalog clone
    through gitexec too, so a command planted in its config never runs."""

    def test_a_planted_fsmonitor_in_the_catalog_never_runs(self):
        repo = self.tmp / "catalog"
        wip.build_seed(json.loads(TASKSET.read_text(encoding="utf-8")), repo)
        marker = self.tmp / "ran.log"
        hook = self.tmp / "hook.sh"
        hook.write_text(f"#!/bin/sh\necho ran >> {marker}\n", encoding="utf-8")
        hook.chmod(0o755)
        subprocess.run(["git", "-C", str(repo), "config", "core.fsmonitor", str(hook)], check=True)
        with mock.patch.object(wip, "ROOT", repo), mock.patch.object(wip.first_run, "ROOT", repo):
            facts = wip.host_facts()
        self.assertFalse(marker.exists(), "a command planted in the catalog's git config ran")
        self.assertEqual(facts["catalog_commit"], wip.git_out(repo, "rev-parse", "HEAD"))
        self.assertIs(facts["catalog_dirty"], False)


class TestGate(Tmp):
    """The merge gate runs the oracle of every task the prefix commit contains, so a later unit
    that breaks a landed one fails the gate even when its own oracle passes."""

    def test_a_regression_of_a_landed_task_fails_the_gate(self):
        taskset = json.loads(TASKSET.read_text(encoding="utf-8"))
        repo = self.tmp / "repo"
        wip.build_seed(taskset, repo)
        t3 = wip.task_by_id(taskset)["T3"]
        wip.apply_edits(repo, t3["reference"])
        wip.git(repo, "commit", "-qam", "T3")
        landed = wip.git_out(repo, "rev-parse", "HEAD")
        landing = self.tmp / "landing.json"
        landing.write_text(json.dumps({"T3": [landed]}), encoding="utf-8")
        gate = ["gate", "--taskset", str(TASKSET), "--landing", str(landing)]
        ok = runner(*gate, cwd=repo)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("['T3']", ok.stdout)
        units = repo / "stocklib" / "units.py"
        units.write_text(units.read_text(encoding="utf-8").replace('    "lb": 453.59237,\n', ""), encoding="utf-8")
        wip.git(repo, "commit", "-qam", "a later unit drops pounds")
        broken = runner(*gate, cwd=repo)
        self.assertEqual(broken.returncode, 1, broken.stdout)


# ---------------------------------------------------------------------------- the inert pipeline

_DRY_RUNS: dict = {}


def dry_run(run: str, args: tuple, relative: bool = False):
    """(tmp, env, tripwire log, process) of one inert run, made once per module. `relative` runs
    it from the temp directory with --results, --workdir and --prereg given as relative paths."""
    key = (run, args, relative)
    if key not in _DRY_RUNS:
        tmp = tempfile.TemporaryDirectory(prefix="wip-curve-dry-")
        root = Path(tmp.name).resolve()  # a relative path walks the real directories (/var -> /private/var)
        env, trip_log = tripwired_env(root)
        if relative:
            proc = runner("--prereg", os.path.relpath(PREREG, root), "run", "--results", "results", "--runs", run,
                          "--workdir", "wd", *args, env=env, cwd=root)
        else:
            proc = runner("run", "--results", str(root / "results"), "--runs", run, "--workdir",
                          str(root / "wd"), *args, env=env)
        _DRY_RUNS[key] = (tmp, env, trip_log, proc)
    return _DRY_RUNS[key]


B3 = ("wip1-b3r1-rep1", ("--cost-cap-usd", "0"))
B6_CAPPED = ("wip1-b6r2-rep1", ("--cost-cap-usd", "3.40", "--inert-cost-usd", "0.25"))
# b1r1-rep1 builds T5 first. A cap of exactly one unit's worst case (a builder and a reviewer at
# 0.25 each); in the second, the fake harness reports 0.40 for the builder, over its reservation.
B1_BOUNDARY = ("wip1-b1r1-rep1", ("--cost-cap-usd", "0.50", "--inert-cost-usd", "0.25"))
_PLANT_MARKER = Path(tempfile.gettempdir()) / f"wip-curve-plant-{os.getpid()}.log"
# One run serves two findings. T5 lands first, after its builder planted diff.external, a textconv
# and a smudge driver selected by a committed .gitattributes, core.fsmonitor and a hooks directory
# in the SHARED repository config: commands only someone else's git would run, while the
# coordinator diffs, checks out, pushes and merges next to them. T3's builder then also empties
# Ledger.history(): its own oracle passes, T5's fails in the merge gate, so the queue writes a
# real `gate_failed` receipt and T3 is rebuilt.
B1_GATE = ("wip1-b1r1-rep1", ("--cost-cap-usd", "0", "--inert-script", json.dumps(
    {"T5": {"builder": ["plant"]}, "_plant": str(_PLANT_MARKER), "T3": {"builder": ["regress"]}, "_regress": {"T3": [
        {"file": "stocklib/ledger.py", "replace": "        return list(self._history)", "with": ["        return []"]}]}})))
B1_OVERSPEND = ("wip1-b1r1-rep1", ("--cost-cap-usd", "0.50", "--inert-cost-usd", "0.25",
                                   "--inert-script", json.dumps({"_cost": {"builder": "0.40"}})))


def tearDownModule():
    for tmp, *_rest in _DRY_RUNS.values():
        tmp.cleanup()
    if "tmp" in _DOCUMENTED:
        _DOCUMENTED["tmp"].cleanup()


class DryRun(unittest.TestCase):
    """One inert run per (run, arguments), shared by every class that asks for it (a run takes
    ~20 s); each tamper test works on a copy."""

    RUN, ARGS = B3

    @classmethod
    def setUpClass(cls):
        tmp, cls.env, cls.trip_log, cls.proc = dry_run(cls.RUN, cls.ARGS)
        cls.results = Path(tmp.name) / "results"
        cls.run_dir = cls.results / "runs" / cls.RUN

    def setUp(self):
        self.assertTrue((self.run_dir / "run.json").is_file(), self.proc.stdout + self.proc.stderr)
        self.record = json.loads((self.run_dir / "run.json").read_text(encoding="utf-8"))
        self.addCleanup(self.no_tripwire_hit)

    def no_tripwire_hit(self):
        hits = self.trip_log.read_text() if self.trip_log.exists() else ""
        self.assertEqual(hits, "", f"something resolved a real harness name: {hits!r}")

    def copy(self) -> Path:
        work = Path(tempfile.mkdtemp(prefix="wip-curve-copy-"))
        self.addCleanup(shutil.rmtree, work, True)
        shutil.copytree(self.results, work / "results")
        return work / "results"

    def report(self, results: Path, basis="all"):
        p = runner("report", "--results", str(results), "--basis", basis, env=self.env)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads((results / "report.json").read_text(encoding="utf-8"))

    def verify(self, results: Path):
        return runner("verify", "--results", str(results), "--report", str(results / "report.json"),
                      "--report-md", str(results / "report.md"), env=self.env)


class TestDryRunPipeline(DryRun):
    def test_the_run_completes_through_the_public_wrappers(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stdout + self.proc.stderr)
        self.assertEqual(self.record["status"], "complete")
        self.assertEqual(self.record["tier"], "fixture-tested", "an inert run is never labelled live")
        used = {Path(c["argv"][1]).name for c in self.record["commands"] if len(c["argv"]) > 1}
        for script in ("task_ops.py", "spawn_worker.sh", "worker_ops.py", "orca_cli.py", "merge_queue.py"):
            self.assertIn(script, used, f"{script} never ran: the run bypassed the public wrapper")
        self.assertEqual(self.record["seed_commit"], json.loads(PREREG.read_text())["taskset"]["seed_commit"])

    def test_the_dry_run_exercises_rework_conflict_and_close(self):
        outcomes = {t: [a["outcome"] for a in u["attempts"]] for t, u in self.record["units"].items()}
        self.assertEqual(outcomes["T1"][0], "changes-requested")
        self.assertEqual(outcomes["T3"][0], "oracle-failed")
        self.assertIn("merge-conflict", outcomes["T2"] + outcomes["T5"])
        self.assertTrue(all(u["final"] == "closed" for u in self.record["units"].values()), outcomes)
        self.assertEqual(wip.merge_counts(wip.Bound(self.run_dir))["conflicts"], 1)

    def test_every_wave_cell_derives_and_the_rows_check(self):
        rep = subprocess.run([sys.executable, str(EVENTS), "--log", str(self.run_dir / "events.jsonl"), "report"],
                             capture_output=True, text=True)
        self.assertEqual(rep.returncode, 0, rep.stdout + rep.stderr)
        chk = subprocess.run([sys.executable, str(EVENTS), "--log", str(self.run_dir / "events.jsonl"), "check",
                              "--run-report", str(self.run_dir / "run-report.md")], capture_output=True, text=True)
        self.assertEqual(chk.returncode, 0, chk.stderr)

    def test_the_report_recomputes_and_every_outcome_binds(self):
        results = self.copy()
        report = self.report(results)
        run = report["runs"][0]
        self.assertEqual(run["binding_problems"], [])
        self.assertEqual(run["metrics"]["conflicts"], 1)
        self.assertIsNotNone(run["metrics"]["throughput"]["value"])
        reviews = sum(len(u["reviews"]) for u in self.record["units"].values())
        self.assertEqual(run["metrics"]["review_usage"]["reviews"], reviews)
        self.assertEqual(run["metrics"]["review_usage"]["observed"], reviews, "a reviewer's usage went unread")
        b3 = next(c for c in report["conditions"] if c["condition"] == "b3r1")
        self.assertEqual(sorted(b3["tasks"]), ["T1", "T2", "T3", "T4", "T5", "T6"])
        p = self.verify(results)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("recomputes", p.stdout)

    def test_the_report_emits_every_registered_metric(self):
        """The registration's metric list, diffed against what the report emits (PR #652's class)."""
        fields = json.loads(PREREG.read_text(encoding="utf-8"))["metrics"]["report_fields"]
        results = self.copy()
        report = self.report(results)
        md = (results / "report.md").read_text(encoding="utf-8")
        for run in report["runs"]:
            self.assertEqual(sorted(run["registered"]), sorted(fields["run"]), run["run_id"])
        for cond in report["conditions"]:
            self.assertEqual(sorted(cond["registered"]), sorted(fields["condition"]), cond["condition"])
        for name in fields["run"] + fields["condition"]:
            self.assertIn(f"`{name}`", md, f"report.md never shows {name}")
        run = report["runs"][0]["registered"]
        self.assertIsNotNone(run["review_queue_median_min"], "the run's reviews have a measurable queue")
        self.assertEqual(run["parked"], {})

    def test_a_fixture_run_is_never_evidence(self):
        report = self.report(self.copy())
        self.assertEqual(report["compliant_runs"], [])
        self.assertIn("not a live run", " ".join(report["runs"][0]["noncompliance"]))
        self.assertTrue(report["evidence"].startswith("none"))
        self.assertEqual(report["recommendation"]["status"], "not-issued")

    def test_an_altered_metric_row_in_the_report_is_detected(self):
        results = self.copy()
        self.report(results)
        md = results / "report.md"
        text = md.read_text(encoding="utf-8")
        row = next(ln for ln in text.splitlines() if ln.startswith(f"| `{self.RUN}`"))
        forged = re.sub(r"\| [0-9.]+/h \|", "| 9.99/h |", row, count=1)
        self.assertNotEqual(forged, row)
        md.write_text(text.replace(row, forged), encoding="utf-8")
        p = self.verify(results)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("9.99/h", p.stderr)

    def test_an_altered_metric_in_the_report_json_is_detected(self):
        results = self.copy()
        report = self.report(results)
        forged = copy.deepcopy(report)
        forged["runs"][0]["metrics"]["conflicts"] = 0
        (results / "report.json").write_text(json.dumps(forged), encoding="utf-8")
        p = self.verify(results)
        self.assertEqual(p.returncode, 1)
        self.assertIn("$.runs[0].metrics.conflicts", p.stderr)

    def test_an_altered_wave_row_is_caught_by_events_check_even_when_rebound(self):
        results = self.copy()
        self.report(results)
        run_dir = results / "runs" / self.RUN
        rr = run_dir / "run-report.md"
        text = rr.read_text(encoding="utf-8")
        m = re.search(r"`rework=(\d+)/(\d+)`", text)  # wave 1's cell
        forged = f"`rework={0 if m.group(1) != '0' else m.group(2)}/{m.group(2)}`"
        rr.write_text(text.replace(m.group(0), forged, 1), encoding="utf-8")
        rebind(run_dir)  # run.json now binds the edited bytes: only the record can catch it
        p = self.verify(results)
        self.assertEqual(p.returncode, 1, p.stdout)
        self.assertIn("events: MISMATCH wave 1 rework", p.stderr)

    def test_an_edited_source_fails_closed(self):
        results = self.copy()
        (results / "runs" / self.RUN / "run-report.md").write_text("edited\n", encoding="utf-8")
        p = runner("report", "--results", str(results), env=self.env)
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("altered after the run", p.stderr)

    def test_an_unbound_file_fails_closed(self):
        results = self.copy()
        (results / "runs" / self.RUN / "oracle" / "extra.json").write_text("{}", encoding="utf-8")
        p = runner("report", "--results", str(results), env=self.env)
        self.assertEqual(p.returncode, 3)
        self.assertIn("unbound file", p.stderr)

    def test_an_edited_event_record_fails_closed_even_when_rebound(self):
        results = self.copy()
        run_dir = results / "runs" / self.RUN
        log = run_dir / "events.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        lines[3] = lines[3].replace('"v":1', '"v": 1', 1)  # the same JSON, other bytes
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rebind(run_dir)
        p = runner("report", "--results", str(results), env=self.env)
        self.assertEqual(p.returncode, 3, p.stderr)
        self.assertIn("prev does not match", p.stderr)


class TestOutcomesBindToGitAndReview(DryRun):
    """Each terminal outcome is re-derived from the retained bundle and artifacts; a forged one
    stops binding, and the run stops being compliant."""

    def problems_after(self, mutate) -> list[str]:
        results = self.copy()
        run_dir = results / "runs" / self.RUN
        mutate(run_dir)
        rebind(run_dir)
        return wip.build_report(results, basis="all")["runs"][0]["binding_problems"]

    def test_a_closed_head_missing_from_the_integration_branch_does_not_bind(self):
        def rewind(run_dir):
            work = run_dir.parent.parent / "rewind"
            wip.git(run_dir.parent, "clone", "-q", "--mirror", str(run_dir / "target.bundle"), str(work))
            seed = json.loads(PREREG.read_text())["taskset"]["seed_commit"]
            wip.git(work, "update-ref", "refs/heads/wip-integration", seed)
            (run_dir / "target.bundle").unlink()
            wip.git(work, "bundle", "create", "-q", str(run_dir / "target.bundle"), "--all")
            shutil.rmtree(work)
        problems = self.problems_after(rewind)
        self.assertTrue(any("not on wip-integration" in p for p in problems), problems)

    def test_a_forged_review_artifact_does_not_bind(self):
        def forge(run_dir):
            for review in (run_dir / "reviews").iterdir():  # rewritten after the review.verdict event
                review.write_text(review.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        problems = self.problems_after(forge)
        self.assertTrue(any("review artifact" in p for p in problems), problems)

    def test_an_altered_oracle_transcript_does_not_bind(self):
        def forge(run_dir):
            path = run_dir / "oracle" / "t4-a1.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            doc["tail"] = ["edited"]
            path.write_text(json.dumps(doc), encoding="utf-8")
        problems = self.problems_after(forge)
        self.assertTrue(any("oracle transcript" in p for p in problems), problems)

    def test_a_recorded_conflict_git_does_not_reproduce_does_not_bind(self):
        def forge(run_dir):
            rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            seed = json.loads(PREREG.read_text())["taskset"]["seed_commit"]
            for merge in rec["merges"]:
                if merge["result"] == "conflict":
                    merge["against_ref"] = seed  # the unit's own base: it merges cleanly there
            (run_dir / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        problems = self.problems_after(forge)
        self.assertTrue(any("does not re-derive" in p for p in problems), problems)

    def test_a_reviewer_may_dress_its_verdict_line_in_markdown(self):
        nonce, head = "WIP-NONCE:" + "ab" * 8, "c" * 40
        for line in (f"WIP-REVIEW {nonce} {head} approve", f"`WIP-REVIEW {nonce} {head} approve`",
                     f"**WIP-REVIEW {nonce} {head} approve**"):
            self.assertEqual(wip.REVIEW_LINE.search(f"notes\n{line}\n").group(3), "approve", line)
        self.assertIsNone(wip.REVIEW_LINE.search(f"I would say WIP-REVIEW {nonce} {head} approve"),
                          "a verdict inside a sentence is not the verdict line")

    def test_the_untouched_run_binds(self):
        self.assertEqual(self.problems_after(lambda _d: None), [])


class TestGuardIsVerified(Tmp):
    """Every spawned worker's installed deny hook is checked armed (first_run.py's guard step)."""

    def test_an_unarmed_guard_fails_the_run(self):
        wt = self.tmp / "wt"
        (wt / ".claude").mkdir(parents=True)
        block = subprocess.run(["sh", str(ROOT / "runtime" / "scripts" / "deny-hook.sh"), "--settings", str(wt)],
                               capture_output=True, text=True, check=True).stdout
        (wt / ".claude" / "settings.local.json").write_text(block, encoding="utf-8")
        run = wip.Run.__new__(wip.Run)
        run.guard(wt)  # the hook deny-hook.sh itself writes is armed
        doc = json.loads(block)
        for entry in doc["hooks"]["PreToolUse"]:
            for hook in entry["hooks"]:
                hook["command"] = "true # registered but never denies"
        (wt / ".claude" / "settings.local.json").write_text(json.dumps(doc), encoding="utf-8")
        with self.assertRaises(wip.RunFailed):
            run.guard(wt)


class TestTheAssignmentReachesTheLaunch(Tmp):
    """Adversarial pass (inputs that never reach the launch): the unit's assignment, by its nonce,
    must be in the launch the provider recorded; a launch without it is stopped at once and the
    run fails. Every dispatch's effective launch (agent, flags, command digest) is recorded."""

    def spawned(self, launch):
        run = wip.Run.__new__(wip.Run)
        run.launched, run.launches, run.commands, run.rid = {}, {}, [], "wip1-b1r1-rep1"
        run.args = argparse.Namespace(agent="claude")
        run.guard = lambda _wt: None
        calls = []

        def wrapper(argv, env=None, cwd=None, timeout=600):
            calls.append([str(a) for a in argv])
            out = "DISPATCH=disp_0123456789\nHANDLE=term_x\n" + (f"LAUNCH_EFFECTIVE={json.dumps(launch)}\n" if launch else "")
            return subprocess.CompletedProcess(argv, 0, out, "")
        run.wrapper = wrapper
        return run, calls

    def test_a_launch_without_the_assignment_is_stopped(self):
        run, calls = self.spawned({"agent": "claude", "args": "--dangerously-skip-permissions",
                                   "command": "claude -p --dangerously-skip-permissions 'another task'"})
        with self.assertRaises(wip.RunFailed):
            run.spawn("task_1", self.tmp, "t", "rw", "T1:builder", "WIP-NONCE:" + "a" * 16)
        self.assertTrue(any("stop" in c for c in calls), "the launched worker was not stopped")

    def test_a_launch_the_provider_did_not_record_is_refused(self):
        run, _calls = self.spawned(None)
        with self.assertRaises(wip.RunFailed):
            run.spawn("task_1", self.tmp, "t", "rw", "T1:builder", "WIP-NONCE:" + "a" * 16)

    def test_the_effective_launch_is_recorded(self):
        nonce = "WIP-NONCE:" + "a" * 16
        command = f"claude -p --dangerously-skip-permissions 'WIP-BUILD {nonce} task=T1'"
        run, _calls = self.spawned({"agent": "claude", "args": "--dangerously-skip-permissions", "command": command})
        disp = run.spawn("task_1", self.tmp, "t", "rw", "T1:builder", nonce)
        self.assertEqual(run.launches[disp], {"agent": "claude", "args": "--dangerously-skip-permissions",
                                              "command_sha256": hashlib.sha256(command.encode()).hexdigest()})


class TestCostCapStopsTheExperiment(DryRun):
    """The inert stand-in reports a synthetic 0.25 USD per dispatch (not a spend) so the cap is
    reached: six builders and six reviewers spend 3.00 of 3.40, the four bounced units' next wave
    would need 2.00 more, so the run parks them and stays derivable, and no further run starts."""

    RUN, ARGS = B6_CAPPED

    def test_the_run_stops_and_parks_every_unit_in_flight(self):
        self.assertEqual(self.record["status"], "stopped", self.proc.stdout + self.proc.stderr)
        self.assertEqual(self.record["stop_reason"], "cost-cap")
        parked = {t: u["park_class"] for t, u in self.record["units"].items() if u["final"] == "parked"}
        self.assertTrue(parked)
        self.assertEqual(set(parked.values()), {"stopped-cost-cap"})
        self.assertEqual(Decimal(self.record["cost"]["observed_usd"]), Decimal("3.00"))
        rep = subprocess.run([sys.executable, str(EVENTS), "--log", str(self.run_dir / "events.jsonl"), "report"],
                             capture_output=True, text=True)
        self.assertEqual(rep.returncode, 0, "a stopped run's record must still derive every cell\n" + rep.stdout)
        self.assertIn("reviewers=2", rep.stdout)

    def test_a_parked_head_git_does_not_hold_does_not_bind(self):
        parked = [a["head"] for u in self.record["units"].values() if u["final"] == "parked"
                  for a in u["attempts"][-1:] if a.get("head")]
        self.assertTrue(parked)
        results = self.copy()
        run_dir = results / "runs" / self.RUN
        self.assertEqual(wip.build_report(results, basis="all")["runs"][0]["binding_problems"], [])
        work = results.parent / "drop"
        wip.git(run_dir, "clone", "-q", "--mirror", str(run_dir / "target.bundle"), str(work))
        refs = wip.git_out(work, "for-each-ref", "--format=%(refname)", "--points-at", parked[0]).split()
        for ref in refs:
            wip.git(work, "update-ref", "-d", ref)
        (run_dir / "target.bundle").unlink()
        wip.git(work, "bundle", "create", "-q", str(run_dir / "target.bundle"), "--all")
        rebind(run_dir)
        problems = wip.build_report(results, basis="all")["runs"][0]["binding_problems"]
        self.assertTrue(any("does not hold that head" in p for p in problems), problems)

    def test_a_stopped_run_is_reported_not_dropped(self):
        results = self.copy()
        report = wip.build_report(results, basis="all")
        run = report["runs"][0]
        self.assertEqual(run["status"], "stopped")
        self.assertIn("the run ended stopped (cost-cap)", run["noncompliance"])

    def test_no_further_run_starts_past_the_cap(self):
        results = self.copy()
        # 3.00 spent; even the serial next run's first wave (2 x 0.25) would pass 3.40.
        p = runner("run", "--results", str(results), "--cost-cap-usd", "3.40", "--inert-cost-usd", "0.25",
                   "--next", "1", "--workdir", str(results.parent / "wd2"), env=self.env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("not started", p.stderr)
        self.assertEqual([d.name for d in (results / "runs").iterdir()], [self.RUN])

    def test_a_stream_with_any_unreported_cost_is_unobserved(self):
        stream = Path(tempfile.mkdtemp(prefix="wip-curve-stream-")) / "s.jsonl"
        self.addCleanup(shutil.rmtree, stream.parent, True)
        stream.write_text(json.dumps({"type": "result", "result": "a", "total_cost_usd": 0.5}) + "\n"
                          + json.dumps({"type": "result", "result": "b"}) + "\n", encoding="utf-8")
        self.assertIsNone(wip.Run.stream_cost(stream), "a partial sum is not the dispatch's cost")
        stream.write_text(json.dumps({"type": "result", "result": "a", "total_cost_usd": 0.5}) + "\n",
                          encoding="utf-8")
        self.assertEqual(wip.Run.stream_cost(stream), Decimal("0.5"))

    def test_an_unobserved_dispatch_is_charged_the_reservation(self):
        run = wip.Run.__new__(wip.Run)
        run.usage_seen, run.observed, run.reserved, run.held = set(), Decimal(0), Decimal(0), {}
        run.reservation, run.spent_before = Decimal("2.00"), Decimal("1.00")
        run.dispatch_row = lambda _d: {"lane_dir": None}  # no stream retained: nothing observed
        self.assertEqual(run.ingest_usage("disp_x", "task_x"), Decimal("2.00"))
        self.assertEqual(run.ingest_usage("disp_x", "task_x"), Decimal(0), "one dispatch is charged once")
        self.assertEqual(run.spent(), Decimal("3.00"))


class TestComplianceNeedsLiveBoundEvidence(unittest.TestCase):
    """A run counts toward the curve only when it is live, pinned, from the seed and cooled down:
    fixture runs relabelled as live show each rule catching what it is for."""

    @classmethod
    def setUpClass(cls):
        cls.env = dry_run(*B3)[1]
        cls.sources = [Path(dry_run(*key)[0].name) / "results" / "runs" / key[0] for key in (B3, B6_CAPPED)]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wip-curve-compliance-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for src in self.sources:
            self.assertTrue((src / "run.json").is_file())
            shutil.copytree(src, self.tmp / "runs" / src.name)

    def edit(self, run, **fields):
        path = self.tmp / "runs" / run / "run.json"
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec.update(fields)
        path.write_text(json.dumps(rec), encoding="utf-8")  # run.json binds; it is not bound itself

    def runs(self):
        return {r["run_id"]: r for r in wip.build_report(self.tmp, basis="all")["runs"]}

    def test_a_run_that_did_not_keep_the_cooldown_is_not_compliant(self):
        live = {"tier": "live-unreviewed", "worker": "live"}
        self.edit(B3[0], started_at="2026-10-24T10:00:00+00:00", finished_at="2026-10-24T11:00:00+00:00", **live)
        self.edit(B6_CAPPED[0], started_at="2026-10-24T11:01:00+00:00", finished_at="2026-10-24T12:00:00+00:00",
                  **live)
        runs = self.runs()
        self.assertTrue(any("the cooldown is 600s" in why for why in runs[B6_CAPPED[0]]["noncompliance"]),
                        runs[B6_CAPPED[0]]["noncompliance"])
        self.assertFalse(any("cooldown" in why for why in runs[B3[0]]["noncompliance"]))

    def test_an_observed_model_other_than_the_pin_is_not_compliant(self):
        self.edit(B3[0], model_pin="claude-pinned", harness={"version": "1.0"})
        why = self.runs()[B3[0]]["noncompliance"]
        self.assertIn("observed model(s) ['inert-stand-in'] are not the pin 'claude-pinned'", why)
        self.edit(B3[0], model_pin="inert-stand-in")
        self.assertFalse(any("not the pin" in w for w in self.runs()[B3[0]]["noncompliance"]))

    def test_a_run_on_other_experiment_inputs_is_not_compliant(self):
        live = {"tier": "live-unreviewed", "worker": "live"}
        self.edit(B3[0], started_at="2026-10-24T10:00:00+00:00", finished_at="2026-10-24T11:00:00+00:00", **live)
        self.edit(B6_CAPPED[0], started_at="2026-10-24T12:00:00+00:00", finished_at="2026-10-24T13:00:00+00:00",
                  inputs={"sha256": "f" * 64, "files": {}}, **live)
        why = self.runs()[B6_CAPPED[0]]["noncompliance"]
        self.assertTrue(any("experiment inputs" in w for w in why), why)

    def test_a_run_that_did_not_start_at_the_seed_does_not_bind(self):
        self.edit(B3[0], seed_commit="0" * 40)
        problems = self.runs()[B3[0]]["binding_problems"]
        self.assertTrue(any("not the registered seed commit" in p for p in problems), problems)


class TestSpendIsReservedBeforeEachDispatch(Tmp):
    """The ledger admits a dispatch only while measured spend, unobserved charges and every held
    reservation, this dispatch's included, stay within the cap: the exact boundary is admitted,
    a cent over is not."""

    def ledger(self, cap, spent_before="0"):
        run = wip.Run.__new__(wip.Run)
        run.cap, run.spent_before, run.reservation = Decimal(cap), Decimal(spent_before), Decimal("0.25")
        run.observed, run.reserved, run.held, run.usage_seen = Decimal(0), Decimal(0), {}, set()
        run.halt, run.deadline = None, float("inf")
        return run

    def test_the_exact_boundary_is_admitted_and_a_cent_over_is_not(self):
        run = self.ledger("0.50")
        self.assertTrue(run.hold_unit("T1"))  # builder + reviewer, 0.50 of 0.50
        self.assertTrue(run.admit("T1:builder"))
        self.assertFalse(self.ledger("0.49").hold_unit("T1"))

    def test_a_measured_overspend_refuses_the_next_dispatch_before_it_starts(self):
        run = self.ledger("0.50")
        self.assertTrue(run.hold_unit("T1"))
        run.settle("T1:builder", Decimal("0.40"))  # the builder spent past its 0.25 reservation
        self.assertEqual(run.committed(), Decimal("0.65"))
        self.assertFalse(run.admit("T1:reviewer"), "a reviewer may not start once the cap is passed")
        self.assertEqual(run.committed(), Decimal("0.40"), "a refused dispatch releases its hold")

    def test_spend_before_this_run_counts(self):
        self.assertFalse(self.ledger("0.50", spent_before="0.01").hold_unit("T1"))


class TestExactCapBoundary(DryRun):
    RUN, ARGS = B1_BOUNDARY

    def test_a_cap_that_exactly_covers_one_unit_runs_it_and_no_more(self):
        self.assertEqual(self.record["status"], "stopped", self.proc.stdout + self.proc.stderr)
        self.assertEqual(self.record["stop_reason"], "cost-cap")
        t5 = self.record["units"]["T5"]
        self.assertEqual((t5["final"], len(t5["attempts"]), len(t5["reviews"])), ("closed", 1, 1))
        self.assertEqual(Decimal(self.record["cost"]["observed_usd"]), Decimal("0.50"))
        self.assertEqual(sorted(self.record["not_run"]), ["T1", "T2", "T3", "T4", "T6"])


class TestAnOverspentBuilderGetsNoReviewer(DryRun):
    """A fake harness reports 0.40 for a builder reserved at 0.25: the reviewer that would take
    the run to 0.65 of 0.50 is refused BEFORE it starts, so the cap is never passed."""

    RUN, ARGS = B1_OVERSPEND

    def test_the_reviewer_is_refused_and_the_unit_parked(self):
        t5 = self.record["units"]["T5"]
        self.assertEqual(t5["reviews"], [], "a reviewer was dispatched past the cap")
        self.assertEqual(t5["attempts"][0]["outcome"], "stopped-cost-cap")
        self.assertEqual((t5["final"], t5["park_class"]), ("parked", "stopped-cost-cap"))
        spent = Decimal(self.record["cost"]["observed_usd"]) + Decimal(self.record["cost"]["reserved_unobserved_usd"])
        self.assertEqual(spent, Decimal("0.40"))
        self.assertLessEqual(spent, Decimal(self.record["cost"]["cap_usd"]))
        rep = subprocess.run([sys.executable, str(EVENTS), "--log", str(self.run_dir / "events.jsonl"), "report"],
                             capture_output=True, text=True)
        self.assertNotIn("unavailable", rep.stdout.split("Derived by")[0], "the stopped run must stay derivable")


class TestNoWriteTouchesTheRepository(Tmp):
    """Every path the runner writes to, or later deletes, is refused when it resolves to, inside
    or around the repository's sources or the registered task set, symlinks followed; and a
    sandbox is only ever a fresh directory, never one that already holds something."""

    def setUp(self):
        super().setUp()
        self.env, self.trip_log = tripwired_env(self.tmp)
        self.addCleanup(lambda: self.assertFalse(self.trip_log.exists(), "a refused run reached a harness"))

    def link(self, name, target):
        path = self.tmp / name
        path.symlink_to(target, target_is_directory=Path(target).is_dir())
        return path

    def test_the_overlap_check_refuses_sources_seed_and_symlinks(self):
        refused = [ROOT / "docs" / "experiments" / "out", ROOT / "scripts", ROOT, ROOT.parent, TASKSET, PREREG,
                   ROOT / "skills" / "ship-it", self.link("into-runtime", ROOT / "runtime") / "x",
                   self.link("into-tests", ROOT / "tests")]
        for path in refused:
            with self.subTest(path=str(path)), self.assertRaises(wip.Refused):
                wip.check_writable(path, "--results")
        wip.check_writable(self.tmp / "results", "--results")  # an unrelated directory is fine

    def test_a_report_into_a_symlink_to_the_docs_is_refused_and_writes_nothing(self):
        out = self.link("out", ROOT / "docs" / "experiments")
        results = Path(dry_run(*B1_BOUNDARY)[0].name) / "results"
        p = runner("report", "--results", str(results), "--out", str(out), "--basis", "all", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse((ROOT / "docs" / "experiments" / "report.json").exists())

    def test_a_report_file_that_is_a_link_into_the_sources_is_refused(self):
        out = self.tmp / "out"
        out.mkdir()
        before = TASKSET.read_bytes()
        (out / "report.json").symlink_to(TASKSET)
        results = Path(dry_run(*B1_BOUNDARY)[0].name) / "results"
        p = runner("report", "--results", str(results), "--out", str(out), "--basis", "all", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(TASKSET.read_bytes(), before, "the report overwrote the registered task set")

    def test_any_existing_link_as_a_report_file_is_refused(self):
        out = self.tmp / "out"
        out.mkdir()
        elsewhere = self.tmp / "elsewhere.md"
        elsewhere.write_text("not a report\n", encoding="utf-8")
        (out / "report.md").symlink_to(elsewhere)
        results = Path(dry_run(*B1_BOUNDARY)[0].name) / "results"
        p = runner("report", "--results", str(results), "--out", str(out), "--basis", "all", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertEqual(elsewhere.read_text(encoding="utf-8"), "not a report\n")

    def test_a_run_into_a_symlink_to_the_docs_is_refused_and_writes_nothing(self):
        results = self.link("results", ROOT / "docs")
        p = runner("run", "--results", str(results), "--workdir", str(self.tmp / "wd"), "--runs",
                   "wip1-b1r1-rep1", "--cost-cap-usd", "0.50", "--inert-cost-usd", "0.25", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse((ROOT / "docs" / "runs" / "wip1-b1r1-rep1").exists())

    def test_a_runs_directory_linked_into_the_sources_is_refused(self):
        results = self.tmp / "results"
        results.mkdir()
        (results / "runs").symlink_to(ROOT / "docs" / "runs")
        p = runner("run", "--results", str(results), "--workdir", str(self.tmp / "wd"), "--runs",
                   "wip1-b1r1-rep1", "--cost-cap-usd", "0.50", "--inert-cost-usd", "0.25", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse((ROOT / "docs" / "runs" / "wip1-b1r1-rep1").exists())

    def test_a_sandbox_that_already_holds_something_is_refused_and_kept(self):
        keep = self.tmp / "wd" / "wip1-b6r1-rep1" / "keep.txt"
        keep.parent.mkdir(parents=True)
        keep.write_text("not the runner's", encoding="utf-8")
        p = runner("run", "--results", str(self.tmp / "results"), "--workdir", str(self.tmp / "wd"), "--runs",
                   "wip1-b6r1-rep1", "--cost-cap-usd", "0", "--inert-script", "{}", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertTrue(keep.is_file(), "a complete run deleted a directory it did not create")

    def test_results_inside_the_sandbox_it_deletes_are_refused(self):
        wd = self.tmp / "wd"
        results = wd / "wip1-b6r1-rep1" / "results"
        p = runner("run", "--results", str(results), "--workdir", str(wd), "--runs", "wip1-b6r1-rep1",
                   "--cost-cap-usd", "0", "--inert-script", "{}", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertFalse(results.exists())


class TestRegisteredInputsBlockARun(Tmp):
    """A change to anything the experiment depends on blocks a run until it is re-registered."""

    def setUp(self):
        super().setUp()
        self.env, self.trip_log = tripwired_env(self.tmp)

    def test_a_seed_the_task_set_does_not_build_is_refused_before_a_run_starts(self):
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        prereg["taskset"]["path"] = str(TASKSET)
        prereg["taskset"]["seed_commit"] = "0" * 40
        path = self.tmp / "prereg.json"
        path.write_text(json.dumps(prereg), encoding="utf-8")
        p = runner("--prereg", str(path), "run", "--results", str(self.tmp / "results"), "--workdir",
                   str(self.tmp / "wd"), "--runs", "wip1-b1r1-rep1", "--cost-cap-usd", "0", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("seed_commit", p.stderr)
        self.assertFalse((self.tmp / "results" / "runs").exists(), "a refused run left a run record")

    def test_results_under_another_registration_refuse_the_next_run(self):
        src = Path(dry_run(*B1_BOUNDARY)[0].name) / "results" / "runs" / B1_BOUNDARY[0]
        results = self.tmp / "results"
        shutil.copytree(src, results / "runs" / src.name)
        rec = json.loads((results / "runs" / src.name / "run.json").read_text(encoding="utf-8"))
        rec["prereg"]["sha256"] = "e" * 64  # a run made under an earlier registration
        (results / "runs" / src.name / "run.json").write_text(json.dumps(rec), encoding="utf-8")
        p = runner("run", "--results", str(results), "--workdir", str(self.tmp / "wd"), "--runs", "wip1-b3r1-rep1",
                   "--cost-cap-usd", "0", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("re-register", p.stderr)
        self.assertEqual([d.name for d in (results / "runs").iterdir()], [src.name])

    def test_uncommitted_experiment_inputs_are_named(self):
        repo = self.tmp / "repo"
        for rel in ("scripts/wip_curve.py", "docs/experiments/wip-curve-prereg.json", "README.md"):
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text("v1\n", encoding="utf-8")
        wip.git(repo, "init", "-q")
        wip.git(repo, "add", "-A")
        wip.git(repo, "-c", "user.email=t@t.invalid", "-c", "user.name=t", "commit", "-qm", "seed")
        self.assertEqual(wip.dirty_inputs(repo), [])
        (repo / "scripts" / "wip_curve.py").write_text("v2\n", encoding="utf-8")
        (repo / "README.md").write_text("v2\n", encoding="utf-8")  # not an experiment input
        self.assertEqual(wip.dirty_inputs(repo), ["scripts/wip_curve.py"])

    def test_a_live_run_refuses_uncommitted_inputs_before_anything_starts(self):
        # In-process with dirty_inputs faked. Were the check gone, the cost pre-check (a cap of 1.00
        # below the first wave's 2.00) would still stop the run before any harness: rc 1, not 2.
        err = io.StringIO()
        with mock.patch.object(wip, "dirty_inputs", return_value=["scripts/wip_curve.py"]), \
                contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            rc = wip.main(["run", "--results", str(self.tmp / "results"), "--workdir", str(self.tmp / "wd"),
                           "--worker", "live", "--model", "m", "--cost-cap-usd", "1.00", "--reservation-usd",
                           "1.00", "--runs", "wip1-b1r1-rep1"])
        self.assertEqual(rc, 2, err.getvalue())
        self.assertIn("uncommitted: ['scripts/wip_curve.py']", err.getvalue())
        self.assertFalse((self.tmp / "results" / "runs").exists())

    def test_every_run_records_the_digest_of_its_inputs(self):
        record = json.loads((Path(dry_run(*B1_BOUNDARY)[0].name) / "results" / "runs" / B1_BOUNDARY[0]
                             / "run.json").read_text(encoding="utf-8"))
        files = record["inputs"]["files"]
        for rel in ("scripts/wip_curve.py", "docs/experiments/wip-curve-prereg.json",
                    "docs/experiments/wip-curve-taskset.json", "runtime/scripts/events.py",
                    "runtime/providers/posix.py"):
            self.assertEqual(files[rel], hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), rel)
        self.assertEqual(record["inputs"]["sha256"], wip.experiment_inputs()["sha256"])


class TestMergeQueueFailuresAreCounted(Tmp):
    """Conflicts and gate failures come from the merge queue's own receipts, as it writes them:
    a real failed-gate receipt (reason `gate_failed`) counts once, never as zero."""

    def receipts_with_a_failed_gate(self) -> Path:
        mq = [sys.executable, str(ROOT / "runtime" / "scripts" / "merge_queue.py"), "--db", str(self.tmp / "mq.db"),
              "--repo-dir", str(self.tmp / "clone")]
        env = {**os.environ, "OPEN_FLEET_STATE_DIR": str(self.tmp / "mq-state")}
        wip.git(self.tmp, "init", "-q", "--bare", str(self.tmp / "origin.git"))
        seed = self.tmp / "seed"
        wip.build_seed(json.loads(TASKSET.read_text(encoding="utf-8")), seed)
        wip.git(seed, "push", "-q", str(self.tmp / "origin.git"), "main:refs/heads/main", "main:refs/heads/wip-integration")
        wip.git(self.tmp, "clone", "-q", str(self.tmp / "origin.git"), str(self.tmp / "clone"))
        clone = self.tmp / "clone"
        wip.configure_repo(clone)
        wip.git(clone, "checkout", "-q", "-b", "unit", "origin/wip-integration")
        (clone / "NOTES.md").write_text("a unit\n", encoding="utf-8")
        wip.git(clone, "add", "NOTES.md")
        wip.git(clone, "commit", "-qm", "unit")
        wip.git(clone, "push", "-q", "origin", "unit")
        head = wip.git_out(clone, "rev-parse", "HEAD")

        def call(*args):
            out = subprocess.run([*mq, *args], capture_output=True, text=True, env=env)
            return json.loads(out.stdout)
        call("init", "--base", "wip-integration", "--default", "main", "--consent", "test", "--mode", "git")
        token = call("acquire", "--base", "wip-integration", "--holder", "t")["token"]
        call("enqueue", "--token", token, "--payload", json.dumps(
            {"unit": "u1", "branch": "unit", "base": "wip-integration", "reviewed_sha": head, "pr": None}))
        call("release", "--token", token)
        drained = call("drain", "--base", "wip-integration", "--holder", "t", "--gate-cmd", "exit 1", "--ack")
        self.assertEqual((drained.get("data") or {}).get("reason"), "gate_failed", drained)
        run_dir = self.tmp / "run"
        run_dir.mkdir()
        (run_dir / "merge-receipts.json").write_text(json.dumps(call("receipts", "--base", "wip-integration")),
                                                    encoding="utf-8")
        (run_dir / "run.json").write_text(json.dumps({"run_id": "r", "sources": {
            "merge-receipts.json": hashlib.sha256((run_dir / "merge-receipts.json").read_bytes()).hexdigest()}}),
            encoding="utf-8")
        return run_dir

    def test_a_real_failed_gate_receipt_counts_as_a_gate_failure(self):
        counts = wip.merge_counts(wip.Bound(self.receipts_with_a_failed_gate()))
        self.assertEqual((counts["gate_failures"], counts["conflicts"]), (1, 0), counts)

    def test_an_unclassified_failure_leaves_the_counts_unavailable_not_zero(self):
        run_dir = self.receipts_with_a_failed_gate()
        doc = json.loads((run_dir / "merge-receipts.json").read_text(encoding="utf-8"))
        for receipt in doc["receipts"]:
            if receipt["kind"] == "failed":
                receipt["body"]["reason"] = "merge_refused"
        (run_dir / "merge-receipts.json").write_text(json.dumps(doc), encoding="utf-8")
        rebind(run_dir)
        counts = wip.merge_counts(wip.Bound(run_dir))
        self.assertIsNone(counts["gate_failures"], counts)


class TestAFailedMergeGateIsReported(DryRun):
    RUN, ARGS = B1_GATE

    def test_the_failed_gate_bounces_the_unit_and_counts_once(self):
        self.assertEqual(self.record["status"], "complete", self.proc.stdout + self.proc.stderr)
        t3 = self.record["units"]["T3"]
        self.assertEqual([a["outcome"] for a in t3["attempts"]], ["gate-failed", "landed"])
        report = wip.build_report(self.copy(), basis="all")
        self.assertEqual(report["runs"][0]["registered"]["gate_failures"], 1)
        self.assertEqual(report["runs"][0]["binding_problems"], [])


class TestWorkerGitConfigNeverRunsOnTheCoordinator(DryRun):
    """PR #653 review: every coordinator git call over the target repository goes through
    gitexec's hardened environment with the repository's declared drivers blanked."""

    RUN, ARGS = B1_GATE

    def test_no_planted_command_ran_on_the_coordinator(self):
        for path in (_PLANT_MARKER, Path(f"{_PLANT_MARKER}.sh"), Path(f"{_PLANT_MARKER}.hooks")):
            self.addCleanup(shutil.rmtree if path.suffix == ".hooks" else Path.unlink, *(
                (path, True) if path.suffix == ".hooks" else (path,)))
        ran = _PLANT_MARKER.read_text(encoding="utf-8").splitlines() if _PLANT_MARKER.exists() else []
        # Later builders share the config, so their OWN git runs it (worker=<their dispatch>): that
        # stays inside a guarded worker session. Nothing may run with no worker (the coordinator).
        self.assertEqual([ln for ln in ran if "worker=none" in ln], [],
                         "a worker-planted git command ran on the coordinator")
        self.assertTrue(ran, "the plant never armed: later builders' own git should have run it")
        self.assertEqual(self.record["status"], "complete", self.proc.stdout + self.proc.stderr)
        self.assertEqual(self.record["units"]["T5"]["final"], "closed")


class TestAnInterruptedRunSettlesItsSpend(Tmp):
    """PR #653 review: SIGTERM, SIGHUP or Ctrl-C mid-dispatch. The runner kills every child
    process group and stops every worker before it exits 128+N, and charges each launched
    dispatch whose usage was never read its full reservation, so a later run cannot spend it."""

    def interrupt(self, sig):
        env, trip_log = tripwired_env(self.tmp)
        wd, results = self.tmp / "wd", self.tmp / "results"
        script = json.dumps({"_sleep": {"builder": 60}})
        proc = subprocess.Popen([sys.executable, str(RUNNER), "run", "--results", str(results), "--workdir", str(wd),
                                 "--runs", "wip1-b1r1-rep1", "--cost-cap-usd", "5", "--inert-cost-usd", "0.25",
                                 "--inert-script", script], cwd=str(ROOT), env=env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        runs_log = wd / "wip1-b1r1-rep1" / "inert" / "runs.log"
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline and not (runs_log.is_file() and '"builder"' in runs_log.read_text()):
            time.sleep(0.2)
        self.assertTrue(runs_log.is_file(), "the builder never started")
        time.sleep(1.0)  # the stand-in is now asleep inside its dispatch
        pids = [int(p.read_text()) for p in (wd / "wip1-b1r1-rep1" / "inert").glob("*.pid")]
        proc.send_signal(sig)
        out, err = proc.communicate(timeout=180)
        self.assertEqual(proc.returncode, 128 + sig, out + err)
        record = json.loads((results / "runs" / "wip1-b1r1-rep1" / "run.json").read_text(encoding="utf-8"))
        self.assertFalse(trip_log.exists())
        return record, pids

    def assert_settled(self, record, pids):
        self.assertEqual(record["status"], "interrupted")
        self.assertEqual(Decimal(record["cost"]["reserved_unobserved_usd"]), Decimal("0.25"),
                         "the interrupted builder's call was never charged")
        self.assertEqual(Decimal(record["cost"]["observed_usd"]), Decimal("0"))
        self.assertTrue(pids, "the stand-in recorded no pid")
        for pid in pids:
            with self.assertRaises(ProcessLookupError, msg=f"pid {pid} outlived the run"):
                os.kill(pid, 0)

    def test_sigterm_mid_dispatch(self):
        self.assert_settled(*self.interrupt(signal.SIGTERM))

    def test_ctrl_c_mid_dispatch(self):
        self.assert_settled(*self.interrupt(signal.SIGINT))


def install_fake_harness(bin_dir: Path, *, cost="0.25", script=None) -> Path:
    """A fake `claude` first on PATH for a --worker live run: the runner's own inert stand-in,
    answering as a harness that reads its model from ANTHROPIC_MODEL and reports fake costs."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "worker.py").write_text(wip.INERT_WORKER, encoding="utf-8")
    (bin_dir / "wip-config.json").write_text(json.dumps(
        {"taskset": str(TASKSET), "runner": str(RUNNER), "script": script or {}, "cost_usd": cost}), encoding="utf-8")
    launcher = bin_dir / "claude"
    launcher.write_text(f'#!/bin/sh\nexec {sys.executable} -I {bin_dir / "worker.py"} claude "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


class LiveWithAFakeHarness(Tmp):
    """--worker live end to end, against a fake harness (never a real one: a tripwire answers
    for every other harness name, and HOME is private)."""

    def live(self, *extra, script=None, run="wip1-b1r1-rep1", model="wip-fake-model", cost="0.25"):
        env, self.trip_log = tripwired_env(self.tmp)
        fake = self.tmp / "fake-bin"
        install_fake_harness(fake, cost=cost, script=script)
        env.update(PATH=os.pathsep.join([str(fake), env["PATH"]]), HOME=str(self.tmp / "home"))
        (self.tmp / "home").mkdir(exist_ok=True)
        self.results = self.tmp / "results"
        with mock.patch.object(wip, "dirty_inputs", return_value=[]):
            p = run_in_process(["run", "--results", str(self.results), "--workdir", str(self.tmp / "wd"),
                                "--worker", "live", "--agent", "claude", "--model", model, "--cost-cap-usd", "20",
                                "--reservation-usd", cost, "--runs", run, *extra], env)
        self.assertFalse(self.trip_log.exists(), "a real harness name was reached")
        return p, self.results / "runs" / run / "run.json"


class TestTheModelPinReachesTheLaunch(LiveWithAFakeHarness):
    """PR #653 review: --model must reach the harness, and the run records the model each call
    truly launched; a harness that ignores the pin is stopped before its next call."""

    def test_the_pinned_model_is_the_model_every_call_launched(self):
        results, p = documented_live_run()  # the page's own live command, against a fake claude
        record = json.loads((results / "runs" / "wip1-b1r1-rep1" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(record["status"], "complete", p.stdout + p.stderr)
        self.assertTrue(record["launched_models"])
        self.assertEqual(set(record["launched_models"].values()), {"wip-fake-model"})
        report = wip.build_report(results, basis="all")
        self.assertEqual(report["runs"][0]["metrics"]["models"], ["wip-fake-model"])
        self.assertTrue(report["runs"][0]["compliant"], report["runs"][0]["noncompliance"])

    def test_a_harness_that_ignores_the_pin_gets_no_second_call(self):
        p, run_json = self.live(script={"_ignore_model_env": True})
        record = json.loads(run_json.read_text(encoding="utf-8"))
        self.assertEqual((record["status"], record["stop_reason"]), ("stopped", "model-mismatch"),
                         p.stdout + p.stderr)
        self.assertEqual(list(record["launched_models"].values()), ["inert-stand-in"])
        t5 = record["units"]["T5"]
        self.assertEqual((t5["reviews"], t5["final"], t5["park_class"]), ([], "parked", "stopped-model-mismatch"))

    def test_a_harness_with_no_enforceable_model_selection_is_refused(self):
        env, trip_log = tripwired_env(self.tmp)
        p = run_in_process(["run", "--results", str(self.tmp / "r"), "--worker", "live", "--agent", "codex",
                            "--model", "m", "--cost-cap-usd", "5", "--reservation-usd", "1", "--runs",
                            "wip1-b1r1-rep1"], env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("cannot enforce", p.stderr)
        self.assertFalse(trip_log.exists())


class TestTheRunDeadlineIsKeptInsideAWave(Tmp):
    """PR #653 review: the run's wall-clock limit is an absolute deadline carried into builder
    waits, reviewer admission and reviewer waits. A call still running at the deadline is stopped,
    its unit parked stopped-time-limit, and the run never reads complete. The registration copy
    here sets the limit to 0.1 minute (6 s); its task set is the registered one."""

    def deadline_run(self, script, minutes=0.1):
        prereg = json.loads(PREREG.read_text(encoding="utf-8"))
        prereg["taskset"]["path"] = str(TASKSET)
        prereg["stopping_rule"]["run_wall_clock_minutes"] = minutes
        path = self.tmp / "prereg.json"
        path.write_text(json.dumps(prereg), encoding="utf-8")
        env, trip_log = tripwired_env(self.tmp)
        started = time.monotonic()
        p = run_in_process(["--prereg", str(path), "run", "--results", str(self.tmp / "results"), "--workdir",
                            str(self.tmp / "wd"), "--runs", "wip1-b1r1-rep1", "--cost-cap-usd", "0",
                            "--inert-script", json.dumps(script)], env)
        elapsed = time.monotonic() - started
        self.assertFalse(trip_log.exists())
        record = json.loads((self.tmp / "results" / "runs" / "wip1-b1r1-rep1" / "run.json").read_text(encoding="utf-8"))
        return p, record, elapsed

    def test_a_builder_running_at_the_deadline_is_stopped_and_its_unit_parked(self):
        p, record, elapsed = self.deadline_run({"_sleep": {"builder": 40}})
        self.assertEqual((record["status"], record["stop_reason"]), ("stopped", "time-limit"), p.stdout + p.stderr)
        t5 = record["units"]["T5"]
        self.assertEqual((t5["final"], t5["park_class"], t5["reviews"]), ("parked", "stopped-time-limit", []))
        self.assertLess(elapsed, 35, "the builder was waited for past the run's deadline")

    def test_no_reviewer_starts_or_runs_past_the_deadline(self):
        p, record, elapsed = self.deadline_run({"_sleep": {"reviewer": 40}}, minutes=0.15)
        self.assertEqual((record["status"], record["stop_reason"]), ("stopped", "time-limit"), p.stdout + p.stderr)
        t5 = record["units"]["T5"]
        self.assertEqual((t5["final"], t5["park_class"]), ("parked", "stopped-time-limit"))
        self.assertLess(elapsed, 35, "the reviewer was waited for past the run's deadline")


_DOCUMENTED: dict = {}


def documented_live_run():
    """(results, process) of the protocol page's live command, placeholders filled, run once per
    module against a fake claude: a live-tier run that every check in this module can read."""
    if "run" not in _DOCUMENTED:
        tmp = tempfile.TemporaryDirectory(prefix="wip-curve-documented-")
        root = Path(tmp.name).resolve()
        page = (ROOT / "docs" / "experiments" / "wip-curve-prereg.md").read_text(encoding="utf-8")
        block = next(b for b in re.findall(r"```bash\n(.*?)```", page, re.S) if "--worker live" in b)
        command = block.replace("\\\n", " ")
        fill = {"dir": str(root / "results"), "model": "wip-fake-model", "cap": "20", "reservation": "0.25"}
        for placeholder in re.findall(r"<[^>]+>", command):
            key = next((k for k in fill if k in placeholder), None)
            if key is None:
                raise AssertionError(f"an unknown placeholder {placeholder} in the documented live command")
            command = command.replace(placeholder, fill[key])
        argv = shlex.split(command)
        if argv[:2] != ["python3", "scripts/wip_curve.py"]:
            raise AssertionError(f"the documented live command is not the runner: {argv[:2]}")
        env, trip_log = tripwired_env(root)
        install_fake_harness(root / "fake-bin")
        env.update(PATH=os.pathsep.join([str(root / "fake-bin"), env["PATH"]]), HOME=str(root / "home"))
        (root / "home").mkdir()
        with mock.patch.object(wip, "dirty_inputs", return_value=[]):
            proc = run_in_process(argv[2:], env)
        _DOCUMENTED.update(run=(root / "results", proc), tmp=tmp, trip_log=trip_log)
    return _DOCUMENTED["run"]


class TestTheDocumentedLiveCommandRuns(unittest.TestCase):
    """PR #653 review (P2): the live command the protocol page prints must parse and start a run.
    It is read from the page, its placeholders filled, and run against a fake harness."""

    def test_the_documented_live_command_starts_a_run(self):
        results, p = documented_live_run()
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        record = json.loads((results / "runs" / "wip1-b1r1-rep1" / "run.json").read_text(encoding="utf-8"))
        self.assertEqual((record["tier"], record["status"]), ("live-unreviewed", "complete"))
        self.assertFalse(_DOCUMENTED["trip_log"].exists())


class TestAKilledRunStillCounts(Tmp):
    """Adversarial pass (unavailable read as 0): a runner killed outright (SIGKILL, power loss)
    writes no run.json. Its spend ledger, kept current while it ran, is still counted against
    the cap, the run is reported as lost, and only it may be re-run once."""

    def setUp(self):
        super().setUp()
        self.env, self.trip_log = tripwired_env(self.tmp)
        self.results = self.tmp / "results"
        lost = self.results / "runs" / "wip1-b1r1-rep1"
        lost.mkdir(parents=True)
        (lost / "spend.json").write_text(json.dumps({"committed_usd": "3.00", "observed_usd": "2.50",
                                                     "reserved_unobserved_usd": "0.00",
                                                     "updated_at": "2026-10-24T10:00:00+00:00"}), encoding="utf-8")

    def test_its_spend_is_counted(self):
        self.assertEqual(wip.spent_in(self.results), Decimal("3.00"))
        p = runner("run", "--results", str(self.results), "--workdir", str(self.tmp / "wd"), "--runs",
                   "wip1-b3r1-rep1", "--cost-cap-usd", "3.40", "--inert-cost-usd", "0.25", env=self.env)
        self.assertEqual(p.returncode, 1, p.stdout + p.stderr)
        self.assertIn("not started", p.stderr)

    def test_it_is_reported_as_lost(self):
        runs = wip.build_report(self.results, basis="all")["runs"]
        self.assertEqual([(r["run_id"], r["status"], r["compliant"]) for r in runs],
                         [("wip1-b1r1-rep1", "lost", False)])

    def test_it_may_be_re_run_once(self):
        # -a2 passes the retry rule; the bogus second id is the refusal that must be reached
        p = runner("run", "--results", str(self.results), "--workdir", str(self.tmp / "wd"), "--runs",
                   "wip1-b1r1-rep1-a2,wip1-b9r9-rep1", "--cost-cap-usd", "0", env=self.env)
        self.assertEqual(p.returncode, 2, p.stdout + p.stderr)
        self.assertIn("not a scheduled run", p.stderr)

    def test_a_run_keeps_its_ledger_and_binds_it(self):
        run_dir = Path(dry_run(*B1_BOUNDARY)[0].name) / "results" / "runs" / B1_BOUNDARY[0]
        record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
        ledger = json.loads((run_dir / "spend.json").read_text(encoding="utf-8"))
        self.assertIn("spend.json", record["sources"])
        self.assertEqual(Decimal(ledger["committed_usd"]), Decimal("0.50"))


class TestRelativePaths(unittest.TestCase):
    """--results, --workdir and --prereg given relative to another working directory: the run,
    the report and the verifier resolve them once, before anything changes directory (git reads
    a bundle from a temporary repository's cwd, events.py runs in the run directory)."""

    @classmethod
    def setUpClass(cls):
        tmp, cls.env, cls.trip_log, cls.proc = dry_run(*B1_BOUNDARY, relative=True)
        cls.root = Path(tmp.name).resolve()

    def test_a_relative_results_dir_runs_reports_and_verifies(self):
        run_json = self.root / "results" / "runs" / B1_BOUNDARY[0] / "run.json"
        self.assertTrue(run_json.is_file(), self.proc.stdout + self.proc.stderr)
        record = json.loads(run_json.read_text(encoding="utf-8"))
        self.assertTrue(Path(record["sandbox"]).is_absolute())
        self.assertEqual(record["status"], "stopped")
        rel = os.path.relpath(PREREG, self.root)
        p = runner("--prereg", rel, "report", "--results", "results", "--basis", "all", env=self.env, cwd=self.root)
        self.assertEqual(p.returncode, 0, p.stderr)
        report = json.loads((self.root / "results" / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["runs"][0]["binding_problems"], [])
        v = runner("--prereg", rel, "verify", "--results", "results", "--report", "results/report.json",
                   "--report-md", "results/report.md", env=self.env, cwd=self.root)
        self.assertEqual(v.returncode, 0, v.stderr)
        self.assertFalse(self.trip_log.exists())


if __name__ == "__main__":
    unittest.main()
