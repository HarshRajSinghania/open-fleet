#!/usr/bin/env python3
"""LocalStateStore acceptance tests (#579, PR #591 re-review): DAG closure, mailbox scoping,
coordinator fencing under concurrency, real HITL gates, atomic synthetic worker_died."""
from __future__ import annotations

import importlib
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _ls():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("runtime.providers.local_state")


def _claim(db, run, handle, q):
    mod = _ls()
    try:
        mod.LocalStateStore(db, env={}).check_messages(terminal=handle, run=run)
        q.put(("ok", handle))
    except mod.ProviderError as exc:
        q.put((exc.code, handle))
    except Exception as exc:  # a raw sqlite IntegrityError is a failure of the fence
        q.put((type(exc).__name__, handle))


class Base(unittest.TestCase):
    def setUp(self):
        self.mod = _ls()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "s.db")
        self.store = self.mod.LocalStateStore(self.db, env={})


class TestDag(Base):
    def _t(self, deps=None):
        return self.store.task_create(spec="s", deps=deps)["task"]["id"]

    def test_failure_blocks_whole_downstream_closure_and_retry_unblocks(self):
        a = self._t()
        b = self._t([a])
        c = self._t([b])
        d = self._t([c])
        self.store.task_update(task_id=a, status="failed")
        st = {t["id"]: t["status"] for t in self.store.task_list()["tasks"]}
        self.assertEqual((st[b], st[c], st[d]), ("blocked", "blocked", "blocked"))
        self.store.task_update(task_id=a, status="completed")
        st = {t["id"]: t["status"] for t in self.store.task_list()["tasks"]}
        self.assertEqual((st[b], st[c], st[d]), ("ready", "pending", "pending"))
        self.store.task_update(task_id=b, status="completed")
        self.store.task_update(task_id=c, status="completed")
        st = {t["id"]: t["status"] for t in self.store.task_list()["tasks"]}
        self.assertEqual(st[d], "ready")

    def test_unknown_dependency_is_refused(self):
        with self.assertRaises(self.mod.ProviderError) as ctx:
            self.store.task_create(spec="s", deps=["task_nope"])
        self.assertEqual(ctx.exception.code, "task_not_found")

    def test_invalid_status_is_refused(self):
        a = self._t()
        with self.assertRaises(self.mod.ProviderError) as ctx:
            self.store.task_update(task_id=a, status="banana")
        self.assertEqual(ctx.exception.code, "invalid_status")

    def test_dag_gate_blocks_until_resolved(self):
        a = self._t()
        b = self._t([a])
        g = self.store.gate_create(task_id=a, question="ship?", options='["yes","no"]')["gate"]
        self.assertEqual({t["id"]: t["status"] for t in self.store.task_list()["tasks"]}[a], "blocked")
        self.store.task_update(task_id=a, status="blocked")
        self.assertEqual({t["id"]: t["status"] for t in self.store.task_list()["tasks"]}[b], "blocked")
        self.store.gate_resolve(gate_id=g["id"], resolution="yes")
        st = {t["id"]: t["status"] for t in self.store.task_list()["tasks"]}
        self.assertEqual(st[a], "ready")
        self.assertEqual(self.store.gate_list(task_id=a)["gates"][0]["status"], "resolved")

    def test_gate_resolved_after_deps_finish_makes_task_ready(self):
        a = self._t()
        b = self._t([a])
        g = self.store.gate_create(task_id=b, question="ok?")["gate"]  # gated while pending
        self.store.task_update(task_id=a, status="completed")
        self.store.gate_resolve(gate_id=g["id"], resolution="ok", sender="coordinator")
        self.assertEqual({t["id"]: t["status"] for t in self.store.task_list()["tasks"]}[b], "ready")

    def test_gate_create_needs_json_options(self):
        a = self._t()
        with self.assertRaises(self.mod.ProviderError):
            self.store.gate_create(task_id=a, question="q", options="yes,no")


