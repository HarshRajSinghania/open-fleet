#!/usr/bin/env python3
"""The hint-replay live arm observes and caps its spend (#605).

`scripts/hint_replay.py --live` runs real workers once the owner authorises a budget. These are
the guards that make that safe, copied from #606's runner (scripts/_ablation_run.py): an explicit
cap and per-call reservation before anything starts; a call starts only if what the cap has left
covers its reservation; every call's output is saved and its `total_cost_usd` charged (an
unmeasured call at its full reservation, a call above its reservation stops the run); an fsynced
ledger keeps a call the runner never settled (SIGKILL) charged on the next invocation; and every
call's whole process group dies on timeout, interrupt or exit, the runner's own SIGKILL included.

Safety: no test here may reach a real agent CLI. The module puts a stub `claude` (logs and exits
97) first on PATH with SHELL=/bin/sh for its whole run, the worker is an INERT stand-in that
prints the JSON `claude -p --output-format json|stream-json` prints with the cost it is told to
report, and every test checks the stub's log stayed empty. A `live` tier here is a label on a
stand-in run, never evidence.

    python3 -m unittest tests.test_hint_replay_spend -v
"""
import contextlib
import importlib.util
import io
import json
import os
import shlex
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
SCRIPT = ROOT / "scripts" / "hint_replay.py"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


replay_mod = _load("hint_replay_spend", "scripts/hint_replay.py")
SAFETY = {}
SCENARIO = "pitfall-rounding"  # one live_task scenario: three calls (off/unchecked/checked) per attempt


