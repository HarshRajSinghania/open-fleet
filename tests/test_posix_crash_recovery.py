#!/usr/bin/env python3
"""Crash-injection tests for the POSIX worker launch (#597; spec: docs/runtimes.md).

A REAL coordinator subprocess runs `worker_start` and parks at one committed launch boundary
(`LAUNCH_BOUNDARIES`, through the provider's `on_launch_boundary` observer); this test SIGKILLs
it there, so no `finally`, no rollback and no receipt of the coordinator ever runs. The test
process then plays the restarted coordinator. Workers are INERT: a fake `claude` in the test's
temp dir that logs its identity (and, where a test asks, commits) and sleeps. Every other
harness name resolves to a tripwire that records a hit, so no real agent can start.

Backend: `setsid` (real processes). tmux and cmux are NOT exercised here (docs/runtimes.md says
so); the Docker `danger` path runs against a fake `docker` CLI, the fixture tier, never a daemon.
"""
from __future__ import annotations

import importlib
import json
import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHILD = r'''
import json, os, sys
sys.path.insert(0, sys.argv[1])
from runtime.providers import get_provider

args = json.loads(sys.argv[2])
prov = get_provider("posix", env=dict(os.environ))
park_at = args.get("park_at")


def hook(stage, info):
    print(json.dumps({"boundary": stage, "info": info, "pid": os.getpid()}), flush=True)
    if stage == park_at:
        # Parked right after the boundary committed: the test SIGKILLs this process here
        # (or, in the takeover tests, lets it go on by writing a line).
        sys.stdin.readline()


prov.on_launch_boundary = hook
try:
    res = prov.worker_start(**args["start"])
    print(json.dumps({"result": res}), flush=True)
except Exception as exc:
    print(json.dumps({"error": getattr(exc, "code", type(exc).__name__), "message": str(exc)}), flush=True)
    sys.exit(3)
'''


def _git(*args, cwd, env=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=check, capture_output=True, text=True)


