#!/usr/bin/env python3
"""Contract tests for runtime/scripts/events.py (#603).

The record's job is to let a run report's WIP-curve rows be DERIVED instead of typed. So the
properties pinned here are the ones a typed row would silently get wrong: a duplicate delivery
counted twice, a negative or cross-clock interval reported as a number, a fenced coordinator's
write treated as fact, an unknown cost written as 0, and a report that does not reproduce.

The two committed fixture streams (tests/fixtures/events/) are built by `scenario_clean()` and
`scenario_crash()` below — the expected rows beside them were calculated by hand from the
timestamps in those functions, not by running the tool.
"""
import calendar
import contextlib
import importlib
import io
import importlib.util
import json
import os
import random
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
EVENTS = ROOT / "runtime" / "scripts" / "events.py"
FIXTURES = ROOT / "tests" / "fixtures" / "events"
SPEC = importlib.util.spec_from_file_location("events", EVENTS)
events = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(events)


def sha(tag):
    """A full 40-hex commit id from a two-hex tag: sha('a1') -> 'a1a1…a1'."""
    return tag * 20


def ev(kind, hms, *, run, epoch, clock, task=None, dispatch=None, data=None, event_id=None,
       producer="coordinator", basis="observed", day="2026-10-20", ref=None, digest=None):
    return events.build_event(kind, run, epoch=epoch, producer=producer, clock=clock,
                              observed_at=f"{day}T{hms}Z", basis=basis,
                              source_ref=ref or f"fixture:{kind}", source_sha256=digest,
                              task=task, dispatch=dispatch, data=data, event_id=event_id)


def chain(evs):
    """The record's bytes for `evs` in this order, duplicates kept — what a concatenation, or a
    producer that skipped append's dedup, leaves on disk."""
    out, prev = [], None
    for event in evs:
        raw = json.dumps(dict(event, prev="" if prev is None else events.sha256_hex(prev)),
                         sort_keys=True, separators=(",", ":"))
        out.append(raw + "\n")
        prev = raw
    return "".join(out)


def scenario_clean():
    """run-a: two complete waves, appended OUT OF ORDER, with a duplicate delivery, a
    re-observation under a new id, a retry, a bounce, a voided review and a tree-equal rebase.

    Hand calculation (clock host-a throughout):
      wave 1 open 10:00, close 11:45 -> 6300 s; t1 and t2 verified-CLOSED -> 2*3600/6300 = 1.14/h
        t1: done@A1 10:20 (also re-observed 10:21) -> pass@A1 10:40 = 20 m
        t2: done@B1 10:30 -> FAIL@B1 (bounce) -> retry d3 -> done@B2 11:10 -> pass@B2 11:34 = 24 m
        latency median (20+24)/2 = 22.00m, max 24.00m; rework 1/2;
        freshness: t2's approval at B1 is voided by the close at B2 -> 1
        review queue 5 m (t1), 2 m (t2@B1), 10 m (t2@B2) -> median 5.00m, max 10.00m; retries 1
      wave 2 open 11:50, close 13:00 -> 4200 s; t4 verified-CLOSED, t3 parked -> 3600/4200 = 0.86/h
        t3: done@C1 12:10 -> parked 12:15 = 5 m
        t4: done@D1 12:20 -> pass@D1 12:40 = 20 m (the conductor's rebase D2 re-verifies a head no
            worker reported); approval at D1 survives the close at D2: same tree W1
        latency median (5+20)/2 = 12.50m, max 20.00m; rework 0/2; freshness 0
      usage: input 1000+1500+500+400+600 = 4000, output 200+300+100+80+120 = 800;
        cost 0.50+0.25+0.10+0.15 known = 1.00 but d2 never reported one -> null, never 0
    """
    c = {"run": "run-a", "epoch": 1, "clock": "host-a"}
    st = {"producer": "local_state", "basis": "occurred"}
    a1, b1, b2, c1, d1, d2, w1 = sha("a1"), sha("b1"), sha("b2"), sha("c1"), sha("d1"), sha("d2"), sha("e7")
    done_t1 = ev("task.done", "10:20:00", task="t1", dispatch="d1", data={"head_sha": a1},
                 event_id="local-state:message:m1", **st, **c)

    def usage(dispatch, task, inp, out, cost, line):
        prov = f"fixture stream {dispatch} result line {line}"
        if cost is None:
            prov += "; not reported: cost_usd"
        return ev("model.usage", "13:05:00", task=task, dispatch=dispatch,
                  data={"model": "claude-fixture", "input_tokens": inp, "output_tokens": out,
                        "cost_usd": cost, "provenance": prov},
                  event_id=f"usage:{dispatch}:{line}", producer="claude-stream-json", **c)
    usage_d3 = usage("d3", "t2", 500, 100, "0.25", 22)
    return [
        ev("run.start", "10:00:00", data={"coordinator": "coord-1"}, **c),
        ev("wave.open", "10:00:00", data={"wave": 1, "builders": 2, "reviewers": 1,
                                          "tasks": ["t1", "t2"]}, **c),
        ev("dispatch.launched", "10:01:00", task="t1", dispatch="d1", data={"agent": "claude"},
           event_id="local-state:dispatch:d1", **st, **c),
        ev("dispatch.launched", "10:01:30", task="t2", dispatch="d2", data={"agent": "claude"},
           event_id="local-state:dispatch:d2", **st, **c),
        # out of order: t1's verdict lands before its worker_done
        ev("verify.verdict", "10:40:00", task="t1", data={"exit": 0, "head_sha": a1},
           producer="verify.py", basis="occurred", digest=sha("f1") + "f1" * 12, **c),
        done_t1,
        ev("review.started", "10:25:00", task="t1", dispatch="r1", data={"head_sha": a1}, **c),
        ev("task.done", "10:30:00", task="t2", dispatch="d2", data={"head_sha": b1},
           event_id="local-state:message:m2", **st, **c),
        done_t1,  # the same delivery, again
        ev("review.verdict", "10:35:00", task="t1", data={"verdict": "approve", "reviewed_sha": a1}, **c),
        ev("review.started", "10:32:00", task="t2", dispatch="r2", data={"head_sha": b1}, **c),
        ev("task.done", "10:21:00", task="t1", dispatch="d1", data={"head_sha": a1},
           event_id="coordinator-saw-done-t1", **c),  # a later re-observation of the same fact
        ev("review.verdict", "10:45:00", task="t2", data={"verdict": "approve", "reviewed_sha": b1}, **c),
        ev("verify.verdict", "10:50:00", task="t2", data={"exit": 2, "head_sha": b1},
           producer="verify.py", basis="occurred", **c),
        ev("unit.closed", "10:55:00", task="t1", data={"head_sha": a1}, **c),
        ev("dispatch.launched", "10:52:00", task="t2", dispatch="d3", data={"agent": "claude"},
           event_id="local-state:dispatch:d3", **st, **c),
        ev("unit.closed", "11:40:00", task="t2", data={"head_sha": b2}, **c),
        ev("task.done", "11:10:00", task="t2", dispatch="d3", data={"head_sha": b2},
           event_id="local-state:message:m3", **st, **c),
        ev("review.started", "11:20:00", task="t2", dispatch="r3", data={"head_sha": b2}, **c),
        ev("review.verdict", "11:25:00", task="t2", data={"verdict": "approve", "reviewed_sha": b2}, **c),
        ev("verify.verdict", "11:34:00", task="t2", data={"exit": 0, "head_sha": b2},
           producer="verify.py", basis="occurred", **c),
        ev("wave.close", "11:45:00", data={"wave": 1}, **c),
        ev("wave.open", "11:50:00", data={"wave": 2, "builders": 1, "reviewers": 1,
                                          "tasks": ["t3", "t4"]}, **c),
        ev("dispatch.launched", "11:51:00", task="t3", dispatch="d4", event_id="local-state:dispatch:d4", **st, **c),
        ev("dispatch.launched", "11:52:00", task="t4", dispatch="d5", event_id="local-state:dispatch:d5", **st, **c),
        ev("unit.parked", "12:15:00", task="t3", data={"park_class": "needs-human", "head_sha": c1}, **c),
        ev("task.done", "12:10:00", task="t3", dispatch="d4", data={"head_sha": c1},
           event_id="local-state:message:m4", **st, **c),
        ev("task.done", "12:20:00", task="t4", dispatch="d5", data={"head_sha": d1},
           event_id="local-state:message:m5", **st, **c),
        ev("review.started", "12:21:00", task="t4", dispatch="r4", data={"head_sha": d1}, **c),
        ev("review.verdict", "12:30:00", task="t4", data={"verdict": "approve", "reviewed_sha": d1,
                                                          "reviewed_wtree": w1}, **c),
        ev("verify.verdict", "12:48:00", task="t4", data={"exit": 0, "head_sha": d2},
           producer="verify.py", basis="occurred", **c),
        ev("verify.verdict", "12:40:00", task="t4", data={"exit": 0, "head_sha": d1},
           producer="verify.py", basis="occurred", **c),
        ev("unit.closed", "12:50:00", task="t4", data={"head_sha": d2, "head_wtree": w1}, **c),
        ev("wave.close", "13:00:00", data={"wave": 2}, **c),
        usage("d1", "t1", 1000, 200, "0.50", 40),
        usage("d2", "t2", 1500, 300, None, 31),
        usage_d3,
        usage_d3,  # duplicate delivery: must not add 500 more input tokens
        usage("d4", "t3", 400, 80, "0.10", 18),
        usage("d5", "t4", 600, 120, "0.15", 27),
    ]


