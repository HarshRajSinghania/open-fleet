#!/usr/bin/env python3
"""Behavior of the persisted, fenced merge queue (#599; runtime/scripts/merge_queue.py).

Every test builds disposable repositories (a bare "remote", a worker clone, a conductor clone)
and a fake GitHub (tests/fixtures/merge_queue/fake_gh.py) over the bare repo. Nothing touches the
network. The process-level drills (two conductors, pause-transfer-resume, crash restarts, the
mutation controls) are tests/test_merge_queue_drills.py.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The fixture harness sits beside its fake gh, loaded by path (it is not a package CI installs).
_spec = importlib.util.spec_from_file_location("mq_world", ROOT / "tests" / "fixtures" / "merge_queue" / "world.py")
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

mq_mod = W.load_module()
egress = mq_mod.egress


class QueueCase(unittest.TestCase):
    mode = "gh"

    def setUp(self):
        self.w = W.World(Path(tempfile.mkdtemp(prefix="mq-test-")), mode=self.mode)
        self.addCleanup(self.w.cleanup)
        rc, out = self.w.cli(*self.w.init_args())
        self.assertEqual(rc, 0, out)
        self.repo = out["repo"]

    def acquire(self, holder="c1", *extra):
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", holder, *extra)
        self.assertEqual(rc, 0, out)
        return out["token"]

    def board(self, token, *units, run="r1"):
        ids = []
        for u in units:
            rc, out = self.w.cli("enqueue", "--token", token, "--payload", json.dumps(u), "--run", run)
            self.assertEqual(rc, 0, out)
            ids.append(out["entry"]["entry_id"])
        return ids

    def status(self):
        # --repo pins the queue's identity: the offline drills point origin somewhere else.
        rc, out = self.w.cli("--repo", self.repo, "status", "--base", W.BASE)
        self.assertEqual(rc, 0, out)
        return out

    def receipts(self, entry=None):
        args = ["receipts", "--base", W.BASE] + (["--entry", entry] if entry else [])
        return self.w.cli(*args)[1]["receipts"]

    def state_of(self, entry):
        return next(e["state"] for e in self.status()["all"] if e["entry_id"] == entry)


class LeaseAndFencing(QueueCase):
    def test_one_conductor_per_repository_and_base(self):
        self.acquire("c1")
        rc, out = self.w.cli("acquire", "--base", W.BASE, "--holder", "c2")
        self.assertEqual((rc, out.get("code")), (3, "lease_held"), out)
        self.assertEqual(out["data"]["holder"], "c1")
        # A second BASE in the same repository is a second queue with its own conductor.
        self.w.git(self.w.worker, "push", "-q", "origin", f"origin/{W.BASE}:refs/heads/integration-2")
        rc, out = self.w.cli("init", "--base", "integration-2", "--default", W.DEFAULT, "--consent", "grant:x",
                             "--host", "github.invalid")
        self.assertEqual(rc, 0, out)
        rc, out = self.w.cli("acquire", "--base", "integration-2", "--holder", "c2")
        self.assertEqual((rc, out["epoch"]), (0, 1), out)

    def test_a_stale_owner_cannot_board_plan_dequeue_merge_ack_resolve_or_release(self):
        old = self.acquire("c1")
        (entry,) = self.board(old, self.w.unit("alpha"))
        new = self.acquire("c2", "--takeover")
        before = self.status()["all"]
        attempts = {
            "enqueue": ["enqueue", "--token", old, "--payload", json.dumps(self.w.unit("beta"))],
            "plan": ["plan", "--token", old],
            "merge": ["merge", "--token", old],
            "ack": ["ack", "--token", old, "--entry", entry],
            "resolve": ["resolve", "--token", old, "--entry", entry, "--action", "drop", "--reason", "x"],
            "reconcile": ["reconcile", "--token", old],
            "release": ["release", "--token", old],
        }
        for name, args in attempts.items():
            with self.subTest(op=name):
                rc, out = self.w.cli(*args)
                self.assertEqual((rc, out.get("code")), (3, "fenced"), out)
                self.assertEqual(out["data"]["currentEpoch"], 2)
        self.assertEqual(self.status()["all"], before, "a fenced write changed queue state")
        self.assertEqual(self.w.merge_log("start"), [], "a fenced conductor reached GitHub")
        stale = [r for r in self.receipts() if r["epoch"] == 1 and r["kind"] not in ("lease_acquired", "boarded")]
        self.assertEqual(stale, [], "epoch 1 wrote a receipt after it was fenced")
        rc, out = self.w.cli("plan", "--token", new)
        self.assertEqual(rc, 0, out)

    def test_a_restart_under_the_same_holder_fences_the_older_process(self):
        first = self.acquire("c1")
        second = self.acquire("c1")
        rc, out = self.w.cli("plan", "--token", first)
        self.assertEqual((rc, out.get("code")), (3, "fenced"))
        self.assertEqual(self.w.cli("plan", "--token", second)[0], 0)

    def test_an_expired_lease_is_acquirable_without_takeover(self):
        mq = self.w.queue(mq_mod)
        now = [1000.0]
        mq.clock = lambda: now[0]
        mq.acquire(repo=self.repo, base=W.BASE, holder="c1", ttl=60)
        with self.assertRaises(mq_mod.QueueError) as held:
            mq.acquire(repo=self.repo, base=W.BASE, holder="c2", ttl=60)
        self.assertEqual(held.exception.code, "lease_held")
        now[0] += 61
        self.assertEqual(mq.acquire(repo=self.repo, base=W.BASE, holder="c2", ttl=60)["epoch"], 2)

    def test_every_owner_write_renews_the_lease(self):
        mq = self.w.queue(mq_mod)
        now = [1000.0]
        mq.clock = lambda: now[0]
        token = mq.acquire(repo=self.repo, base=W.BASE, holder="c1", ttl=60)["token"]
        for _ in range(3):
            now[0] += 50
            mq.enqueue(token, self.w.unit(f"u{int(now[0])}"))
        with self.assertRaises(mq_mod.QueueError) as held:
            mq.acquire(repo=self.repo, base=W.BASE, holder="c2", ttl=60)
        self.assertEqual(held.exception.code, "lease_held")

    def test_an_unknown_token_is_not_an_owner(self):
        rc, out = self.w.cli("plan", "--token", "0" * 32)
        self.assertEqual((rc, out.get("code")), (3, "unknown_token"))


class Boarding(QueueCase):
    def test_an_entry_binds_run_unit_pr_branch_reviewed_sha_tree_base_and_arrival(self):
        token = self.acquire()
        a, b = self.w.unit("alpha"), self.w.unit("beta")
        ids = self.board(token, a, b, run="run-7")
        line = self.status()["line"]
        self.assertEqual([e["entry_id"] for e in line], ids)
        self.assertEqual([e["seq"] for e in line], [1, 2])
        got = line[0]
        self.assertEqual((got["run_id"], got["unit"], got["pr"], got["branch"], got["reviewed_sha"], got["reviewed_tree"]),
                         ("run-7", "alpha", a["pr"], "alpha", a["reviewed_sha"], a["reviewed_wtree"]))
        boarded = [r for r in self.receipts(ids[0]) if r["kind"] == "boarded"][0]["body"]
        self.assertEqual((boarded["base"], boarded["seq"], boarded["reviewedSha"], boarded["reviewedTree"]),
                         (W.BASE, 1, a["reviewed_sha"], a["reviewed_wtree"]))

    def test_a_duplicate_merge_ready_delivery_is_idempotent(self):
        token = self.acquire()
        a = self.w.unit("alpha")
        rc1, first = self.w.cli("enqueue", "--token", token, "--payload", json.dumps(a), "--run", "r1", "--delivery", "d1")
        rc2, again = self.w.cli("enqueue", "--token", token, "--payload", json.dumps(a), "--run", "r1", "--delivery", "d2")
        self.assertEqual((rc1, rc2), (0, 0))
        self.assertEqual((first["duplicate"], again["duplicate"]), (False, True))
        self.assertEqual(again["entry"]["entry_id"], first["entry"]["entry_id"])
        self.assertEqual(len(self.status()["all"]), 1)
        # No arrival slot was consumed by the duplicate.
        (nxt,) = self.board(token, self.w.unit("beta"))
        self.assertEqual(next(e["seq"] for e in self.status()["all"] if e["entry_id"] == nxt), 2)
        kinds = [r["kind"] for r in self.receipts(first["entry"]["entry_id"])]
        self.assertEqual(kinds.count("boarded"), 1)
        self.assertEqual(kinds.count("duplicate_delivery"), 1)

    def test_the_same_delivery_key_with_another_payload_is_refused(self):
        token = self.acquire()
        a = self.w.unit("alpha")
        self.board(token, a)
        rc, out = self.w.cli("enqueue", "--token", token, "--payload", json.dumps({**a, "branch": "elsewhere"}), "--run", "r1")
        self.assertEqual((rc, out.get("code")), (2, "payload_mismatch"))

    def test_reboarding_a_unit_supersedes_it_and_joins_the_back(self):
        token = self.acquire()
        a, b = self.w.unit("alpha"), self.w.unit("beta")
        old_a, _ = self.board(token, a, b)
        moved = {**a, "reviewed_sha": self.w.push_change(a), }
        moved["reviewed_wtree"] = self.w.tree(moved["reviewed_sha"])
        rc, out = self.w.cli("enqueue", "--token", token, "--payload", json.dumps(moved), "--run", "r1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["superseded"], [old_a])
        self.assertEqual([e["unit"] for e in self.status()["line"]], ["beta", "alpha"])
        self.assertEqual(self.state_of(old_a), "superseded")

    def test_a_redelivery_after_landing_is_a_no_op(self):
        a = self.w.unit("alpha")
        token = self.acquire()
        self.board(token, a)
        self.w.cli("release", "--token", token)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")
        self.assertEqual(rc, 0, out)
        token = self.acquire()
        rc, out = self.w.cli("enqueue", "--token", token, "--payload", json.dumps(a), "--run", "r1")
        self.assertEqual((rc, out["duplicate"], out["entry"]["state"]), (0, True, "landed"))
        self.assertEqual(len(self.w.merge_log()), 1)

    def test_payloads_are_validated_before_any_write(self):
        token = self.acquire()
        a = self.w.unit("alpha")
        bad = {"not json": "{", "no unit": json.dumps({**a, "unit": ""}),
               "short sha": json.dumps({**a, "reviewed_sha": "abc"}),
               "bool pr": json.dumps({**a, "pr": True}), "no pr on gh lane": json.dumps({**a, "pr": None}),
               "refspec in branch": json.dumps({**a, "branch": "alpha:refs/heads/integration"}),
               "option as branch": json.dumps({**a, "branch": "--upload-pack=x"})}
        for name, payload in bad.items():
            with self.subTest(name):
                rc, out = self.w.cli("enqueue", "--token", token, "--payload", payload)
                self.assertEqual(rc, 2, out)
        forged = {**a, "reviewed_wtree": self.w.tree(f"{W.DEFAULT}")}
        self.w.git(self.w.conductor, "fetch", "-q", "origin", "alpha")
        rc, out = self.w.cli("enqueue", "--token", token, "--payload", json.dumps(forged))
        self.assertEqual((rc, out.get("code")), (2, "reviewed_tree_mismatch"))
        self.assertEqual(self.status()["all"], [])


class FifoAndFreeze(QueueCase):
    def test_units_merge_once_each_in_arrival_order(self):
        units = [self.w.unit(n) for n in ("alpha", "beta", "gamma")]
        token = self.acquire()
        ids = self.board(token, *units)
        self.w.cli("release", "--token", token)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.merged_heads(), [u["reviewed_sha"] for u in units])
        self.assertEqual([x["pr"] for x in self.w.merge_log()], [u["pr"] for u in units])
        intents = [r["entry_id"] for r in self.receipts() if r["kind"] == "merge_intent"]
        self.assertEqual(intents, ids)
        self.assertEqual({self.state_of(i) for i in ids}, {"landed"})

    def test_only_the_head_of_the_train_may_merge(self):
        token = self.acquire()
        _a, b = self.board(token, self.w.unit("alpha"), self.w.unit("beta"))
        self.assertEqual(self.w.cli("plan", "--token", token)[0], 0)
        rc, out = self.w.cli("merge", "--token", token, "--entry", b)
        self.assertEqual((rc, out.get("code")), (2, "not_head"))
        self.assertEqual(self.w.merge_log("start"), [])

    def test_a_merged_entry_must_be_acknowledged_before_the_next_merge(self):
        token = self.acquire()
        a, _b = self.board(token, self.w.unit("alpha"), self.w.unit("beta"))
        self.w.cli("plan", "--token", token)
        self.assertEqual(self.w.cli("merge", "--token", token)[0], 0)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code")), (1, "ack_owed"))
        rc, out = self.w.cli("ack", "--token", token, "--entry", a, "--note", "ledgered")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.cli("merge", "--token", token)[0], 0)

    def test_a_failed_gate_freezes_the_train_behind_it_until_resolved(self):
        a, b, c = (self.w.unit(n) for n in ("alpha", "beta", "gamma"))
        token = self.acquire()
        ids = self.board(token, a, b, c)
        rc, out = self.w.cli("plan", "--token", token, "--gate-cmd", "test ! -f beta.txt")
        self.assertEqual(rc, 0, out)
        self.assertEqual([p["result"] for p in out["planned"]], ["tested", "fail"])
        self.assertEqual(out["planned"][1]["reason"], "gate_failed")
        self.assertEqual(self.w.cli("merge", "--token", token)[0], 0)
        self.w.cli("ack", "--token", token, "--entry", ids[0])
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code"), out["data"]["entry"]), (1, "queue_frozen", ids[1]))
        rc, out = self.w.cli("plan", "--token", token)
        self.assertEqual((rc, out.get("code")), (1, "queue_frozen"))
        self.assertEqual(self.status()["frozen"]["entry"], ids[1])
        self.assertEqual(self.w.merged_heads(), [a["reviewed_sha"]], "a unit merged past a frozen predecessor")
        failed = [r for r in self.receipts(ids[1]) if r["kind"] == "failed"][0]["body"]
        self.assertTrue(failed["frozen"])
        self.assertEqual(failed["gate"]["exit"], 1)
        rc, out = self.w.cli("resolve", "--token", token, "--entry", ids[1], "--action", "drop", "--reason", "gate red")
        self.assertEqual(rc, 0, out)
        self.w.cli("release", "--token", token)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.merged_heads(), [a["reviewed_sha"], c["reviewed_sha"]])
        self.assertIn("resolved", [r["kind"] for r in self.receipts(ids[1])])

    def test_a_refused_remote_merge_freezes_the_train(self):
        a, b = self.w.unit("alpha"), self.w.unit("beta")
        token = self.acquire()
        ids = self.board(token, a, b)
        self.w.set_gh(lambda s: s["prs"][str(a["pr"])].__setitem__("refuse", "Required status check is failing"))
        self.w.cli("plan", "--token", token)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code")), (1, "merge_refused"), out)
        self.assertEqual(self.state_of(ids[0]), "failed")
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual(out.get("code"), "queue_frozen")
        self.w.set_gh(lambda s: s["prs"][str(a["pr"])].pop("refuse"))
        self.w.cli("resolve", "--token", token, "--entry", ids[0], "--action", "requeue", "--reason", "checks fixed")
        self.w.cli("release", "--token", token)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.merged_heads(), [a["reviewed_sha"], b["reviewed_sha"]])

    def test_a_conflicting_unit_fails_at_plan_and_freezes(self):
        a = self.w.unit("alpha", {"shared.txt": "alpha\n"})
        b = self.w.unit("beta", {"shared.txt": "beta\n"})
        token = self.acquire()
        ids = self.board(token, a, b)
        rc, out = self.w.cli("plan", "--token", token)
        self.assertEqual([(p["result"], p.get("reason")) for p in out["planned"]], [("tested", None), ("fail", "conflict")])
        self.assertEqual(out["planned"][1]["conflicts"], ["shared.txt"])
        self.assertEqual(self.state_of(ids[1]), "failed")


class Freshness(QueueCase):
    def _planned(self, *units):
        token = self.acquire()
        ids = self.board(token, *units)
        rc, out = self.w.cli("plan", "--token", token)
        self.assertEqual(rc, 0, out)
        return token, ids

    def test_a_changed_tree_returns_to_review_and_never_merges(self):
        a, b = self.w.unit("alpha"), self.w.unit("beta")
        token, ids = self._planned(a, b)
        moved = self.w.push_change(a)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("result"), out.get("reason")), (1, "returned_to_review", "content_changed"), out)
        self.assertEqual(out["head"], moved)
        self.assertEqual(self.state_of(ids[0]), "bounced")
        self.assertEqual(self.w.merge_log("start"), [], "unreviewed content reached GitHub")
        self.w.cli("release", "--token", token)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.w.merged_heads(), [b["reviewed_sha"]])
        self.assertNotIn(moved, self.w.git(self.w.tmp, "--git-dir", str(self.w.bare), "rev-list", W.BASE).split())

    def test_a_unit_changed_before_its_first_plan_returns_to_review(self):
        # The conductor never fetched the reviewed commit, so the payload's tree is the reference.
        a, b = self.w.unit("alpha"), self.w.unit("beta")
        token = self.acquire()
        ids = self.board(token, a, b)
        self.w.push_change(a)
        rc, out = self.w.cli("plan", "--token", token)
        self.assertEqual([(p["result"], p.get("reason")) for p in out["planned"]],
                         [("bounce", "content_changed"), ("tested", None)], out)
        self.assertEqual(self.state_of(ids[0]), "bounced")

    def test_a_content_identical_move_keeps_the_review_and_pins_the_new_head(self):
        a = self.w.unit("alpha")
        token, ids = self._planned(a)
        moved = self.w.amend_same_tree(a)
        self.assertNotEqual(moved, a["reviewed_sha"])
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out["result"], out["acceptedHead"]), (0, "merged", moved), out)
        intent = [r for r in self.receipts(ids[0]) if r["kind"] == "merge_intent"][0]["body"]
        self.assertEqual(intent["how"], "content_equivalent")
        call = self.w.merge_log("start")[0]["argv"]
        self.assertEqual(call[call.index("--match-head-commit") + 1], moved)
        self.assertEqual(self.w.merged_heads(), [moved])

    def test_a_moved_base_makes_the_tested_prefix_stale(self):
        a = self.w.unit("alpha")
        token, ids = self._planned(a)
        self.w.external_base_write()
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code"), out["data"]["reason"]), (1, "retest_required", "base_moved"), out)
        self.assertEqual(self.w.merge_log("start"), [])
        self.assertIn("retest_required", [r["kind"] for r in self.receipts(ids[0])])
        self.assertEqual(self.w.cli("plan", "--token", token)[0], 0)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out["treeMatchesTested"]), (0, True), out)


class GitLaneFreshness(Freshness):
    mode = "git"

    def test_a_content_identical_move_keeps_the_review_and_pins_the_new_head(self):
        a = self.w.unit("alpha")
        token, _ids = self._planned(a)
        moved = self.w.amend_same_tree(a)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out["acceptedHead"], out["noGh"]), (0, moved, True), out)
        self.assertEqual(self.w.merged_heads(), [moved])


class OfflineAndPromotion(QueueCase):
    def test_offline_github_blocks_the_merge_and_loses_nothing(self):
        a = self.w.unit("alpha")
        token = self.acquire()
        (entry,) = self.board(token, a)
        self.w.cli("plan", "--token", token)
        self.w.set_gh(lambda s: s.__setitem__("offline", True))
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code")), (1, "offline"), out)
        self.assertEqual(self.state_of(entry), "queued")
        self.assertEqual([r["body"]["step"] for r in self.receipts(entry) if r["kind"] == "offline"], ["revalidate"])
        # The lease itself needs no network: a handoff with nothing in flight succeeds offline.
        token = self.acquire("c2", "--takeover")
        self.w.set_gh(lambda s: s.__setitem__("offline", False))
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.w.merge_log()), 1)

    def test_the_default_branch_is_never_a_merge_queue_base(self):
        rc, out = self.w.cli("init", "--base", W.DEFAULT, "--default", W.DEFAULT, "--consent", "grant:x")
        self.assertEqual((rc, out.get("code")), (2, "promotion_is_human"))

    def test_a_payload_aimed_at_the_default_branch_is_refused(self):
        token = self.acquire()
        rc, out = self.w.cli("enqueue", "--token", token, "--payload", json.dumps({**self.w.unit("alpha"), "base": W.DEFAULT}))
        self.assertEqual((rc, out.get("code")), (2, "promotion_is_human"))

    def test_a_pr_retargeted_at_the_default_branch_returns_to_review(self):
        a = self.w.unit("alpha")
        token = self.acquire()
        (entry,) = self.board(token, a)
        self.w.set_gh(lambda s: s["prs"][str(a["pr"])].__setitem__("baseRefName", W.DEFAULT))
        rc, out = self.w.cli("plan", "--token", token)
        self.assertEqual([(p["result"], p["reason"]) for p in out["planned"]], [("bounce", "wrong_base")])
        self.assertEqual(self.state_of(entry), "bounced")
        self.assertEqual(self.w.merge_log("start"), [])

    def test_a_drained_train_leaves_promotion_to_a_human(self):
        main_before = self.w.remote_ref(W.DEFAULT)
        token = self.acquire()
        ids = self.board(token, self.w.unit("alpha"), self.w.unit("beta"))
        self.w.cli("release", "--token", token)
        rc, out = self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")
        self.assertEqual(rc, 0, out)
        self.assertEqual(out["promotion"], {"from": W.BASE, "by": "human", "automated": False})
        self.assertEqual(self.w.remote_ref(W.DEFAULT), main_before, "the queue moved the default branch")
        self.assertEqual(self.status()["promotion"]["automated"], False)
        acks = [r["body"]["promotion"] for r in self.receipts() if r["kind"] == "acknowledged"]
        self.assertEqual(len(acks), len(ids))
        self.assertTrue(all("human gate" in p for p in acks))
        sub = subprocess.run([sys.executable, str(W.SCRIPT), "--help"], capture_output=True, text=True).stdout
        self.assertNotIn("promote", sub)

    def test_an_egress_receipt_precedes_every_merge(self):
        token = self.acquire()
        self.board(token, self.w.unit("alpha"), self.w.unit("beta"))
        self.w.cli("release", "--token", token)
        self.assertEqual(self.w.cli("drain", "--base", W.BASE, "--holder", "c1", "--ack")[0], 0)
        ok, count, _line, _why = egress.verify_ledger(self.w.ledger)
        self.assertEqual((ok, count), (True, 2))
        lines = [json.loads(x) for x in self.w.ledger.read_text().splitlines()]
        self.assertEqual({(x["sink"], x["payload_class"], x["consent"]) for x in lines},
                         {("merge-queue", "pr-merge", "grant:merge-to-integration")})

    def test_no_receipt_means_no_send(self):
        token = self.acquire()
        (entry,) = self.board(token, self.w.unit("alpha"))
        self.w.cli("plan", "--token", token)
        self.w.ledger.mkdir()  # the ledger path is a directory: the receipt cannot be written
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code")), (1, "egress_failed"), out)
        self.assertEqual(self.w.merge_log("start"), [])
        self.assertEqual(self.state_of(entry), "queued")


class NonCooperatingWriters(QueueCase):
    def test_a_merge_github_landed_on_a_moved_base_needs_an_explicit_ack(self):
        # GitHub, not the queue, picks the base commit it merges onto: a write that bypasses the
        # queue between revalidation and the merge cannot be fenced, only surfaced.
        token = self.acquire()
        (entry,) = self.board(token, self.w.unit("alpha"))
        self.w.cli("plan", "--token", token)
        self.w.set_gh(lambda s: s.__setitem__("race_base_write", True))
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out["result"], out["treeMatchesTested"]), (0, "merged", False), out)
        rc, out = self.w.cli("ack", "--token", token, "--entry", entry)
        self.assertEqual((rc, out.get("code")), (1, "untested_tree_merged"), out)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual(out.get("code"), "ack_owed")
        rc, out = self.w.cli("ack", "--token", token, "--entry", entry, "--accept-untested-tree", "--note", "re-gated")
        self.assertEqual((rc, out["acceptedUntestedTree"]), (0, True), out)


class GitLaneOffline(QueueCase):
    mode = "git"

    def test_an_unreachable_remote_blocks_the_no_gh_lane_and_loses_nothing(self):
        token = self.acquire()
        (entry,) = self.board(token, self.w.unit("alpha"))
        self.w.cli("plan", "--token", token)
        url = self.w.git(self.w.conductor, "remote", "get-url", "origin")
        self.w.git(self.w.conductor, "remote", "set-url", "origin", str(self.w.tmp / "gone.git"))
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out.get("code")), (1, "offline"), out)
        self.assertEqual(self.state_of(entry), "queued")
        self.w.git(self.w.conductor, "remote", "set-url", "origin", url)
        rc, out = self.w.cli("merge", "--token", token)
        self.assertEqual((rc, out["noGh"]), (0, True), out)
        rc, out = self.w.cli("ack", "--token", token, "--entry", entry)
        self.assertEqual((rc, out["ledger"]), (0, "no-gh: local-merge"))
        merge = self.w.remote_ref(W.BASE)
        author = self.w.git(self.w.tmp, "--git-dir", str(self.w.bare), "log", "-1", "--format=%an", merge)
        self.assertEqual(author, "Fleet Maintainer")


class StoreMigration(unittest.TestCase):
    def test_an_older_store_gains_the_new_columns_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mq.db"
            conn = sqlite3.connect(db)
            conn.executescript(mq_mod.Store.SCHEMA)
            conn.execute("INSERT INTO mq_queues VALUES ('r', 'b', 'main', 'gh', 'origin', 'h', 'c', 1, 0)")
            conn.commit()
            have = {r[1] for r in conn.execute("PRAGMA table_info(mq_entries)")}
            conn.close()
            self.assertNotIn("tested_tree", have)
            mq_mod.Store(db)
            mq_mod.Store(db)  # idempotent: a second open adds nothing and raises nothing
            conn = sqlite3.connect(db)
            have = {r[1] for r in conn.execute("PRAGMA table_info(mq_entries)")}
            kept = conn.execute("SELECT base FROM mq_queues").fetchall()
            conn.close()
            self.assertTrue(set(mq_mod.Store.COLUMNS["mq_entries"]) <= have)
            self.assertEqual(kept, [("b",)])

    def test_concurrent_openers_both_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mq.db"
            code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('m',sys.argv[1]);"
                    "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.Store(sys.argv[2]);print('ok')")
            procs = [subprocess.Popen([sys.executable, "-c", code, str(W.SCRIPT), str(db)], stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True) for _ in range(4)]
            results = [p.communicate(timeout=60) for p in procs]
            self.assertEqual([p.returncode for p in procs], [0] * 4, results)

    OPENER = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('m',sys.argv[1]);"
              "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);m.Store(sys.argv[2]);print('ok')")

    def _open_together(self, db: Path, count: int) -> None:
        procs = [subprocess.Popen([sys.executable, "-c", self.OPENER, str(W.SCRIPT), str(db)], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True) for _ in range(count)]
        errors = [p.communicate(timeout=120)[1] for p in procs]
        self.assertEqual([p.returncode for p in procs], [0] * count, [e for e in errors if e])

    def test_many_openers_of_a_fresh_store_all_succeed_round_after_round(self):
        # The CI race (PR #647): switching a fresh store to WAL refused a concurrent opener with
        # `database is locked` instead of waiting. One round of four rarely shows it; eight
        # openers over several rounds made it reproducible.
        for _round in range(6):
            with tempfile.TemporaryDirectory() as tmp:
                self._open_together(Path(tmp) / "mq.db", 8)

    def test_openers_racing_a_migration_all_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "mq.db"
            conn = sqlite3.connect(db)
            conn.executescript(mq_mod.Store.SCHEMA)  # an older store: rollback journal, no new columns
            conn.close()
            self._open_together(db, 8)
            conn = sqlite3.connect(db)
            names = [r[1] for r in conn.execute("PRAGMA table_info(mq_entries)")]
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            conn.close()
            self.assertTrue(set(mq_mod.Store.COLUMNS["mq_entries"]) <= set(names))
            self.assertEqual(mode, "wal")


class DoctrineWiring(unittest.TestCase):
    def test_the_policy_names_the_mechanism_that_enforces_it(self):
        text = (ROOT / "runtime" / "merge-serialization.md").read_text(encoding="utf-8")
        self.assertIn("merge_queue.py", text, "merge serialization is doctrine with no mechanism named")

    def test_the_reference_page_documents_the_script(self):
        text = (ROOT / "docs" / "runtime-scripts.md").read_text(encoding="utf-8")
        self.assertIn("## `merge_queue.py`", text)
        self.assertIn("tests/test_merge_queue_drills.py", text)


if __name__ == "__main__":
    unittest.main()