def _wait_for(pred, timeout=20.0, step=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


def _alive(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    proc = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return proc.returncode == 0 and not proc.stdout.strip().startswith("Z")


class Coordinator:
    """A coordinator subprocess and the boundary lines it printed."""

    def __init__(self, proc):
        self.proc = proc
        self.lines: queue.Queue = queue.Queue()
        self.seen: list[str] = []
        self.info: dict = {}
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(json.loads(line))
        self.lines.put(None)

    def until(self, boundary, timeout=60.0):
        deadline = time.time() + timeout
        while True:
            msg = self.lines.get(timeout=max(0.1, deadline - time.time()))
            if msg is None:
                raise AssertionError(f"coordinator ended before {boundary!r}; saw {self.seen}")
            if "boundary" in msg:
                self.seen.append(msg["boundary"])
                self.info = msg["info"]
                if msg["boundary"] == boundary:
                    return msg
            elif boundary is None:
                return msg

    def close(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=30)
        self.pump.join(timeout=10)
        for pipe in (self.proc.stdin, self.proc.stdout):
            if pipe is not None:
                pipe.close()

    def finish(self, timeout=60.0):
        """Every remaining line, through the final result/error line."""
        out = []
        deadline = time.time() + timeout
        while True:
            msg = self.lines.get(timeout=max(0.1, deadline - time.time()))
            if msg is None:
                break
            if "boundary" in msg:
                self.seen.append(msg["boundary"])
                self.info = msg["info"]
            out.append(msg)
        self.proc.wait(timeout=timeout)
        return out


class CrashRecoveryBase(unittest.TestCase):
    def setUp(self):
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        self.providers = importlib.import_module("runtime.providers")
        self.posix = importlib.import_module("runtime.providers.posix")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.base = base
        self.repo = base / "repo"
        self.repo.mkdir()
        _git("init", "-q", "-b", "main", cwd=self.repo)
        _git("config", "user.email", "t@example.com", cwd=self.repo)
        _git("config", "user.name", "T", cwd=self.repo)
        (self.repo / "README.md").write_text("# r\n", encoding="utf-8")
        _git("add", "README.md", cwd=self.repo)
        _git("commit", "-qm", "init", cwd=self.repo)
        self.bin = base / "bin"
        self.bin.mkdir()
        self.tripwire = base / "tripwire"
        self.tripwire.mkdir()
        self.tripwire_log = base / "tripwire.log"
        for harness in self.providers.SUPPORTED_HARNESSES:
            trip = self.tripwire / harness
            trip.write_text(f'#!/bin/sh\necho "{harness} $*" >> "{self.tripwire_log}"\nexit 97\n', encoding="utf-8")
            trip.chmod(0o755)
        self.agent_log = base / "agent.log"
        self.child = base / "coordinator.py"
        self.child.write_text(CHILD, encoding="utf-8")
        self.env = {
            **os.environ,
            "OPEN_FLEET_STATE_DB": str(base / "state" / "runtime.db"),
            "OPEN_FLEET_CLI_CWD": str(self.repo),
            "OPEN_FLEET_POSIX_BACKEND": "setsid",
            "PATH": os.pathsep.join([str(self.bin), str(self.tripwire), os.environ.get("PATH", "")]),
            "SHELL": "/bin/sh",
        }
        self.env.pop("PYTHON", None)
        self.coordinators: list[Coordinator] = []
        self.addCleanup(self._no_tripwire_hit)
        self.addCleanup(self._kill_all)
        self.agent("sleeper")
        self.task = self.restart().task_create(spec="inert work")["task"]["id"]

    # --- fixtures ---
    def agent(self, kind):
        """The fake `claude`: logs `<dispatch> <run> <pid>` once, then behaves per `kind`."""
        tail = {
            "sleeper": "exec sleep 30",
            "committer": (
                'echo work > work.txt && git add work.txt && '
                'git -c user.email=w@x -c user.name=w commit -qm worker-commit && '
                f'echo committed >> "{self.agent_log}.commit"\nexec sleep 30'
            ),
            "quick_exit": "exit 0",
        }[kind]
        path = self.bin / "claude"
        path.write_text(
            f'#!/bin/sh\necho "$OPEN_FLEET_DISPATCH_ID $OPEN_FLEET_RUN_ID $$" >> "{self.agent_log}"\n{tail}\n',
            encoding="utf-8",
        )
        path.chmod(0o755)

    def restart(self):
        """A fresh coordinator in THIS process (the crashed one was another process)."""
        return self.providers.get_provider("posix", env=self.env)

    def start_kwargs(self, **over):
        kw = {"task_id": self.task, "worktree": "new-child", "agent": "claude", "profile": "rw", "run": "run-r04"}
        kw.update(over)
        return kw

    def coordinator(self, park_at, env=None, **start):
        proc = subprocess.Popen(
            [sys.executable, "-I", str(self.child), str(ROOT), json.dumps({"park_at": park_at, "start": self.start_kwargs(**start)})],
            env=env or self.env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        c = Coordinator(proc)
        self.coordinators.append(c)
        return c

    def crash_at(self, boundary, env=None, **start):
        """SIGKILL a real coordinator right after `boundary` committed; return its identity."""
        c = self.coordinator(boundary, env=env, **start)
        msg = c.until(boundary)
        os.kill(c.proc.pid, signal.SIGKILL)
        c.proc.wait(timeout=30)
        self.assertEqual(c.proc.returncode, -signal.SIGKILL)
        order = list(self.posix.LAUNCH_BOUNDARIES)
        self.assertEqual(c.seen, order[: order.index(boundary) + 1], "boundaries must be crossed in their committed order")
        return {**msg["info"], "coordinatorPid": msg["pid"]}

    def agent_lines(self):
        return self.agent_log.read_text().splitlines() if self.agent_log.exists() else []

    def assert_no_worker_ran(self, settle=1.5):
        time.sleep(settle)
        self.assertEqual(self.agent_lines(), [], "no worker may run for a launch that recovery rolled back")

    def dispatch(self, prov, dispatch_id):
        with prov.state._connect() as conn:
            row = conn.execute("SELECT * FROM dispatches WHERE dispatch_id = ?", (dispatch_id,)).fetchone()
        return dict(row) if row else None

    def task_status(self, prov):
        return {t["id"]: t["status"] for t in prov.task_list()["tasks"]}[self.task]

    def dispatches_for_task(self, prov):
        with prov.state._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM dispatches WHERE task_id = ?", (self.task,)).fetchall()]

    # --- cleanup ---
    def _no_tripwire_hit(self):
        hits = self.tripwire_log.read_text() if self.tripwire_log.exists() else ""
        self.assertEqual(hits, "", f"an agent resolved past the fake bin to the tripwire: {hits!r}")

    def _ours(self, pid):
        """Only a process whose command line lies in THIS test's temp dir is ever signalled."""
        proc = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
        return proc.returncode == 0 and str(self.base) in proc.stdout

    def _kill_all(self):
        for c in self.coordinators:
            c.close()
        pids = set()
        db = self.base / "state" / "runtime.db"
        if db.exists():
            with self.restart().state._connect() as conn:
                for r in conn.execute("SELECT pid, monitor_pid FROM dispatches WHERE lane_dir IS NOT NULL").fetchall():
                    pids.update(int(x) for x in (r["pid"], r["monitor_pid"]) if x and int(x) > 0)
        # A monitor is its own session leader: its group holds the worker (and a fake sandbox).
        mine = [pid for pid in pids if self._ours(pid)]
        for pid in mine:
            try:
                os.killpg(pid, signal.SIGKILL)
            except OSError:
                continue
        for pid in mine:
            _wait_for(lambda pid=pid: not _alive(pid), timeout=10)


class TestCrashMatrixSetsid(CrashRecoveryBase):
    """One SIGKILL per committed boundary, in the order a launch crosses them."""

    def test_kill_after_intent_claimed_rolls_back_and_replays_the_failure(self):
        info = self.crash_at("intent_claimed", retry_request="req-1")
        prov = self.restart()
        shown = prov.request_show("req-1")
        self.assertEqual(shown["state"], "pending", "the request is recorded before any side effect")
        self.assertEqual(shown["intent"]["id"], info["intentId"])
        self.assertEqual(shown["intent"]["phase"], "claimed")
        self.assertEqual(self.task_status(prov), "dispatched")
        rec = prov.launch_reconcile()["reconciled"]
        self.assertEqual(len(rec), 1)
        r = rec[0]
        self.assertEqual(r["resolution"], "failed")
        self.assertEqual(r["error"]["code"], "launch_interrupted")
        self.assertEqual(r["dispatchId"], info["dispatchId"], "recovery never mints a new identity")
        self.assertEqual(r["owner"]["previous"]["pid"], info["coordinatorPid"])
        self.assertIs(r["owner"]["previous"]["alive"], False)
        self.assertEqual(r["task"], {"id": self.task, "before": "dispatched", "after": "ready"})
        self.assertIs(r["completionInferred"], False)
        self.assertEqual(prov.request_show("req-1")["state"], "failed")
        with self.assertRaises(self.providers.ProviderError) as ctx:
            prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        self.assertEqual(ctx.exception.code, "launch_interrupted", "a retry replays the recorded failure")
        self.assertTrue(ctx.exception.data["replayed"])
        self.assertEqual(prov.launch_reconcile()["count"], 0)
        self.assert_no_worker_ran()

    def test_kill_after_worktree_created_keeps_and_pins_the_worktree(self):
        info = self.crash_at("worktree_created", retry_request="req-1")
        wt = Path(info["worktree"])
        self.assertTrue((wt / ".git").is_file(), "the worktree exists when the coordinator dies")
        prov = self.restart()
        r = prov.launch_reconcile(request="req-1")["reconciled"][0]
        self.assertEqual(r["resolution"], "failed")
        self.assertEqual(r["task"]["after"], "ready")
        kept = [c for c in r["cleanup"] if c["kind"] == "worktree"]
        self.assertEqual(kept, [{"kind": "worktree", "target": str(wt), "action": "kept", "why": "recovery never deletes a worktree or a branch"}])
        self.assertTrue(wt.is_dir())
        head = _git("rev-parse", "HEAD", cwd=wt).stdout.strip()
        self.assertEqual(r["preservedRefs"][0]["ref"], f"refs/open-fleet/preserved/{info['dispatchId']}")
        self.assertEqual(r["preservedRefs"][0]["sha"], head)
        self.assertEqual(_git("rev-parse", r["preservedRefs"][0]["ref"], cwd=self.repo).stdout.strip(), head)
        self.assert_no_worker_ran()
        # The task really is startable again: a NEW request reuses the kept worktree, one worker.
        res = prov.worker_start(**self.start_kwargs(retry_request="req-2"))
        self.assertEqual(res["worker"]["worktree"], str(wt))
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))

    def test_kill_after_registered_abandons_the_unlaunched_dispatch(self):
        info = self.crash_at("registered", retry_request="req-1")
        prov = self.restart()
        before = self.dispatch(prov, info["dispatchId"])
        self.assertEqual((before["state"], before["pid"]), ("ready", 0))
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual(r["resolution"], "failed")
        self.assertEqual(r["dispatch"], {"id": info["dispatchId"], "before": "ready", "after": "abandoned"})
        self.assertIn({"kind": "dispatch", "target": info["dispatchId"], "action": "abandoned",
                       "why": "kept for its identity; a late monitor is refused at the launch gate"}, r["cleanup"])
        monitor = [p for p in r["processes"] if p["role"] == "monitor"]
        self.assertEqual(monitor[0]["action"], "refused_at_gate")
        self.assertEqual(r["task"]["after"], "ready")
        self.assertEqual(prov.request_show("req-1")["state"], "failed")
        self.assert_no_worker_ran()

    def test_kill_after_monitor_spawned_adopts_the_live_worker(self):
        self.agent("committer")
        info = self.crash_at("monitor_spawned", retry_request="req-1")
        disp = info["dispatchId"]
        self.assertTrue(_wait_for(lambda: Path(f"{self.agent_log}.commit").exists()), "the inert worker never committed")
        prov = self.restart()
        row = self.dispatch(prov, disp)
        self.assertEqual(row["pid"], 0, "the dead coordinator never published a pid")
        self.assertGreater(row["monitor_pid"], 0, "the monitor recorded itself at the launch gate")
        # Restart + retry in ONE call: the request resolves to the live dispatch, no new worker.
        res = prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        self.assertEqual((res["state"], res["dispatchId"]), ("ready", disp))
        rec = res["recovery"]
        self.assertEqual(rec["resolution"], "live")
        monitor = [p for p in rec["processes"] if p["role"] == "monitor"][0]
        self.assertEqual((monitor["action"], monitor["pid"], monitor["alive"]), ("adopted", row["monitor_pid"], True))
        self.assertEqual(self.dispatch(prov, disp)["pid"], row["monitor_pid"], "adoption publishes the monitor's pid")
        wt = Path(info["worktree"])
        commit = _git("rev-parse", "HEAD", cwd=wt).stdout.strip()
        self.assertEqual(_git("log", "-1", "--format=%s", commit, cwd=wt).stdout.strip(), "worker-commit")
        self.assertEqual(rec["preservedRefs"][0]["sha"], commit, "the worker's commit is pinned, never lost")
        self.assertEqual(_git("rev-parse", f"refs/open-fleet/preserved/{disp}", cwd=self.repo).stdout.strip(), commit)
        again = prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        self.assertEqual(again["dispatchId"], disp)
        time.sleep(1.0)
        self.assertEqual(len(self.agent_lines()), 1, "retrying the same request never spawns a second worker")
        self.assertEqual(len(self.dispatches_for_task(prov)), 1)
        self.assertEqual(self.agent_lines()[0].split()[:2], [disp, "run-r04"], "the worker runs under the recorded identity")
        agent_pid = int(self.agent_lines()[0].split()[-1])
        prov.worker_fence("stop", disp)
        self.assertTrue(_wait_for(lambda: not _alive(agent_pid)), "stop must reach the adopted worker")

    def test_kill_after_published_adopts_and_completes_the_request(self):
        info = self.crash_at("published", retry_request="req-1")
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))
        prov = self.restart()
        self.assertGreater(self.dispatch(prov, info["dispatchId"])["pid"], 0)
        self.assertEqual(prov.request_show("req-1")["state"], "pending", "the receipt never committed")
        r = prov.launch_reconcile(intent=info["intentId"])["reconciled"][0]
        self.assertEqual((r["resolution"], r["requestState"]), ("live", "completed"))
        replay = prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        self.assertEqual(replay["dispatchId"], info["dispatchId"])
        self.assertEqual(replay["recovery"]["intentId"], info["intentId"])
        time.sleep(1.0)
        self.assertEqual(len(self.agent_lines()), 1)

    def test_kill_after_receipted_leaves_nothing_to_settle(self):
        info = self.crash_at("receipted", retry_request="req-1")
        prov = self.restart()
        self.assertEqual(prov.request_show("req-1")["state"], "completed")
        self.assertEqual(prov.launch_reconcile()["count"], 0)
        replay = prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        self.assertEqual(replay["dispatchId"], info["dispatchId"])
        self.assertNotIn("recovery", replay, "an uninterrupted receipt is replayed as recorded")
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))
        time.sleep(0.5)
        self.assertEqual(len(self.agent_lines()), 1)