CLEAN_ROWS = [
    "| `wave=1` | `builders=2 reviewers=1` | `throughput=1.14/h` | "
    "`latency_median=22.00m latency_max=24.00m` | `rework=1/2` | `freshness=1` |",
    "| `wave=2` | `builders=1 reviewers=1` | `throughput=0.86/h` | "
    "`latency_median=12.50m latency_max=20.00m` | `rework=0/2` | `freshness=0` |",
]


def scenario_crash():
    """run-b: a coordinator crash on host-a, a resume on host-b, and the observations that a
    crash leaves incomplete — every metric below that the record cannot support is unavailable.

    Hand calculation:
      wave 1: opened on host-a, closed on host-b -> no common clock, throughput unavailable;
        u1 done on host-a, verified on host-b -> latency unavailable (two clocks);
        u2's done was RECOVERED at resume -> its time is the rebuild time -> unavailable;
        both verified-CLOSED with fresh approvals, no bounce -> rework 0/2, freshness 0
      wave 2: never closed; u3 verified at 10:25 before its done at 10:30 -> a negative interval
        (a clock that stepped back) -> unavailable, not 0; u4 launched and never heard from
        -> open, so throughput/rework/freshness are unavailable
      wave 3: complete on host-b, but the fenced epoch-1 coordinator wrote unit.suspect for u5
        after epoch 2 was declared -> excluded, and wave 3 is unavailable rather than guessed
      plus: one event of another run, an unplanned reviewer task whose launch was delivered
        twice with different bodies (a conflict), and a usage event under an undeclared epoch
    """
    a = {"run": "run-b", "epoch": 1, "clock": "host-a"}
    b = {"run": "run-b", "epoch": 2, "clock": "host-b"}
    e1, f1, g1, h1 = sha("e1"), sha("f1"), sha("f2"), sha("f3")
    return [
        ev("run.start", "09:00:00", data={"coordinator": "coord-1"}, **a),
        ev("wave.open", "09:00:00", data={"wave": 1, "builders": 2, "reviewers": 1,
                                          "tasks": ["u1", "u2"]}, **a),
        ev("dispatch.launched", "09:01:00", task="u1", dispatch="x1", **a),
        ev("dispatch.launched", "09:02:00", task="u2", dispatch="x2", **a),
        ev("task.done", "09:20:00", task="u1", dispatch="x1", data={"head_sha": e1}, **a),
        ev("run.start", "08:00:00", run="run-other", epoch=1, clock="host-z",
           data={"coordinator": "coord-z"}),
        ev("coordinator.resume", "09:40:00", data={"coordinator": "coord-2"}, **b),
        ev("task.done", "09:35:00", task="u2", dispatch="x2", data={"head_sha": f1},
           basis="recovered", **b),
        ev("review.verdict", "09:44:00", task="u1", data={"verdict": "approve", "reviewed_sha": e1}, **b),
        ev("verify.verdict", "09:45:00", task="u1", data={"exit": 0, "head_sha": e1}, **b),
        ev("unit.closed", "09:50:00", task="u1", data={"head_sha": e1}, **b),
        ev("review.verdict", "09:52:00", task="u2", data={"verdict": "approve", "reviewed_sha": f1}, **b),
        ev("verify.verdict", "09:55:00", task="u2", data={"exit": 0, "head_sha": f1}, **b),
        ev("unit.closed", "10:00:00", task="u2", data={"head_sha": f1}, **b),
        ev("wave.close", "10:05:00", data={"wave": 1}, **b),
        ev("wave.open", "10:10:00", data={"wave": 2, "builders": 1, "reviewers": 1,
                                          "tasks": ["u3", "u4"]}, **b),
        ev("dispatch.launched", "10:11:00", task="u3", dispatch="x3", **b),
        ev("dispatch.launched", "10:12:00", task="u4", dispatch="x4", **b),
        ev("verify.verdict", "10:25:00", task="u3", data={"exit": 0, "head_sha": g1}, **b),
        ev("task.done", "10:30:00", task="u3", dispatch="x3", data={"head_sha": g1}, **b),
        ev("review.verdict", "10:35:00", task="u3", data={"verdict": "approve", "reviewed_sha": g1}, **b),
        ev("unit.closed", "10:40:00", task="u3", data={"head_sha": g1}, **b),
        ev("wave.open", "11:00:00", data={"wave": 3, "builders": 1, "reviewers": 0,
                                          "tasks": ["u5"]}, **b),
        ev("dispatch.launched", "11:01:00", task="u5", dispatch="x5", **b),
        ev("unit.suspect", "11:05:00", task="u5", **a),  # the fenced coordinator, still writing
        ev("task.done", "11:10:00", task="u5", dispatch="x5", data={"head_sha": h1}, **b),
        ev("review.verdict", "11:12:00", task="u5", data={"verdict": "approve", "reviewed_sha": h1}, **b),
        ev("verify.verdict", "11:15:00", task="u5", data={"exit": 0, "head_sha": h1}, **b),
        ev("unit.closed", "11:20:00", task="u5", data={"head_sha": h1}, **b),
        ev("wave.close", "11:30:00", data={"wave": 3}, **b),
        ev("dispatch.launched", "10:20:00", task="rv1", dispatch="xr1", data={"agent": "claude"},
           event_id="rv-launch", **b),
        ev("dispatch.launched", "10:20:00", task="rv1", dispatch="xr1", data={"agent": "codex"},
           event_id="rv-launch", **b),
        ev("model.usage", "11:31:00", run="run-b", epoch=3, clock="host-b", dispatch="x1",
           data={"model": "claude-fixture", "input_tokens": 10, "provenance": "undeclared epoch"}),
        ev("model.usage", "11:31:00", task="u5", dispatch="x5",
           data={"model": None, "input_tokens": 900,
                 "provenance": "fixture stream x5 result line 12; not reported: model, output_tokens, cost_usd"},
           event_id="usage:x5:12", **b),
    ]


