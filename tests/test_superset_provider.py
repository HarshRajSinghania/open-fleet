#!/usr/bin/env python3
"""#582 acceptance: SupersetProvider contract tests and negative controls.

Proves PROFILE=ro never spawns a Superset agent preset (whose built-in commands carry
`--dangerously-skip-permissions`), the task spec reaches the worker on every profile, the cloud
sandbox is reached via `workspaces create --environment`, read/show/kill route by the recorded
mechanism, `agents wait --until settled` is wired, and malformed upstream output is ok:false.
"""
from __future__ import annotations

import importlib
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
local_state = importlib.import_module("runtime.providers.local_state")
superset = importlib.import_module("runtime.providers.superset")
ProviderError = base.ProviderError


def _load_worker_ops():
    spec = importlib.util.spec_from_file_location("worker_ops_t582", ROOT / "runtime" / "scripts" / "worker_ops.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


WORKER_OPS = _load_worker_ops()
SPEC = "Audit src/billing for unchecked refunds and report findings."
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}


def git_out(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True, env=GIT_ENV).stdout.strip()


class Scripted:
    def __init__(self, rules: list[tuple[tuple[str, ...], Any]]) -> None:
        self.rules = list(rules)
        self.calls: list[list[str]] = []

    def add(self, prefix: tuple[str, ...], response: Any) -> None:
        self.rules.insert(0, (prefix, response))

    def __call__(self, argv: list[str], **_kw: Any) -> Any:
        self.calls.append(list(argv))
        for prefix, response in self.rules:
            if tuple(argv[: len(prefix)]) == prefix:
                if isinstance(response, BaseException):
                    raise response
                return response
        if argv[0] == "git":  # worktree_rm inspects the real worktree before archiving it
            proc = subprocess.run(argv, capture_output=True, text=True, env=GIT_ENV, check=False)
            if proc.returncode:
                raise ProviderError("git_error", proc.stderr.strip())
            return proc.stdout
        raise AssertionError(f"unexpected upstream call: {argv}")

    def called(self, *prefix: str) -> list[list[str]]:
        return [c for c in self.calls if tuple(c[: len(prefix)]) == prefix]