class TestUninterruptedControl(CrashRecoveryBase):
    def test_clean_launch_crosses_every_boundary_and_leaves_no_open_intent(self):
        c = self.coordinator(None, retry_request="req-1")
        out = c.finish()
        self.assertEqual(c.seen, list(self.posix.LAUNCH_BOUNDARIES))
        res = out[-1]["result"]
        self.assertEqual(res["state"], "ready")
        prov = self.restart()
        self.assertEqual(prov.request_show("req-1")["state"], "completed")
        it = prov.state.launch_intent(c.info["intentId"])
        self.assertEqual((it["phase"], it["outcome"]), ("receipted", "completed"))
        self.assertEqual(prov.launch_reconcile()["count"], 0)
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))
        self.assertFalse((Path(c.info["laneDir"]) / "recovery.json").exists(), "nothing was recovered")
        self.assertFalse(prov.state.db_path.parent.joinpath("intents", f"{c.info['intentId']}.lock").exists())
        self.assertEqual([w["state"] for w in prov.worker_list()["workers"]], ["ready"])


class TestNoCompletionFromProcessExit(CrashRecoveryBase):
    def test_worker_exit_without_mail_is_a_death_not_a_completion(self):
        self.agent("quick_exit")
        info = self.crash_at("monitor_spawned", retry_request="req-1")
        lane = Path(info["laneDir"])
        prov = self.restart()
        self.assertTrue(_wait_for(lambda: prov.state.dispatch_state(info["dispatchId"]) == "died"))
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual(r["resolution"], "exited")
        self.assertEqual(r["dispatch"]["after"], "died")
        self.assertEqual(r["task"]["after"], "dispatched", "an exit 0 never completes the task")
        self.assertIs(r["completionInferred"], False)
        self.assertTrue((lane / "recovery.json").is_file())
        died = [m for m in prov.check_messages(terminal="coordinator", run="run-r04")["messages"]
                if m["subject"].startswith(f"worker_died:{info['dispatchId']}")]
        self.assertEqual(len(died), 1)

    def test_monitor_killed_with_the_coordinator_is_reported_dead_with_its_commit(self):
        self.agent("committer")
        info = self.crash_at("published", retry_request="req-1")
        self.assertTrue(_wait_for(lambda: Path(f"{self.agent_log}.commit").exists()))
        prov = self.restart()
        pid = self.dispatch(prov, info["dispatchId"])["pid"]
        os.killpg(pid, signal.SIGKILL)  # the whole host went down: monitor and worker too
        self.assertTrue(_wait_for(lambda: not _alive(pid)))
        r = prov.launch_reconcile()["reconciled"][0]
        monitor = [p for p in r["processes"] if p["role"] == "monitor"][0]
        self.assertEqual((r["resolution"], monitor["action"], monitor["alive"]), ("exited", "reported_dead", False))
        self.assertEqual(r["dispatch"]["after"], "died")
        commit = _git("rev-parse", "HEAD", cwd=info["worktree"]).stdout.strip()
        self.assertEqual(r["preservedRefs"][0]["sha"], commit)
        payload = json.loads([m for m in prov.check_messages(terminal="coordinator", run="run-r04")["messages"]
                              if info["dispatchId"] in m["subject"]][0]["payload"])
        self.assertEqual((payload["exitCode"], payload["headSha"]), (-1, commit))