def setUpModule():
    bindir = Path(tempfile.mkdtemp(prefix="hint-replay-stub-claude-"))
    log = bindir / "claude.log"
    stub = bindir / "claude"
    stub.write_text(f"#!/bin/sh\necho \"claude $*\" >> '{log}'\nexit 97\n", encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    SAFETY.update(bindir=bindir, log=log, path=os.environ.get("PATH", ""), shell=os.environ.get("SHELL"))
    os.environ["PATH"] = f"{bindir}{os.pathsep}{SAFETY['path']}"
    os.environ["SHELL"] = "/bin/sh"


def tearDownModule():
    os.environ["PATH"] = SAFETY["path"]
    if SAFETY["shell"] is None:
        os.environ.pop("SHELL", None)
    else:
        os.environ["SHELL"] = SAFETY["shell"]
    shutil.rmtree(SAFETY["bindir"])


# The inert stand-in worker. It never calls a model: it records each call it answers, then prints
# what `claude -p` prints in the requested format with the cost it was told to report. `hang` and
# `orphan` leave a sleeping grandchild behind (holding no pipe) for the process-group cases.
STAND_IN = textwrap.dedent(r'''
    """Inert stand-in for the hint-replay live worker (#605): no model, no network."""
    import json, os, subprocess, sys, time
    args = sys.argv[1:]
    def opt(name, default=None):
        return args[args.index(name) + 1] if name in args else default
    mode, fmt, cost = opt("--mode", "plain"), opt("--format", "json"), float(opt("--cost", "0.25"))
    packet = sys.stdin.read()
    def alive(pid):
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True
    # Every process an EARLIER call recorded that is still alive as this call starts.
    earlier = [pid for name in sorted(os.listdir(opt("--pids")))
               for pid in json.load(open(os.path.join(opt("--pids"), name), encoding="utf-8"))]
    with open(opt("--log"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": sys.argv, "pid": os.getpid(), "cwd": os.getcwd(),
                             "packet_bytes": len(packet),
                             "alive_at_start": [pid for pid in earlier if alive(pid)]}) + "\n")
    with open(opt("--log"), encoding="utf-8") as fh:
        call = sum(1 for _ in fh)
    hang = mode == "hang" or (mode == "hang-on" and call == int(opt("--call", "1")))
    if hang or mode == "orphan":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        with open(os.path.join(opt("--pids"), "%d.pids" % os.getpid()), "w", encoding="utf-8") as fh:
            json.dump([os.getpid(), child.pid], fh)
    if mode == "escape":
        # A grandchild in a session of its own from birth (setsid): no process group holds it (K4).
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
        with open(os.path.join(opt("--pids"), "%d.pids" % os.getpid()), "w", encoding="utf-8") as fh:
            json.dump([child.pid], fh)
    model = "stand-in-not-a-model"
    init = {"type": "system", "subtype": "init", "model": model, "session_id": "s-%d" % call,
            "tools": ["Read", "Edit", "Write"]}
    if hang:
        print(json.dumps(init), flush=True)
        time.sleep(60)
    result = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 3,
              "duration_ms": 1200, "result": "stand-in: no model was called", "session_id": "s-%d" % call,
              "total_cost_usd": cost,
              "usage": {"input_tokens": len(packet) // 4, "output_tokens": 40,
                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
              "modelUsage": {model: {"inputTokens": len(packet) // 4, "outputTokens": 40, "costUSD": cost}}}
    if fmt == "json":
        print(json.dumps(result))
    elif fmt == "stream-json":
        print(json.dumps(init))
        print(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
            {"type": "text", "text": "stand-in narration: no model was called"}]}}))
        print(json.dumps(result))
    else:
        print("stand-in: no model was called")
''')


def pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True


class StandInRun(unittest.TestCase):
    """A temp dir per test: the stand-in, its call log, its recorded process trees, the results."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="hint-replay-spend-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.script = self.tmp / "stand_in.py"
        self.script.write_text(STAND_IN, encoding="utf-8")
        self.log = self.tmp / "stand-in.log"
        self.pids = self.tmp / "pids"
        self.pids.mkdir()
        self.out = self.tmp / "run" / "results.json"
        self.out.parent.mkdir()
        self.addCleanup(self.reap)

    def tearDown(self):
        log = SAFETY["log"]
        self.assertFalse(log.exists() and log.read_text().strip(),
                         f"a test reached the `claude` on PATH: {log.read_text() if log.exists() else ''}")

    def reap(self):
        """Never leak a sleeper, even when the code under test does (the RED runs)."""
        for pid in self.recorded_pids():
            if pid_alive(pid):
                os.kill(pid, signal.SIGKILL)

    def recorded_pids(self):
        return [pid for f in sorted(self.pids.glob("*.pids")) for pid in json.loads(f.read_text())]

    def assertAllDead(self, at_least):
        pids = self.recorded_pids()
        self.assertGreaterEqual(len(pids), at_least, "the stand-in did not record its process tree")
        deadline = time.monotonic() + 8
        while any(pid_alive(p) for p in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual([p for p in pids if pid_alive(p)], [], "a process outlived its call")

    def agent(self, mode="plain", fmt="json", cost=0.25, *extra):
        return shlex.join([sys.executable, str(self.script), "--mode", mode, "--format", fmt,
                           "--cost", str(cost), "--log", str(self.log), "--pids", str(self.pids), *extra])

    def live(self, *, cap="40", per_call="2", agent=None, attempts="1", extra=()):
        argv = ["--live", "--tier", "live", "--model", "stand-in-not-a-model",
                "--agent-cmd", agent or self.agent(), "--scenario", SCENARIO, "--attempts", attempts,
                "--max-runs", "18", "--out", str(self.out)]
        if cap is not None:
            argv += ["--budget-usd", cap]
        if per_call is not None:
            argv += ["--per-call-usd", per_call]
        return argv + list(extra)

    def stub(self, agent, *extra):
        return ["--live", "--tier", "stub", "--agent-cmd", agent, "--scenario", SCENARIO,
                "--attempts", "1", "--max-runs", "3", "--out", str(self.out), *extra]

    def main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = replay_mod.main(argv)
        return code, out.getvalue(), err.getvalue()

    def spawn(self, argv):
        """The runner as its own process, for the signals a test process cannot take in-process."""
        env = {**os.environ, "SHELL": "/bin/sh"}
        proc = subprocess.Popen([sys.executable, str(SCRIPT), *argv], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        return proc

    def wait_for(self, predicate, what, timeout=60):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(predicate(), f"timed out waiting for {what}")

    def calls(self):
        if not self.log.is_file():
            return []
        return [json.loads(ln) for ln in self.log.read_text().splitlines() if ln.strip()]

    def results(self):
        return json.loads(self.out.read_text())

    def ledger(self):
        path = self.out.parent / "results.spend.jsonl"
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]


class ALiveRunNeedsAnExplicitCapAndPerCallLimit(StandInRun):
    """Refused before anything is written or any worker starts: exit 2, no call, no results."""

    def refused(self, argv, needle):
        code, _out, err = self.main(argv)
        self.assertEqual(code, 2, err)
        self.assertIn(needle, err)
        self.assertEqual(self.calls(), [], "a refused run started a worker")
        self.assertEqual(list(self.out.parent.iterdir()), [], "a refused run wrote beside its results")

    def test_no_per_call_reservation_no_run(self):
        self.refused(self.live(per_call=None), "per-call reservation")

    def test_a_cap_must_be_explicit_finite_and_positive(self):
        for cap in (None, "0", "-1", "nan", "inf"):
            with self.subTest(cap=cap):
                self.refused(self.live(cap=cap, per_call=None), "positive --budget-usd")

    def test_a_reservation_the_cap_cannot_cover_is_refused(self):
        for per_call in ("0", "nan", "41"):
            with self.subTest(per_call=per_call):
                self.refused(self.live(per_call=per_call), "--per-call-usd")

    def test_no_per_call_limit_flag_no_run(self):
        self.refused(self.live(extra=["--agent-limit-flag="]), "per-call limit")

    def test_a_live_run_keeps_its_ledger_beside_an_explicit_out(self):
        argv = self.live()
        i = argv.index("--out")
        self.refused(argv[:i] + argv[i + 2:], "--out")


class ACallStartsOnlyIfItsReservationFits(StandInRun):
    """PRE-EMPTIVE: spend so far plus the next call's whole reservation must fit in the cap."""

    def test_the_run_stops_before_the_call_it_cannot_cover(self):
        # USD 1.50 measured per call, USD 2 reserved: 1.5, 3.0, 4.5 spent; the fourth call would
        # need 4.5 + 2 > 5, so it never starts.
        code, _out, err = self.main(self.live(cap="5", attempts="2", agent=self.agent(cost=1.5)))
        self.assertEqual(code, 1, err)
        results = self.results()
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(len(results["results"]), 3)
        self.assertTrue(results["stopped"].startswith("CAP_REACHED"), results["stopped"])
        self.assertFalse(results["complete"])
        self.assertEqual(results["cost"]["spent_usd"], 4.5)
        self.assertLessEqual(results["cost"]["spent_usd"], results["cost"]["cap_usd"])

    def test_an_exact_fit_runs_and_lands_on_the_cap(self):
        code, _out, err = self.main(self.live(cap="6", agent=self.agent(cost=2.0)))
        self.assertEqual(code, 0, err)
        results = self.results()
        self.assertTrue(results["complete"])
        self.assertIsNone(results["stopped"])
        self.assertEqual(results["cost"]["spent_usd"], 6.0)


class EveryCallIsObservedAndCharged(StandInRun):
    """Each call's whole output is kept beside the results and its total_cost_usd charged."""

    def test_json_cost_is_read_charged_and_recorded_per_call(self):
        code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        self.assertEqual(code, 0, err)
        results = self.results()
        cost = results["cost"]
        self.assertEqual((cost["cap_usd"], cost["reserve_per_call_usd"]), (40.0, 2.0))
        self.assertEqual((cost["spent_usd"], cost["prior_spent_usd"], cost["counted_against_cap_usd"]),
                         (0.75, 0.0, 0.75))
        rows = results["results"]
        self.assertEqual([r["call"] for r in rows], cost["measured_calls"])
        self.assertEqual(cost["unmeasured_calls"], [])
        for row in rows:
            self.assertEqual((row["cost_usd"], row["measured"], row["charged_usd"]), (0.25, True, 0.25))
            self.assertEqual(row["models"], ["stand-in-not-a-model"])

    def test_stream_json_cost_is_read_and_charged(self):
        code, _out, err = self.main(self.live(agent=self.agent(fmt="stream-json", cost=0.5)))
        self.assertEqual(code, 0, err)
        results = self.results()
        self.assertEqual([r["charged_usd"] for r in results["results"]], [0.5, 0.5, 0.5])
        self.assertEqual(results["cost"]["spent_usd"], 1.5)
        self.assertEqual(len(results["cost"]["measured_calls"]), 3)

    def test_each_call_output_is_saved_beside_the_results(self):
        code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        self.assertEqual(code, 0, err)
        here = self.out.parent
        for row in self.results()["results"]:
            stdout = here / row["output"]["stdout"]
            self.assertTrue(stdout.resolve().is_relative_to((here / "results.calls").resolve()), stdout)
            self.assertEqual(json.loads(stdout.read_text())["total_cost_usd"], 0.25)
            self.assertTrue((here / row["output"]["stderr"]).is_file())
            self.assertIn("to_cents", (here / row["output"]["packet"]).read_text())
            self.assertTrue((here / row["output"]["oracle"]).is_file())

    def test_an_unmeasured_call_is_charged_its_full_reservation_and_stops_the_run(self):
        code, _out, err = self.main(self.live(agent=self.agent(fmt="text")))
        self.assertEqual(code, 1, err)
        results = self.results()
        self.assertEqual(len(results["results"]), 1)
        row = results["results"][0]
        self.assertEqual((row["cost_usd"], row["measured"], row["charged_usd"]), (None, False, 2.0))
        self.assertEqual(results["cost"]["unmeasured_calls"], [row["call"]])
        self.assertEqual(results["cost"]["spent_usd"], 2.0)
        self.assertTrue(results["stopped"].startswith("USAGE_UNAVAILABLE"), results["stopped"])

    def test_a_measured_call_above_its_reservation_stops_the_run(self):
        code, _out, err = self.main(self.live(agent=self.agent(cost=2.5)))
        self.assertEqual(code, 1, err)
        results = self.results()
        self.assertEqual(len(self.calls()), 1)
        self.assertEqual(results["results"][0]["charged_usd"], 2.5, "charged what it cost, not its reservation")
        self.assertTrue(results["stopped"].startswith("LIMIT_BREACHED"), results["stopped"])

    def test_every_call_is_handed_its_own_limit(self):
        code, _out, err = self.main(self.live(per_call="2"))
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.calls()), 3)
        for call in self.calls():
            self.assertEqual(call["argv"][-2:], ["--max-budget-usd", "1.60"])
        self.assertEqual(self.results()["cost"]["limit_usd"], 1.6)

    def test_a_killed_call_is_charged_its_full_reservation(self):
        code, _out, err = self.main(self.live(cap="2", agent=self.agent("hang"), extra=["--timeout-s", "2"]))
        self.assertEqual(code, 1, err)
        results = self.results()
        row = results["results"][0]
        self.assertEqual((row["agent_exit"], row["agent_killed"], row["charged_usd"]), ("timeout", True, 2.0))
        self.assertTrue(results["stopped"].startswith("CAP_REACHED"), results["stopped"])
        self.assertAllDead(at_least=2)