CRASH_ROWS = [
    "| `wave=1` | `builders=2 reviewers=1` | `throughput=unavailable` | "
    "`latency_median=unavailable latency_max=unavailable` | `rework=0/2` | `freshness=0` |",
    "| `wave=2` | `builders=1 reviewers=1` | `throughput=unavailable` | "
    "`latency_median=unavailable latency_max=unavailable` | `rework=unavailable` | "
    "`freshness=unavailable` |",
    "| `wave=3` | `builders=1 reviewers=0` | `throughput=unavailable` | "
    "`latency_median=unavailable latency_max=unavailable` | `rework=unavailable` | "
    "`freshness=unavailable` |",
]

SCENARIOS = {"clean-two-waves": (scenario_clean, "run-a"), "crash-resume": (scenario_crash, "run-b")}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="events-"))
        self.log = self.tmp / "state" / "events.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, evs, path=None):
        path = path or self.log
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(chain(evs), encoding="utf-8")
        return path

    def derive(self, evs, run=None):
        self.write(evs)
        recorded, file_sha, head = events.read_log(self.log)
        return events.derive(recorded, run, file_sha, head)

    def cli(self, *args, log=None, env=None):
        return subprocess.run([sys.executable, str(EVENTS), "--log", str(log or self.log), *args],
                              capture_output=True, text=True, env=env, cwd=str(self.tmp))

    def rows(self, report):
        return [w["row"] for w in report["waves"]]

    def metric(self, report, wave, name):
        return report["waves"][wave - 1]["metrics"][name]


class TestHandCalculatedRows(Base):
    """The derived rows equal the rows calculated by hand from the scenario timestamps."""

    def test_clean_stream_derives_the_hand_calculated_rows(self):
        report = self.derive(scenario_clean())
        self.assertEqual(self.rows(report), CLEAN_ROWS)
        self.assertTrue(report["complete"])

    def test_clean_stream_extra_metrics_and_outcomes(self):
        report = self.derive(scenario_clean())
        self.assertEqual(self.metric(report, 1, "review_queue_median")["value"], "5.00m")
        self.assertEqual(self.metric(report, 1, "review_queue_max")["value"], "10.00m")
        self.assertEqual(self.metric(report, 1, "retries")["value"], "1")
        self.assertEqual(self.metric(report, 2, "retries")["value"], "0")
        self.assertEqual(self.metric(report, 1, "throughput")["wall_clock_s"], "6300")
        # task completion, verified-CLOSED and parked are distinct counts
        self.assertEqual(report["waves"][0]["outcomes"]["verified-closed"], 2)
        self.assertEqual(report["waves"][1]["outcomes"]["verified-closed"], 1)
        self.assertEqual(report["waves"][1]["outcomes"]["parked"], 1)
        self.assertEqual(report["waves"][1]["outcomes"]["task_completed"], 2)
        units = {u["task"]: u for w in report["waves"] for u in w["units"]}
        self.assertEqual(units["t2"]["voided_reviews"], [sha("b1")])
        self.assertEqual(units["t4"]["voided_reviews"], [], "a tree-equal rebase keeps the review")
        self.assertTrue(units["t2"]["bounced"])
        self.assertEqual(units["t2"]["dispatches"], ["d2", "d3"])
        self.assertEqual(units["t3"]["park_classes"], ["needs-human"])

    def test_crash_stream_derives_the_hand_calculated_rows(self):
        report = self.derive(scenario_crash(), run="run-b")
        self.assertEqual(self.rows(report), CRASH_ROWS)
        self.assertFalse(report["complete"])
        self.assertEqual(report["record"]["other_run_events"], 1)
        self.assertEqual(report["record"]["conflicts"], 1)
        self.assertEqual(report["record"]["fenced"], 2)
        self.assertEqual([e["epoch"] for e in report["epochs"]], [1, 2])
        self.assertEqual(report["unplanned"], [{"task": "rv1", "events": 1}])

    def test_crash_stream_names_why_each_metric_is_unavailable(self):
        report = self.derive(scenario_crash(), run="run-b")

        def reasons(wave, name):
            return " ".join(self.metric(report, wave, name)["unavailable"])
        self.assertIn("different clocks", reasons(1, "throughput"))
        self.assertIn("different clocks", reasons(1, "latency_median"))
        self.assertIn("recovered after a coordinator resume", reasons(1, "latency_median"))
        self.assertIn("negative", reasons(2, "latency_max"))
        self.assertIn("never clamped to 0", reasons(2, "latency_max"))
        self.assertIn("wave.close not observed", reasons(2, "throughput"))
        self.assertIn("['u4']", reasons(2, "rework"))
        self.assertIn("fenced coordinator", reasons(3, "throughput"))
        self.assertIn("fenced coordinator", reasons(3, "freshness"))