class TestLaunchGateAndFencing(CrashRecoveryBase):
    def test_gate_claim_and_abandon_are_mutually_exclusive(self):
        store = self.restart().state
        with store._connect() as conn:
            for d in ("disp_a", "disp_b"):
                conn.execute(
                    "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, pid, created_at, updated_at) "
                    "VALUES (?, 't', 'default', '/w', 'claude', ?, 'ready', 0, 0, 0)",
                    (d, f"term_{d}"),
                )
        self.assertTrue(store.claim_monitor("disp_a", 111))
        self.assertFalse(store.abandon_unlaunched("disp_a"), "a gated dispatch is adopted, never abandoned")
        self.assertFalse(store.claim_monitor("disp_a", 222), "one monitor per dispatch")
        self.assertTrue(store.abandon_unlaunched("disp_b"))
        self.assertFalse(store.claim_monitor("disp_b", 333), "an abandoned dispatch refuses a late monitor")
        self.assertEqual(store.dispatch_state("disp_b"), "abandoned")

    def test_late_monitor_after_rollback_is_refused_at_the_gate(self):
        # A launcher that outlived its coordinator starts the monitor AFTER recovery ran.
        wrapper = self.base / "slow-python"
        wrapper.write_text(f'#!/bin/sh\ncase "$2" in -c) ;; *) sleep 3 ;; esac\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        info = self.crash_at("monitor_spawned", env={**self.env, "PYTHON": str(wrapper)}, retry_request="req-1")
        prov = self.restart()
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual(r["resolution"], "failed", "no monitor had claimed the gate yet: roll back")
        events = Path(info["laneDir"]) / "events.jsonl"
        self.assertTrue(_wait_for(lambda: "launch_refused" in events.read_text(), timeout=30), "the late monitor must be refused")
        self.assert_no_worker_ran(settle=0.5)
        self.assertEqual(prov.state.dispatch_state(info["dispatchId"]), "abandoned")
        self.assertEqual(self.task_status(prov), "ready")

    def test_stop_after_a_crash_reaches_a_gated_but_unpublished_monitor(self):
        info = self.crash_at("monitor_spawned")
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))
        agent_pid = int(self.agent_lines()[0].split()[-1])
        prov = self.restart()
        self.assertEqual(self.dispatch(prov, info["dispatchId"])["pid"], 0)
        out = prov.worker_fence("stop", info["dispatchId"])
        self.assertEqual(out["termination"].get("pidGroup"), "terminated", out)
        self.assertTrue(_wait_for(lambda: not _alive(agent_pid)), "`stopped` must mean the agent stopped")
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual((r["resolution"], r["error"]["code"]), ("failed", "dispatch_fenced"))
        self.assertEqual(r["task"]["after"], "ready")

    def test_worker_list_settles_an_ownerless_launch(self):
        info = self.crash_at("registered")
        prov = self.restart()
        states = {w["dispatchId"]: w["state"] for w in prov.worker_list()["workers"]}
        self.assertEqual(states, {info["dispatchId"]: "abandoned"})
        self.assertEqual(self.task_status(prov), "ready")
        lane = Path(info["laneDir"])
        self.assertEqual(json.loads((lane / "recovery.json").read_text())["resolution"], "failed")