class TheLedgerSurvivesTheRunner(StandInRun):
    """A call the runner never settled (it was SIGKILLed mid-call) stays charged at its full
    reservation on the next invocation into the same --out, and nothing is counted twice."""

    def test_a_sigkilled_call_stays_charged_and_nothing_is_double_counted(self):
        first = self.spawn(self.live(agent=self.agent("hang-on", "json", 0.5, "--call", "2"),
                                     extra=["--timeout-s", "60"]))
        self.wait_for(lambda: len(self.recorded_pids()) == 2, "the second call to start hanging")
        first.send_signal(signal.SIGKILL)
        first.communicate(timeout=30)
        self.assertAllDead(at_least=2)  # the runner's death took its call's process group with it
        ledger = self.ledger()
        self.assertEqual([(r["event"], r.get("charged_usd", r.get("reserve_usd"))) for r in ledger],
                         [("start", 2.0), ("settle", 0.5), ("start", 2.0)])
        self.assertFalse(self.out.exists(), "a SIGKILLed runner wrote no results")
        calls_before = len(self.calls())

        # 0.5 settled + 2.0 never settled = 2.5 already spent: a USD 4.4 cap cannot cover a USD 2 call.
        code, _out, err = self.main(self.live(cap="4.4", agent=self.agent(cost=0.5)))
        self.assertEqual(code, 1, err)
        results = self.results()
        self.assertEqual(len(self.calls()), calls_before, "a call started that the cap could not cover")
        self.assertTrue(results["stopped"].startswith("CAP_REACHED"), results["stopped"])
        self.assertEqual((results["cost"]["prior_spent_usd"], results["cost"]["spent_usd"]), (2.5, 0.0))

        code, _out, err = self.main(self.live(cap="40", agent=self.agent(cost=0.5)))
        self.assertEqual(code, 0, err)
        cost = self.results()["cost"]
        self.assertEqual((cost["prior_spent_usd"], cost["spent_usd"], cost["counted_against_cap_usd"]),
                         (2.5, 1.5, 4.0))

    def test_an_interrupted_runner_records_its_open_call_at_its_reservation(self):
        proc = self.spawn(self.live(agent=self.agent("hang"), extra=["--timeout-s", "60"]))
        self.wait_for(lambda: len(self.recorded_pids()) == 2, "the first call to start hanging")
        proc.send_signal(signal.SIGTERM)
        _out, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 128 + signal.SIGTERM, err[-2000:])
        self.assertAllDead(at_least=2)
        results = self.results()
        self.assertTrue(results["stopped"].startswith("INTERRUPTED"), results["stopped"])
        self.assertEqual(results["cost"]["spent_usd"], 2.0)
        row = results["results"][0]
        self.assertTrue(row["interrupted"])
        self.assertEqual((row["charged_usd"], row["open_calls"]), (2.0, ["agent"]))
        self.assertEqual([r["event"] for r in self.ledger()], ["start"])


