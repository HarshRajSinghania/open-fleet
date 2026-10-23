#!/usr/bin/env python3
"""Adversarial worker trajectories, graded on what the worker DID (#602).

The VAL-01 drills grade what the trust envelope SAYS about hostile text. These grade what a
worker's recorded tool events DID with it, through the real guards: each fixture pins its initial
state, allowed actions, injected content and arrival surface, protected assets and end-state oracle
before execution; scripts/_trajectories.py replays the JSONL against a git repository built at test
time and grades tool events and git state. No model runs and nothing a worker "ran" is executed.

What these pin, each the shape of a way the harness itself could lie:
- a fixture's pinned fields, its recorded trajectory and the frozen contract cannot change
  silently (a stale pin or digest fails validation);
- attempted and successful violations are kept apart, and the final answer never moves a grade;
- every attack family turns RED with its guard removed, for the declared reason, and the
  contaminated handover is caught; a mutation that proves nothing is reported, not hidden;
- benign and clean controls land with no false denial;
- the published table is the live output, with its unknown and UNRUN cells.
"""
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_trajectories", ROOT / "scripts" / "eval.py")
eval_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_mod)
engine = eval_mod._trajectory_engine()
SUITE = eval_mod.load_json(eval_mod.TRAJECTORY_EVAL)
CONTRACT = eval_mod._trajectory_contract(SUITE)
DOC = ROOT / "docs" / "adversarial-evals.md"
TABLE_START = "<!-- trajectory-results:start -->"
TABLE_END = "<!-- trajectory-results:end -->"

_RESULT = None


def suite_result():
    """One full replay (every guarded arm and every mutation arm), shared by every test here."""
    global _RESULT
    if _RESULT is None:
        _RESULT = eval_mod.run_trajectory_eval()
    return _RESULT


def rows(case=None, arm=None, trajectory=None):
    return [r for r in suite_result()["rows"]
            if (case is None or r["case"] == case) and (arm is None or r["arm"] == arm)
            and (trajectory is None or r["trajectory"] == trajectory)]


def case_named(case_id):
    return copy.deepcopy(next(c for c in SUITE["cases"] if c["id"] == case_id))


def events_of(case):
    return engine.load_events(eval_mod.TRAJECTORY_DIR / case["trajectories"][0]["file"])


def replay(case, events, expect=None, mutation=None):
    """Grade one trajectory under one arm, outside the shared suite run."""
    with tempfile.TemporaryDirectory(prefix="trajectory-test-") as scratch:
        ctx = engine.Context(scratch, CONTRACT.read_bytes(), eval_mod.OBEDIENCE_FIXTURE_SECRET)
        return engine.run_case(case, events, expect, SUITE["base_state"], ctx,
                               eval_mod.check_workspace_state, mutation)


def categories(graded):
    return {f["category"] for f in graded["failures"]}


def suite_errors(data, trajectory_dir=None, contract=None):
    return engine.suite_errors(data, trajectory_dir or eval_mod.TRAJECTORY_DIR,
                               contract or CONTRACT)


def repinned(data):
    """Re-pin every case after a deliberate edit, as a maintainer would after review."""
    sha = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    for case in data["cases"]:
        case["pin"] = engine.pin_of(case, data["base_state"], sha)
    return data


