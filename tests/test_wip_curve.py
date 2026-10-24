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

import contextlib
import copy
import hashlib
import io
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
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


def runner(*args, env=None, timeout=600, cwd=ROOT):
    return subprocess.run([sys.executable, str(RUNNER), *args], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=timeout)


def rebind(run_dir: Path) -> None:
    """Forge run.json's source digests after an edit: what a careful tamperer would do."""
    rec = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    rec["sources"] = {str(p.relative_to(run_dir)): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(run_dir.rglob("*")) if p.is_file() and p.name != "run.json"}
    (run_dir / "run.json").write_text(json.dumps(rec, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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
        # Only the inert stand-in is claude-only; a bogus run id is the refusal that must be reached.
        self.refused("--worker", "live", "--agent", "codex", "--cost-cap-usd", "5", "--model", "m",
                     "--reservation-usd", "1", "--runs", "wip1-b9r9-rep1", text="not a scheduled run")

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
        gate = [sys.executable, str(RUNNER), "gate", "--taskset", str(TASKSET), "--landing", str(landing)]
        ok = subprocess.run(gate, cwd=str(repo), capture_output=True, text=True)
        self.assertEqual(ok.returncode, 0, ok.stdout)
        self.assertIn("['T3']", ok.stdout)
        units = repo / "stocklib" / "units.py"
        units.write_text(units.read_text(encoding="utf-8").replace('    "lb": 453.59237,\n', ""), encoding="utf-8")
        wip.git(repo, "commit", "-qam", "a later unit drops pounds")
        broken = subprocess.run(gate, cwd=str(repo), capture_output=True, text=True)
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
B1_OVERSPEND = ("wip1-b1r1-rep1", ("--cost-cap-usd", "0.50", "--inert-cost-usd", "0.25",
                                   "--inert-script", json.dumps({"_cost": {"builder": "0.40"}})))


def tearDownModule():
    for tmp, *_rest in _DRY_RUNS.values():
        tmp.cleanup()


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

    def test_a_run_into_a_symlink_to_the_docs_is_refused_and_writes_nothing(self):
        results = self.link("results", ROOT / "docs")
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