class TestSupersetProvider(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = local_state.LocalStateStore(db_path=self.tmp / "state.db")
        self.wt = self.tmp / "ws-1-tree"
        self.wt.mkdir()
        self.hook_calls: list[tuple[str, str, str]] = []
        self.runner = Scripted(
            [
                (("superset", "workspaces", "get"), {"id": "ws-1", "name": "w", "worktreePath": str(self.wt), "worktreeExists": True}),
                (("superset", "workspaces", "list"), [{"id": "ws-1"}, {"id": "ws-2"}]),
                (("superset", "workspaces", "create"), {"workspace": {"id": "ws-new"}, "terminals": [], "agents": [], "alreadyExists": False}),
                (("superset", "workspaces", "delete"), {"deleted": ["ws-1"], "notFound": [], "failed": []}),
                (("superset", "terminals", "create"), {"terminalId": "term-ro-1", "status": "active"}),
                (("superset", "agents", "create"), {"kind": "terminal", "sessionId": "term-rw-1", "label": "claude"}),
                (("superset", "agents", "explain"), {"terminalId": "term-rw-1", "state": "working", "headline": "editing"}),
                (("superset", "agents", "read"), {"text": "I found two unchecked refunds.", "harness": "claude"}),
                (("superset", "agents", "wait"), {"terminalId": "term-rw-1", "state": "settled"}),
                (("superset", "terminals", "read"), {"terminalId": "term-ro-1", "cols": 80, "rows": 24, "text": "a\nb\nc\n"}),
                (("superset", "terminals", "close"), {"terminalId": "term-ro-1", "status": "disposed"}),
                (("superset", "snapshot"), {"workspaces": [{"id": "ws-1", "terminals": [{"id": "term-ro-1", "title": "t", "agent": None}]}]}),
            ]
        )
        self.prov = superset.SupersetProvider(state=self.state, runner=self.runner, env={}, install_hooks=self.fake_hooks)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake_hooks(self, wt: str, agent: str, profile: str) -> dict[str, str]:
        self.hook_calls.append((wt, agent, profile))
        return {"deny_hook": "fake"}

    def _task(self) -> str:
        return self.prov.dispatch(["orchestration", "task-create", "--spec", SPEC, "--json"])["task"]["id"]

    def test_ro_never_uses_agent_presets_and_carries_spec(self) -> None:
        tid = self._task()
        res = self.prov.dispatch(
            ["orchestration", "worker-start", "--task", tid, "--worktree", "ws-1", "--profile", "ro", "--agent", "claude"], env={}
        )
        self.assertFalse(self.runner.called("superset", "agents"), "ro must never call `superset agents create`")
        term = self.runner.called("superset", "terminals", "create")[0]
        cmd = term[term.index("--command") + 1]
        self.assertIn("--permission-mode plan", cmd)
        self.assertNotIn("dangerously", cmd)
        self.assertIn("Audit src/billing", cmd)  # the COMPLETE launch line carries the spec
        self.assertEqual(term[term.index("--cwd") + 1], str(self.wt))
        self.assertNotIn("--title", term)  # not an upstream flag
        self.assertEqual(res["worktree"], str(self.wt))
        self.assertEqual(self.hook_calls, [(str(self.wt), "claude", "ro")])
        self.assertEqual(res["launch"]["effective"]["mechanism"], "terminals.create")
        self.assertEqual(res["dispatchId"], "sup_term-ro-1")

    def test_ro_fails_closed_without_real_worktree(self) -> None:
        self.runner.add(("superset", "workspaces", "get"), {"id": "ws-1", "worktreePath": None, "worktreeExists": False})
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="ro")
        self.assertEqual(ctx.exception.code, "worktree_unresolved")
        self.assertFalse(self.runner.called("superset", "terminals", "create"))

    def test_rw_passes_prompt_and_installs_hooks(self) -> None:
        tid = self._task()
        res = self.prov.worker_start(task_id=tid, worktree="ws-1", agent="claude", profile="rw")
        self.assertEqual(
            self.runner.called("superset", "agents", "create")[0],
            ["superset", "agents", "create", "--local", "--json", "--workspace", "ws-1", "--agent", "claude", "--prompt", SPEC],
        )
        self.assertEqual(res["launch"]["effective"]["terminalId"], "term-rw-1")
        self.assertEqual(self.hook_calls, [(str(self.wt), "claude", "rw")])

    def test_new_child_creates_workspace_and_records_real_path(self) -> None:
        prov = superset.SupersetProvider(
            state=self.state, runner=self.runner, env={"OPEN_FLEET_SUPERSET_PROJECT": "proj-1"}, install_hooks=self.fake_hooks
        )
        res = prov.worker_start(task_id="", name="feat-a", prompt=SPEC, profile="rw")
        create = self.runner.called("superset", "workspaces", "create")[0]
        self.assertIn("--project", create)
        self.assertEqual(create[create.index("--branch") + 1], "feat-a")
        self.assertEqual(self.runner.called("superset", "workspaces", "get")[0][3], "ws-new")
        self.assertEqual(res["worktree"], str(self.wt))
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", prompt=SPEC)  # no project configured
        self.assertEqual(ctx.exception.code, "missing_project")

    def test_danger_uses_cloud_workspace_environment(self) -> None:
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="danger")
        self.assertEqual(ctx.exception.code, "missing_sandbox_recipe")
        self.runner.add(("superset", "workspaces", "create"), {"id": "cloud-ws-9", "branch": "worker-x", "status": "provisioning"})
        prov = superset.SupersetProvider(state=self.state, runner=self.runner, env={"OPEN_FLEET_SANDBOX_RECIPE": "env-7"})
        res = prov.worker_start(task_id="", name="worker-x", prompt=SPEC, profile="danger")
        create = self.runner.called("superset", "workspaces", "create")[-1]
        self.assertEqual(create[create.index("--environment") + 1], "env-7")
        self.assertEqual(create[create.index("--prompt") + 1], SPEC)
        self.assertNotIn("--local", create)
        self.assertFalse(self.runner.called("superset", "agents", "create"))
        self.assertEqual(res["launch"]["effective"]["mechanism"], "workspaces.create+cloud")
        # Cloud workers expose no terminal: read/stop fail closed instead of faking.
        with self.assertRaises(ProviderError):
            prov.worker_read(dispatch_id=res["dispatchId"])
        with self.assertRaises(ProviderError) as sctx:
            prov.worker_fence(verb="abandon", dispatch_id=res["dispatchId"])
        self.assertEqual(sctx.exception.code, "unsupported_operation")
        self.assertFalse(self.runner.called("superset", "workspaces", "delete"))

    def test_monotonic_privilege(self) -> None:
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="rw", parent_profile="ro")
        self.assertEqual(ctx.exception.code, "privilege_escalation")

    def test_read_show_route_by_mechanism_and_pass_worker_ops(self) -> None:
        ro = self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="ro")["dispatchId"]
        rw = self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="rw")["dispatchId"]

        rw_read = self.prov.dispatch(["orchestration", "worker-read", "--dispatch", rw, "--transcript"])
        self.assertIn("unchecked refunds", "\n".join(WORKER_OPS.format_read(rw_read, want="transcript")))
        self.assertEqual(
            self.runner.called("superset", "agents", "read")[0],
            ["superset", "agents", "read", "--workspace", "ws-1", "--terminal", "term-rw-1", "--local", "--json"],
        )
        ro_read = self.prov.worker_read(dispatch_id=ro, source="terminal", limit=2)
        self.assertEqual(WORKER_OPS.format_read(ro_read)[-2:], ["b", "c"])
        self.assertIn("--max-lines", self.runner.called("superset", "terminals", "read")[0])
        with self.assertRaises(WORKER_OPS.Failed):  # terminal output never certifies as transcript
            WORKER_OPS.format_read(self.prov.worker_read(dispatch_id=ro, source="transcript"), want="transcript")

        self.assertIn("STAGE=working", WORKER_OPS.format_show(self.prov.worker_show(dispatch_id=rw)))
        self.assertIn("STAGE=running", WORKER_OPS.format_show(self.prov.worker_show(dispatch_id=ro)))

        waited = self.prov.worker_wait(dispatch_id=rw)
        self.assertEqual(self.runner.called("superset", "agents", "wait")[0][-4:], ["--until", "settled", "--timeout", "600"])
        self.assertEqual(waited["wait"]["state"], "settled")
        with self.assertRaises(ProviderError):
            self.prov.worker_wait(dispatch_id=rw, until="done")

    def test_fence_retain_close_and_unknown(self) -> None:
        did = self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="ro")["dispatchId"]
        before = len(self.runner.calls)
        self.assertEqual(self.prov.dispatch(["orchestration", "worker-retain", "--dispatch", did])["state"], "retained")
        self.assertEqual(len(self.runner.calls), before)
        stopped = self.prov.worker_fence(verb="stop", dispatch_id=did)
        self.assertEqual(stopped["state"], "stopped")
        self.assertEqual(
            self.runner.called("superset", "terminals", "close")[0],
            ["superset", "terminals", "close", "--workspace", "ws-1", "--terminal", "term-ro-1", "--local", "--json"],
        )
        self.assertFalse(self.runner.called("superset", "workspaces", "delete"))
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_fence(verb="stop", dispatch_id="sup-unknown")
        self.assertEqual(ctx.exception.code, "dispatch_not_found")
        with self.assertRaises(ProviderError) as vctx:
            self.prov.worker_fence(verb="explode", dispatch_id=did)
        self.assertEqual(vctx.exception.code, "invalid_verb")

    def test_bad_output_and_missing_ids_are_errors(self) -> None:
        self.runner.add(("superset", "terminals", "create"), "Terminal started")
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="ro")
        self.assertEqual(ctx.exception.code, "superset_bad_json")
        self.assertFalse(ctx.exception.to_envelope()["ok"])
        self.runner.add(("superset", "agents", "create"), {"kind": "terminal"})
        with self.assertRaises(ProviderError) as ctx2:
            self.prov.worker_start(task_id="", worktree="ws-1", prompt=SPEC, profile="rw")
        self.assertEqual(ctx2.exception.code, "upstream_no_id")
        self.runner.add(("superset", "snapshot"), "")
        with self.assertRaises(ProviderError) as ctx3:
            self.prov.worker_list()
        self.assertEqual(ctx3.exception.code, "superset_empty_output")
        self.runner.add(("superset",), FileNotFoundError("superset"))
        with self.assertRaises(ProviderError) as ctx4:
            self.prov.worktree_list()
        self.assertEqual(ctx4.exception.code, "superset_cli_missing")

    def _linked_worktree(self) -> tuple[Path, Path, str]:
        main, wt = self.tmp / "repo", self.tmp / "ws-linked"
        subprocess.run(["git", "init", "-q", str(main)], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(main), "commit", "-q", "--allow-empty", "-m", "base"], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "ws-feat", str(wt)], check=True, env=GIT_ENV)
        (wt / "fix.py").write_text("fixed\n")
        subprocess.run(["git", "-C", str(wt), "add", "fix.py"], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "worker"], check=True, env=GIT_ENV)
        self.runner.add(("superset", "workspaces", "get"), {"id": "ws-1", "worktreePath": str(wt), "worktreeExists": True})
        return main, wt, git_out("-C", str(wt), "rev-parse", "HEAD")

    def test_worktree_ops(self) -> None:
        self.assertEqual([w["id"] for w in self.prov.worktree_list(limit=1)["worktrees"]], ["ws-1"])
        self.assertEqual(self.runner.calls[-1], ["superset", "workspaces", "list", "--local", "--json"])
        self.assertEqual(self.prov.worktree_show(selector="ws-1")["worktree"]["path"], str(self.wt))
        main, _wt, head = self._linked_worktree()
        removed = self.prov.worktree_rm(selector="ws-1")  # clean: archive after pinning HEAD
        self.assertEqual(self.runner.calls[-1], ["superset", "workspaces", "delete", "ws-1", "--local", "--json"])
        self.assertEqual(removed["preserved"]["sha"], head)
        self.assertEqual(git_out("-C", str(main), "rev-parse", "refs/open-fleet/preserved/superset-ws-1"), head)
        with self.assertRaises(ProviderError):
            self.prov.worktree_rm(selector="")
        self.runner.add(("superset", "workspaces", "delete"), {"deleted": [], "notFound": ["ws-9"], "failed": []})
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worktree_rm(selector="ws-9")
        self.assertEqual(ctx.exception.code, "superset_delete_failed")

    def test_worktree_rm_unforced_never_archives_uncommitted_work(self) -> None:
        main, wt, head = self._linked_worktree()
        (wt / "unsaved.py").write_text("wip\n")
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worktree_rm(selector="ws-1", force=False)
        self.assertEqual(ctx.exception.code, "uncommitted_work")
        self.assertFalse(self.runner.called("superset", "workspaces", "delete"))
        self.assertTrue((wt / "unsaved.py").is_file())
        # HEAD is pinned even on the refused path, before anything could be deleted.
        self.assertEqual(git_out("-C", str(main), "rev-parse", "refs/open-fleet/preserved/superset-ws-1"), head)

        forced = self.prov.worktree_rm(selector="ws-1", force=True)  # explicit force: dirt knowingly discarded
        self.assertEqual(forced["discardedDirty"], ["unsaved.py"])
        self.assertEqual(forced["preserved"]["sha"], head)
        self.assertEqual(len(self.runner.called("superset", "workspaces", "delete")), 1)

    def test_worktree_rm_refuses_when_head_cannot_be_preserved(self) -> None:
        # self.wt is a plain directory (no git): the HEAD pin fails, so nothing is archived even forced.
        for force in (False, True):
            with self.assertRaises(ProviderError) as ctx:
                self.prov.worktree_rm(selector="ws-1", force=force)
            self.assertIn(ctx.exception.code, ("git_error", "preserve_failed"))
        self.assertFalse(self.runner.called("superset", "workspaces", "delete"))
        self.runner.add(("superset", "workspaces", "get"), {"id": "ws-1", "worktreePath": None, "worktreeExists": False})
        with self.assertRaises(ProviderError) as uctx:
            self.prov.worktree_rm(selector="ws-1")
        self.assertEqual(uctx.exception.code, "worktree_unresolved")
        self.assertFalse(self.runner.called("superset", "workspaces", "delete"))


if __name__ == "__main__":
    unittest.main()