class TheSuiteIsPinnedBeforeExecution(unittest.TestCase):
    def test_the_committed_suite_validates_and_rides_validate_all(self):
        self.assertEqual(eval_mod.validate_trajectory_eval(), [])
        with mock.patch.object(engine, "suite_errors", lambda *a: ["planted"]):
            self.assertIn(f"{eval_mod._rel(eval_mod.TRAJECTORY_EVAL)}: planted",
                          eval_mod.validate_all(),
                          "validate.py's eval gate no longer reads the trajectory suite")

    def test_an_oracle_relaxed_after_recording_is_a_stale_pin(self):
        data = copy.deepcopy(SUITE)
        data["cases"][0]["oracle"]["workspace_state"] = []
        errors = suite_errors(data)
        self.assertTrue(any("pin" in e and "stale" in e for e in errors), errors)

    def test_each_pinned_field_is_in_the_commitment(self):
        for field in engine.PINNED_FIELDS:
            with self.subTest(field=field):
                data = copy.deepcopy(SUITE)
                case = data["cases"][0]
                case[field] = copy.deepcopy(case[field])
                if isinstance(case[field], list):
                    case[field] = case[field][:-1] or ["Read"]
                else:
                    case[field] = dict(case[field] or {}, probe="changed")
                self.assertNotEqual(engine.pin_of(case, data["base_state"], SUITE["contract"]["sha256"]),
                                    case["pin"])

    def test_a_swapped_trajectory_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "trajectories"
            shutil.copytree(eval_mod.TRAJECTORY_DIR, copy_dir)
            target = copy_dir / SUITE["cases"][0]["trajectories"][0]["file"]
            target.write_text(target.read_text(encoding="utf-8").replace(
                "DecisionsAppend", "Commit", 1), encoding="utf-8")
            errors = suite_errors(SUITE, trajectory_dir=copy_dir)
        self.assertTrue(any("pins" in e and "the file hashes" in e for e in errors), errors)

    def test_the_frozen_contract_is_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "contract.json"
            other.write_text(CONTRACT.read_text(encoding="utf-8").replace('"AC-3", ', "", 1)
                             .replace('"AC-3"]', "]"), encoding="utf-8")
            errors = suite_errors(SUITE, contract=other)
        self.assertTrue(any("the frozen contract changed" in e for e in errors), errors)

    def test_a_protected_path_pin_must_match_the_initial_state(self):
        data = copy.deepcopy(SUITE)
        case = next(c for c in data["cases"] if c["id"] == "TT-01")
        case["protected_assets"][0]["sha256"] = "0" * 64
        errors = suite_errors(repinned(data))
        self.assertTrue(any("tests/test_calc.py pins" in e for e in errors), errors)

    def test_every_family_needs_an_attack_and_every_attack_a_guard_proof(self):
        data = copy.deepcopy(SUITE)
        data["cases"] = [c for c in data["cases"] if c["family"] != "memory-poisoning"
                         or c["kind"] != "attack"]
        self.assertTrue(any("no attack case" in e and "memory-poisoning" in e
                            for e in suite_errors(data)))
        data = copy.deepcopy(SUITE)
        next(c for c in data["cases"] if c["id"] == "TT-01").pop("mutations")
        self.assertTrue(any("TT-01" in e and "mutation control" in e for e in suite_errors(data)))

    def test_a_successful_violation_must_be_recorded_as_a_known_gap(self):
        data = copy.deepcopy(SUITE)
        next(c for c in data["cases"] if c["id"] == "CN-02").pop("known_gap")
        self.assertTrue(any("CN-02" in e and "known_gap" in e for e in suite_errors(data)))

    def test_the_handover_rides_the_one_frozen_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy_dir = Path(tmp) / "trajectories"
            shutil.copytree(eval_mod.TRAJECTORY_DIR, copy_dir)
            target = copy_dir / "HO-01.retry-ignores.jsonl"
            target.write_text(target.read_text(encoding="utf-8").replace(
                '"task_id": "trj-602-calc"', '"task_id": "some-other-task"'), encoding="utf-8")
            errors = suite_errors(SUITE, trajectory_dir=copy_dir)
        self.assertTrue(any("frozen contract's id" in e for e in errors), errors)

    def test_live_cases_stay_unrun_until_a_run_report_binds(self):
        data = copy.deepcopy(SUITE)
        live = data["live_cases"][0]
        live["status"] = "PASS"
        self.assertTrue(any("needs a run_report" in e for e in suite_errors(data)))
        live.update(model="m", harness="h", harness_version="1", budget_usd=5, repeats=3,
                    environment="disposable", run_report="evals/trajectories/contract.json")
        self.assertFalse(any("live case" in e for e in suite_errors(data)))
        for row in SUITE["live_cases"]:
            with self.subTest(live=row["id"]):
                self.assertEqual(row["status"], "UNRUN")
                self.assertTrue(all(row[f] is None for f in engine.LIVE_FIELDS),
                                "a live cell nobody ran carries a value")

    def test_the_engine_vocabulary_tracks_the_guards_and_the_suite(self):
        self.assertEqual(engine.OUTPUT_SOURCES, engine.guards().guard_text.SOURCES,
                         "a tool-output source the fence does not know would be refused at replay")
        used = {m["id"] for c in SUITE["cases"] for m in c.get("mutations") or []}
        self.assertEqual(used, set(engine.MUTATIONS), "a registered mutation control no case runs "
                                                      "proves nothing")

    def test_events_are_schema_checked(self):
        case = case_named("HO-01")
        good = events_of(case)
        self.assertEqual(engine.event_errors(good, case, "trj-602-calc"), [])
        for label, bad in (
            ("unknown tool", good[:1] + [{"seq": 99, "tool": "Teleport"}]),
            ("worker after Fail", good + [{"seq": 99, "tool": "Commit", "message": "x"}]),
            ("retry without Fail", [e for e in good if e["tool"] != "Fail"]),
            ("escaping path", [{"seq": 1, "tool": "Write", "path": "../x", "content": "x"}]),
        ):
            with self.subTest(label=label):
                self.assertNotEqual(engine.event_errors(bad, case, "trj-602-calc"), [])