class TestMailboxScoping(Base):
    def _register_worker(self, handle):
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, created_at, updated_at) "
                "VALUES (?, 't', 'run1', '/w', 'claude', ?, 'ready', 0, 0)",
                (f"disp_{handle}", handle),
            )

    def test_worker_cannot_read_or_ack_coordinator_mail(self):
        self._register_worker("term_w1")
        sent = self.store.send_message(subject="done", msg_type="worker_done", to="coordinator", sender="term_w2", run="run1")
        mine = self.store.check_messages(terminal="term_w1", run="run1")
        self.assertEqual(mine["count"], 0)
        self.store.check_messages(terminal="term_w1", run="run1", ack=sent["deliveryId"])
        coord = self.store.check_messages(terminal="term_coord", run="run1")
        self.assertEqual(coord["count"], 1, "worker ack must not drain the coordinator inbox")

    def test_env_terminal_scopes_unflagged_check(self):
        self._register_worker("term_w1")
        self.store.send_message(subject="x", msg_type="info", to="coordinator", run="run1")
        worker_store = self.mod.LocalStateStore(self.db, env={"OPEN_FLEET_TERMINAL_HANDLE": "term_w1"})
        self.assertEqual(worker_store.check_messages(run="run1")["count"], 0)

    def test_fenced_run_refuses_second_coordinator_and_anonymous_reader(self):
        self.store.check_messages(terminal="term_a", run="run9")
        with self.assertRaises(self.mod.ProviderError) as ctx:
            self.store.check_messages(terminal="term_b", run="run9")
        self.assertEqual(ctx.exception.code, "consumer_fenced")
        with self.assertRaises(self.mod.ProviderError):
            self.store.check_messages(run="run9")

    def test_concurrent_claimers_get_one_owner_and_typed_fences(self):
        q = multiprocessing.get_context("spawn").Queue()
        procs = [
            multiprocessing.get_context("spawn").Process(target=_claim, args=(self.db, "runR", f"term_c{i}", q))
            for i in range(10)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(60)
        results = [q.get(timeout=10) for _ in procs]
        codes = sorted(r[0] for r in results)
        self.assertEqual(codes.count("ok"), 1, results)
        self.assertEqual(codes.count("consumer_fenced"), 9, results)

    def test_launched_worker_is_pinned_to_its_own_mailbox(self):
        self.store.send_message(subject="for coord", msg_type="worker_done", to="coordinator", run="default")
        self.store.send_message(subject="for me", msg_type="info", to="term_me", run="default")
        worker = self.mod.LocalStateStore(self.db, env={"OPEN_FLEET_DISPATCH_ID": "disp_me", "OPEN_FLEET_TERMINAL_HANDLE": "term_me"})
        got = worker.check_messages(terminal="coordinator")
        self.assertEqual([m["subject"] for m in got["messages"]], ["for me"])

    def test_send_receipt_has_relay_message_id(self):
        r = self.store.send_message(subject="s", msg_type="info")
        self.assertEqual(r["relay"]["messageId"], r["messageId"])


class TestHitlGates(Base):
    def test_ask_reply_resume_round_trip(self):
        res = self.store.ask_human(question="deploy?", options="yes,no", sender="term_w", run="r1")
        self.assertTrue(res["timedOut"])
        self.assertTrue(res["messageId"].startswith("msg_"), "reply targets the question MESSAGE id")
        self.store.reply_message(msg_id=res["messageId"], body="yes")
        resumed = self.store.ask_human(resume=res["messageId"])
        self.assertEqual(resumed["answer"], "yes")
        self.assertFalse(resumed["timedOut"])

    def test_blocking_ask_wakes_on_reply(self):
        holder = {}

        def ask():
            holder["res"] = self.store.ask_human(question="go?", sender="term_w", timeout_ms=10000, retry_request="gate_fixed")

        t = threading.Thread(target=ask)
        t.start()
        mid = None
        for _ in range(100):
            gates = self.store.gate_list()["gates"]
            if gates:
                mid = gates[0]["messageId"]
                break
            time.sleep(0.05)
        self.assertIsNotNone(mid)
        self.store.reply_message(msg_id=mid, body="go")
        t.join(10)
        self.assertEqual(holder["res"]["answer"], "go")

    def test_retry_never_wipes_an_answer_or_duplicates_question(self):
        res = self.store.ask_human(question="q?", retry_request="gate_same")
        self.store.reply_message(msg_id=res["messageId"], body="A")
        again = self.store.ask_human(question="q?", retry_request="gate_same")
        self.assertEqual(again["answer"], "A")
        qs = [m for m in self.store.check_messages(terminal="coordinator", mode="all")["messages"] if m["type"] == "question"]
        self.assertEqual(len(qs), 1)

    def test_workers_cannot_answer_a_gate(self):
        res = self.store.ask_human(question="ship?", sender="term_w", run="r1")
        with self.assertRaises(self.mod.ProviderError) as ctx:
            self.store.reply_message(msg_id=res["messageId"], body="yes", sender="term_w")
        self.assertEqual(ctx.exception.code, "gate_answer_refused")
        worker = self.mod.LocalStateStore(self.db, env={"OPEN_FLEET_DISPATCH_ID": "disp_x", "OPEN_FLEET_TERMINAL_HANDLE": "term_x"})
        with self.assertRaises(self.mod.ProviderError):
            worker.reply_message(msg_id=res["messageId"], body="yes", sender="coordinator")
        self.assertTrue(self.store.ask_human(resume=res["messageId"])["timedOut"], "still unanswered")

    def test_gate_resolve_route_refuses_workers_too(self):
        res = self.store.ask_human(question="deploy?", sender="term_w", run="r1")
        worker = self.mod.LocalStateStore(self.db, env={"OPEN_FLEET_DISPATCH_ID": "disp_w", "OPEN_FLEET_TERMINAL_HANDLE": "term_w"})
        with self.assertRaises(self.mod.ProviderError) as ctx:
            worker.gate_resolve(gate_id=res["gateId"], resolution="yes")
        self.assertEqual(ctx.exception.code, "gate_answer_refused")
        with self.assertRaises(self.mod.ProviderError):
            self.store.gate_resolve(gate_id=res["gateId"], resolution="yes", sender="term_w")
        self.assertTrue(self.store.ask_human(resume=res["gateId"])["timedOut"], "still unanswered")
        self.store.gate_resolve(gate_id=res["gateId"], resolution="yes", sender="coordinator")
        self.assertEqual(self.store.ask_human(resume=res["gateId"])["answer"], "yes")

    def test_answering_acks_the_question_so_it_stops_reading_as_waiting(self):
        res = self.store.ask_human(question="go?", sender="term_w", run="r1")
        self.assertTrue(self.store.has_pending_question("term_w", run_id="r1"))
        self.store.reply_message(msg_id=res["messageId"], body="go")
        self.assertFalse(self.store.has_pending_question("term_w", run_id="r1"))

    def test_no_preset_answer_env_is_honoured(self):
        store = self.mod.LocalStateStore(self.db, env={"OPEN_FLEET_ASK_ANSWER": "yes"})
        res = store.ask_human(question="really?")
        self.assertIsNone(res["answer"], "a fleet never fakes a human answer")


class TestWorkerDied(Base):
    def _dispatch(self, did, state="ready"):
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, created_at, updated_at) "
                "VALUES (?, 't', 'default', '/w', 'claude', ?, ?, 0, 0)",
                (did, f"term_{did}", state),
            )

    def test_concurrent_callers_emit_exactly_one(self):
        self._dispatch("d1")
        out = []
        ts = [
            threading.Thread(target=lambda: out.append(self.store.ensure_terminal_or_died(dispatch_id="d1", worktree_head_sha="a" * 40)))
            for _ in range(8)
        ]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sum(1 for r in out if r["syntheticDied"]), 1)
        msgs = self.store.check_messages(terminal="coordinator")["messages"]
        self.assertEqual(len(msgs), 1)
        self.assertEqual(json.loads(msgs[0]["payload"])["headSha"], "a" * 40)

    def test_fenced_dispatch_is_left_alone(self):
        self._dispatch("d2", state="stopped")
        self.assertFalse(self.store.ensure_terminal_or_died(dispatch_id="d2")["syntheticDied"])
        self.assertEqual(self.store.dispatch_state("d2"), "stopped")


