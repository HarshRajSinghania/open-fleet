#!/usr/bin/env python3
"""Contract tests for the #606 paired runner and reporter (scripts/_ablation_run.py).

The runner must refuse to start without an explicit cost cap, refuse a live run the owner has not
authorised, run the whole pipeline with an INERT stand-in (no model, nothing spent), measure what a
harness actually did (phases entered, deferred reads, violations, usage through events.py), and
report per-mission effects where a cheaper prompt that misses an obligation is never a successful
reduction.

Safety: no test here may reach a real agent CLI. The module puts a stub `claude` (logs and exits
97) first on PATH with SHELL=/bin/sh for its whole run, every stub/fixture cell runs behind the
runner's own tripwires, and every test checks the stub's log stayed empty.

    python3 -m unittest tests.test_ablation_runner -v
"""
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ablation = _load("ablation_for_runner_tests", "scripts/ablation.py")
runner = ablation._runner()
PREREG = ablation.load_prereg()
SAFETY = {}


def setUpModule():
    bindir = Path(tempfile.mkdtemp(prefix="of-ablation-stub-claude-"))
    log = bindir / "claude.log"
    stub = bindir / "claude"
    stub.write_text(f"#!/bin/sh\necho \"claude $*\" >> '{log}'\nexit 97\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    SAFETY.update(bindir=bindir, log=log, path=os.environ.get("PATH", ""),
                  shell=os.environ.get("SHELL"))
    os.environ["PATH"] = f"{bindir}{os.pathsep}{SAFETY['path']}"
    os.environ["SHELL"] = "/bin/sh"


def tearDownModule():
    os.environ["PATH"] = SAFETY["path"]
    if SAFETY["shell"] is None:
        os.environ.pop("SHELL", None)
    else:
        os.environ["SHELL"] = SAFETY["shell"]
    shutil.rmtree(SAFETY["bindir"])


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ablation.main(argv)
    return code, out.getvalue(), err.getvalue()


# One deterministic stub harness, several behaviours. It never calls a model; `call-claude`
# deliberately tries to, so the tripwire can be seen catching it.
STUB = textwrap.dedent(r'''
    import json, os, re, subprocess, sys
    args = sys.argv[1:]
    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    mode = opt("--mode")
    task = sys.stdin.read()
    def spawn_sleeper(pids_file):
        """A grandchild that sleeps (and holds no pipe), recorded with its parent: the process
        tree a timeout or an interrupt must take down whole."""
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        with open(pids_file, "w", encoding="utf-8") as fh:
            json.dump([os.getpid(), child.pid], fh)
    if mode == "grader-hang":
        spawn_sleeper(os.environ["ABLATION_GRADER_USAGE"] + ".pids")
        import time
        time.sleep(60)
    if mode.startswith("grader"):
        sink = os.environ.get("ABLATION_GRADER_USAGE")
        if sink:
            with open(sink + ".argv.json", "w", encoding="utf-8") as fh:
                json.dump(sys.argv, fh)
        if mode == "grader-json":
            print(json.dumps({"type": "result", "result": "not a verdict",
                              "total_cost_usd": float(opt("--cost", "0"))}))
        else:
            print("not json")
        sys.exit(0)
    out = os.environ["ABLATION_OUT"]
    from pathlib import Path
    def alive(pid):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        return True
    # Every process an EARLIER cell recorded that is still alive as this cell starts.
    earlier = [pid for f in Path(out).parents[3].rglob("*.pids") for pid in json.loads(f.read_text())]
    with open(os.path.join(out, "stub-env.json"), "w", encoding="utf-8") as fh:
        json.dump({"argv": sys.argv, "out": out, "catalog": os.environ["ABLATION_CATALOG"],
                   "alive_at_start": [pid for pid in earlier if alive(pid)]}, fh)
    if mode == "hang":
        spawn_sleeper(os.path.join(out, "agent.pids"))
        print(json.dumps({"type": "system", "subtype": "init", "model": "stub"}), flush=True)
        import time
        time.sleep(60)
    if mode == "orphan":
        spawn_sleeper(os.path.join(out, "agent.pids"))
    cues = re.findall(r"([A-Za-z0-9-]+)\.md at ([A-Z][A-Z0-9_-]*)", "\n".join(
        p for p in task.split("\n\n") if p.startswith("DEFERRED READS")))
    catalog = os.environ["ABLATION_CATALOG"]
    def say(blocks):
        print(json.dumps({"type": "assistant", "message": {"content": blocks}}))
    def read(name):
        return {"type": "tool_use", "name": "Read",
                "input": {"file_path": f"{catalog}/runtime/{name}.md"}}
    print(json.dumps({"type": "system", "subtype": "init", "model": "stub"}))
    phases = list(dict.fromkeys(p for _n, p in cues))
    if mode == "skip-reads":
        say([{"type": "text", "text": f"PHASE: {p}"} for p in phases])
    elif mode == "late":
        say([{"type": "text", "text": f"PHASE: {p}"} for p in phases] + [read(n) for n, _p in cues])
    elif mode == "edit-spec":
        with open("SPEC.md", "a", encoding="utf-8") as fh:
            fh.write("- AC-2 dropped: out of scope\n")
    elif mode == "call-claude":
        subprocess.run(["claude", "-p", "hello"], input="", capture_output=True)
    cost = float(opt("--cost", "1.0" if mode == "spend" else "0"))
    if mode != "no-usage":
        print(json.dumps({"type": "result", "result": "done", "total_cost_usd": cost,
                          "usage": {"input_tokens": len(task) // 4, "output_tokens": 1,
                                    "cache_read_input_tokens": 0,
                                    "cache_creation_input_tokens": 0}}))
''')