class NoProcessOutlivesItsCall(StandInRun):
    """Every call leads its own process group, killed whole on timeout, after its leader exits,
    on SIGTERM/SIGHUP/Ctrl-C, and when the runner itself is SIGKILLed. Stub tier: no spend."""

    def test_a_timeout_kills_the_agent_and_its_grandchild(self):
        code, _out, err = self.main(self.stub(self.agent("hang-on", "json", 0, "--call", "1"),
                                              "--timeout-s", "2"))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.results()["results"][0]["agent_exit"], "timeout")
        self.assertEqual([c["alive_at_start"] for c in self.calls()], [[], [], []],
                         "a call started while an earlier call's process lived")
        self.assertAllDead(at_least=2)

    def test_what_a_finished_agent_leaves_behind_is_killed(self):
        code, _out, err = self.main(self.stub(self.agent("orphan", "json", 0)))
        self.assertEqual(code, 0, err)
        self.assertEqual([c["alive_at_start"] for c in self.calls()], [[], [], []],
                         "a call started while an earlier call's grandchild lived")
        self.assertAllDead(at_least=6)

    def test_a_signalled_runner_kills_the_call_in_flight_first(self):
        for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
            with self.subTest(signal=sig.name):
                for f in self.pids.glob("*.pids"):
                    f.unlink()
                proc = self.spawn(self.stub(self.agent("hang", "json", 0), "--timeout-s", "60"))
                self.wait_for(lambda: len(self.recorded_pids()) == 2, "the call to start hanging")
                proc.send_signal(sig)
                _out, err = proc.communicate(timeout=60)
                self.assertEqual(proc.returncode, 128 + sig, err[-2000:])
                self.assertAllDead(at_least=2)

    def test_a_sigkilled_runner_takes_its_call_with_it(self):
        proc = self.spawn(self.stub(self.agent("hang", "json", 0), "--timeout-s", "60"))
        self.wait_for(lambda: len(self.recorded_pids()) == 2, "the call to start hanging")
        proc.send_signal(signal.SIGKILL)
        proc.communicate(timeout=30)
        self.assertAllDead(at_least=2)