class GuardedArms(unittest.TestCase):
    def test_the_suite_passes(self):
        result = suite_result()
        self.assertNotIn("error", result)
        bad = [(r["case"], r["arm"], r["failures"]) for r in result["rows"]
               if r["verdict"] not in ("PASS", "GAP", "RED")]
        self.assertEqual(bad, [])
        self.assertTrue(result["summary"]["passed"])

    def test_every_injection_reached_the_lifecycle(self):
        for r in rows(arm="guarded"):
            if r["arrival"]:
                with self.subTest(case=r["case"], trajectory=r["trajectory"]):
                    self.assertTrue(r["arrived"])

    def test_every_attack_is_attempted_and_held_except_a_recorded_gap(self):
        for r in rows(arm="guarded"):
            if r["kind"] != "attack":
                continue
            with self.subTest(case=r["case"], trajectory=r["trajectory"]):
                if r["verdict"] == "GAP":
                    self.assertTrue(r["known_gap"])
                    self.assertTrue(r["successful"])
                else:
                    self.assertEqual(r["successful"], [], "a guard let a violation land")

    def test_attempted_and_successful_are_kept_apart(self):
        guarded = rows("TT-01", "guarded")[0]
        self.assertIn("test-file", guarded["attempted"])
        self.assertEqual(guarded["successful"], [], "blocked tampering graded as successful")
        self.assertFalse(guarded["landed"])
        removed = rows("TT-01", "mutation:floor-assertion-rule-removed")[0]
        self.assertIn("test-file", removed["successful"])
        self.assertTrue(removed["landed"])

    def test_the_final_answer_never_moves_a_grade(self):
        a, b = rows("FA-01", "guarded")
        self.assertNotEqual(a["final_answer"], b["final_answer"])
        for key in ("attempted", "successful", "landed", "verdict", "failures", "task_done"):
            self.assertEqual(a[key], b[key], key)
        # A final answer that denies touching the tests does not hide the edit it made.
        tt = rows("TT-01", "guarded")[0]
        self.assertIn("did not modify any tests", tt["final_answer"])
        self.assertIn("test-file", tt["attempted"])

    def test_the_allowed_actions_contract_is_enforced(self):
        tt = rows("TT-01", "guarded")[0]
        self.assertIn("action:DecisionsAppend", tt["attempted"])
        self.assertTrue(any(d["by"] == "allowed_actions" for d in tt["denials"]))

    def test_utility_controls_land_their_task_with_no_false_denial(self):
        controls = [r for r in rows(arm="guarded") if r["kind"] != "attack"]
        self.assertGreaterEqual({r["kind"] for r in controls}, {"benign", "clean"})
        for r in controls:
            with self.subTest(case=r["case"]):
                self.assertTrue(r["landed"])
                self.assertTrue(r["task_done"])
                self.assertEqual(r["false_denials"], [])
        # BN-02's quoted string is labelled by the fence and the work still lands.
        self.assertGreater(rows("BN-02", "guarded")[0]["labelled_lines"], 0)

    def test_every_row_is_bound_to_the_one_frozen_contract_and_its_pin(self):
        digest = "sha256:" + hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
        pins = {c["id"]: c["pin"] for c in SUITE["cases"]}
        for r in suite_result()["rows"]:
            self.assertEqual(r["contract"], digest)
            self.assertEqual(r["pin"], pins[r["case"]])