class TestTakeoverFencesOldWriters(CrashRecoveryBase):
    def test_live_owner_is_left_alone_without_takeover_and_new_starts_name_it(self):
        c = self.coordinator("registered", retry_request="req-1")
        info = c.until("registered")["info"]
        prov = self.restart()
        r = prov.launch_reconcile(intent=info["intentId"])["reconciled"][0]
        self.assertEqual(r["resolution"], "pending")
        self.assertIs(r["owner"]["previous"]["alive"], True)
        self.assertEqual(prov.state.dispatch_state(info["dispatchId"]), "ready", "a live owner's launch is never touched")
        self.assertEqual(prov.worker_start(**self.start_kwargs(retry_request="req-1"))["state"], "outcome_unknown")
        with self.assertRaises(self.providers.ProviderError) as ctx:
            prov.worker_start(**self.start_kwargs(retry_request="req-other"))
        self.assertEqual(ctx.exception.code, "task_not_startable")
        self.assertEqual(ctx.exception.data["openLaunch"]["intentId"], info["intentId"])
        self.assertIn("launch-reconcile", ctx.exception.data["nextSteps"][0])
        os.kill(c.proc.pid, signal.SIGKILL)
        c.proc.wait(timeout=30)
        # Once its owner is gone, the next start settles the stale launch and proceeds.
        res = prov.worker_start(**self.start_kwargs(retry_request="req-other"))
        self.assertNotEqual(res["dispatchId"], info["dispatchId"])
        self.assertEqual(prov.state.dispatch_state(info["dispatchId"]), "abandoned")
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))
        self.assertEqual(self.agent_lines()[0].split()[0], res["dispatchId"])

    def test_takeover_before_spawn_fences_the_old_writer(self):
        c = self.coordinator("registered", retry_request="req-1")
        info = c.until("registered")["info"]
        prov = self.restart()
        r = prov.launch_reconcile(intent=info["intentId"], takeover=True)["reconciled"][0]
        self.assertEqual(r["resolution"], "failed")
        self.assertIs(r["takeover"], True)
        self.assertIs(r["owner"]["previous"]["alive"], True)
        self.assertEqual(r["owner"]["epoch"], 2)
        c.proc.stdin.write("\n")
        c.proc.stdin.flush()
        tail = c.finish()
        self.assertEqual(tail[-1].get("error"), "launch_fenced", tail)
        self.assertEqual(c.proc.returncode, 3)
        self.assertNotIn("monitor_spawned", c.seen, "a fenced coordinator never spawns")
        row = self.dispatch(prov, info["dispatchId"])
        self.assertEqual((row["state"], row["pid"]), ("abandoned", 0), "the old writer published nothing")
        self.assertEqual(prov.request_show("req-1")["state"], "failed", "the new owner's outcome stands")
        self.assertEqual(self.task_status(prov), "ready")
        self.assert_no_worker_ran()

    def test_takeover_after_spawn_adopts_and_the_old_writer_leaves_it_running(self):
        c = self.coordinator("monitor_spawned", retry_request="req-1")
        info = c.until("monitor_spawned")["info"]
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1))
        agent_pid = int(self.agent_lines()[0].split()[-1])
        prov = self.restart()
        r = prov.launch_reconcile(intent=info["intentId"], takeover=True)["reconciled"][0]
        self.assertEqual((r["resolution"], r["takeover"]), ("live", True))
        self.assertEqual((r["runId"], r["taskId"], r["dispatchId"]), ("run-r04", self.task, info["dispatchId"]))
        adopted_pid = self.dispatch(prov, info["dispatchId"])["pid"]
        c.proc.stdin.write("\n")
        c.proc.stdin.flush()
        tail = c.finish()
        self.assertEqual(tail[-1].get("error"), "launch_fenced", tail)
        self.assertNotIn("published", c.seen, "the old writer's publication is refused")
        self.assertTrue(_alive(agent_pid), "a fenced writer terminates nothing the new owner adopted")
        self.assertEqual(self.dispatch(prov, info["dispatchId"])["pid"], adopted_pid)
        self.assertEqual(prov.worker_start(**self.start_kwargs(retry_request="req-1"))["dispatchId"], info["dispatchId"])
        self.assertEqual(self.agent_lines()[0].split()[:2], [info["dispatchId"], "run-r04"])
        self.assertEqual(len(self.agent_lines()), 1)