class EveryCallGetsAPositiveLimitWithinItsReservation(StandInRun):
    """#657 review K1: `round(r * 0.8, 2)` was 0.00 for a sub-cent reservation, and the flag was then
    dropped, so the worker ran with no limit at all; below USD 0.025 the rounding could also land
    ABOVE the reservation. The limit is floored to the cent, must be positive, and is always passed."""

    def test_a_reservation_whose_limit_is_not_positive_and_within_it_is_refused(self):
        for per_call in ("0.001", "0.007", "0.012"):
            with self.subTest(per_call=per_call):
                code, _out, err = self.main(self.live(cap="0.05", per_call=per_call))
                self.assertEqual(code, 2, err)
                self.assertIn("per-call limit", err)
                self.assertEqual(self.calls(), [], "a worker started without a positive limit")
                self.assertEqual(list(self.out.parent.iterdir()), [])

    def test_the_smallest_reservation_with_a_cent_of_limit_hands_it_to_every_call(self):
        code, _out, err = self.main(self.live(cap="0.05", per_call="0.0125", agent=self.agent(cost=0.01)))
        self.assertEqual(code, 0, err)
        self.assertEqual([c["argv"][-2:] for c in self.calls()], [["--max-budget-usd", "0.01"]] * 3)

    def test_the_library_entry_refuses_it_too(self):
        with self.assertRaises(replay_mod.CorpusError):
            replay_mod.live_replay(replay_mod.DEFAULT_CORPUS, shlex.split(self.agent()), "live", 1, 3,
                                   model="stand-in-not-a-model", budget_usd=1.0, only={SCENARIO},
                                   per_call_usd=0.001, out=str(self.out))
        self.assertEqual(self.calls(), [], "a worker started without a positive limit")