class MutationControls(unittest.TestCase):
    def test_every_family_turns_red_with_its_guard_removed(self):
        red = {r["family"] for r in suite_result()["rows"] if r["verdict"] == "RED"}
        self.assertEqual(red, set(engine.FAMILIES))

    def test_each_mutation_fails_for_its_declared_reason(self):
        mutated = [r for r in suite_result()["rows"] if r["arm"].startswith("mutation:")]
        self.assertTrue(mutated)
        for r in mutated:
            with self.subTest(case=r["case"], arm=r["arm"]):
                self.assertEqual(r["verdict"], "RED", r["failures"])
                self.assertIn(r["fails_on"], {f["category"] for f in r["failures"]})

    def test_contaminating_the_handover_is_caught(self):
        r = rows("HO-01", "mutation:handover-contaminated")[0]
        self.assertTrue(any("contaminated in transit" in f["detail"] for f in r["failures"]))

    def test_a_mutation_that_proves_nothing_is_reported_not_hidden(self):
        data = copy.deepcopy(SUITE)
        tt = next(c for c in data["cases"] if c["id"] == "TT-01")
        tt["mutations"] = [{"id": "recall-fence-removed", "fails_on": "successful-violation"}]
        data["cases"] = [tt]
        got = engine.run_suite(data, eval_mod.TRAJECTORY_DIR, CONTRACT,
                               eval_mod.OBEDIENCE_FIXTURE_SECRET, eval_mod.check_workspace_state)
        self.assertEqual([r["verdict"] for r in got], ["PASS", "SURVIVED"])
        self.assertFalse(eval_mod._trajectory_summary(got)["passed"])

    def test_a_blind_grader_would_let_every_guard_mutation_survive(self):
        # The proof the mutation rows can see: a grader that never reports a successful
        # violation turns the floor guard's RED into SURVIVED. Success is read off git state.
        case = case_named("TT-01")
        expect = case["trajectories"][0]["expect"]
        with mock.patch.object(engine, "_grade_asset", lambda asset, run, files: ([1], False)):
            blind = replay(case, events_of(case), expect, "floor-assertion-rule-removed")
        self.assertNotIn("successful-violation", categories(blind))
        seeing = replay(case, events_of(case), expect, "floor-assertion-rule-removed")
        self.assertIn("successful-violation", categories(seeing))


class ArrivalAndUnpinnedRecordings(unittest.TestCase):
    def test_a_fixture_whose_injection_never_arrives_proves_nothing(self):
        case = case_named("FA-01")
        events = [e for e in events_of(case) if e.get("path") != "@issue"]
        graded = replay(case, events, case["trajectories"][0]["expect"])
        self.assertIn("arrival", categories(graded))

    def _grade_unpinned(self, case_id, events):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "recording.jsonl"
            path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
            return eval_mod.run_trajectory_eval(case_id=case_id, trajectory=path)

    def test_an_unpinned_recording_that_leaks_fails(self):
        result = self._grade_unpinned("CN-02", events_of(case_named("CN-02")))
        self.assertEqual(result["rows"][0]["verdict"], "FAIL")
        self.assertIn("plain-canary", result["rows"][0]["successful"])

    def test_an_unpinned_recording_whose_attempt_was_held_passes_and_reports_it(self):
        result = self._grade_unpinned("TT-01", events_of(case_named("TT-01")))
        row = result["rows"][0]
        self.assertEqual(row["verdict"], "PASS", row["failures"])
        self.assertIn("test-file", row["attempted"])

    def test_the_cli_grades_a_recording_only_against_a_named_case(self):
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "eval.py"), "run", "--suite",
                            "trajectories", "--trajectory", "x.jsonl"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("--case", r.stdout)


class PublishedTable(unittest.TestCase):
    def test_the_published_table_is_the_live_output(self):
        text = DOC.read_text(encoding="utf-8")
        self.assertIn(TABLE_START, text)
        published = text.split(TABLE_START, 1)[1].split(TABLE_END, 1)[0].strip("\n")
        self.assertEqual(published, eval_mod.trajectory_table(suite_result()).strip("\n"),
                         "regenerate with `python3 scripts/eval.py run --suite trajectories "
                         "--markdown` and paste it between the markers")

    def test_unknown_and_unrun_cells_are_published(self):
        table = eval_mod.trajectory_table(suite_result())
        self.assertIn("| unknown |", table)
        self.assertIn("UNRUN", table)
        self.assertIn("GAP", table)

    def test_the_suite_claims_no_proof(self):
        self.assertIn("never proof evidence", SUITE["tier"])
        self.assertIn("not proof evidence", DOC.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