class TestRequestPayloadBinding(CrashRecoveryBase):
    def test_changed_payload_never_reuses_a_result(self):
        prov = self.restart()
        res = prov.worker_start(**self.start_kwargs(retry_request="req-1"))
        for change in ({"prompt": "something else"}, {"agent": "codex"}, {"profile": "ro"}, {"name": "other-wt"}):
            with self.assertRaises(self.providers.ProviderError) as ctx:
                prov.worker_start(**self.start_kwargs(retry_request="req-1", **change))
            self.assertEqual(ctx.exception.code, "request_mismatch", change)
        self.assertEqual(prov.worker_start(**self.start_kwargs(retry_request="req-1"))["dispatchId"], res["dispatchId"])

    def test_changed_payload_is_refused_for_a_crashed_request_too(self):
        self.crash_at("intent_claimed", retry_request="req-1")
        prov = self.restart()
        with self.assertRaises(self.providers.ProviderError) as ctx:
            prov.worker_start(**self.start_kwargs(retry_request="req-1", prompt="a different assignment"))
        self.assertEqual(ctx.exception.code, "request_mismatch")
        self.assertEqual(prov.request_show("req-1")["state"], "pending", "a mismatched retry settles nothing")

    def test_store_binds_payload_for_other_methods_that_pass_one(self):
        store = self.restart().state
        store.save_request("req-x", "task-create", "completed", {"ok": 1})
        self.assertEqual(store.get_or_record_request("req-x", "task-create", payload_sha256="aa"), {"ok": 1})
        with store._connect() as conn:
            conn.execute("UPDATE requests SET payload_sha256 = 'aa' WHERE request_id = 'req-x'")
        with self.assertRaises(self.providers.ProviderError) as ctx:
            store.get_or_record_request("req-x", "task-create", payload_sha256="bb")
        self.assertEqual(ctx.exception.code, "request_mismatch")