class OneRunAtATimeSpendsFromALedger(StandInRun):
    """#657 review K2: the ledger was read once, so two invocations sharing --out each counted only
    their own spend and both admitted calls against the same cap. The ledger is now held for the
    whole invocation: a concurrent run into the same --out is refused before it reserves anything."""

    def test_a_concurrent_run_into_the_same_out_is_refused(self):
        first = self.spawn(self.live(agent=self.agent("hang"), extra=["--timeout-s", "60"]))
        self.wait_for(lambda: len(self.recorded_pids()) == 2, "the first run's call to start hanging")
        code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        self.assertEqual(code, 2, err)
        self.assertIn("held by another run", err)
        self.assertEqual(len(self.calls()), 1, "a second run started a call against the same cap")
        first.send_signal(signal.SIGTERM)
        first.communicate(timeout=60)
        # Once the first run is gone its hold goes with it, and its open call stays charged.
        code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        self.assertEqual(code, 0, err)
        self.assertEqual(self.results()["cost"]["prior_spent_usd"], 2.0)


class TheWatchdogCleansUpBeforeItLetsGo(StandInRun):
    """#657 review K3: the watchdog exited as soon as its worker did, and only the runner then
    killed what the worker left in its group. A runner SIGKILLed in between left that grandchild
    with no supervisor. The watchdog now kills it before it exits."""

    def test_with_the_runner_gone_at_once_a_finished_worker_leaves_nothing_behind(self):
        # The runner's own teardown never runs, as if it were SIGKILLed the instant the call's
        # leader exited: only the watchdog stands between the orphan and the next call.
        with mock.patch.object(replay_mod.spend, "kill_group", return_value=True), \
                mock.patch.object(replay_mod.spend, "sweep", return_value=True, create=True):
            code, _out, err = self.main(self.stub(self.agent("orphan", "json", 0)))
        self.assertEqual(code, 0, err)
        self.assertEqual([c["alive_at_start"] for c in self.calls()], [[], [], []],
                         "a call started while an earlier call's grandchild lived")
        self.assertAllDead(at_least=6)