class TestFixturesReproduce(Base):
    """Committed fixture streams, and the reports over them, reproduce byte-for-byte."""

    def test_committed_streams_are_the_documented_scenarios(self):
        for name, (build, _run) in SCENARIOS.items():
            with self.subTest(name):
                self.assertEqual((FIXTURES / f"{name}.jsonl").read_text(encoding="utf-8"),
                                 chain(build()))

    def test_report_is_byte_for_byte_the_golden_report(self):
        for name, (_build, run) in SCENARIOS.items():
            for fmt, ext in ((["--json"], "json"), ([], "md")):
                with self.subTest(name=name, fmt=ext):
                    proc = self.cli("report", "--run", run, *fmt, log=FIXTURES / f"{name}.jsonl")
                    self.assertIn(proc.returncode, (0, 1), proc.stderr)
                    self.assertEqual(proc.stdout,
                                     (FIXTURES / f"{name}.report.{ext}").read_text(encoding="utf-8"))

    def test_report_does_not_depend_on_hash_seed_timezone_or_cwd(self):
        golden = (FIXTURES / "clean-two-waves.report.json").read_text(encoding="utf-8")
        for seed, tz in (("0", "UTC"), ("12345", "Asia/Kolkata"), ("random", "America/Los_Angeles")):
            env = dict(os.environ, PYTHONHASHSEED=seed, TZ=tz)
            proc = self.cli("report", "--json", log=FIXTURES / "clean-two-waves.jsonl", env=env)
            self.assertEqual(proc.stdout, golden, f"seed={seed} tz={tz}")

    def test_the_report_names_raw_event_digests_and_exact_revisions(self):
        path = FIXTURES / "clean-two-waves.jsonl"
        raw_lines = [ln for ln in path.read_text(encoding="utf-8").split("\n") if ln]
        report = json.loads((FIXTURES / "clean-two-waves.report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["record"]["log_sha256"], events.sha256_hex(path.read_bytes()))
        self.assertEqual(report["record"]["head"], events.sha256_hex(raw_lines[-1]))
        digests = {events.sha256_hex(ln) for ln in raw_lines}
        cited = {e["digest"] for w in report["waves"] for u in w["units"] for e in u["events"]}
        self.assertTrue(cited and cited <= digests)
        t4 = next(u for w in report["waves"] for u in w["units"] if u["task"] == "t4")
        self.assertEqual(t4["revisions"]["closed_at"], sha("d2"))
        self.assertEqual(t4["revisions"]["verified_at"], [sha("d1"), sha("d2")])


class TestOrderAndDuplicates(Base):
    def _metrics(self, report):
        return [(w["row"], json.dumps(w["metrics"], sort_keys=True)) for w in report["waves"]]

    def test_any_append_order_derives_the_same_rows(self):
        baseline = self._metrics(self.derive(scenario_clean()))
        for seed in range(6):
            evs = scenario_clean()
            head, rest = evs[:1], evs[1:]  # run.start must declare epoch 1 before it is used
            random.Random(seed).shuffle(rest)
            with self.subTest(seed=seed):
                self.assertEqual(self._metrics(self.derive(head + rest)), baseline)

    def test_a_duplicate_delivery_does_not_double_count(self):
        report = self.derive(scenario_clean())
        self.assertEqual(report["record"]["duplicates"], 2)
        model = report["usage"]["models"]["claude-fixture"]
        self.assertEqual(model["observations"], 5)
        self.assertEqual(model["input_tokens"], {"value": 4000})
        self.assertEqual(report["usage"]["run_total"]["output_tokens"], {"value": 800})

    def test_a_re_observation_never_moves_an_interval_endpoint(self):
        # t1's done is seen twice (10:20 at the store, 10:21 by the coordinator); latency is 20m.
        report = self.derive(scenario_clean())
        t1 = next(u for u in report["waves"][0]["units"] if u["task"] == "t1")
        self.assertEqual(t1["latency"]["value"], "20.00m")

    def test_append_skips_an_event_the_record_already_holds(self):
        evs = scenario_clean()[:3]
        first = events.append_events(self.log, evs)
        again = events.append_events(self.log, evs)
        self.assertEqual([s for _i, s in first], ["appended"] * 3)
        self.assertEqual([s for _i, s in again], ["duplicate"] * 3)
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 3)

    def test_a_reused_id_with_a_different_body_contests_the_unit(self):
        evs = scenario_clean()
        evs.append(ev("unit.closed", "10:56:00", task="t1", data={"head_sha": sha("a9")},
                      event_id=evs[14]["event_id"], run="run-a", epoch=1, clock="host-a"))
        report = self.derive(evs)
        self.assertEqual(report["record"]["conflicts"], 1)
        reasons = self.metric(report, 1, "throughput")["unavailable"]
        self.assertTrue(any("different bodies" in r for r in reasons), reasons)
        self.assertEqual(self.metric(report, 2, "throughput")["value"], "0.86/h",
                         "a conflict contests its own wave, not every wave")


ONE = {"run": "r", "epoch": 1, "clock": "host-a"}


def unit_stream(done_at="10:10:00", verdict_at="10:20:00", done_kw=None, verdict_kw=None):
    """One unit, one wave, one clock: done 10:10 -> verified 10:20 (latency 10 m)."""
    c = ONE
    return [
        ev("run.start", "10:00:00", data={"coordinator": "c1"}, **c),
        ev("wave.open", "10:00:00", data={"wave": 1, "builders": 1, "reviewers": 1, "tasks": ["t"]}, **c),
        ev("dispatch.launched", "10:01:00", task="t", dispatch="d", **c),
        ev("task.done", done_at, task="t", dispatch="d", data={"head_sha": sha("aa")},
           **{**c, **(done_kw or {})}),
        ev("review.verdict", "10:15:00", task="t", data={"verdict": "approve", "reviewed_sha": sha("aa")}, **c),
        ev("verify.verdict", verdict_at, task="t", data={"exit": 0, "head_sha": sha("aa")},
           **{**c, **(verdict_kw or {})}),
        ev("unit.closed", "10:30:00", task="t", data={"head_sha": sha("aa")}, **c),
        ev("wave.close", "10:40:00", data={"wave": 1}, **c),
    ]


class TestClocksAndResume(Base):
    def test_control_the_same_stream_on_one_clock_is_measured(self):
        report = self.derive(unit_stream())
        self.assertEqual(self.metric(report, 1, "latency_max")["value"], "10.00m")

    def test_a_negative_interval_is_unavailable_never_zero(self):
        report = self.derive(unit_stream(done_at="10:25:00"))
        latency = self.metric(report, 1, "latency_max")
        self.assertIsNone(latency["value"])
        self.assertTrue(any("negative" in r for r in latency["unavailable"]))

    def test_two_clocks_give_no_interval(self):
        report = self.derive(unit_stream(verdict_kw={"clock": "host-b"}))
        self.assertIsNone(self.metric(report, 1, "latency_median")["value"])

    def test_a_recovered_endpoint_gives_no_interval(self):
        report = self.derive(unit_stream(done_kw={"basis": "recovered"}))
        self.assertIsNone(self.metric(report, 1, "latency_median")["value"])
        self.assertEqual(self.metric(report, 1, "rework")["value"], "0/1",
                         "recovery hides a time, not an outcome")

    def test_a_fenced_coordinators_write_is_excluded_and_contests_its_wave(self):
        evs = unit_stream()
        evs.insert(4, ev("coordinator.resume", "10:12:00", data={"coordinator": "c2"},
                         run="r", epoch=2, clock="host-a"))
        for event in evs[5:]:
            event["epoch"] = 2
        evs.append(ev("unit.suspect", "10:41:00", task="t", **ONE))  # epoch 1, after the resume
        report = self.derive(evs)
        self.assertEqual(report["record"]["fenced"], 1)
        self.assertIsNone(self.metric(report, 1, "rework")["value"],
                          "the stale SUSPECT is neither counted nor silently dropped")
        self.assertTrue(any("fenced coordinator" in r
                            for r in self.metric(report, 1, "rework")["unavailable"]))

    def test_resume_on_the_same_clock_keeps_intervals_that_span_it(self):
        evs = unit_stream()
        evs.insert(4, ev("coordinator.resume", "10:12:00", data={"coordinator": "c2"},
                         run="r", epoch=2, clock="host-a"))
        for event in evs[5:]:
            event["epoch"] = 2
        report = self.derive(evs)
        self.assertEqual(self.metric(report, 1, "latency_max")["value"], "10.00m")

    def test_an_undeclared_epoch_is_excluded(self):
        evs = unit_stream()
        evs[5]["epoch"] = 2  # a verdict under an epoch no resume declared
        report = self.derive(evs)
        self.assertEqual(report["record"]["fenced"], 1)
        self.assertIsNone(self.metric(report, 1, "throughput")["value"])

    def test_without_run_start_nothing_is_measured(self):
        report = self.derive(unit_stream()[1:])
        self.assertFalse(report["complete"])
        self.assertEqual(report["record"]["fenced"], 7, "every event's epoch is undeclared")
        self.assertEqual(report["waves"], [])

    def test_a_missing_wave_close_leaves_throughput_unavailable(self):
        report = self.derive(unit_stream()[:-1])
        self.assertIsNone(self.metric(report, 1, "throughput")["value"])
        self.assertEqual(self.metric(report, 1, "latency_max")["value"], "10.00m")

    def test_a_unit_with_no_close_leaves_throughput_unavailable(self):
        evs = [e for e in unit_stream() if e["kind"] != "unit.closed"]
        report = self.derive(evs)
        self.assertIsNone(self.metric(report, 1, "throughput")["value"])
        self.assertEqual(report["waves"][0]["units"][0]["outcome"], "verified")

    def test_a_close_with_no_passing_verdict_is_completion_not_verified_closed(self):
        evs = [e for e in unit_stream() if e["kind"] != "verify.verdict"]
        report = self.derive(evs)
        self.assertEqual(report["waves"][0]["units"][0]["outcome"], "closed-unverified")
        self.assertEqual(self.metric(report, 1, "throughput")["verified_closed"], 0)


def carried_stream(late_clock="host-a"):
    """Task t parked in wave 1, re-planned, retried and closed in wave 2 (one clock).

    Hand calculation: wave 1 10:00-10:20 (1200 s): parked, 0 closed -> 0.00/h; done 10:10 ->
    parked 10:15 = 5 m. Wave 2 10:30-11:00 (1800 s): 1 closed -> 2.00/h; done 10:40 -> pass
    10:45 = 5 m."""
    c = ONE
    late = dict(c, clock=late_clock)
    return [
        ev("run.start", "10:00:00", data={"coordinator": "c1"}, **c),
        ev("wave.open", "10:00:00", data={"wave": 1, "builders": 1, "reviewers": 1, "tasks": ["t"]}, **c),
        ev("dispatch.launched", "10:01:00", task="t", dispatch="d1", **c),
        ev("task.done", "10:10:00", task="t", dispatch="d1", data={"head_sha": sha("a1")}, **c),
        ev("unit.parked", "10:15:00", task="t", data={"park_class": "needs-human", "head_sha": sha("a1")}, **c),
        ev("wave.close", "10:20:00", data={"wave": 1}, **c),
        ev("wave.open", "10:30:00", data={"wave": 2, "builders": 1, "reviewers": 1, "tasks": ["t"]}, **c),
        ev("dispatch.launched", "10:31:00", task="t", dispatch="d2", **c),
        ev("task.done", "10:40:00", task="t", dispatch="d2", data={"head_sha": sha("b1")}, **late),
        ev("review.verdict", "10:42:00", task="t", data={"verdict": "approve", "reviewed_sha": sha("b1")}, **c),
        ev("verify.verdict", "10:45:00", task="t", data={"exit": 0, "head_sha": sha("b1")}, **c),
        ev("unit.closed", "10:50:00", task="t", data={"head_sha": sha("b1")}, **c),
        ev("wave.close", "11:00:00", data={"wave": 2}, **c),
    ]


class TestCarriedUnits(Base):
    """PR #638 review (P1): a later close must not rewrite an earlier wave's outcome."""

    def test_each_wave_measures_its_own_window_of_a_carried_unit(self):
        report = self.derive(carried_stream())
        self.assertEqual(report["waves"][0]["row"],
                         "| `wave=1` | `builders=1 reviewers=1` | `throughput=0.00/h` | "
                         "`latency_median=5.00m latency_max=5.00m` | `rework=0/1` | `freshness=0` |")
        self.assertEqual([u["outcome"] for u in report["waves"][0]["units"]], ["parked"])
        self.assertEqual([u["outcome"] for u in report["waves"][1]["units"]], ["verified-closed"])
        self.assertEqual(self.metric(report, 2, "throughput")["value"], "2.00/h")
        self.assertEqual(self.metric(report, 2, "latency_max")["value"], "5.00m")
        self.assertEqual(report["carried"], [{"task": "t", "waves": [1, 2]}])

    def test_an_event_no_window_can_hold_leaves_both_waves_unavailable(self):
        report = self.derive(carried_stream(late_clock="host-b"))
        for wave in (1, 2):
            reasons = self.metric(report, wave, "throughput")["unavailable"]
            with self.subTest(wave=wave):
                self.assertTrue(any("cannot be placed" in r for r in reasons), reasons)


class TestRedispatchIsRework(Base):
    """PR #638 review (P1): rework is the share of units bounced 'by evidence-manifest.md §2
    (re-dispatch / SUSPECT)' — a replaced worker is a re-dispatch, verdict or not."""

    def test_a_worker_that_died_and_was_replaced_counts_as_rework(self):
        evs = unit_stream()
        evs.insert(3, ev("dispatch.died", "10:05:00", task="t", dispatch="d", **ONE))
        evs.insert(4, ev("dispatch.launched", "10:06:00", task="t", dispatch="d2", **ONE))
        evs[5]["dispatch"] = "d2"
        report = self.derive(evs)
        self.assertEqual(self.metric(report, 1, "rework")["value"], "1/1")
        self.assertEqual(self.metric(report, 1, "retries")["value"], "1")

    def test_control_a_single_dispatch_is_not_rework(self):
        self.assertEqual(self.metric(self.derive(unit_stream()), 1, "rework")["value"], "0/1")

    def test_a_unit_re_dispatched_into_a_later_wave_is_rework_there(self):
        report = self.derive(carried_stream())
        self.assertEqual(self.metric(report, 1, "rework")["value"], "0/1")
        self.assertEqual(self.metric(report, 2, "rework")["value"], "1/1")


class TestFreshnessCountsReviews(Base):
    def test_two_approvals_of_one_head_voided_count_twice(self):
        # PR #638 review (P2): freshness counted distinct reviewed SHAs, so two reviews of the
        # same head, both voided when it moved, counted once. A duplicate delivery or a
        # re-observation of ONE review (same reviewer, same head) still counts once.
        a, b = sha("aa"), sha("bb")

        def approve(at, reviewer, head, **kw):
            return ev("review.verdict", at, task="t", dispatch=reviewer,
                      data={"verdict": "approve", "reviewed_sha": head}, **ONE, **kw)
        first_r1 = approve("10:11:00", "r1", a)
        evs = unit_stream()[:4] + [
            first_r1, approve("10:12:00", "r2", a), first_r1,
            approve("10:13:00", "r1", a, event_id="r1-seen-again"),
            ev("task.done", "10:20:00", task="t", dispatch="d", data={"head_sha": b}, **ONE),
            approve("10:22:00", "r3", b),
            ev("verify.verdict", "10:25:00", task="t", data={"exit": 0, "head_sha": b}, **ONE),
            ev("unit.closed", "10:30:00", task="t", data={"head_sha": b}, **ONE),
            ev("wave.close", "10:40:00", data={"wave": 1}, **ONE),
        ]
        report = self.derive(evs)
        self.assertEqual(self.metric(report, 1, "freshness")["value"], "2")
        self.assertEqual(report["waves"][0]["units"][0]["voided_reviews"], [a, a])


class TestUsage(Base):
    def test_unknown_cost_stays_null_with_provenance_never_zero(self):
        report = self.derive(scenario_clean())
        cost = report["usage"]["models"]["claude-fixture"]["cost_usd"]
        self.assertIsNone(cost["value"])
        self.assertEqual(cost["known_sum"], "1.00")
        self.assertIn("1 of 5", cost["unavailable"])
        self.assertIn("fixture stream d2 result line 31; not reported: cost_usd",
                      report["usage"]["models"]["claude-fixture"]["provenance"])
        self.assertIsNone(report["usage"]["run_total"]["cost_usd"]["value"])
        cache = report["usage"]["run_total"]["cache_read_input_tokens"]
        self.assertIsNone(cache["value"], "a field nobody reported is null, not 0")

    def test_a_dispatch_with_no_usage_observation_leaves_the_run_total_unknown(self):
        evs = [e for e in scenario_clean() if not (e["kind"] == "model.usage" and e["dispatch"] == "d5")]
        report = self.derive(evs)
        self.assertEqual(report["usage"]["unobserved_dispatches"], ["d5"])
        self.assertIsNone(report["usage"]["run_total"]["input_tokens"]["value"])

    def _stream(self, lines):
        path = self.tmp / "worker.jsonl"
        path.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
        return path

    def test_ingest_usage_records_what_the_result_line_carries_and_nulls_the_rest(self):
        stream = self._stream([{"type": "system", "subtype": "init", "model": "claude-fixture"},
                               {"type": "assistant", "message": {}},
                               {"type": "result", "usage": {"input_tokens": 12, "output_tokens": 3}}])
        proc = self.cli("ingest-usage", "--stream", str(stream), "--run", "r", "--epoch", "1",
                        "--clock", "host-a", "--dispatch", "d", "--observed-at", "2026-10-20T10:00:00Z")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        recorded, _sha, _head = events.read_log(self.log)
        data = recorded[0]["data"]
        self.assertEqual((data["model"], data["input_tokens"], data["output_tokens"]),
                         ("claude-fixture", 12, 3))
        self.assertIsNone(data["cost_usd"])
        self.assertIn("not reported: cache_read_input_tokens, cache_creation_input_tokens, cost_usd",
                      data["provenance"])
        again = self.cli("ingest-usage", "--stream", str(stream), "--run", "r", "--epoch", "1",
                         "--clock", "host-a", "--dispatch", "d", "--observed-at", "2026-10-20T10:00:00Z")
        self.assertIn("duplicate", again.stdout)

    def test_ingest_usage_without_a_result_line_records_nothing(self):
        stream = self._stream([{"type": "system", "subtype": "init", "model": "m"}])
        proc = self.cli("ingest-usage", "--stream", str(stream), "--run", "r", "--epoch", "1",
                        "--clock", "host-a")
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(self.log.exists())


class TestRecordIntegrity(Base):
    BIND = ("--run", "r", "--epoch", "1", "--clock", "host-a")

    def emit(self, *extra, kind="run.start", data='{"coordinator": "c1"}'):
        return self.cli("emit", "--kind", kind, *self.BIND, "--source-ref", "ledger:header",
                        "--observed-at", "2026-10-20T10:00:00Z", "--data", data, *extra)

    def test_emit_appends_a_chained_0600_line_and_is_idempotent(self):
        first = self.emit("--event-id", "start-1")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)
        again = self.emit("--event-id", "start-1")
        self.assertEqual(again.stdout.strip(), "duplicate start-1")
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(self.cli("verify").returncode, 0)

    def test_emit_without_an_id_is_still_idempotent(self):
        self.assertEqual(self.emit().returncode, 0)
        self.assertTrue(self.emit().stdout.startswith("duplicate content:"))

    def test_emit_records_a_conflict_and_says_so(self):
        self.emit("--event-id", "start-1")
        proc = self.emit("--event-id", "start-1", data='{"coordinator": "c9"}')
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(len(self.log.read_text(encoding="utf-8").splitlines()), 2)

    def test_emit_refuses_a_schema_violation(self):
        for extra, data in ((("--kind",), None), ((), '{"coordinator": "c1", "note": "x"}'),
                            ((), '{"coordinator": "not an id"}')):
            with self.subTest(data=data):
                proc = self.emit(data=data) if data else self.cli("emit", *self.BIND, "--source-ref", "x")
                self.assertEqual(proc.returncode, 2, proc.stdout)
        self.assertFalse(self.log.exists())

    def test_emit_refuses_a_credential_shape_and_writes_nothing(self):
        token = "gh" + "p_" + "A" * 36
        for extra in (("--source-ref", f"https://ci.example/{token}"),
                      ("--source-ref", "https://user:" + "hunter2hunter2" + "@example.com/x")):
            with self.subTest(extra=extra[1][:20]):
                proc = self.cli("emit", "--kind", "run.start", *self.BIND, *extra,
                                "--data", '{"coordinator": "c1"}')
                self.assertEqual(proc.returncode, 2)
                self.assertNotIn(token, proc.stderr)
        self.assertFalse(self.log.exists())

    def test_report_redacts_a_credential_already_in_the_record(self):
        token = "gh" + "p_" + "B" * 36
        evs = unit_stream()
        evs[5]["source"]["ref"] = f"https://ci.example/run?{token}"
        self.write(evs)
        proc = self.cli("report", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(token, proc.stdout)
        self.assertIn("[REDACTED:github-token]", proc.stdout)

    def test_report_redacts_a_credential_in_a_key(self):
        token = "gh" + "p_" + "C" * 36
        evs = unit_stream() + [ev("model.usage", "10:41:00", dispatch="d", **ONE,
                                  data={"model": "m", "provenance": "p"})]
        evs[-1]["data"]["model"] = token  # written by hand, past emit's refusal
        self.write(evs)
        proc = self.cli("report", "--json")
        self.assertNotIn(token, proc.stdout)
        self.assertIn('"[REDACTED:github-token]": {', proc.stdout)

    def test_concurrent_emitters_keep_one_intact_chain(self):
        procs = [subprocess.Popen([sys.executable, str(EVENTS), "--log", str(self.log), "emit",
                                   "--kind", "unit.suspect", *self.BIND, "--task", f"t{i}",
                                   "--source-ref", "ledger", "--observed-at",
                                   "2026-10-20T10:00:00Z"], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE) for i in range(12)]
        self.assertEqual([p.wait() for p in procs], [0] * 12)
        for p in procs:
            p.stdout.close()
            p.stderr.close()
        recorded, _sha, _head = events.read_log(self.log)
        self.assertEqual(sorted(e["task"] for e in recorded), sorted(f"t{i}" for i in range(12)))

    def test_an_edited_event_fails_closed(self):
        self.write(scenario_clean())
        lines = self.log.read_text(encoding="utf-8").splitlines()
        lines[20] = lines[20].replace('"exit":0', '"exit":2')
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        for cmd in (("report",), ("verify",)):
            with self.subTest(cmd=cmd):
                proc = self.cli(*cmd)
                self.assertEqual(proc.returncode, 3)
                self.assertIn(":22: prev does not match", proc.stderr)

    def test_a_dropped_event_fails_closed(self):
        self.write(scenario_clean())
        lines = self.log.read_text(encoding="utf-8").splitlines()
        del lines[16]
        self.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(self.cli("report").returncode, 3)

    def test_a_rewritten_record_is_caught_only_by_an_anchor(self):
        self.write(scenario_clean())
        head = self.cli("verify").stdout.split("head ")[1].split()[0]
        evs = scenario_clean()
        evs[20]["data"]["exit"] = 2  # rewritten from scratch: the chain is internally intact
        self.write(evs)
        self.assertEqual(self.cli("verify").returncode, 0)
        self.assertEqual(self.cli("report", "--expect-head", head).returncode, 3)
        self.assertEqual(self.cli("verify", "--expect-ancestor", head).returncode, 3)

    def test_a_schema_invalid_line_fails_closed(self):
        evs = scenario_clean()[:3]
        evs[2]["kind"] = "task.teleported"
        self.write(evs)
        proc = self.cli("report")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("task.teleported", proc.stderr)

    def test_several_runs_need_run(self):
        self.write(scenario_crash())
        self.assertEqual(self.cli("report").returncode, 2)
        self.assertEqual(self.cli("report", "--run", "run-b").returncode, 1)


class TestCheckAgainstARunReport(Base):
    def report_file(self, rows):
        path = self.tmp / "run.md"
        path.write_text("RUN: mission=ship-it waves=2\n\n## WIP-curve protocol row\n\n"
                        "| Wave | WIP setting | Builder throughput | Verification latency | "
                        "Rework rate | Freshness violations |\n|---|---|---|---|---|---|\n"
                        + "".join(r + "\n" for r in rows), encoding="utf-8")
        return path

    def test_the_derived_rows_check_clean(self):
        self.write(scenario_clean())
        proc = self.cli("check", "--run-report", str(self.report_file(CLEAN_ROWS)))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_a_deliberately_altered_metric_row_is_detected(self):
        self.write(scenario_clean())
        altered = [CLEAN_ROWS[0].replace("throughput=1.14/h", "throughput=1.71/h"), CLEAN_ROWS[1]]
        proc = self.cli("check", "--run-report", str(self.report_file(altered)))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("wave 1 throughput: the report says '1.71/h', the record derives '1.14/h'",
                      proc.stderr)

    def test_a_dropped_or_invented_wave_is_detected(self):
        self.write(scenario_clean())
        invented = CLEAN_ROWS[1].replace("wave=2", "wave=3")
        proc = self.cli("check", "--run-report", str(self.report_file([CLEAN_ROWS[0], invented])))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("wave 2: the record derives a row the report does not carry", proc.stderr)
        self.assertIn("wave 3: the report carries a row for a wave the record never", proc.stderr)

    def test_empty_evidence_does_not_check_clean(self):
        # PR #638 review (P1): no wave in the record and no row in the report compared nothing,
        # and nothing compared exited 0.
        self.write(unit_stream()[:1])
        proc = self.cli("check", "--run-report", str(self.report_file([])))
        self.assertEqual(proc.returncode, 1, proc.stdout)
        self.assertIn("the record derives no WIP-curve row", proc.stderr)

    def test_a_measured_value_the_record_cannot_support_is_detected(self):
        self.write(scenario_crash())
        claimed = [CRASH_ROWS[0].replace("throughput=unavailable", "throughput=2.00/h")]
        proc = self.cli("check", "--run", "run-b", "--run-report", str(self.report_file(claimed)))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("wave 1 throughput: the record cannot derive it, yet the report claims '2.00/h'",
                      proc.stderr)


class TestIngest(Base):
    def store(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        LocalStateStore = importlib.import_module("runtime.providers.local_state").LocalStateStore
        db = self.tmp / "runtime.db"
        store = LocalStateStore(db, env={})
        ten = calendar.timegm((2026, 10, 20, 10, 0, 0))  # 2026-10-20T10:00:00Z as the DB stores it
        with store._connect() as conn:
            for disp, task, handle, state, created in (("disp_1", "task_1", "term_1", "completed", ten),
                                                       ("disp_2", "task_2", "term_2", "died", ten + 60.5)):
                conn.execute("INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, "
                             "terminal_handle, state, created_at, updated_at) VALUES "
                             "(?, ?, 'run_x', '/w', 'claude', ?, ?, ?, ?)",
                             (disp, task, handle, state, created, created + 600))
        store.send_message(subject="done", msg_type="worker_done", sender="term_1", run="run_x",
                           attrs={"headSha": sha("c4")})
        store.send_message(subject="done", msg_type="worker_done", sender="term_ghost", run="run_x")
        store.send_message(subject="other", msg_type="worker_done", sender="term_1", run="run_y")
        return db

    def ingest(self, db):
        return self.cli("ingest-state", "--db", str(db), "--run", "run_x", "--epoch", "1",
                        "--clock", "host-a")

    def test_ingest_state_reads_launches_done_and_deaths_read_only(self):
        db = self.store()
        before = {p.name: p.read_bytes() for p in self.tmp.iterdir() if p.name.startswith("runtime.db")}
        proc = self.ingest(db)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("1 worker_done message(s) name no single dispatch", proc.stderr)
        after = {p.name: p.read_bytes() for p in self.tmp.iterdir() if p.name.startswith("runtime.db")}
        self.assertEqual(before, after, "ingest must not write beside or into the DB")
        recorded, _sha, _head = events.read_log(self.log)
        kinds = sorted((e["kind"], e["dispatch"]) for e in recorded)
        self.assertEqual(kinds, [("dispatch.died", "disp_2"), ("dispatch.launched", "disp_1"),
                                 ("dispatch.launched", "disp_2"), ("task.done", "disp_1")])
        done = next(e for e in recorded if e["kind"] == "task.done")
        self.assertEqual((done["task"], done["data"]["head_sha"], done["basis"]),
                         ("task_1", sha("c4"), "occurred"))
        launch = next(e for e in recorded if e["dispatch"] == "disp_2" and e["kind"] == "dispatch.launched")
        self.assertEqual(launch["observed_at"], "2026-10-20T10:01:00.500000+00:00")
        died = next(e for e in recorded if e["kind"] == "dispatch.died")
        self.assertEqual(died["observed_at"], "2026-10-20T10:11:00.500000+00:00")

    def test_re_ingesting_the_same_db_records_nothing_new(self):
        db = self.store()
        self.ingest(db)
        size = self.log.stat().st_size
        proc = self.ingest(db)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.count("duplicate"), 4)
        self.assertEqual(self.log.stat().st_size, size)

    def test_re_ingesting_the_db_after_a_resume_is_a_duplicate_not_a_conflict(self):
        # PR #638 review (P1): the ingesting coordinator's epoch is who RECORDED a row, not what
        # the row says; a resumed coordinator re-reading the same DB must not contest it.
        db = self.store()
        bind = ("--run", "run_x", "--clock", "host-a", "--source-ref", "ledger",
                "--observed-at", "2026-10-20T09:59:00Z")
        self.cli("emit", "--kind", "run.start", "--epoch", "1", *bind,
                 "--data", '{"coordinator": "c1"}')
        self.ingest(db)
        self.cli("emit", "--kind", "coordinator.resume", "--epoch", "2", *bind,
                 "--data", '{"coordinator": "c2"}')
        proc = self.cli("ingest-state", "--db", str(db), "--run", "run_x", "--epoch", "2",
                        "--clock", "host-a")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.count("duplicate"), 4, proc.stdout)
        recorded, file_sha, head = events.read_log(self.log)
        self.assertEqual(events.derive(recorded, "run_x", file_sha, head)["record"]["conflicts"], 0)

    def test_re_ingesting_usage_later_is_a_duplicate_not_a_conflict(self):
        # PR #638 review (P1): without --observed-at the time is the ingest's own clock; a second
        # ingest of the same unchanged stream must not turn the observation into a conflict.
        path = self.tmp / "worker.jsonl"
        path.write_text(json.dumps({"type": "result", "usage": {"input_tokens": 5}}) + "\n",
                        encoding="utf-8")
        argv = ["--log", str(self.log), "ingest-usage", "--stream", str(path), "--run", "r",
                "--epoch", "1", "--clock", "host-a", "--dispatch", "d"]
        codes, out = [], io.StringIO()
        for now in ("2026-10-20T10:00:00+00:00", "2026-10-20T11:00:00+00:00"):
            with mock.patch.object(events, "_now", return_value=now), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                codes.append(events.main(argv))
        self.assertEqual(codes, [0, 0], out.getvalue())
        self.assertIn("duplicate", out.getvalue())
        self.assertEqual(len(events.read_log(self.log)[0]), 1)

    def test_a_copy_recorded_again_after_a_resume_does_not_contest_the_unit(self):
        evs = unit_stream()
        evs.insert(4, ev("coordinator.resume", "10:12:00", data={"coordinator": "c2"},
                         run="r", epoch=2, clock="host-a"))
        for event in evs[5:]:
            event["epoch"] = 2
        evs.append(dict(evs[3], epoch=2))  # the epoch-1 worker_done, re-recorded by epoch 2
        report = self.derive(evs)
        self.assertEqual((report["record"]["conflicts"], report["record"]["duplicates"]), (0, 1))
        self.assertEqual(self.metric(report, 1, "latency_max")["value"], "10.00m")

    def _transcript(self, exit_code=0, signed=False, manifest_bytes=None):
        manifest = self.tmp / "manifest.json"
        manifest.write_bytes(manifest_bytes or json.dumps({"unit": "u", "head_sha": sha("d9")}).encode())
        record = {"unit": "u", "manifest": str(manifest),
                  "manifest_sha256": events.sha256_hex(manifest.read_bytes()), "exit": exit_code,
                  "fatal": [], "notes": [], "timestamp": "2026-10-20T10:40:00+00:00"}
        path = self.tmp / "transcript.json"
        path.write_text(json.dumps({"record": record, "sig_b64": "AAAA"} if signed else record),
                        encoding="utf-8")
        return path, manifest

    def _ingest_transcript(self, path):
        return self.cli("ingest-transcript", "--transcript", str(path), "--task", "t", "--run", "r",
                        "--epoch", "1", "--clock", "host-a")

    def test_ingest_transcript_binds_the_verdict_to_the_judged_head(self):
        for signed in (False, True):
            with self.subTest(signed=signed):
                self.log.unlink(missing_ok=True)
                path, _manifest = self._transcript(signed=signed)
                proc = self._ingest_transcript(path)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                recorded, _sha, _head = events.read_log(self.log)
                event = recorded[0]
                self.assertEqual((event["kind"], event["data"]["exit"], event["data"]["head_sha"]),
                                 ("verify.verdict", 0, sha("d9")))
                self.assertEqual(event["source"]["sha256"], events.sha256_hex(path.read_bytes()))
                self.assertIn("duplicate", self._ingest_transcript(path).stdout)

    def test_a_manifest_changed_since_the_verdict_binds_no_head(self):
        path, manifest = self._transcript()
        manifest.write_text(json.dumps({"unit": "u", "head_sha": sha("ee")}), encoding="utf-8")
        proc = self._ingest_transcript(path)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("not the bytes the verdict judged", proc.stderr)
        recorded, _sha, _head = events.read_log(self.log)
        self.assertIsNone(recorded[0]["data"]["head_sha"])

    def test_a_file_that_is_no_transcript_is_a_usage_error(self):
        path = self.tmp / "nope.json"
        path.write_text('{"exit": true}', encoding="utf-8")
        self.assertEqual(self._ingest_transcript(path).returncode, 2)
        self.assertFalse(self.log.exists())


class TestStateDBNotTouched(unittest.TestCase):
    def test_a_db_that_is_not_local_state_fails_closed(self):
        tmp = Path(tempfile.mkdtemp(prefix="events-db-"))
        try:
            db = tmp / "x.db"
            sqlite3.connect(str(db)).close()
            proc = subprocess.run([sys.executable, str(EVENTS), "--log", str(tmp / "e.jsonl"),
                                   "ingest-state", "--db", str(db), "--run", "r", "--epoch", "1",
                                   "--clock", "h"], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 3, proc.stderr)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