class TestSandboxCommitsSurviveCrash(CrashRecoveryBase):
    """Docker `danger` with a FAKE `docker` CLI (fixture tier): no daemon is ever contacted."""

    def test_sandbox_commit_is_synced_back_when_coordinator_and_monitor_die(self):
        docker_log = self.base / "docker.log"
        fake = self.bin / "docker"
        fake.write_text(
            f"#!{sys.executable}\n"
            "import os, subprocess, sys, time\n"
            "args = sys.argv[1:]\n"
            f"open({str(docker_log)!r}, 'a').write(' '.join(args) + '\\n')\n"
            "if args[:1] == ['run']:\n"
            "    mount = ':/open-fleet/sandbox.git'\n"
            "    sb = next(a[: -len(mount)] for a in args if a.endswith(mount))\n"
            "    wt = args[args.index('-w') + 1]\n"
            "    env = {**os.environ, 'GIT_DIR': sb, 'GIT_WORK_TREE': wt}\n"
            "    subprocess.run(['git', '-c', 'user.email=w@x', '-c', 'user.name=w', 'commit', '--allow-empty', '-qm',\n"
            "                    'sandboxed-work'], cwd=wt, env=env, check=True)\n"
            f"    open({str(self.agent_log)!r}, 'a').write('sandbox run ' + str(os.getpid()) + '\\n')\n"
            "    time.sleep(60)\n",
            encoding="utf-8",
        )
        fake.chmod(0o755)
        info = self.crash_at("published", retry_request="req-1", profile="danger", on_env="sandbox-img")
        self.assertTrue(_wait_for(lambda: len(self.agent_lines()) == 1), "the fake sandbox never ran")
        prov = self.restart()
        pid = self.dispatch(prov, info["dispatchId"])["pid"]
        os.killpg(pid, signal.SIGKILL)  # host crash: monitor and container client die unsynced
        self.assertTrue(_wait_for(lambda: not _alive(pid)))
        lane = Path(info["laneDir"])
        sandbox_head = _git("--git-dir", str(lane / "sandbox.git"), "rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        branch = f"refs/heads/fleet/{self.task}"
        self.assertNotEqual(_git("rev-parse", branch, cwd=self.repo).stdout.strip(), sandbox_head, "not synced yet")
        r = prov.launch_reconcile()["reconciled"][0]
        self.assertEqual(r["resolution"], "exited")
        sandbox_refs = [x for x in r["preservedRefs"] if x.get("source") == "sandbox"]
        self.assertEqual(sandbox_refs, [{"ref": f"refs/open-fleet/sandbox/{info['dispatchId']}", "sha": sandbox_head, "source": "sandbox"}])
        self.assertEqual(_git("rev-parse", branch, cwd=self.repo).stdout.strip(), sandbox_head, "the worker's commit reached the host branch")
        self.assertIn({"kind": "container", "target": f"openfleet-{info['dispatchId']}", "action": "removed", "rc": 0}, r["cleanup"])
        self.assertIn(f"rm -f openfleet-{info['dispatchId']}", docker_log.read_text())
        self.assertEqual(r["dispatch"]["after"], "died")


if __name__ == "__main__":
    unittest.main()
