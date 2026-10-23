#!/usr/bin/env python3
"""Process-level drills for the fenced merge queue (#599; runtime/scripts/merge_queue.py).

Each conductor here is a REAL process: either the CLI, or world.CHILD, a conductor that parks at
one committed merge boundary (MERGE_BOUNDARIES) until the test writes a line to it or SIGKILLs it
there. When it is killed, no `finally`, rollback or receipt of that conductor runs. The test
process then plays the competing or restarted conductor. GitHub is fake_gh.py over a bare repo,
the fixture tier: nothing touches the network.

  * two conductors compete for one BASE, and a takeover lands mid-train;
  * pause-transfer-resume: a conductor paused after its lease check, with ownership transferred
    meanwhile, must not merge when it resumes. A handoff waits for a merge inside the boundary,
    and a conductor killed mid-call holds the boundary until the remote merge ends;
  * restarts before the merge, after the remote merge and before the acknowledgement reconcile
    from authoritative state with no duplicate merge and no lost unit, on the gh lane and the
    local (no-gh) lane;
  * mutation controls: removing the fencing check, or the freshness check, from a copy of the
    script makes the invariant the drill pins break, so neither guard is decorative.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "fixtures" / "merge_queue"))
import world as W  # the fixture module sits beside its fake gh

SCRIPTS = ROOT / "runtime" / "scripts"
# The two guards, as exact text: each recipe must match the script exactly once, so a refactor
# that moves a guard fails here by name instead of silently mutating nothing.
FENCE_GUARD = ('        if lease is None or lease["token"] != token or lease["released_at"] is not None:\n',
               "        if False:\n")
FRESHNESS_GUARD = ("        if reviewed_tree and self.git.tree(head) == reviewed_tree:\n",
                   "        if True:\n")


class Conductor:
    """A conductor process (world.CHILD running `drain --ack`) and the boundary lines it prints."""

    def __init__(self, w: W.World, repo: str, holder: str, *, park_at=(), takeover=False, env=None):
        args = {"db": str(w.db), "repo_dir": str(w.conductor), "repo": repo, "base": W.BASE, "holder": holder,
                "park_at": [list(p) for p in park_at], "takeover": takeover, "ack": True, "wait": 10.0}
        self.proc = subprocess.Popen([sys.executable, "-c", W.CHILD, str(w.script), json.dumps(args)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     text=True, env={**w.env, **(env or {})})
        self.lines: queue.Queue = queue.Queue()
        self.seen: list[dict] = []
        self.pump = threading.Thread(target=self._pump, daemon=True)
        self.pump.start()

    def _pump(self):
        for line in self.proc.stdout:
            self.lines.put(json.loads(line))
        self.lines.put(None)

    def until(self, stage: str, nth: int = 1, timeout: float = 60.0) -> dict:
        deadline = time.time() + timeout
        while True:
            msg = self.lines.get(timeout=max(0.1, deadline - time.time()))
            if msg is None:
                raise AssertionError(f"conductor ended before {stage}#{nth}; saw {self.seen}; "
                                     f"stderr={self.proc.stderr.read()}")
            self.seen.append(msg)
            if msg.get("boundary") == stage and msg.get("nth") == nth:
                return msg

    def resume(self) -> None:
        self.proc.stdin.write("\n")
        self.proc.stdin.flush()

    def kill(self) -> None:
        if self.proc.poll() is None:
            os.kill(self.proc.pid, signal.SIGKILL)
        self.proc.wait(timeout=30)

    def close(self) -> None:
        """Kill if still running, then close the pipes once the pump has read to EOF."""
        self.kill()
        self.pump.join(timeout=10)
        for pipe in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            pipe.close()

    def finish(self, timeout: float = 90.0) -> tuple[int, dict]:
        rc = self.proc.wait(timeout=timeout)
        last: dict = {}
        while True:
            msg = self.lines.get(timeout=10)
            if msg is None:
                return rc, last
            self.seen.append(msg)
            if "result" in msg or "error" in msg:
                last = msg


class DrillCase(unittest.TestCase):
    mode = "gh"
    script = W.SCRIPT

    def setUp(self):
        self.w = W.World(Path(tempfile.mkdtemp(prefix="mq-drill-")), mode=self.mode, script=self.script)
        self.addCleanup(self.w.cleanup)
        rc, out = self.w.cli(*self.w.init_args())
        self.assertEqual(rc, 0, out)
        self.repo = out["repo"]

    def boarded(self, *names: str) -> list[dict]:
        """Units boarded by a setup conductor that then releases the lease."""
        units = [self.w.unit(n) for n in names]
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "setup")
        self.assertEqual(rc, 0, out)
        for u in units:
            self.assertEqual(self.w.cli("enqueue", "--token", out["token"], "--payload", json.dumps(u), "--run", "r1")[0], 0)
        self.assertEqual(self.w.cli("release", "--token", out["token"])[0], 0)
        return units

    def conductor(self, holder: str, **kw) -> Conductor:
        c = Conductor(self.w, self.repo, holder, **kw)
        self.addCleanup(c.close)
        return c

    def status(self) -> dict:
        rc, out = self.w.cli("--repo", self.repo, "status", "--base", W.BASE)
        self.assertEqual(rc, 0, out)
        return out

    def receipts(self) -> list[dict]:
        return self.w.cli("--repo", self.repo, "receipts", "--base", W.BASE)[1]["receipts"]

    def assert_landed_once(self, units: list[dict]) -> None:
        """Every unit landed, exactly one merge each, in arrival order: no duplicate, no lost unit."""
        self.assertEqual(self.w.merged_heads(), [u["reviewed_sha"] for u in units])
        if self.mode == "gh":
            self.assertEqual([m["pr"] for m in self.w.merge_log()], [u["pr"] for u in units])
        self.assertEqual([e["state"] for e in self.status()["all"]], ["landed"] * len(units))


class PauseTransferResume(DrillCase):
    def test_a_conductor_paused_after_its_lease_check_never_merges_after_a_transfer(self):
        units = self.boarded("alpha", "beta")
        a = self.conductor("A", park_at=[("lease_checked", 1)])
        parked = a.until("lease_checked")
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual((rc, out["epoch"]), (0, parked["info"]["epoch"] + 1), out)
        a.resume()
        rc, final = a.finish()
        self.assertEqual((rc, final.get("error")), (3, "fenced"), final)
        self.assertEqual(self.w.merge_log("start"), [], "the stale conductor issued a merge after the transfer")
        stale = [r for r in self.receipts() if r["kind"] == "merge_intent" and r["epoch"] == parked["info"]["epoch"]]
        self.assertEqual(stale, [])
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "B", "--ack")
        self.assertEqual(rc, 0, out)
        self.assert_landed_once(units)
        self.assertNotIn(a.proc.pid, {m["caller"] for m in self.w.merge_log()})

    def test_a_handoff_waits_for_a_merge_inside_the_boundary(self):
        units = self.boarded("alpha", "beta")
        a = self.conductor("A", park_at=[("intent_recorded", 1)])
        parked = a.until("intent_recorded")
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual((rc, out["code"]), (1, "merge_in_flight"), out)
        lease = self.status()["lease"]
        self.assertEqual((lease["holder"], lease["epoch"]), ("A", parked["info"]["epoch"]), "ownership moved mid-merge")
        a.resume()
        rc, final = a.finish()
        self.assertEqual(rc, 0, final)
        self.assert_landed_once(units)
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual((rc, out["reconciled"]), (0, []), out)

    def test_a_conductor_killed_mid_call_holds_the_boundary_until_the_remote_merge_ends(self):
        units = self.boarded("alpha", "beta")
        a = self.conductor("A", env={"FAKE_GH_MERGE_DELAY": "3"})
        deadline = time.time() + 60
        while not self.w.merge_log("start") and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(self.w.merge_log("start"), "the conductor never reached GitHub")
        a.kill()  # the merge child it spawned is still sending, holding the inherited lock
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual((rc, out["code"]), (1, "merge_in_flight"), out)
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover", "--wait", "30")
        self.assertEqual(rc, 0, out)
        self.assertEqual([d["resolution"] for d in out["reconciled"]], ["merged"],
                         "the handoff did not reconcile the in-flight merge from GitHub's state")
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "B", "--ack")
        self.assertEqual(rc, 0, out)
        self.assert_landed_once(units)

    def test_an_in_flight_merge_nobody_can_read_blocks_the_handoff(self):
        units = self.boarded("alpha", "beta")
        a = self.conductor("A", park_at=[("intent_recorded", 1)])
        parked = a.until("intent_recorded")
        a.kill()
        self.w.set_gh(lambda s: s.__setitem__("offline", True))
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual((rc, out["code"]), (1, "in_flight_unknown"), out)
        lease = self.status()["lease"]
        self.assertEqual((lease["holder"], lease["epoch"]), ("A", parked["info"]["epoch"]), "handed off on a guess")
        self.assertEqual(self.status()["inFlight"], [self.status()["line"][0]["entry_id"]])
        self.w.set_gh(lambda s: s.__setitem__("offline", False))
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual((rc, [d["resolution"] for d in out["reconciled"]]), (0, ["requeued"]), out)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "B", "--ack")
        self.assertEqual(rc, 0, out)
        self.assert_landed_once(units)


class TwoConductors(DrillCase):
    def test_two_competing_conductors_merge_each_unit_exactly_once(self):
        units = self.boarded("alpha", "beta", "gamma")
        env = {**self.w.env, "FAKE_GH_MERGE_DELAY": "0.3"}
        procs = [subprocess.Popen([sys.executable, str(W.SCRIPT), "--repo-dir", str(self.w.conductor), "drain",
                                   "--base", W.BASE, "--holder", holder, "--ack", "--wait", "30"],
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                 for holder in ("A", "B")]
        outs = [json.loads(p.communicate(timeout=120)[0]) for p in procs]
        codes = sorted(p.returncode for p in procs)
        self.assertIn(codes, ([0, 0], [0, 3]), outs)
        if codes == [0, 3]:
            self.assertIn("lease_held", [o.get("code") for o in outs])
        self.assert_landed_once(units)
        self.assertEqual(self.w.merge_log("refused"), [])
        epochs = {r["epoch"] for r in self.receipts() if r["kind"] == "merge_intent"}
        self.assertEqual(len(epochs), 1, f"two conductors merged onto one BASE: epochs {epochs}")

    def test_a_takeover_mid_train_fences_the_first_conductor(self):
        units = self.boarded("alpha", "beta", "gamma")
        a = self.conductor("A", park_at=[("lease_checked", 2)])
        a.until("lease_checked", 2)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "B", "--takeover", "--ack")
        self.assertEqual(rc, 0, out)
        a.resume()
        rc, final = a.finish()
        self.assertEqual((rc, final.get("error")), (3, "fenced"), final)
        self.assert_landed_once(units)
        callers = [m["caller"] for m in self.w.merge_log()]
        self.assertEqual(callers[0], a.proc.pid)
        self.assertNotIn(a.proc.pid, callers[1:], "the fenced conductor merged after the takeover")


class RestartDrills(DrillCase):
    """Kill the conductor at a boundary; the restart (same holder) reconciles and finishes the train."""

    def crash_and_restart(self, stage: str) -> tuple[list[dict], dict]:
        units = self.boarded("alpha", "beta")
        a = self.conductor("A", park_at=[(stage, 1)])
        a.until(stage)
        a.kill()
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "A", "--ack")
        self.assertEqual(rc, 0, out)
        self.assert_landed_once(units)
        return units, out

    def test_restart_before_the_merge_merges_once(self):
        _units, out = self.crash_and_restart("lease_checked")
        self.assertEqual(out["reconciled"], [])

    def test_restart_with_an_intent_but_no_remote_merge_requeues_then_merges_once(self):
        _units, out = self.crash_and_restart("intent_recorded")
        self.assertEqual([d["resolution"] for d in out["reconciled"]], ["requeued"])

    def test_restart_after_the_remote_merge_adopts_it_without_merging_again(self):
        units, out = self.crash_and_restart("remote_merged")
        self.assertEqual([d["resolution"] for d in out["reconciled"]], ["merged"])
        self.assertEqual(out["reconciled"][0]["acceptedHead"], units[0]["reviewed_sha"])

    def test_restart_before_the_acknowledgement_acknowledges_without_merging_again(self):
        _units, out = self.crash_and_restart("merged_recorded")
        self.assertEqual(out["reconciled"], [])
        self.assertIn("ack", out["steps"][0], "the restart did not settle the owed acknowledgement first")


class LocalMergeRecoveryDrill(RestartDrills):
    """The same restarts on the no-gh lane: reconciled through git ancestry alone."""

    mode = "git"

    def crash_and_restart(self, stage: str) -> tuple[list[dict], dict]:
        units, out = super().crash_and_restart(stage)
        acks = [r["body"] for r in self.receipts() if r["kind"] == "acknowledged"]
        self.assertEqual([a["ledger"] for a in acks], ["no-gh: local-merge"] * len(units))
        return units, out


class MutationControls(unittest.TestCase):
    """Delete one guard from a copy of the script; the invariant its drill pins must break."""

    def mutated(self, guard: tuple[str, str]) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="mq-mutant-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        for name in ("merge_queue.py", "egress.py", "diff_scope.py"):
            shutil.copy2(SCRIPTS / name, tmp / name)
        text = (tmp / "merge_queue.py").read_text(encoding="utf-8")
        self.assertEqual(text.count(guard[0]), 1, "the guard moved: update the recipe")
        (tmp / "merge_queue.py").write_text(text.replace(guard[0], guard[1]), encoding="utf-8")
        return tmp / "merge_queue.py"

    def drill(self, script: Path) -> DrillCase:
        case = type("Mutant", (DrillCase,), {"script": script, "runTest": lambda self: None})()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def test_without_the_fencing_check_a_stale_conductor_merges_after_the_transfer(self):
        case = self.drill(self.mutated(FENCE_GUARD))
        case.boarded("alpha")
        a = case.conductor("A", park_at=[("lease_checked", 1)])
        a.until("lease_checked")
        rc, _out = case.w.cli("acquire", "--base", W.BASE, "--holder", "B", "--takeover")
        self.assertEqual(rc, 0)
        a.resume()
        a.finish()
        self.assertIn(a.proc.pid, {m["caller"] for m in case.w.merge_log()},
                      "the drill no longer depends on the fencing check: a stale conductor stayed silent without it")

    def test_without_the_freshness_check_a_changed_tree_merges(self):
        case = self.drill(self.mutated(FRESHNESS_GUARD))
        (u,) = case.boarded("alpha")
        rc, out = case.w.cli("acquire", "--base", W.BASE, "--holder", "B")
        token = out["token"]
        case.w.cli("plan", "--token", token)
        moved = case.w.push_change(u)
        case.w.cli("release", "--token", token)
        case.w.cli("drain", "--base", W.BASE, "--holder", "B", "--ack")
        self.assertIn(moved, case.w.merged_heads(),
                      "the drill no longer depends on the freshness check: unreviewed content stayed out without it")


if __name__ == "__main__":
    unittest.main()
