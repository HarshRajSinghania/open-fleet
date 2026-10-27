#!/usr/bin/env python3
"""#588 acceptance (Overstory + T3 Code): PROFILE=ro vs rw enforcement, the task spec reaching
the upstream worker, the real worktree recorded, worker_ops-compatible read/show receipts, and
negative controls (bad output ok:false, retain non-destructive, unknown dispatch, danger refused).

The AO and JCode Swarm halves of #588 are covered by their own provider tests.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
local_state = importlib.import_module("runtime.providers.local_state")
overstory = importlib.import_module("runtime.providers.overstory")
t3code = importlib.import_module("runtime.providers.t3code")
ProviderError = base.ProviderError


def _load_worker_ops():
    spec = importlib.util.spec_from_file_location("worker_ops_t588", ROOT / "runtime" / "scripts" / "worker_ops.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


WORKER_OPS = _load_worker_ops()
SPEC = "Map every caller of LegacyClient.fetch and report which can migrate."
GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}


class Scripted:
    def __init__(self, rules: list[tuple[tuple[str, ...], Any]], *, real_git: bool = False) -> None:
        self.rules = list(rules)
        self.calls: list[list[str]] = []
        self.real_git = real_git

    def add(self, prefix: tuple[str, ...], response: Any) -> None:
        self.rules.insert(0, (prefix, response))

    def __call__(self, argv: list[str], **_kw: Any) -> Any:
        self.calls.append(list(argv))
        for prefix, response in self.rules:
            if tuple(argv[: len(prefix)]) == prefix:
                if isinstance(response, BaseException):
                    raise response
                return response
        if self.real_git and argv[0] == "git":
            proc = subprocess.run(argv, capture_output=True, text=True, env=GIT_ENV, check=False)
            if proc.returncode:
                raise ProviderError("git_error", proc.stderr.strip())
            return proc.stdout
        raise AssertionError(f"unexpected upstream call: {argv}")

    def called(self, *prefix: str) -> list[list[str]]:
        return [c for c in self.calls if tuple(c[: len(prefix)]) == prefix]


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = local_state.LocalStateStore(db_path=self.tmp / "state.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()


# --------------------------------------------------------------------------------------
# Overstory
# --------------------------------------------------------------------------------------
class TestOverstoryProvider(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.wt = str(self.tmp / ".overstory" / "worktrees" / "scout-t1")
        self.runner = Scripted(
            [
                (("ov", "spec", "write"), {"success": True, "command": "spec-write", "taskId": "t1", "path": "/repo/.overstory/specs/t1.md"}),
                (("ov", "sling"), {"success": True, "command": "sling", "agentName": "scout-t1", "capability": "scout", "taskId": "t1",
                                   "branch": "overstory/scout-t1/t1", "worktree": self.wt, "tmuxSession": "ov-scout-t1", "pid": 42}),
                (("ov", "inspect"), {"success": True, "command": "inspect",
                                     "session": {"agentName": "scout-t1", "state": "working", "worktreePath": self.wt},
                                     "tmuxOutput": "reading files\nfound 3 callers\n", "recentToolCalls": [{"toolName": "Grep"}]}),
                (("ov", "stop"), {"success": True, "command": "stop", "stopped": True, "worktreeRemoved": False}),
                (("ov", "status"), {"success": True, "command": "status", "agents": [{"agentName": "scout-t1"}]}),
                (("ov", "mail", "send"), {"success": True, "command": "mail-send", "id": "msg-1"}),
                (("ov", "mail", "check"), {"success": True, "command": "mail-check", "messages": [{"id": "msg-up-1"}]}),
                (("ov", "mail", "list"), {"success": True, "command": "mail-list", "messages": [{"id": "msg-up-2"}]}),
                (("ov", "mail", "reply"), {"success": True, "command": "mail-reply", "id": "msg-3"}),
            ]
        )
        self.prov = overstory.OverstoryProvider(state=self.state, runner=self.runner, env={})

    def test_spec_written_and_slung_with_scout_under_ro(self) -> None:
        tid = self.prov.dispatch(["orchestration", "task-create", "--spec", SPEC])["task"]["id"]
        res = self.prov.dispatch(["orchestration", "worker-start", "--task", tid, "--profile", "ro", "--agent", "claude"], env={})
        self.assertEqual(self.runner.called("ov", "spec", "write")[0], ["ov", "spec", "write", tid, "--body", SPEC, "--json"])
        self.assertEqual(
            self.runner.called("ov", "sling")[0],
            ["ov", "sling", tid, "--capability", "scout", "--runtime", "claude", "--spec", "/repo/.overstory/specs/t1.md",
             "--skip-task-check", "--json"],
        )
        self.assertEqual(res["dispatchId"], "scout-t1")
        self.assertEqual(res["worktree"], self.wt)
        self.assertEqual(res["capability"], "scout")

    def test_rw_builder_and_ro_capability_rejection(self) -> None:
        rw = self.prov.worker_start(task_id="t2", prompt=SPEC, agent="codex", profile="rw", name="b-1")
        self.assertEqual(self.runner.called("ov", "sling")[-1][:6], ["ov", "sling", "t2", "--name", "b-1", "--capability"])
        self.assertEqual(rw["capability"], "builder")
        for cap in ("builder", "merger", "lead", "coordinator", "monitor"):
            with self.assertRaises(ProviderError) as ctx:
                self.prov.worker_start(task_id="t3", prompt=SPEC, profile="ro", capability=cap)
            self.assertEqual(ctx.exception.code, "privilege_escalation", cap)
        # Codex always runs --full-auto inside Overstory: ro would not be enforced.
        with self.assertRaises(ProviderError) as cctx:
            self.prov.worker_start(task_id="t3", prompt=SPEC, profile="ro", agent="codex")
        self.assertEqual(cctx.exception.code, "unsupported_profile")
        with self.assertRaises(ProviderError) as dctx:
            self.prov.worker_start(task_id="t3", prompt=SPEC, profile="danger")
        self.assertEqual(dctx.exception.code, "unsupported_profile")
        with self.assertRaises(ProviderError) as actx:
            self.prov.worker_start(task_id="t3", prompt=SPEC, agent="hermes")
        self.assertEqual(actx.exception.code, "unsupported_agent")
        self.assertEqual(len(self.runner.called("ov", "sling")), 1, "refused starts never reach ov sling")

    def test_bad_output_is_an_error(self) -> None:
        self.runner.add(("ov", "sling"), "spawned scout-t1")
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="t1", prompt=SPEC, profile="ro")
        self.assertEqual(ctx.exception.code, "overstory_bad_json")
        self.assertFalse(ctx.exception.to_envelope()["ok"])
        self.runner.add(("ov", "sling"), {"success": False, "command": "sling", "error": "Task not found"})
        with self.assertRaises(ProviderError) as ctx2:
            self.prov.worker_start(task_id="t1", prompt=SPEC, profile="ro")
        self.assertEqual(ctx2.exception.code, "overstory_error")
        self.runner.add(("ov", "sling"), {"success": True, "worktree": self.wt})
        with self.assertRaises(ProviderError) as ctx3:
            self.prov.worker_start(task_id="t1", prompt=SPEC, profile="ro")
        self.assertEqual(ctx3.exception.code, "upstream_no_id")

    def test_read_show_retain_stop_unknown(self) -> None:
        did = self.prov.worker_start(task_id="t1", prompt=SPEC, profile="ro")["dispatchId"]
        lines = WORKER_OPS.format_read(self.prov.worker_read(dispatch_id=did, source="terminal"))
        self.assertIn("found 3 callers", lines)
        with self.assertRaises(WORKER_OPS.Failed):
            WORKER_OPS.format_read(self.prov.worker_read(dispatch_id=did), want="transcript")
        show = WORKER_OPS.format_show(self.prov.worker_show(dispatch_id=did))
        self.assertIn("STAGE=working", show)

        before = len(self.runner.calls)
        self.assertEqual(self.prov.worker_fence(verb="retain", dispatch_id=did)["state"], "retained")
        self.assertEqual(len(self.runner.calls), before)
        released = self.prov.worker_fence(verb="release", dispatch_id=did)
        self.assertEqual(self.runner.called("ov", "stop")[0], ["ov", "stop", "scout-t1", "--json"])
        self.assertNotIn("--clean-worktree", self.runner.called("ov", "stop")[0])
        self.assertEqual(released["state"], "released")
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_fence(verb="stop", dispatch_id="ghost")
        self.assertEqual(ctx.exception.code, "dispatch_not_found")

    def test_worktree_rm_never_cleans_everything(self) -> None:
        with self.assertRaises(ProviderError) as ctx:
            self.prov.dispatch(["worktree", "rm"])
        self.assertEqual(ctx.exception.code, "invalid_selector")
        self.assertFalse(self.runner.called("ov", "worktree", "clean"))

        main = self.tmp / "repo"
        wt = self.tmp / "agent-wt"
        subprocess.run(["git", "init", "-q", str(main)], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(main), "commit", "-q", "--allow-empty", "-m", "i"], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt), "-b", "overstory/b-1/t9"], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(wt), "commit", "-q", "--allow-empty", "-m", "work"], check=True, env=GIT_ENV)
        runner = Scripted(
            [(("ov", "worktree", "list"), {"success": True, "worktrees": [{"path": str(wt), "branch": "overstory/b-1/t9", "agentName": "b-1"}]}),
             (("ov", "stop"), {"success": True, "worktreeRemoved": True})],
            real_git=True,
        )
        prov = overstory.OverstoryProvider(state=self.state, runner=runner, env={})
        (wt / "wip.py").write_text("x")
        with self.assertRaises(ProviderError) as dctx:
            prov.worktree_rm(selector="b-1")
        self.assertEqual(dctx.exception.code, "uncommitted_work")
        self.assertFalse(runner.called("ov", "stop"))
        (wt / "wip.py").unlink()
        (wt / ".claude").mkdir()
        (wt / ".claude" / "CLAUDE.md").write_text("overlay")  # overstory's own overlay is not work
        res = prov.worktree_rm(selector="b-1")
        head = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        self.assertEqual(res["preserved"]["sha"], head)
        self.assertEqual(
            subprocess.run(["git", "-C", str(main), "rev-parse", "refs/open-fleet/preserved/b-1"], capture_output=True, text=True).stdout.strip(),
            head,
        )
        self.assertEqual(runner.called("ov", "stop")[0], ["ov", "stop", "b-1", "--clean-worktree", "--force", "--json"])
        with self.assertRaises(ProviderError):
            prov.worktree_rm(selector="nobody")

    def test_worker_list_is_our_dispatches_not_every_ov_agent(self) -> None:
        self.runner.add(("ov", "status"), {"success": True, "command": "status", "agents": [
            {"agentName": "scout-t1", "state": "working"}, {"agentName": "builder-not-ours", "state": "working"}]})
        self.assertEqual(self.prov.worker_list()["workers"], [])
        self.prov.worker_start(task_id="t1", prompt=SPEC, profile="ro")
        listed = self.prov.worker_list()
        self.assertEqual(WORKER_OPS.format_list(listed), ["ROWS=1", "SCOPE=overstory", "NEXT_CURSOR=none", "scout-t1 t1 active"])
        self.assertEqual(listed["workers"][0]["stage"], "working")
        self.runner.add(("ov", "status"), {"success": True, "command": "status"})
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_list()
        self.assertEqual(ctx.exception.code, "overstory_bad_json")

    def test_mail_types_peek_and_reply(self) -> None:
        self.prov.send_message(subject="ready", msg_type="merge_ready", to="orchestrator", payload="sha123")
        self.assertEqual(
            self.runner.called("ov", "mail", "send")[0],
            ["ov", "mail", "send", "--to", "orchestrator", "--subject", "ready", "--body", "sha123", "--type", "merge_ready", "--json"],
        )
        self.prov.send_message(subject="fyi", msg_type="info")
        self.assertIn("status", self.runner.called("ov", "mail", "send")[-1])
        with self.assertRaises(ProviderError):
            self.prov.send_message(subject="x", msg_type="bogus")
        got = self.prov.check_messages()
        self.assertEqual(self.runner.called("ov", "mail", "check")[0], ["ov", "mail", "check", "--agent", "orchestrator", "--json"])
        self.assertNotIn("--ack", self.runner.called("ov", "mail", "check")[0])
        self.assertEqual(got["upstreamMessages"], [{"id": "msg-up-1"}])
        self.prov.check_messages(mode="peek")
        self.assertEqual(self.runner.called("ov", "mail", "list")[0], ["ov", "mail", "list", "--to", "orchestrator", "--unread", "--json"])
        self.assertEqual(self.prov.reply_message(msg_id="msg-up-1", body="go")["scope"], "upstream")


# --------------------------------------------------------------------------------------
# T3 Code
# --------------------------------------------------------------------------------------
def mcp(data: dict[str, Any], *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(data)}], "structuredContent": data, "isError": error}


class ToolScript:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = dict(routes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, call: dict[str, Any], **_kw: Any) -> Any:
        self.calls.append(call)
        resp = self.routes[call["tool"]]
        if isinstance(resp, BaseException):
            raise resp
        return resp

    def of(self, tool: str) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["tool"] == tool]


class TestT3CodeProvider(_Base):
    def setUp(self) -> None:
        super().setUp()
        self.wt = self.tmp / "t3-wt"
        self.wt.mkdir()
        self.hook_calls: list[tuple[str, str, str]] = []
        self.tools = ToolScript(
            {
                "t3_thread_launch": mcp({"threadId": "thr-1", "projectId": "p-1", "modelSelection": {"instanceId": "codex", "model": "gpt"},
                                         "runId": "run-1", "status": "running"}),
                "t3_thread_read": mcp({"thread": {"threadId": "thr-1", "status": "running", "worktreePath": str(self.wt), "branch": "t3-x"},
                                       "recentRuns": [], "nextPosition": 7, "hasMore": True,
                                       "items": [{"itemId": "i1", "createdBy": "user", "type": "message", "text": SPEC},
                                                 {"itemId": "i2", "createdBy": "agent", "type": "message", "text": "Found 4 callers."}]}),
                "t3_thread_interrupt": mcp({"threadId": "thr-1", "runId": "run-1", "status": "interrupt_requested"}),
                "t3_thread_send": mcp({"threadId": "thr-1", "messageId": "m-1", "runId": "run-2", "status": "queued", "delivery": "queued"}),
                "t3_thread_list": mcp({"projectId": "p-1", "currentThreadId": None, "threads": [{"threadId": "thr-1", "status": "running"}], "nextCursor": None, "total": 1}),
            }
        )
        self.prov = t3code.T3CodeProvider(state=self.state, runner=self.tools, env={"OPEN_FLEET_T3_PROJECT_ID": "p-1"},
                                          install_hooks=self.fake_hooks)

    def fake_hooks(self, wt: str, agent: str, profile: str) -> dict[str, str]:
        self.hook_calls.append((wt, agent, profile))
        return {}

    def test_ro_launch_carries_spec_and_plan_modes(self) -> None:
        tid = self.prov.dispatch(["orchestration", "task-create", "--spec", SPEC])["task"]["id"]
        res = self.prov.dispatch(["orchestration", "worker-start", "--task", tid, "--profile", "ro"], env={})
        call = self.tools.of("t3_thread_launch")[0]
        args = call["arguments"]
        self.assertEqual(call["argv"][:3], ["t3", "acp-mcp-call", "t3_thread_launch"])
        self.assertEqual(json.loads(call["argv"][3]), args)  # positional JSON, no invented --params
        self.assertEqual(args["message"], SPEC)
        self.assertEqual(args["runtimeMode"], "approval-required")
        self.assertEqual(args["interactionMode"], "plan")
        self.assertEqual(args["projectId"], "p-1")
        self.assertEqual(args["workspaceStrategy"]["type"], "worktree")
        self.assertEqual(res["dispatchId"], "thr-1")
        self.assertEqual(res["worktree"], str(self.wt))  # read back from thread.worktreePath
        self.assertNotIn("Execute task", json.dumps(self.tools.calls))

    def test_rw_existing_worktree_installs_hooks_first(self) -> None:
        self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="rw", agent="codex")
        args = self.tools.of("t3_thread_launch")[0]["arguments"]
        self.assertEqual(args["runtimeMode"], "full-access")
        self.assertEqual(args["interactionMode"], "default")
        self.assertEqual(args["workspaceStrategy"], {"type": "existing_worktree", "worktreePath": str(self.wt)})
        self.assertEqual(self.hook_calls, [(str(self.wt), "codex", "rw")])

    def _rw_cut_provider(self, workspace_root: Any) -> Any:
        self.tools.routes["t3_project_read"] = mcp({"id": "p-1", "title": "p", "workspaceRoot": workspace_root})
        self.launches_at_hook: list[int] = []

        def hooks(wt: str, agent: str, profile: str) -> dict[str, str]:
            self.launches_at_hook.append(len(self.tools.of("t3_thread_launch")))
            return self.fake_hooks(wt, agent, profile)

        def real_git(argv: list[str]) -> str:
            proc = subprocess.run(argv, capture_output=True, text=True, env=GIT_ENV, check=False)
            if proc.returncode:
                raise ProviderError("git_error", proc.stderr.strip())
            return proc.stdout

        env = {"OPEN_FLEET_T3_PROJECT_ID": "p-1", "OPEN_FLEET_T3_WORKTREE_ROOT": str(self.tmp / "t3-wts")}
        return t3code.T3CodeProvider(state=self.state, runner=self.tools, env=env, install_hooks=hooks, git_runner=real_git)

    def test_rw_new_worktree_is_cut_and_hooked_before_any_agent_starts(self) -> None:
        repo = self.tmp / "t3-repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True, env=GIT_ENV)
        subprocess.run(["git", "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "base"], check=True, env=GIT_ENV)
        prov = self._rw_cut_provider(str(repo))
        res = prov.worker_start(task_id="", name="t3-fix", prompt=SPEC, profile="rw", agent="codex")
        wt = os.path.realpath(self.tmp / "t3-wts" / "t3-fix")
        self.assertTrue(os.path.isdir(wt))
        self.assertIn(wt, subprocess.run(["git", "-C", str(repo), "worktree", "list"], capture_output=True, text=True,
                                         check=True).stdout)
        self.assertEqual(self.tools.of("t3_project_read")[0]["arguments"], {"projectId": "p-1"})
        self.assertEqual(self.hook_calls, [(wt, "codex", "rw")])
        self.assertEqual(self.launches_at_hook, [0], "hooks must exist before t3_thread_launch")
        args = self.tools.of("t3_thread_launch")[0]["arguments"]
        self.assertEqual(args["workspaceStrategy"], {"type": "existing_worktree", "worktreePath": wt})
        self.assertEqual(args["runtimeMode"], "full-access")
        self.assertEqual(res["launch"]["effective"]["hooks"], {})
        self.assertEqual(res["launch"]["effective"]["createdWorktree"]["path"], wt)

    def test_rw_new_worktree_without_workspace_root_never_launches(self) -> None:
        prov = self._rw_cut_provider(None)
        with self.assertRaises(ProviderError) as ctx:
            prov.worker_start(task_id="", name="t3-fix", prompt=SPEC, profile="rw")
        self.assertEqual(ctx.exception.code, "worktree_unresolved")
        self.assertFalse(self.tools.of("t3_thread_launch"))
        self.assertEqual(self.hook_calls, [])
        with self.assertRaises(ProviderError) as mctx:
            self.prov.worker_start(task_id="", worktree=str(self.tmp / "no-such-wt"), prompt=SPEC, profile="rw")
        self.assertEqual(mctx.exception.code, "worktree_unknown")
        self.assertFalse(self.tools.of("t3_thread_launch"))

    def test_danger_missing_project_and_spec_fail_closed(self) -> None:
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", prompt=SPEC, profile="danger")
        self.assertEqual(ctx.exception.code, "unsupported_profile")
        bare = t3code.T3CodeProvider(state=self.state, runner=self.tools, env={})
        with self.assertRaises(ProviderError) as pctx:
            bare.worker_start(task_id="", prompt=SPEC, profile="ro")
        self.assertEqual(pctx.exception.code, "missing_project")
        with self.assertRaises(ProviderError) as sctx:
            self.prov.worker_start(task_id="task_none", profile="ro")
        self.assertEqual(sctx.exception.code, "missing_task_spec")
        self.assertFalse(self.tools.of("t3_thread_launch"))
        with self.assertRaises(ProviderError) as ectx:
            t3code.T3CodeProvider(state=self.state, env={"OPEN_FLEET_T3_PROJECT_ID": "p"}).worker_start(task_id="", prompt=SPEC, profile="ro")
        self.assertEqual(ectx.exception.code, "t3code_not_configured")

    def test_tool_errors_and_bad_output(self) -> None:
        self.tools.routes["t3_thread_launch"] = mcp({"error": "forbidden"}, error=True)
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", prompt=SPEC, profile="ro")
        self.assertEqual(ctx.exception.code, "t3code_tool_error")
        self.tools.routes["t3_thread_launch"] = "not json"
        with self.assertRaises(ProviderError) as ctx2:
            self.prov.worker_start(task_id="", prompt=SPEC, profile="ro")
        self.assertEqual(ctx2.exception.code, "t3code_bad_json")
        self.assertFalse(ctx2.exception.to_envelope()["ok"])
        self.tools.routes["t3_thread_launch"] = mcp({"status": "running"})
        with self.assertRaises(ProviderError) as ctx3:
            self.prov.worker_start(task_id="", prompt=SPEC, profile="ro")
        self.assertEqual(ctx3.exception.code, "upstream_no_id")

    def test_read_show_inject_fence(self) -> None:
        did = self.prov.worker_start(task_id="", prompt=SPEC, profile="ro")["dispatchId"]
        lines = WORKER_OPS.format_read(self.prov.dispatch(["orchestration", "worker-read", "--dispatch", did, "--transcript"]), want="transcript")
        self.assertIn("CURSOR=7", lines)
        self.assertIn("Found 4 callers.", lines)
        self.assertIn("--- i1 (user)", lines)
        self.assertIn("STAGE=running", WORKER_OPS.format_show(self.prov.worker_show(dispatch_id=did)))

        inj = self.prov.dispatch_inject(task_id="", to_handle="t3:thr-1", prompt="Also check tests/.")
        self.assertEqual(self.tools.of("t3_thread_send")[0]["arguments"]["message"], "Also check tests/.")
        self.assertEqual(inj["delivery"], "queued")
        with self.assertRaises(ProviderError):
            self.prov.dispatch_inject(task_id="task_none", to_handle="t3:thr-1")

        before = len(self.tools.calls)
        self.assertEqual(self.prov.worker_fence(verb="retain", dispatch_id=did)["state"], "retained")
        self.assertEqual(len(self.tools.calls), before)
        stopped = self.prov.worker_fence(verb="stop", dispatch_id=did, reason="budget")
        self.assertEqual(self.tools.of("t3_thread_interrupt")[0]["arguments"], {"threadId": "thr-1", "reason": "budget"})
        self.assertEqual(stopped["state"], "stopped")
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_show(dispatch_id="thr-ghost")
        self.assertEqual(ctx.exception.code, "dispatch_not_found")
        listed = self.prov.worker_list()
        self.assertEqual([w["dispatchId"] for w in listed["workers"]], ["thr-1"])  # OUR rows, not raw threads
        self.assertEqual(listed["workers"][0]["stage"], "running")  # annotated from t3_thread_list
        self.assertEqual(WORKER_OPS.format_list(listed)[3], "thr-1 ? stopped")
        self.assertEqual(WORKER_OPS.format_list(listed)[1], "SCOPE=t3code")

    def test_worker_list_ignores_foreign_threads_and_rejects_bad_shape(self) -> None:
        self.tools.routes["t3_thread_list"] = mcp({"projectId": "p-1", "threads": [{"threadId": "thr-foreign", "status": "running"}]})
        self.assertEqual(self.prov.worker_list()["workers"], [])
        self.tools.routes["t3_thread_list"] = mcp({"projectId": "p-1", "items": []})
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_list()
        self.assertEqual(ctx.exception.code, "t3code_bad_json")


# --------------------------------------------------------------------------------------
# W4-01 class sweep: the adapters' own git
# --------------------------------------------------------------------------------------
class TestAdapterGitRunsNothingTheRepoNames(_Base):
    """W4-01 swept to the external adapters. Their `git` (the dirty check before a removal, the
    HEAD pin, t3code's worktree cut, worktrunk's merge prediction) runs in the COORDINATOR over a
    worker's worktree, through the shared runners `run_cli` / `run_cli_text`. A hook, fsmonitor,
    filter or merge driver planted in the shared `.git/config` or the same-uid `~/.gitconfig` must
    never run. Each probe only appends its channel name to a marker in this test's temp dir."""

    def setUp(self) -> None:
        super().setUp()
        self.ext = importlib.import_module("runtime.providers._external")
        self.marker = self.tmp / "pwned"
        self.repo = self.tmp / "repo"
        self.wt = self.tmp / "wt"
        clean = {**GIT_ENV, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, env=clean)
        (self.repo / "a.txt").write_text("a\n", encoding="utf-8")
        (self.repo / "README.md").write_text("# r\n", encoding="utf-8")  # selected by the linked-only `inc`
        subprocess.run(["git", "-C", str(self.repo), "add", "a.txt", "README.md"], check=True, env=clean)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "a"], check=True, env=clean)
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "work", str(self.wt)],
                       check=True, env=clean)

    def probe(self, channel: str, passthrough: bool = True) -> str:
        return f"sh -c 'echo {channel} >> \"{self.marker}\"" + ("; cat'" if passthrough else "'")

    def hooks_dir(self, name: str) -> Path:
        hooks = self.tmp / name
        hooks.mkdir()
        for hook in ("post-checkout", "reference-transaction", "post-index-change"):
            (hooks / hook).write_text(f'#!/bin/sh\necho hook-{hook} >> "{self.marker}"\n', encoding="utf-8")
            (hooks / hook).chmod(0o755)
        return hooks

    def config_file(self, name: str, pairs: tuple[tuple[str, str], ...]) -> Path:
        path = self.tmp / name
        for key, value in pairs:
            subprocess.run(["git", "config", "-f", str(path), key, value], check=True, cwd=self.tmp)
        return path

    def plant(self) -> None:
        """What a worker does from its own worktree; the test runs no bare git on the repo after."""
        inc = self.config_file("linked-only.gitconfig", (("filter.inc.smudge", self.probe("inc-smudge")),
                                                         ("filter.inc.clean", self.probe("inc-clean"))))
        for key, value in (("core.hooksPath", str(self.hooks_dir("evilhooks"))),
                           ("core.fsmonitor", self.probe("fsmonitor", passthrough=False)),
                           ("filter.evil.smudge", self.probe("smudge")),
                           ("filter.evil.clean", self.probe("clean")),
                           ("merge.evil.driver", self.probe("merge-driver", passthrough=False)),
                           ("includeIf.gitdir:**/worktrees/**.path", str(inc))):
            subprocess.run(["git", "-C", str(self.repo), "config", key, value], check=True)
        (self.repo / ".git" / "info").mkdir(exist_ok=True)
        (self.repo / ".git" / "info" / "attributes").write_text(
            "* filter=evil merge=evil\nREADME.md filter=inc\n", encoding="utf-8")

    def fired(self) -> list[str]:
        return sorted(set(self.marker.read_text().split())) if self.marker.exists() else []

    def text_runner(self, argv: list[str]) -> str:
        return self.ext.run_cli_text(argv, "adapter")

    def test_the_dirty_check_and_head_pin_run_no_planted_command(self) -> None:
        self.plant()
        later = os.path.getmtime(self.wt / "a.txt") + 5
        os.utime(self.wt / "a.txt", (later, later))  # stat changed: the status refresh re-reads it
        (self.wt / "new.txt").write_text("unsaved\n", encoding="utf-8")
        self.assertEqual(self.ext.foreign_dirty_paths(self.text_runner, str(self.wt)), ["new.txt"])
        pinned = self.ext.preserve_worker_head(self.text_runner, str(self.wt), "disp-1")
        self.assertEqual(pinned["ref"], "refs/open-fleet/preserved/disp-1")
        out = self.ext.run_cli(["git", "-C", str(self.wt), "status", "--porcelain"], provider="git")
        self.assertIn("new.txt", out["stdout"])
        self.assertEqual(self.fired(), [], "an adapter's git ran a repo-planted command")

    def test_t3code_cuts_its_worktree_without_running_a_planted_command(self) -> None:
        self.plant()
        tools = ToolScript({"t3_project_read": mcp({"id": "p-1", "title": "p", "workspaceRoot": str(self.repo)})})
        env = {"OPEN_FLEET_T3_PROJECT_ID": "p-1", "OPEN_FLEET_T3_WORKTREE_ROOT": str(self.tmp / "t3-wts")}
        prov = t3code.T3CodeProvider(state=self.state, runner=tools, env=env)
        cut = prov._cut_worktree("t3-cut", None)
        self.assertEqual(self.fired(), [], "t3code's worktree cut ran a repo-planted command")
        self.assertEqual(Path(cut["path"], "a.txt").read_text(encoding="utf-8"), "a\n", "checked out raw")
        # W2-04: the base is a commit-ish after `--`, never an option.
        with self.assertRaises(ProviderError):
            prov._cut_worktree("t3-dash", "--force")
        self.assertFalse((self.tmp / "t3-wts" / "t3-dash" / "a.txt").exists())

    def test_worktrunk_merge_prediction_runs_no_planted_merge_driver(self) -> None:
        clean = {**GIT_ENV, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        for where, body in ((self.wt, "work side\n"), (self.repo, "main side\n")):
            (where / "a.txt").write_text(body, encoding="utf-8")
            subprocess.run(["git", "-C", str(where), "commit", "-qam", "edit"], check=True, env=clean)
        self.plant()
        worktrunk = importlib.import_module("runtime.providers.worktrunk")
        prov = worktrunk.WorktrunkProvider(state=self.state)
        conflicted = prov._predict_conflicts({"path": str(self.wt), "raw": {}}, "work", "main")
        self.assertTrue(conflicted, "a driver that runs nothing leaves the 3-way merge conflicted")
        self.assertEqual(self.fired(), [], "worktrunk's merge-tree ran a repo-planted merge driver")

    def test_every_git_launch_is_blanked_whatever_its_subcommand_or_location(self) -> None:
        # Re-attack P3: blanks were computed only for an allowlist of subcommands, and only when
        # the argv named its repo with `-C`. A future `commit` (its `-a` re-stages through the
        # clean filter) or a `cwd=`-launched `checkout` (smudge) would have run the planted filter.
        for key, value in (("user.email", "t@e"), ("user.name", "t")):
            subprocess.run(["git", "-C", str(self.repo), "config", key, value], check=True)
        self.plant()
        (self.wt / "a.txt").write_text("changed\n", encoding="utf-8")
        self.ext.run_cli(["git", "-C", str(self.wt), "commit", "-qam", "w"], provider="git")
        self.assertEqual(self.fired(), [], "a `-C` commit ran the planted clean filter")
        (self.wt / "a.txt").write_text("dirty again\n", encoding="utf-8")
        self.ext.run_cli(["git", "checkout", "--", "a.txt"], provider="git", cwd=str(self.wt))
        self.assertEqual((self.wt / "a.txt").read_text(encoding="utf-8"), "changed\n")
        self.assertEqual(self.fired(), [], "a cwd-launched checkout ran the planted smudge filter")

    def test_the_same_uid_global_config_is_never_read(self) -> None:
        glob = self.config_file("worker-written.gitconfig", (
            ("core.hooksPath", str(self.hooks_dir("globalhooks"))),
            ("core.fsmonitor", self.probe("global-fsmonitor", passthrough=False))))
        later = os.path.getmtime(self.wt / "a.txt") + 5
        os.utime(self.wt / "a.txt", (later, later))
        with unittest.mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(glob)}):
            self.ext.foreign_dirty_paths(self.text_runner, str(self.wt))
            self.ext.preserve_worker_head(self.text_runner, str(self.wt), "disp-2")
        self.assertEqual(self.fired(), [], "an adapter's git read the worker-writable global config")


if __name__ == "__main__":
    unittest.main()