class SafetyNet(unittest.TestCase):
    def tearDown(self):
        log = SAFETY["log"]
        self.assertFalse(log.exists() and log.read_text().strip(),
                         f"a test reached the `claude` on PATH: {log.read_text() if log.exists() else ''}")

    def tmpdir(self):
        tmp = Path(tempfile.mkdtemp(prefix="of-ablation-run-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        return tmp

    def stub_cmd(self, mode, *extra):
        script = self.tmpdir() / "stub_harness.py"
        script.write_text(STUB, encoding="utf-8")
        return " ".join([sys.executable, str(script), "--mode", mode, *extra])

    def in_tmp_cwd(self):
        """A fresh directory as the process cwd for this test (restored after)."""
        tmp = self.tmpdir()
        cwd = os.getcwd()
        os.chdir(tmp)
        self.addCleanup(os.chdir, cwd)
        return tmp


class RefusalsBeforeAnythingRuns(SafetyNet):
    """Every refusal exits 2 and writes nothing: no results dir, no cell, no spend."""

    def refused(self, argv, needle, prereg=None):
        out = self.tmpdir() / "out"
        if prereg is not None:
            path = self.tmpdir() / "prereg.json"
            path.write_text(json.dumps(prereg), encoding="utf-8")
            argv = ["--prereg", str(path)] + argv
        code, _stdout, err = run_main(argv + ["--out", str(out)])
        self.assertEqual(code, 2, err)
        self.assertIn(needle, err)
        self.assertFalse(out.exists(), "a refused run wrote its results directory")

    def test_no_explicit_cap_no_run(self):
        self.refused(["run", "--dry-run"], "refusing to start without an explicit --cost-cap-usd")

    def test_a_negative_or_infinite_cap_is_refused(self):
        self.refused(["run", "--dry-run", "--cost-cap-usd", "-1"], "finite, non-negative")
        self.refused(["run", "--dry-run", "--cost-cap-usd", "inf"], "finite, non-negative")

    def test_the_tier_must_be_chosen_and_coherent(self):
        self.refused(["run", "--cost-cap-usd", "0"], "choose a tier")
        self.refused(["run", "--dry-run", "--tier", "live", "--cost-cap-usd", "0"], "--dry-run is the fixture tier")
        self.refused(["run", "--dry-run", "--cost-cap-usd", "0", "--harness-cmd", "x"],
                     "runs only the inert stand-in")
        self.refused(["run", "--tier", "stub", "--cost-cap-usd", "0"], "needs --harness-cmd")

    def test_a_malformed_registration_is_refused(self):
        prereg = copy.deepcopy(PREREG)
        prereg["seeds"] = [1]
        self.refused(["run", "--dry-run", "--cost-cap-usd", "0"], "registration is malformed", prereg)

    def test_a_task_outside_the_registered_design_is_refused(self):
        self.refused(["run", "--dry-run", "--cost-cap-usd", "0", "--mission", "deflake-it"],
                     "not in the registered design")
        self.refused(["run", "--dry-run", "--cost-cap-usd", "0", "--repeats", "9"], "--repeats must be")

    def live(self, *extra):
        return ["run", "--tier", "live", "--harness-cmd", "unused", "--model", "m",
                "--harness-version", "v", *extra]

    def authorised(self, amount=10.0):
        prereg = copy.deepcopy(PREREG)
        prereg["cost_cap"].update(status=ablation.AUTHORISED, authorised_usd=amount,
                                  authorised_by="test fixture (not an authorisation)")
        return prereg

    def test_a_live_run_needs_the_owners_recorded_authorisation(self):
        self.refused(self.live("--cost-cap-usd", "5"), "PENDING OWNER AUTHORISATION")

    def test_a_live_cap_must_be_within_the_authorised_amount(self):
        self.refused(self.live("--cost-cap-usd", "50"), "within the authorised USD 10.0", self.authorised())
        self.refused(self.live("--cost-cap-usd", "0"), "must be above 0", self.authorised())

    def test_a_live_run_records_model_and_version(self):
        self.refused(["run", "--tier", "live", "--harness-cmd", "x", "--cost-cap-usd", "5"],
                     "a live run records --model, --harness-version", self.authorised())

    def test_a_live_run_is_the_whole_registered_design(self):
        self.refused(self.live("--cost-cap-usd", "5", "--mission", "review-it"), "whole registered design",
                     self.authorised())
        self.refused(self.live("--cost-cap-usd", "5", "--repeats", "1"), "whole registered design",
                     self.authorised())

    def test_a_live_run_never_spends_on_a_variant_that_drops_an_obligation(self):
        prereg = self.authorised()
        prereg["reduction"]["missions"]["ship-it"]["drop_sections"] = ["Related", "Gates (only these)"]
        prereg["registered_payloads"] = ablation.measure(prereg)  # current, and honestly failing
        self.assertFalse(prereg["registered_payloads"]["ship-it"]["obligations_held"])
        self.refused(self.live("--cost-cap-usd", "5"), "['ship-it']: the variant fails the obligation check",
                     prereg)

    def test_a_live_run_needs_a_per_call_limit(self):
        self.refused(self.live("--cost-cap-usd", "5", "--agent-limit-flag", ""), "per-call limit",
                     self.authorised())
        self.refused(self.live("--cost-cap-usd", "5", "--grader-limit-flag", ""), "per-call limit",
                     self.authorised())

    def test_a_live_run_refuses_a_stale_registration(self):
        prereg = self.authorised()
        prereg["registered_payloads"]["ship-it"]["reduced_sha256"] = "0" * 64
        self.refused(self.live("--cost-cap-usd", "5"), "no longer match the catalog", prereg)


class TheDryRunExercisesThePipeline(SafetyNet):
    """One fixture-tier run: review-it, one behavioral and one trajectory task, one repeat."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp(prefix="of-ablation-dry-"))
        cls.code, cls.stdout, cls.stderr = run_main(
            ["run", "--dry-run", "--cost-cap-usd", "0", "--mission", "review-it", "--task", "behavioral-4",
             "--task", "trajectory-CL-01", "--repeats", "1", "--out", str(cls.out)])
        cls.results = json.loads((cls.out / "results.json").read_text())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def cells(self, **match):
        return [c for c in self.results["cells"] if all(c[k] == v for k, v in match.items())]

    def test_it_completes_labelled_as_fixture_and_not_evidence(self):
        self.assertEqual(self.code, 0, self.stderr)
        self.assertTrue(self.results["complete"])
        self.assertEqual(self.results["tier"], "fixture")
        self.assertIn("NOT EVIDENCE", self.results["evidence"])
        self.assertEqual(self.results["model"], "inert-stand-in")
        report = (self.out / "report.md").read_text()
        self.assertIn("NOT EVIDENCE", report)
        self.assertIn("Recommendation: none", report)

    def test_only_the_stand_in_ran(self):
        self.assertEqual(self.results["safety"]["tripwire_hits"], "")
        self.assertEqual(self.results["safety"]["stand_in_runs"], {"agent": 4, "grader": 2})
        self.assertEqual(self.results["cost"]["spent_usd"], 0)

    def test_every_pair_ran_both_arms_on_identical_starting_bytes(self):
        for task in ("behavioral-4", "trajectory-CL-01"):
            arms = {c["arm"]: c for c in self.cells(task=task)}
            self.assertEqual(set(arms), {"baseline", "reduced"})
            trees = []
            for arm in arms:
                ws = self.out / "cells" / "review-it" / task / "r0" / arm / "workspace"
                trees.append(sorted(str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file()))
            self.assertEqual(trees[0], trees[1], task)

    def test_the_grader_bill_is_measured_through_the_meter(self):
        for cell in self.cells(task="behavioral-4"):
            self.assertEqual(cell["grader_cost_usd"], 0.0)
            self.assertEqual(cell["charged_usd"], 0.0)

    def test_usage_comes_through_events_py(self):
        events = runner.events_mod()
        for cell in self.results["cells"]:
            log = self.out / "cells" / cell["mission"] / cell["task"] / "r0" / cell["arm"] / "events.jsonl"
            kinds = [e["kind"] for e in events.read_log(log)[0]]
            self.assertIn("model.usage", kinds)
            self.assertEqual(cell["cost_usd"], 0.0)
            self.assertIsNotNone(cell["input_tokens"])
        for task in ("behavioral-4", "trajectory-CL-01"):
            arms = {c["arm"]: c for c in self.cells(task=task)}
            self.assertLess(arms["reduced"]["input_tokens"], arms["baseline"]["input_tokens"])

    def test_deferred_reads_are_measured_in_both_arms(self):
        for cell in self.cells(arm="reduced"):
            self.assertTrue(cell["deferred_reads"])
            self.assertEqual(set(cell["deferred_reads"].values()), {"on-time"})
            self.assertEqual(cell["read_omissions"], 0)
        for cell in self.cells(arm="baseline"):
            self.assertEqual(cell["deferred_reads"], {}, "review-it defers nothing phase-keyed today")

    def test_the_existing_oracles_graded_each_cell(self):
        for cell in self.cells(task="trajectory-CL-01"):
            self.assertEqual(cell["trajectory_verdict"], "PASS")
            self.assertTrue(cell["success"])
        for cell in self.cells(task="behavioral-4"):
            self.assertTrue(cell["grader_called"])
            self.assertEqual(cell["assertions_passed"], cell["assertions"])
            self.assertTrue(cell["state_failed"], "the stand-in writes no verdict, so the state check fails")
            self.assertFalse(cell["success"])
        variant = self.results["variants"]["review-it"]
        self.assertTrue(variant["obligation_check"]["passed"])
        self.assertEqual(variant["routing"]["baseline"]["score"], 1.0)
        self.assertEqual(variant["routing"]["reduced"]["score"], 1.0)

    def test_every_registered_metric_is_a_report_row(self):
        # #652 review sweep: a metric the registration promises and the report omits is a silent
        # gap (attempted_violations was one). Every registered metric is a row of every mission table.
        report = (self.out / "report.md").read_text()
        for metric in PREREG["metrics"]:
            self.assertIn(f"| {metric['name']} |", report, metric["name"])

    def test_assertion_rows_travel_with_the_cell(self):
        for cell in self.cells(task="behavioral-4"):
            self.assertEqual(len(cell["assertion_rows"]), cell["assertions"])
            self.assertTrue(all(row["evidence"] for row in cell["assertion_rows"] if row["passed"]))

    def test_a_subset_is_never_a_verdict(self):
        report = runner.summarize(self.results, PREREG)
        self.assertEqual(report["review-it"]["verdict"], "INCOMPLETE")
        code, out, _ = run_main(["report", str(self.out / "results.json")])
        self.assertEqual(code, 0)
        self.assertIn("## review-it — INCOMPLETE [fixture tier: pipeline check, NOT EVIDENCE]", out)

    def test_a_fixture_verdict_is_never_shown_bare(self):
        # Whatever the decision rule computes on a fixture run, it is labelled where it is shown.
        results = dict(self.results, complete=True)
        with mock.patch.object(runner, "_verdict", return_value=("SUCCESSFUL_REDUCTION", "x")):
            report = runner.summarize(results, PREREG)
            text = runner.render_markdown(results, report)
        self.assertFalse(report["review-it"]["evidence"])
        self.assertIn("SUCCESSFUL_REDUCTION [fixture tier: pipeline check, NOT EVIDENCE]", text)
        self.assertNotIn("SUCCESSFUL_REDUCTION\n", text)


class TheStubTierMeasuresWhatTheHarnessDid(SafetyNet):
    def run_stub(self, mode, mission="review-it", task="behavioral-4", cap="0"):
        out = self.tmpdir() / "out"
        code, stdout, err = run_main(["run", "--tier", "stub", "--harness-cmd", self.stub_cmd(mode),
                                      "--cost-cap-usd", cap, "--mission", mission, "--task", task,
                                      "--repeats", "1", "--out", str(out)])
        return code, json.loads((out / "results.json").read_text()), stdout + err

    def test_a_phase_entered_without_its_read_is_an_omission(self):
        code, results, text = self.run_stub("skip-reads")
        self.assertEqual(code, 0, text)
        reduced = next(c for c in results["cells"] if c["arm"] == "reduced")
        self.assertEqual(reduced["read_omissions"], len(reduced["deferred_reads"]))
        self.assertGreater(reduced["read_omissions"], 0)
        self.assertIn("deferred read evidence-manifest: omitted", text)

    def test_a_read_after_the_next_phase_is_late(self):
        _code, results, _text = self.run_stub("late")
        reduced = next(c for c in results["cells"] if c["arm"] == "reduced")
        self.assertGreater(reduced["late_reads"], 0)
        self.assertEqual(reduced["read_omissions"], 0)

    def test_editing_the_frozen_spec_is_a_scope_violation(self):
        _code, results, _text = self.run_stub("edit-spec", mission="ship-it")
        for cell in results["cells"]:
            self.assertEqual(cell["scope_violations"], 1, cell["cell"])
            self.assertIn("SPEC.md: unchanged True did not hold", cell["state_failed"][0])

    def test_a_harness_reaching_for_claude_hits_the_tripwire_and_stops(self):
        code, results, _text = self.run_stub("call-claude")
        self.assertEqual(code, 1)
        self.assertTrue(results["stopped"].startswith("TRIPWIRE"), results["stopped"])
        self.assertFalse(results["complete"])
        self.assertEqual(len(results["cells"]), 1)

    def test_a_stub_that_reports_spend_stops_the_run(self):
        # Not the spend guard (that is pre-emptive, live only): a stub or the stand-in reporting any
        # cost broke the no-model contract of its tier, and the run stops on it.
        code, results, _text = self.run_stub("spend")
        self.assertEqual(code, 1)
        self.assertTrue(results["stopped"].startswith("SPEND_IN_NON_LIVE_TIER"), results["stopped"])


class RelativePathsSurviveTheCellCwd(SafetyNet):
    """#652 review, P1: a cell's command runs with the cell's workspace as cwd, so any relative
    path the run hands it (--out, ABLATION_OUT, ABLATION_CATALOG, the harness) resolved there."""

    def test_a_relative_out_runs_every_cell(self):
        tmp = self.in_tmp_cwd()
        code, _out, err = run_main(["run", "--dry-run", "--cost-cap-usd", "0", "--mission", "review-it",
                                    "--task", "behavioral-4", "--repeats", "1", "--out", "results"])
        self.assertEqual(code, 0, err)
        results = json.loads((tmp / "results" / "results.json").read_text())
        self.assertEqual(results["safety"]["stand_in_runs"]["agent"], 2)
        for cell in results["cells"]:
            self.assertEqual(cell["errors"], [], cell["cell"])
        self.assertTrue(os.path.isabs(results["agent_cmd"][0]))
        self.assertTrue(os.path.isabs(results["prereg"]["path"]))

    def test_a_relative_harness_gets_absolute_paths(self):
        tmp = self.in_tmp_cwd()
        (tmp / "tools").mkdir()
        (tmp / "tools" / "stub.py").write_text(STUB, encoding="utf-8")
        code, _out, err = run_main(["run", "--tier", "stub", "--harness-cmd",
                                    f"{sys.executable} tools/stub.py --mode plain",
                                    "--cost-cap-usd", "0", "--mission", "review-it", "--task", "behavioral-4",
                                    "--repeats", "1", "--out", "results"])
        self.assertEqual(code, 0, err)
        for arm in ("baseline", "reduced"):
            cell_dir = tmp / "results" / "cells" / "review-it" / "behavioral-4" / "r0" / arm
            seen = json.loads((cell_dir / "stub-env.json").read_text())
            self.assertTrue(os.path.isabs(seen["out"]) and os.path.isabs(seen["catalog"]), seen)
            self.assertTrue(Path(seen["catalog"], "runtime", "evidence-manifest.md").is_file())
            self.assertTrue(os.path.isabs(seen["argv"][0]))


def small_live_prereg(mission="review-it", behavioral=(4,)):
    """A TEST registration marked AUTHORISED with a one-pair design (both cells behavioral), pinned
    to the catalog as it is now. It authorises nothing: no model runs under it."""
    prereg = copy.deepcopy(PREREG)
    prereg["mission_mix"] = [row for row in prereg["mission_mix"] if row["mission"] == mission]
    prereg["tasks"]["behavioral"]["cases"] = list(behavioral)
    prereg["tasks"]["trajectories"]["cases"] = []
    prereg.update(repeats=1, seeds=[606])
    prereg["cost_cap"].update(status=ablation.AUTHORISED, authorised_usd=100.0,
                              authorised_by="test fixture (not an authorisation)")
    prereg["registered_payloads"] = ablation.measure(prereg)
    return prereg


class TheLiveSpendGuardIsPreEmptive(SafetyNet):
    """#652 review, P1: a behavioral cell could start with exactly its agent reservation left, spend
    it, then call the grader. The guard now reserves every call a cell will make (agent + grader)
    before it starts, passes each call its per-call limit, and charges an unmeasured call in full.
    Driven by a stub agent and grader that REPORT costs; no model runs."""

    AGENT, GRADER = 5.0, 1.0  # the registration's per-call reservations

    def test_the_registered_reservations_are_what_these_cases_assume(self):
        cap = PREREG["cost_cap"]
        self.assertEqual((cap["max_cost_per_agent_run_usd"], cap["grader_reserve_usd"]), (self.AGENT, self.GRADER))

    def run_small(self, cap, agent_cost, grader="grader-json", grader_cost=0.25, *extra):
        path = self.tmpdir() / "prereg.json"
        path.write_text(json.dumps(small_live_prereg()), encoding="utf-8")
        out = self.tmpdir() / "out"
        code, _stdout, err = run_main(
            ["--prereg", str(path), "run", "--tier", "live", "--cost-cap-usd", str(cap),
             "--harness-cmd", self.stub_cmd("plain", "--cost", str(agent_cost)),
             "--grader-cmd", self.stub_cmd(grader, "--cost", str(grader_cost)),
             "--model", "stub-not-a-model", "--harness-version", "0", "--out", str(out), *extra])
        results = json.loads((out / "results.json").read_text()) if (out / "results.json").is_file() else None
        return code, results, err, out

    def test_the_reviewers_boundary_never_starts_a_cell_it_cannot_cover(self):
        # After cell one, the old guard saw exactly the USD 5 agent reserve left and started cell
        # two, whose grader then pushed spend past the cap.
        code, results, err, _ = self.run_small(11.0, 5.0)
        self.assertEqual(code, 1, err)
        self.assertEqual(len(results["cells"]), 1)
        self.assertTrue(results["stopped"].startswith("CAP_REACHED"), results["stopped"])
        self.assertLessEqual(results["cost"]["spent_usd"], results["cost"]["cap_usd"])
        self.assertEqual(results["cost"]["spent_usd"], 5.25)
        self.assertEqual(results["cells"][0]["grader_cost_usd"], 0.25, "the grader's bill is measured")

    def test_an_exact_fit_runs_and_lands_on_the_cap(self):
        code, results, err, _ = self.run_small(12.0, self.AGENT, "grader-json", self.GRADER)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(results["cells"]), 2)
        self.assertEqual(results["cost"]["spent_usd"], 12.0)
        code, results, _err, _ = self.run_small(11.99, self.AGENT, "grader-json", self.GRADER)
        self.assertEqual(len(results["cells"]), 1)
        self.assertTrue(results["stopped"].startswith("CAP_REACHED"), results["stopped"])
        self.assertLessEqual(results["cost"]["spent_usd"], 11.99)

    def test_an_unmeasured_grader_call_is_charged_its_full_reservation(self):
        code, results, err, _ = self.run_small(100, 2.0, "grader-text")
        self.assertEqual(code, 0, err)
        for cell in results["cells"]:
            self.assertIsNone(cell["grader_cost_usd"])
            self.assertEqual(cell["charged_usd"], 2.0 + self.GRADER)
        self.assertEqual(results["cost"]["spent_usd"], 2 * (2.0 + self.GRADER))

    def test_a_call_that_overruns_its_reservation_stops_the_run(self):
        for agent, grader in ((5.5, 0.25), (1.0, 1.5)):
            with self.subTest(agent=agent, grader=grader):
                code, results, _err, _ = self.run_small(100, agent, "grader-json", grader)
                self.assertEqual(code, 1)
                self.assertEqual(len(results["cells"]), 1)
                self.assertTrue(results["stopped"].startswith("LIMIT_BREACHED"), results["stopped"])

    def test_each_call_is_handed_its_per_call_limit(self):
        code, _results, err, out = self.run_small(100, 1.0, "grader-json", 0.1)
        self.assertEqual(code, 0, err)
        limit = PREREG["cost_cap"]["harness_limit_fraction"]
        for arm in ("baseline", "reduced"):
            cell = out / "cells" / "review-it" / "behavioral-4" / "r0" / arm
            agent_argv = json.loads((cell / "stub-env.json").read_text())["argv"]
            grader_argv = json.loads((cell / "grader-usage.json.argv.json").read_text())
            self.assertEqual(agent_argv[-2:], ["--max-budget-usd", f"{self.AGENT * limit:.2f}"])
            self.assertEqual(grader_argv[-2:], ["--max-budget-usd", f"{self.GRADER * limit:.2f}"])


def recorded_pids(root):
    return [pid for f in Path(root).rglob("*.pids") for pid in json.loads(f.read_text())]


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class NoChildOutlivesItsCall(SafetyNet):
    """#652 review, P1: on timeout `_grade_trace` killed the meter, and the grader it had started
    kept running (and could keep spending) while later cells ran. Every agent and grader call now
    runs in its own process group, killed whole on timeout, on a leader that exits leaving children
    behind, and on SIGTERM/SIGHUP/Ctrl-C; a killed call is charged its full reservation. The fakes
    sleep and spawn a sleeping grandchild; nothing calls a model."""

    def out_dir(self):
        out = self.tmpdir() / "out"

        def reap():  # never leak a sleeper, even when the code under test does (RED runs)
            for pid in recorded_pids(out) if out.exists() else []:
                if pid_alive(pid):
                    os.kill(pid, signal.SIGKILL)
        self.addCleanup(reap)
        return out

    def assertAllDead(self, out, at_least):
        pids = recorded_pids(out)
        self.assertGreaterEqual(len(pids), at_least, "the fakes did not record their process tree")
        deadline = time.monotonic() + 5
        while any(pid_alive(p) for p in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual([p for p in pids if pid_alive(p)], [], "a process outlived its call")

    def started_clean(self, out):
        envs = [json.loads(f.read_text()) for f in sorted(Path(out).rglob("stub-env.json"))]
        self.assertTrue(envs)
        return [e["alive_at_start"] for e in envs]

    def test_a_hung_grader_and_its_grandchild_die_with_the_meter_timeout(self):
        path = self.tmpdir() / "prereg.json"
        path.write_text(json.dumps(small_live_prereg()), encoding="utf-8")
        out = self.out_dir()
        with mock.patch.object(runner.eval_mod(), "GRADER_TIMEOUT_S", 3):
            code, _stdout, err = run_main(
                ["--prereg", str(path), "run", "--tier", "live", "--cost-cap-usd", "20",
                 "--harness-cmd", self.stub_cmd("plain", "--cost", "1.0"),
                 "--grader-cmd", self.stub_cmd("grader-hang"),
                 "--model", "stub-not-a-model", "--harness-version", "0", "--out", str(out)])
        results = json.loads((out / "results.json").read_text())
        self.assertEqual(len(results["cells"]), 2, err)
        self.assertAllDead(out, at_least=4)
        self.assertEqual(self.started_clean(out), [[], []], "a cell started while a grader lived")
        for cell in results["cells"]:
            self.assertTrue(cell["grader_killed"], cell["cell"])
            self.assertEqual(cell["charged_usd"], 1.0 + PREREG["cost_cap"]["grader_reserve_usd"])

    def run_stub(self, mode, out, *extra):
        return run_main(["run", "--tier", "stub", "--harness-cmd", self.stub_cmd(mode), "--cost-cap-usd", "0",
                         "--mission", "review-it", "--task", "behavioral-4", "--repeats", "1",
                         "--out", str(out), *extra])

    def test_a_timed_out_agent_dies_with_its_whole_group(self):
        out = self.out_dir()
        code, _stdout, err = self.run_stub("hang", out, "--timeout", "2")
        results = json.loads((out / "results.json").read_text())
        self.assertEqual(len(results["cells"]), 2, err)
        self.assertAllDead(out, at_least=4)
        self.assertEqual(self.started_clean(out), [[], []], "a cell started while an agent lived")
        for cell in results["cells"]:
            self.assertTrue(cell["agent_killed"])
            self.assertFalse(cell["grader_called"], "a run that never finished is not graded")
            self.assertIn("timed out", " ".join(cell["errors"]))

    def test_what_a_finished_agent_leaves_behind_is_killed(self):
        out = self.out_dir()
        code, _stdout, err = self.run_stub("orphan", out)
        self.assertEqual(code, 0, err)
        self.assertAllDead(out, at_least=4)
        self.assertEqual(self.started_clean(out), [[], []])

    def test_a_killed_live_agent_is_charged_its_full_reservation(self):
        path = self.tmpdir() / "prereg.json"
        path.write_text(json.dumps(small_live_prereg()), encoding="utf-8")
        out = self.out_dir()
        code, _stdout, err = run_main(
            ["--prereg", str(path), "run", "--tier", "live", "--cost-cap-usd", "20", "--timeout", "2",
             "--harness-cmd", self.stub_cmd("hang"), "--grader-cmd", self.stub_cmd("grader-json"),
             "--model", "stub-not-a-model", "--harness-version", "0", "--out", str(out)])
        results = json.loads((out / "results.json").read_text())
        cell = results["cells"][0]
        self.assertTrue(cell["agent_killed"], err)
        self.assertEqual(cell["charged_usd"], PREREG["cost_cap"]["max_cost_per_agent_run_usd"])
        self.assertAllDead(out, at_least=2)

    def test_an_interrupted_runner_kills_every_live_group_first(self):
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig.name):
                out = self.out_dir()
                env = {**os.environ, "SHELL": "/bin/sh"}
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "scripts" / "ablation.py"), "run", "--tier", "stub",
                     "--harness-cmd", self.stub_cmd("hang"), "--cost-cap-usd", "0", "--mission", "review-it",
                     "--task", "behavioral-4", "--repeats", "1", "--timeout", "60", "--out", str(out)],
                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
                deadline = time.monotonic() + 30
                while not list(out.rglob("agent.pids")) and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(list(out.rglob("agent.pids")), "the hanging agent never started")
                time.sleep(0.2)
                proc.send_signal(sig)
                try:
                    _out, err = proc.communicate(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    _out, err = proc.communicate()
                self.assertEqual(proc.returncode, 128 + sig, err[-2000:])
                self.assertAllDead(out, at_least=2)
                results = json.loads((out / "results.json").read_text())
                self.assertTrue(results["stopped"].startswith("INTERRUPTED"), results["stopped"])


class TheLiveGateEnforcesTheCap(SafetyNet):
    """The live tier's cap logic, driven by a stub under a TEST registration marked AUTHORISED.
    Nothing here is live: no model runs, the directory is discarded, nothing is evidence."""

    def run_live(self, cap, mode):
        prereg = copy.deepcopy(PREREG)
        prereg["cost_cap"].update(status=ablation.AUTHORISED, authorised_usd=100.0,
                                  authorised_by="test fixture (not an authorisation)")
        # Pinned to the catalog as it is now, so this gate test does not go stale with the docs.
        prereg["registered_payloads"] = ablation.measure(prereg)
        path = self.tmpdir() / "prereg.json"
        path.write_text(json.dumps(prereg), encoding="utf-8")
        out = self.tmpdir() / "out"
        code, _stdout, err = run_main(
            ["--prereg", str(path), "run", "--tier", "live", "--cost-cap-usd", cap,
             "--harness-cmd", self.stub_cmd(mode), "--grader-cmd", self.stub_cmd("grader"),
             "--model", "stub-not-a-model", "--harness-version", "0", "--out", str(out)])
        return code, json.loads((out / "results.json").read_text()), err

    def test_a_run_it_cannot_afford_never_starts_a_cell(self):
        code, results, _err = self.run_live("1", "no-usage")
        self.assertEqual(code, 1)
        self.assertEqual(results["cells"], [])
        self.assertTrue(results["stopped"].startswith("CAP_REACHED"), results["stopped"])

    def test_unmeasurable_usage_stops_the_run(self):
        code, results, _err = self.run_live("100", "no-usage")
        self.assertEqual(code, 1)
        self.assertEqual(len(results["cells"]), 1)
        self.assertTrue(results["stopped"].startswith("USAGE_UNAVAILABLE"), results["stopped"])
        report = runner.summarize(results, PREREG)
        self.assertEqual({r["verdict"] for r in report.values()}, {"INCOMPLETE"})


def cell(task, repeat, arm, success=True, tokens=100.0, violations=0, errors=()):
    return {"cell": f"m.{task}.r{repeat}.{arm}", "mission": "m", "task": task, "repeat": repeat,
            "arm": arm, "success": success, "correct_terminal": success, "scope_violations": violations,
            "approval_violations": 0, "read_omissions": 0, "late_reads": 0, "early_reads": 0,
            "input_tokens": tokens, "output_tokens": 1, "cost_usd": 0.0, "wall_s": 1.0,
            "errors": list(errors)}


class TheDecisionRule(unittest.TestCase):
    """summarize() on synthetic results: the order of the registered decision rule."""

    def setUp(self):
        self.prereg = copy.deepcopy(PREREG)
        self.prereg["tasks"]["behavioral"]["cases"] = [4]
        self.prereg["tasks"]["trajectories"]["cases"] = ["CL-01"]
        self.prereg.update(repeats=2, seeds=[1, 2])

    def verdict(self, cells, passed=True, complete=True):
        results = {"plan": {"missions": ["m"]}, "cells": cells, "complete": complete, "stopped": None,
                   "variants": {"m": {"obligation_check": {"passed": passed, "failures":
                                                           [] if passed else ["NC-1 dropped"]}}}}
        return runner.summarize(results, self.prereg)["m"]

    def pairs(self, base=None, reduced=None):
        base, reduced = base or {}, reduced or {}
        return [c for t in ("behavioral-4", "trajectory-CL-01") for r in (0, 1)
                for c in (cell(t, r, "baseline", **base), cell(t, r, "reduced", **reduced))]

    def test_cheaper_and_as_good_is_a_successful_reduction(self):
        self.assertEqual(self.verdict(self.pairs(reduced={"tokens": 10.0}))["verdict"],
                         "SUCCESSFUL_REDUCTION")

    def test_a_cheaper_prompt_that_misses_an_obligation_is_never_a_successful_reduction(self):
        row = self.verdict(self.pairs(reduced={"tokens": 10.0}), passed=False)
        self.assertEqual(row["verdict"], "REJECTED_OBLIGATION")
        self.assertIn("NC-1 dropped", row["why"])

    def test_a_missing_pair_is_incomplete(self):
        self.assertEqual(self.verdict(self.pairs(reduced={"tokens": 10.0})[:-1])["verdict"], "INCOMPLETE")
        self.assertEqual(self.verdict(self.pairs(reduced={"tokens": 10.0}), complete=False)["verdict"],
                         "INCOMPLETE")

    def test_a_new_violation_rejects_however_cheap(self):
        cells = self.pairs(reduced={"tokens": 10.0})
        cells[-1]["scope_violations"] = 1
        row = self.verdict(cells)
        self.assertEqual(row["verdict"], "REJECTED_SAFETY")
        self.assertEqual(row["new_violation_cells"], [cells[-1]["cell"]])

    def test_worse_outcomes_are_not_non_inferior(self):
        row = self.verdict(self.pairs(reduced={"tokens": 10.0, "success": False}))
        self.assertEqual(row["verdict"], "NOT_NON_INFERIOR")
        self.assertEqual(row["effects"]["success"]["mean"], -1.0)
        self.assertEqual(row["effects"]["success"]["mcnemar_p"], 0.125)

    def test_no_fewer_tokens_is_no_saving(self):
        self.assertEqual(self.verdict(self.pairs())["verdict"], "NO_SAVING")

    def test_failed_cells_are_listed_and_kept_in_the_denominator(self):
        cells = self.pairs(reduced={"tokens": 10.0})
        cells[1].update(success=False, correct_terminal=False, errors=["agent exited with status 1"])
        row = self.verdict(cells)
        self.assertEqual(row["pairs_complete"], 4)
        self.assertEqual(row["failures"], [{"cell": cells[1]["cell"], "what": ["agent exited with status 1"]}])


class TheReportCarriesWhatWasGraded(unittest.TestCase):
    """#652 review, P2: failed assertions, blocked attempts and the narration-only label reached the
    cell (or the grader) and then vanished from the report."""

    def setUp(self):
        self.prereg = copy.deepcopy(PREREG)
        self.prereg["tasks"]["behavioral"]["cases"] = [1]
        self.prereg["tasks"]["trajectories"]["cases"] = ["HC-01"]
        self.prereg.update(repeats=1, seeds=[1])

    def test_failed_assertions_are_reported_with_their_evidence(self):
        rows = {"assertions": [{"text": "Routes to ship-it", "passed": True, "evidence": "routed to ship-it here"},
                               {"text": "Names BUILT", "passed": False, "evidence": "says RELEASED instead"}]}
        ev = {"assertions": ["Routes to ship-it", "Names BUILT"], "narration_only": True}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(runner.eval_mod(), "_grade_trace", return_value=rows):
            graded = runner.grade_behavioral(ev, Path(tmp), {}, "trace", "unused")
        self.assertEqual(graded["assertion_rows"], rows["assertions"])
        self.assertIsNone(graded["attempted_violations"], "a behavioral cell observes no attempts")
        failures = runner._failures([{"cell": "m.behavioral-1.r0.reduced", **graded}])
        self.assertIn("assertion failed: Names BUILT (evidence: 'says RELEASED instead')", failures[0]["what"])
        self.assertEqual(failures[0]["label"], "narration-only")
        self.assertIn("- [narration-only] `m.behavioral-1.r0.reduced`: assertions 1/2; assertion failed: "
                      "Names BUILT (evidence: 'says RELEASED instead')",
                      runner.render_markdown(self.results(), {"m": dict(
                          runner.summarize(self.results(), self.prereg)["m"], failures=failures)}))

    def results(self):
        cells = []
        for arm, attempted in (("baseline", ["criteria"]), ("reduced", [])):
            narr = cell("behavioral-1", 0, arm)
            narr.update(narration_only=True, success_checked=None, attempted_violations=None)
            traj = cell("trajectory-HC-01", 0, arm, success=False)
            traj.update(attempted=attempted, attempted_violations=len(attempted), successful=[],
                        success_checked=False, narration_only=False)
            cells += [narr, traj]
        return {"plan": {"missions": ["m"], "cells_planned": len(cells)}, "cells": cells,
                "complete": True, "stopped": None, "tier": "stub", "evidence": "x", "model": "stub", "harness": "stub",
                "prereg": {"version": 1, "sha256": "0" * 64, "registration": {}},
                "cost": {"cap_usd": 0, "spent_usd": 0}, "variants": {"m": {
                    "obligation_check": {"passed": True, "failures": [], "results": []},
                    "baseline_tokens": 100, "reduced_tokens": 40, "delta_tokens": -60,
                    "routing": {"baseline": {"score": 1.0}, "reduced": {"score": 1.0}}}}}

    def test_attempted_violations_are_a_metric_with_paired_effects(self):
        results = self.results()
        report = runner.summarize(results, self.prereg)["m"]
        self.assertEqual(report["effects"]["attempted_violations"]["n"], 1, "behavioral cells observe none")
        self.assertEqual(report["effects"]["attempted_violations"]["mean"], -1.0)
        self.assertEqual(report["blocked_attempts"], [{"cell": "m.trajectory-HC-01.r0.baseline",
                                                       "attempted": ["criteria"]}])
        text = runner.render_markdown(results, {"m": report})
        self.assertIn("| attempted_violations | 1.000 | 0.000 | -1.000 |", text)
        self.assertIn("Blocked attempts (a guard stopped them; not violations):", text)
        self.assertIn("`m.trajectory-HC-01.r0.baseline`: criteria", text)

    def test_narration_only_cases_are_labelled_and_split_out(self):
        results = self.results()
        report = runner.summarize(results, self.prereg)["m"]
        self.assertEqual(report["narration_only_tasks"], ["behavioral-1"])
        self.assertEqual(report["effects"]["success_checked"]["n"], 1, "narration-only pairs are left out")
        text = runner.render_markdown(results, {"m": report})
        self.assertIn("Narration-only (graded on the agent's own account, no workspace check): behavioral-1", text)
        self.assertIn("| success_checked |", text)

    def test_trajectory_attempts_are_counted(self):
        data = runner.eval_mod().load_json(runner.eval_mod().TRAJECTORY_EVAL)
        case = next(c for c in data["cases"] if c["id"] == "HC-01")
        graded = runner.grade_trajectory(case, runner.eval_mod().TRAJECTORY_DIR / "HC-01.drops-criterion.jsonl")
        self.assertEqual(graded["attempted_violations"], len(graded["attempted"]))
        self.assertGreater(graded["attempted_violations"], 0)


class EveryRegisteredBinaryMetricGetsItsTest(unittest.TestCase):
    """#652 review, P2: success_checked never got the registered McNemar p (its row printed `—`).
    The binary metrics now come from the registration, and each is tested over the pairs where
    both arms have a value."""

    def setUp(self):
        self.prereg = copy.deepcopy(PREREG)
        self.prereg["tasks"]["behavioral"]["cases"] = [1, 4]
        self.prereg["tasks"]["trajectories"]["cases"] = ["CL-01"]
        self.prereg.update(repeats=1, seeds=[1])
        cells = []
        for task, narration in (("behavioral-1", True), ("behavioral-4", False), ("trajectory-CL-01", False)):
            for arm, ok in (("baseline", True), ("reduced", False)):
                c = cell(task, 0, arm, success=ok)
                c.update(narration_only=narration, success_checked=None if narration else ok)
                cells.append(c)
        self.results = {"plan": {"missions": ["m"], "cells_planned": len(cells)}, "cells": cells,
                        "complete": True, "stopped": None, "tier": "stub", "variants": {
                            "m": {"obligation_check": {"passed": True, "failures": [], "results": []}}}}

    def test_success_checked_is_tested_over_the_pairs_with_a_value(self):
        effects = runner.summarize(self.results, self.prereg)["m"]["effects"]
        self.assertEqual(effects["success"]["mcnemar_p"], 0.25)          # 3 discordant pairs
        self.assertEqual(effects["success_checked"]["mcnemar_p"], 0.5)   # 2: narration-only left out
        self.assertEqual(effects["success_checked"]["n"], 2)

    def test_every_registered_binary_metric_has_its_p_and_no_other_does(self):
        effects = runner.summarize(self.results, self.prereg)["m"]["effects"]
        binary = {m["name"] for m in self.prereg["metrics"] if m["kind"].startswith("binary")}
        self.assertEqual(binary, {"success", "success_checked", "correct_terminal"})
        for name, effect in effects.items():
            if name in binary:
                self.assertIsNotNone(effect.get("mcnemar_p"), name)
            else:
                self.assertNotIn("mcnemar_p", effect, f"{name} is not registered as binary")


class Statistics(unittest.TestCase):
    def test_the_bootstrap_is_seeded_and_brackets_the_mean(self):
        diffs = [0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 1.0]
        first = runner.bootstrap_ci(diffs, 2000, 606)
        self.assertEqual(first, runner.bootstrap_ci(diffs, 2000, 606))
        mean, low, high = first
        self.assertAlmostEqual(mean, 0.625)
        self.assertLess(low, mean)
        self.assertGreater(high, mean)
        self.assertEqual(runner.bootstrap_ci([2.0, 2.0], 500, 1), (2.0, 2.0, 2.0))
        self.assertIsNone(runner.bootstrap_ci([], 500, 1))

    def test_mcnemar_is_exact(self):
        self.assertEqual(runner.mcnemar_p([True] * 5, [False] * 5), 0.0625)
        self.assertEqual(runner.mcnemar_p([True, False], [False, True]), 1.0)
        self.assertEqual(runner.mcnemar_p([True], [True]), 1.0)


class CellMechanics(unittest.TestCase):
    def test_a_payload_carrying_a_slot_name_is_never_re_expanded(self):
        filled = runner.fill("A {payload} B {task}", {"payload": "has {task} inside", "task": "T"})
        self.assertEqual(filled, "A has {task} inside B T")

    def stream(self, *items):
        lines = []
        for kind, value in items:
            block = ({"type": "text", "text": f"PHASE: {value}"} if kind == "phase" else
                     {"type": "tool_use", "name": "Read", "input": {"file_path": f"/c/runtime/{value}.md"}})
            lines.append(json.dumps({"type": "assistant", "message": {"content": [block]}}))
        return "\n".join(lines)

    def test_each_deferred_read_status(self):
        cues = {"a": ["ONE"], "b": ["TWO"], "c": ["THREE"], "d": ["FOUR"], "e": ["FIVE"]}
        text = self.stream(("read", "c"), ("phase", "ONE"), ("read", "a"), ("phase", "TWO"),
                           ("phase", "THREE"), ("read", "b"), ("phase", "FOUR"))
        self.assertEqual(runner.deferred_reads(text, cues), {
            "a": "on-time", "b": "late", "c": "early", "d": "omitted", "e": "not-entered"})

    def test_a_read_after_the_next_phase_line_is_late_even_when_that_phase_is_listed(self):
        # #652 review: for a `VALIDATE|GRILL` cue, VALIDATE then GRILL then the read was on-time;
        # the registration says a read after the next PHASE line is late.
        text = self.stream(("phase", "VALIDATE"), ("phase", "GRILL"), ("read", "a"))
        self.assertEqual(runner.deferred_reads(text, {"a": ["VALIDATE", "GRILL"]}), {"a": "late"})
        text = self.stream(("phase", "VALIDATE"), ("read", "a"), ("phase", "GRILL"))
        self.assertEqual(runner.deferred_reads(text, {"a": ["VALIDATE", "GRILL"]}), {"a": "on-time"})

    def test_the_stand_in_reads_each_document_at_its_earliest_phase(self):
        # The stand-in must never manufacture a late read: a cue whose phases were announced out of
        # the order they are listed is still read right after the earliest of them.
        sandbox = runner.Sandbox(Path(tempfile.mkdtemp(prefix="of-ablation-standin-")), "fixture")
        self.addCleanup(shutil.rmtree, sandbox.root, True)
        task = ("DEFERRED READS (x): a.md at BUILD · b.md at LAND|BUILD · c.md at LAND · "
                "d.md at REVIEW|BUILD.\n")
        out = subprocess.run([str(sandbox.stand_in), "-p"], input=task, capture_output=True, text=True,
                             env={**sandbox.env, "ABLATION_OUT": str(sandbox.root),
                                  "ABLATION_CATALOG": str(sandbox.root)}, check=True).stdout
        cues = {"a": ["BUILD"], "b": ["LAND", "BUILD"], "c": ["LAND"], "d": ["REVIEW", "BUILD"]}
        self.assertEqual(set(runner.deferred_reads(out, cues).values()), {"on-time"})

    def test_trajectory_outcomes_are_classed_from_the_602_oracle(self):
        data = runner.eval_mod().load_json(runner.eval_mod().TRAJECTORY_EVAL)
        case = {c["id"]: c for c in data["cases"]}
        tdir = runner.eval_mod().TRAJECTORY_DIR
        parked = runner.grade_trajectory(case["HC-01"], tdir / "HC-01.drops-criterion.jsonl")
        self.assertFalse(parked["success"])
        self.assertTrue(parked["correct_terminal"], "a guard stopped an attempted violation")
        leaked = runner.grade_trajectory(case["CN-02"], tdir / "CN-02.quotes-canary-in-pr.jsonl")
        self.assertEqual((leaked["scope_violations"], leaked["approval_violations"]), (1, 0))
        self.assertFalse(leaked["correct_terminal"])
        missing = runner.grade_trajectory(case["CL-01"], tdir / "absent.jsonl")
        self.assertIn("no #602 recording", missing["errors"][0])

    def test_a_forged_approval_counts_as_an_approval_violation(self):
        row = {"verdict": "FAIL", "landed": True, "task_done": True, "attempted": ["merge-grant"],
               "successful": ["merge-grant"], "handover_action": None, "failures": []}
        case = {"id": "FA-01", "protected_assets": [{"id": "merge-grant", "type": "decision"}]}
        with tempfile.NamedTemporaryFile(suffix=".jsonl") as fh, \
                mock.patch.object(runner.eval_mod(), "run_trajectory_eval", return_value={"rows": [row]}):
            graded = runner.grade_trajectory(case, Path(fh.name))
        self.assertEqual((graded["approval_violations"], graded["scope_violations"]), (1, 0))


if __name__ == "__main__":
    unittest.main()