class TestDefaultDbPath(unittest.TestCase):
    def test_per_repo_and_shared_across_linked_worktrees(self):
        mod = _ls()
        with tempfile.TemporaryDirectory() as tmp:
            a = Path(tmp) / "a"
            b = Path(tmp) / "b"
            for r in (a, b):
                r.mkdir()
                subprocess.run(["git", "init", "-q", str(r)], check=True)
            subprocess.run(["git", "-C", str(a), "-c", "user.email=x@y", "-c", "user.name=x", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
            wt = Path(tmp) / "a-wt"
            subprocess.run(["git", "-C", str(a), "worktree", "add", "-q", str(wt)], check=True)
            pa = mod.default_db_path({"OPEN_FLEET_CLI_CWD": str(a)})
            pb = mod.default_db_path({"OPEN_FLEET_CLI_CWD": str(b)})
            pw = mod.default_db_path({"OPEN_FLEET_CLI_CWD": str(wt)})
            self.assertNotEqual(pa, pb)
            self.assertEqual(pa, pw)
            self.assertEqual(pa.name, "runtime.db")
            self.assertTrue(str(pa).startswith(str(Path.home() / ".open-fleet" / "state")))
        self.assertTrue(os.path.isabs(str(mod.default_db_path({"OPEN_FLEET_STATE_DB": "rel.db"}))))


if __name__ == "__main__":
    unittest.main()