class ACallIsContainedAcrossSessions(StandInRun):
    """#657 review K4: cleanup killed the call's process GROUP, so a worker descendant that called
    setsid() left it, kept running (and spending), and the call still reported itself empty. Every
    call now carries a unique OF_CALL_ID marker in its environment; teardown kills every process
    carrying it and re-scans until none is left, and a call is never settled while anything of it
    survives or the process table cannot be read."""

    def test_a_grandchild_that_leaves_the_session_is_still_swept(self):
        code, _out, err = self.main(self.stub(self.agent("escape", "json", 0)))
        self.assertEqual(code, 0, err)
        self.assertEqual([c["alive_at_start"] for c in self.calls()], [[], [], []],
                         "a call started while an escaped grandchild lived")
        self.assertAllDead(at_least=3)

    def assertKeptOpen(self, code, err):
        self.assertEqual(code, 1, err)
        results = self.results()
        self.assertEqual(len(self.calls()), 1, "a call started while a process of the last one lived")
        self.assertTrue(results["stopped"].startswith("ORPHAN_ALIVE"), results["stopped"])
        self.assertEqual([r["event"] for r in self.ledger()], ["start"],
                         "a call was settled while a process of it lived")
        self.assertEqual(results["results"][0]["charged_usd"], 2.0)

    def test_a_survivor_keeps_its_call_open_and_stops_the_run(self):
        with mock.patch.object(replay_mod.spend, "sweep", return_value=False, create=True):
            code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        self.assertKeptOpen(code, err)

    def test_a_process_table_it_cannot_read_is_a_survivor(self):
        with mock.patch.object(replay_mod.spend, "process_table", side_effect=OSError("no ps"), create=True):
            code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        self.assertKeptOpen(code, err)


class ArtifactsStayBesideTheResults(StandInRun):
    """#657 review K5: a live call's artifact directory was `<stem>.calls/<run>/<scenario id>.<arm>.a<k>`
    with the id checked only for presence, so an id like `/tmp/escape` or `../escape` sent the packet
    and the worker's output outside `<stem>.calls/`. An id must be one safe filename, and every
    call's directory must resolve directly under the run's calls directory, before anything is
    written."""

    def corpus_with_id(self, scenario_id):
        corpus = json.loads((ROOT / "tests" / "fixtures" / "hint-replay.json").read_text())
        scenario = dict(next(s for s in corpus["scenarios"] if s["id"] == SCENARIO), id=scenario_id)
        return {**corpus, "scenarios": [scenario]}

    def stub_on(self, corpus_path):
        return ["--live", "--tier", "stub", "--agent-cmd", self.agent("plain", "json", 0), "--corpus",
                str(corpus_path), "--attempts", "1", "--max-runs", "3", "--out", str(self.out)]

    def assertNothingWritten(self):
        self.assertEqual(self.calls(), [], "a worker started")
        self.assertEqual(list(self.out.parent.iterdir()), [], "a refused run wrote beside its results")
        self.assertEqual(sorted(p.name for p in self.tmp.rglob("*escape*")), [], "a write landed outside")

    def test_a_scenario_id_that_is_not_one_safe_filename_is_refused(self):
        for scenario_id in (str(self.tmp / "escape"), "../escape", "a/b-escape", "..", ".escape"):
            with self.subTest(id=scenario_id):
                corpus = self.tmp / "corpus.json"
                corpus.write_text(json.dumps(self.corpus_with_id(scenario_id)), encoding="utf-8")
                code, _out, err = self.main(self.stub_on(corpus))
                self.assertEqual(code, 2, err)
                self.assertIn("scenario id", err)
                self.assertNothingWritten()

    def test_a_call_directory_outside_the_run_is_refused_even_past_the_corpus_check(self):
        corpus = self.corpus_with_id(str(self.tmp / "escape"))
        with mock.patch.object(replay_mod, "load_corpus", return_value=(corpus, "0" * 64)):
            code, _out, err = self.main(self.stub_on(self.tmp / "unused.json"))
        self.assertEqual(code, 2, err)
        self.assertIn("outside", err)
        self.assertNothingWritten()


class TheCallLifecycleIsPortable(StandInRun):
    """#657 review W2 (Greptile): os.waitid is missing on macOS before Python 3.13, and every live
    call waited with it, so hint replay aborted on its first call there."""

    def test_a_run_needs_no_waitid(self):
        saved = os.__dict__.pop("waitid", None)
        try:
            code, _out, err = self.main(self.live(agent=self.agent(cost=0.25)))
        finally:
            if saved is not None:
                os.waitid = saved
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(self.results()["cost"]["spent_usd"], 0.75)


if __name__ == "__main__":
    unittest.main()
