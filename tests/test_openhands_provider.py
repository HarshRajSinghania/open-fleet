#!/usr/bin/env python3
"""#584 acceptance: OpenHandsProvider (agent-server REST API).

Verifies PROFILE=ro strips write/terminal tools, the request's `hook_config` runs `deny-hook.sh`
and blocks via exit code 2 (executed for real against the hook), NeverConfirm is requested, the
task spec reaches the conversation, danger is refused unless the server runs docker
conversations, event logs convert into worker_ops transcripts, and bad responses are ok:false.
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
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

base = importlib.import_module("runtime.providers.base")
local_state = importlib.import_module("runtime.providers.local_state")
openhands = importlib.import_module("runtime.providers.openhands")
ProviderError = base.ProviderError


def _load_worker_ops():
    spec = importlib.util.spec_from_file_location("worker_ops_t584", ROOT / "runtime" / "scripts" / "worker_ops.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


WORKER_OPS = _load_worker_ops()
SPEC = "Review the auth middleware for token replay; do not modify files."
ENV = {"OPEN_FLEET_OPENHANDS_MODEL": "anthropic/claude-test"}

EVENTS = {
    "items": [
        {"kind": "MessageEvent", "id": "e1", "source": "user",
         "llm_message": {"role": "user", "content": [{"type": "text", "text": SPEC}]}},
        {"kind": "ActionEvent", "id": "e2", "source": "agent", "tool_name": "grep",
         "thought": [{"type": "text", "text": "Searching for nonce checks."}],
         "action": {"kind": "GrepAction", "pattern": "nonce"}},
        {"kind": "ObservationEvent", "id": "e3", "source": "environment", "tool_name": "grep",
         "observation": {"kind": "GrepObservation", "content": [{"type": "text", "text": "auth.py:12: nonce"}]}},
        {"kind": "ActionEvent", "id": "e4", "source": "agent", "tool_name": "finish",
         "action": {"kind": "FinishAction", "message": "Replay is possible when nonce is absent."}},
    ],
    "next_page_id": "page-2",
}


class HttpScript:
    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = dict(routes)
        self.reqs: list[dict[str, Any]] = []

    def __call__(self, req: dict[str, Any], **_kw: Any) -> Any:
        self.reqs.append(req)
        path = str(req["path"]).split("?", 1)[0]
        key = (req["method"], path)
        if key not in self.routes:
            raise AssertionError(f"unexpected request {key}")
        resp = self.routes[key]
        if isinstance(resp, BaseException):
            raise resp
        return resp

    def find(self, method: str, path: str) -> list[dict[str, Any]]:
        return [r for r in self.reqs if r["method"] == method and str(r["path"]).split("?", 1)[0] == path]


class TestOpenHandsProvider(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.state = local_state.LocalStateStore(db_path=self.tmp / "state.db")
        self.wt = self.tmp / "oh-wt"
        self.wt.mkdir()
        self.http = HttpScript(
            {
                ("POST", "/api/conversations"): {"id": "conv-99", "execution_status": "idle", "workspace": {"working_dir": str(self.wt)}},
                ("POST", "/api/conversations/conv-99/run"): {"success": True},
                ("GET", "/api/conversations/conv-99"): {"id": "conv-99", "execution_status": "running", "workspace": {"working_dir": str(self.wt)}},
                ("GET", "/api/conversations/conv-99/events/search"): EVENTS,
                ("POST", "/api/conversations/conv-99/interrupt"): {"success": True},
                ("GET", "/api/conversations/search"): {"items": [{"id": "conv-99"}], "next_page_id": None},
                ("GET", "/server_info"): {"conversation_runtime": "local"},
            }
        )
        self.hook_calls: list[tuple[str, str, str]] = []
        self.prov = openhands.OpenHandsProvider(state=self.state, runner=self.http, env=ENV, install_hooks=self.fake_hooks)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def fake_hooks(self, wt: str, agent: str, profile: str) -> dict[str, str]:
        self.hook_calls.append((wt, agent, profile))
        return {"openhands": str(Path(wt) / ".openhands" / "hooks.json")}

    def test_ro_strips_tools_never_confirms_and_carries_spec(self) -> None:
        tid = self.prov.dispatch(["orchestration", "task-create", "--spec", SPEC])["task"]["id"]
        res = self.prov.dispatch(
            ["orchestration", "worker-start", "--task", tid, "--worktree", str(self.wt), "--profile", "ro"], env={}
        )
        body = self.http.find("POST", "/api/conversations")[0]["body"]
        names = [t["name"] for t in body["agent"]["tools"]]
        self.assertEqual(names, ["glob", "grep", "planning_file_editor"])
        for forbidden in ("terminal", "file_editor", "apply_patch"):
            self.assertNotIn(forbidden, names)
        self.assertEqual(body["confirmation_policy"], {"kind": "NeverConfirm"})
        self.assertEqual(body["initial_message"]["content"][0]["text"], SPEC)
        self.assertEqual(body["workspace"], {"working_dir": str(self.wt)})
        self.assertFalse(body["worktree"])
        self.assertEqual(body["agent"]["llm"]["model"], "anthropic/claude-test")
        self.assertTrue(all(k.isalnum() and k.islower() for k in body["tags"]))
        self.assertTrue(self.http.find("POST", "/api/conversations/conv-99/run"))
        self.assertEqual(res["dispatchId"], "conv-99")
        self.assertEqual(res["worktree"], str(self.wt))
        self.assertEqual(self.hook_calls, [(str(self.wt), "claude", "ro")])

    def test_hook_config_invokes_deny_hook_with_exit_2(self) -> None:
        self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="rw")
        cfg = self.http.find("POST", "/api/conversations")[0]["body"]["hook_config"]
        entry = cfg["pre_tool_use"][0]
        self.assertEqual(entry["matcher"], "*")
        hook = entry["hooks"][0]
        self.assertEqual(hook["type"], "command")
        self.assertIn("deny-hook.sh", hook["command"])
        self.assertNotIn("action", json.dumps(cfg))  # no fake {"action":"deny"} config

        def run_hook(command: str, event: dict[str, Any]) -> subprocess.CompletedProcess:
            # Exactly how OpenHands' HookExecutor runs it: shell=True, event JSON on stdin.
            env = {**os.environ, "OPENHANDS_PROJECT_DIR": str(self.wt)}
            return subprocess.run(command, shell=True, input=json.dumps(event), capture_output=True, text=True, env=env, cwd=str(self.wt), timeout=60)

        outside = run_hook(hook["command"], {"event_type": "PreToolUse", "tool_name": "file_editor",
                                             "tool_input": {"command": "create", "path": "/etc/passwd-open-fleet-probe", "file_text": "x"}})
        self.assertEqual(outside.returncode, 2, outside.stdout + outside.stderr)
        rm = run_hook(hook["command"], {"event_type": "PreToolUse", "tool_name": "terminal", "tool_input": {"command": "rm -rf /"}})
        self.assertEqual(rm.returncode, 2)
        inside = run_hook(hook["command"], {"event_type": "PreToolUse", "tool_name": "file_editor",
                                            "tool_input": {"command": "create", "path": str(self.wt / "ok.py"), "file_text": "x"}})
        self.assertEqual(inside.returncode, 0, inside.stdout + inside.stderr)

        missing = openhands.deny_hook_config("rw", hook_path=str(self.tmp / "no-such-hook.sh"), unit_worktree=str(self.wt))
        gone = run_hook(missing["pre_tool_use"][0]["hooks"][0]["command"], {"tool_name": "terminal", "tool_input": {"command": "ls"}})
        self.assertEqual(gone.returncode, 2, "a missing hook script must block (fail closed)")

    def test_new_child_uses_server_worktree_and_records_real_path(self) -> None:
        self.http.routes[("POST", "/api/conversations")] = {
            "id": "conv-99", "workspace": {"working_dir": "/tmp/conversation-worktrees/conv-99/repo"},
        }
        res = self.prov.worker_start(task_id="", prompt=SPEC, profile="rw")
        body = self.http.find("POST", "/api/conversations")[0]["body"]
        self.assertTrue(body["worktree"])
        self.assertIn("$OPENHANDS_PROJECT_DIR", body["hook_config"]["pre_tool_use"][0]["hooks"][0]["command"])
        self.assertEqual(res["worktree"], "/tmp/conversation-worktrees/conv-99/repo")
        self.assertNotEqual(res["worktree"], "new-child")

    def test_danger_requires_docker_conversation_runtime(self) -> None:
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="danger")
        self.assertEqual(ctx.exception.code, "sandbox_unavailable")
        self.assertFalse(self.http.find("POST", "/api/conversations"))
        with self.assertRaises(ProviderError) as ctx2:
            self.prov.worker_start(task_id="", prompt=SPEC, profile="danger", workspace_type="apptainer")
        self.assertEqual(ctx2.exception.code, "unsupported_workspace_type")
        with self.assertRaises(ProviderError) as ctx3:
            self.prov.worker_start(task_id="", prompt=SPEC, profile="danger", workspace_type="host")
        self.assertEqual(ctx3.exception.code, "invalid_workspace_type")

        self.http.routes[("GET", "/server_info")] = {"conversation_runtime": "docker"}
        res = self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="danger")
        body = self.http.find("POST", "/api/conversations")[-1]["body"]
        self.assertNotIn("hook_config", body)
        self.assertEqual(res["launch"]["effective"]["conversation_runtime"], "docker")

    def test_missing_llm_and_missing_spec_fail_closed(self) -> None:
        prov = openhands.OpenHandsProvider(state=self.state, runner=self.http, env={})
        with self.assertRaises(ProviderError) as ctx:
            prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="ro")
        self.assertEqual(ctx.exception.code, "missing_llm_config")
        with self.assertRaises(ProviderError) as ctx2:
            self.prov.worker_start(task_id="task_none", worktree=str(self.wt))
        self.assertEqual(ctx2.exception.code, "missing_task_spec")

    def test_events_convert_to_transcript(self) -> None:
        self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="ro")
        read = self.prov.dispatch(["orchestration", "worker-read", "--dispatch", "conv-99", "--transcript", "--limit", "10"])
        lines = WORKER_OPS.format_read(read, want="transcript")
        text = "\n".join(lines)
        self.assertIn("CURSOR=page-2", lines)
        self.assertIn("Searching for nonce checks.", text)
        self.assertIn("auth.py:12: nonce", text)
        self.assertIn("Replay is possible", text)
        path = self.http.find("GET", "/api/conversations/conv-99/events/search")[0]["path"]
        self.assertIn("limit=10", path)
        self.assertIn("sort_order=TIMESTAMP", path)

        show = WORKER_OPS.format_show(self.prov.dispatch(["orchestration", "worker-show", "--dispatch", "conv-99"]))
        self.assertIn("DISPATCH=conv-99", show)
        self.assertIn("STAGE=running", show)

    def test_fence_retain_interrupt_and_unknown(self) -> None:
        self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="ro")
        before = len(self.http.reqs)
        self.assertEqual(self.prov.worker_fence(verb="retain", dispatch_id="conv-99")["state"], "retained")
        self.assertEqual(len(self.http.reqs), before)
        released = self.prov.worker_fence(verb="release", dispatch_id="conv-99", reason="done")
        self.assertEqual(released["state"], "released")
        self.assertEqual(len(self.http.find("POST", "/api/conversations/conv-99/interrupt")), 1)
        self.assertFalse([r for r in self.http.reqs if r["method"] == "DELETE"])
        for call in (
            lambda: self.prov.worker_fence(verb="stop", dispatch_id="conv-x"),
            lambda: self.prov.worker_read(dispatch_id="conv-x"),
            lambda: self.prov.worker_show(dispatch_id="conv-x"),
        ):
            with self.assertRaises(ProviderError) as ctx:
                call()
            self.assertEqual(ctx.exception.code, "dispatch_not_found")

    def test_worker_list_is_our_dispatches_not_every_server_conversation(self) -> None:
        self.http.routes[("GET", "/api/conversations/search")] = {
            "items": [{"id": "conv-99", "execution_status": "running"}, {"id": "conv-someone-else", "execution_status": "idle"}],
            "next_page_id": "page-2",
        }
        self.assertEqual(self.prov.worker_list()["workers"], [])  # nothing dispatched by open-fleet yet
        tid = self.prov.dispatch(["orchestration", "task-create", "--spec", SPEC])["task"]["id"]
        self.prov.worker_start(task_id=tid, worktree=str(self.wt), profile="ro")
        listed = self.prov.dispatch(["orchestration", "worker-list"])
        self.assertEqual(WORKER_OPS.format_list(listed), ["ROWS=1", "SCOPE=openhands", "NEXT_CURSOR=none", f"conv-99 {tid} active"])
        self.assertEqual(listed["workers"][0]["stage"], "running")
        self.http.routes[("GET", "/api/conversations/search")] = {"conversations": []}
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_list()
        self.assertEqual(ctx.exception.code, "openhands_bad_json")

    def test_bad_responses_are_errors(self) -> None:
        self.http.routes[("POST", "/api/conversations")] = {"execution_status": "idle"}
        with self.assertRaises(ProviderError) as ctx:
            self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="rw")
        self.assertEqual(ctx.exception.code, "upstream_no_id")
        self.assertFalse(ctx.exception.to_envelope()["ok"])
        self.http.routes[("POST", "/api/conversations")] = "<html>gateway</html>"
        with self.assertRaises(ProviderError) as ctx2:
            self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="rw")
        self.assertEqual(ctx2.exception.code, "openhands_bad_json")
        self.http.routes[("POST", "/api/conversations")] = TimeoutError("slow")
        with self.assertRaises(ProviderError) as ctx3:
            self.prov.worker_start(task_id="", worktree=str(self.wt), prompt=SPEC, profile="rw")
        self.assertEqual(ctx3.exception.code, "openhands_unreachable")


if __name__ == "__main__":
    unittest.main()
