#!/usr/bin/env python3
"""Real-process tests for the zero-daemon POSIX provider (#580, #590, PR #591 re-review).

Every test here drives REAL processes/git (setsid, tmux when installed) rather than the
dry-run backend, because the gaps the re-review found were all invisible to dry-run:
workers that never got their environment, fences that recorded `stopped` while the agent kept
running, Docker commits that never reached the host, cleanup that deleted unsaved work.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _providers():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return importlib.import_module("runtime.providers")


def _posix():
    _providers()
    return importlib.import_module("runtime.providers.posix")


def _git(*args, cwd, env=None, check=True):
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=check, capture_output=True, text=True)


def _group_alive(pid):
    try:
        os.killpg(int(pid), 0)
        return True
    except OSError:
        return False


def _wait_for(pred, timeout=15.0, step=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(step)
    return False


class PosixRealProcessBase(unittest.TestCase):
    backend = "setsid"

    def setUp(self):
        self.providers = _providers()
        self.posix = _posix()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
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
        self.env = {
            **os.environ,
            "OPEN_FLEET_STATE_DB": str(base / "state" / "runtime.db"),
            "OPEN_FLEET_CLI_CWD": str(self.repo),
            "OPEN_FLEET_POSIX_BACKEND": self.backend,
            "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}",
        }
        self.prov = self.providers.get_provider("posix", env=self.env)
        self.addCleanup(self._kill_all)

    def _kill_all(self):
        # Stop every live worker (retained ones too) and let its monitor finish writing into
        # the temp state dir before the TemporaryDirectory cleanup removes it.
        try:
            for w in self.prov.worker_list()["workers"]:
                if w["state"] in ("ready", "running", "retained"):
                    self.prov.worker_fence("stop", w["dispatchId"])
            with self.prov.state._connect() as conn:
                pids = [r["pid"] for r in conn.execute("SELECT pid FROM dispatches WHERE pid > 0").fetchall()]
            for pid in pids:
                _wait_for(lambda pid=pid: not _group_alive(pid), timeout=10)
        except Exception:
            pass

    def wait_monitor_done(self, dispatch_id, timeout=30.0):
        """The monitor's LAST write is the dispatch state; wait until it has left the live states."""
        return _wait_for(
            lambda: self.prov.state.dispatch_state(dispatch_id) not in ("ready", "running", "retained"),
            timeout=timeout,
        )

    def fake_agent(self, name: str, body: str) -> None:
        """Put a fake `claude` on PATH; `body` is POSIX sh run with the worker's env."""
        path = self.bin / name
        path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8")
        path.chmod(0o755)

    def start(self, spec="do the thing", agent="claude", profile="rw", worktree="new-child", name=None):
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", spec])["task"]
        res = self.prov.dispatch(
            ["orchestration", "worker-start", "--task", task["id"], "--worktree", worktree,
             "--agent", agent, "--profile", profile, "--name", name or task["id"]]
        )
        return task, res


class TestSetsidWorkerLifecycle(PosixRealProcessBase):
    def test_worker_gets_prompt_and_environment(self):
        out = Path(self.tmp.name) / "seen.json"
        self.fake_agent(
            "claude",
            f'python3 -c \'import json,os,sys; json.dump({{"argv": sys.argv[1:], "hook": os.environ.get("OPEN_FLEET_DENY_HOOK"), '
            f'"profile": os.environ.get("OPEN_FLEET_SANDBOX_PROFILE"), "parent": os.environ.get("OPEN_FLEET_PARENT_PROFILE"), '
            f'"dispatch": os.environ.get("OPEN_FLEET_DISPATCH_ID")}}, open("{out}", "w"))\' "$@"',
        )
        _, res = self.start(spec="SENTINEL-SPEC-123")
        self.assertTrue(_wait_for(out.is_file), "fake agent never ran")
        seen = json.loads(out.read_text())
        self.assertIn("SENTINEL-SPEC-123", seen["argv"], "the task spec must reach the agent")
        self.assertEqual(seen["hook"], str(self.posix.CANONICAL_DENY_HOOK), "hook must be the canonical, out-of-worktree path")
        self.assertEqual(seen["profile"], "rw")
        self.assertEqual(seen["parent"], "rw")
        self.assertEqual(seen["dispatch"], res["dispatchId"])

    def test_crash_without_terminal_mail_emits_worker_died_with_head(self):
        self.fake_agent("claude", "exit 3")
        _, res = self.start()
        disp = res["dispatchId"]
        self.assertTrue(_wait_for(lambda: self.prov.worker_show(disp)["worker"]["state"] == "died"))
        mail = self.prov.check_messages(terminal="coordinator")
        died = [m for m in mail["messages"] if m["subject"].startswith(f"worker_died:{disp}")]
        self.assertEqual(len(died), 1)
        payload = json.loads(died[0]["payload"])
        self.assertEqual(payload["exitCode"], 3)
        self.assertRegex(payload["headSha"], r"^[0-9a-f]{40}$")

    def test_fence_stops_process_group_and_suppresses_worker_died(self):
        marker = Path(self.tmp.name) / "still-alive"
        self.fake_agent("claude", f'trap "" TERM HUP; while :; do date > "{marker}"; sleep 0.1; done')
        _, res = self.start()
        disp = res["dispatchId"]
        self.assertTrue(_wait_for(marker.is_file))
        out = self.prov.worker_fence("stop", disp)
        self.assertEqual(out["state"], "stopped")
        stamp = marker.stat().st_mtime
        time.sleep(0.6)
        self.assertEqual(marker.stat().st_mtime, stamp, "agent kept running after stop (SIGKILL escalation missing)")
        self.assertEqual(self.prov.worker_show(disp)["worker"]["state"], "stopped")
        mail = self.prov.check_messages(terminal="coordinator")
        self.assertFalse([m for m in mail["messages"] if disp in m["subject"]], "a fenced exit is not a death")

    def test_retain_never_terminates(self):
        marker = Path(self.tmp.name) / "tick"
        self.fake_agent("claude", f'while :; do date > "{marker}"; sleep 0.1; done')
        _, res = self.start()
        self.assertTrue(_wait_for(marker.is_file))
        self.prov.worker_fence("retain", res["dispatchId"])
        stamp = marker.stat().st_mtime
        self.assertTrue(_wait_for(lambda: marker.stat().st_mtime != stamp, timeout=3))

    def test_launch_gate_refuses_a_dispatch_fenced_before_launch(self):
        ran = Path(self.tmp.name) / "ran"
        self.fake_agent("claude", f'touch "{ran}"')
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        real_spawn = self.prov._spawn_process

        def fence_then_spawn(**kw):
            with self.prov.state._connect() as _c:
                _c.execute(
                "UPDATE dispatches SET state = 'stopped' WHERE dispatch_id = ?", (kw["dispatch_id"],)
            )
            return real_spawn(**kw)

        self.prov._spawn_process = fence_then_spawn
        with self.assertRaises(self.providers.ProviderError) as ctx:
            self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude", profile="rw")
        self.assertEqual(ctx.exception.code, "dispatch_fenced")
        time.sleep(1.0)
        self.assertFalse(ran.exists(), "a fenced dispatch must never run its agent")

    def test_launch_gate_itself_refuses_without_post_spawn_help(self):
        """Drive the generated monitor directly: only the gate stands between a fenced dispatch
        and its agent (the post-spawn teardown must not be what makes this pass)."""
        ran = Path(self.tmp.name) / "gate-ran"
        self.fake_agent("claude", f'touch "{ran}"')
        captured = {}

        def capture(**kw):
            captured.update(kw)
            return {"pid": 0, "backend": "setsid"}

        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        self.prov.runner = None
        real = self.prov._spawn_process
        self.prov._spawn_process = lambda **kw: (captured.update(kw), {"pid": 0, "backend": "dry-run"})[1]
        res = self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude", profile="rw")
        self.prov._spawn_process = real
        disp = res["dispatchId"]
        with self.prov.state._connect() as _c:
            _c.execute("UPDATE dispatches SET state = 'stopped' WHERE dispatch_id = ?", (disp,))
        self.prov.backend = "setsid"
        real(**captured)  # writes run_worker.py and launches it
        lane = Path(captured["lane_dir"])
        self.assertTrue(_wait_for(lambda: "launch_refused" in (lane / "events.jsonl").read_text()))
        time.sleep(0.3)
        self.assertFalse(ran.exists())

    def test_failure_after_spawn_withdraws_dispatch_and_frees_task(self):
        ran = Path(self.tmp.name) / "late"
        self.fake_agent("claude", f'touch "{ran}"')
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        real = self.prov._spawn_process

        def spawn_then_fail(**kw):
            real(**kw)
            raise KeyboardInterrupt()

        self.prov._spawn_process = spawn_then_fail
        with self.assertRaises(KeyboardInterrupt):
            self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude", profile="rw")
        time.sleep(1.0)
        self.assertFalse(ran.exists(), "a withdrawn dispatch must not run its agent")
        self.assertEqual(self.prov.task_list()["tasks"][0]["status"], "ready")
        self.assertEqual(self.prov.check_messages(terminal="coordinator")["count"], 0, "no orphan worker_died")

    def test_fenced_during_startup_returns_task_to_ready(self):
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        self.prov.runner = lambda **kw: (self.prov.worker_fence("stop", kw["dispatch_id"]), {"pid": 0, "backend": "dry-run"})[1]
        with self.assertRaises(self.providers.ProviderError):
            self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude")
        self.assertEqual(self.prov.task_list()["tasks"][0]["status"], "ready")

    def test_starting_tmux_row_is_not_declared_dead(self):
        with self.prov.state._connect() as conn:
            conn.execute(
                "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, pid, backend, created_at, updated_at) "
                "VALUES ('disp_new', 't', 'default', '/w', 'claude', 'term_new', 'ready', 0, 'tmux', 0, 0)"
            )
        self.assertEqual(self.prov.worker_show("disp_new")["worker"]["state"], "ready")
        self.assertEqual(self.prov.check_messages(terminal="coordinator")["count"], 0)

    def test_terminal_state_follows_supervised_exit(self):
        self.fake_agent("claude", "exit 0")
        _, res = self.start()
        handle = res["agentTerminalHandle"]
        self.assertTrue(_wait_for(lambda: self.prov.terminal_show(handle)["terminal"]["state"] == "exited"))
        self.assertTrue(self.prov.terminal_wait(handle, condition="exit", timeout_ms=1000)["wait"]["satisfied"])

    def test_work_injected_into_a_terminal_dies_with_it(self):
        t = self.prov.terminal_create(worktree="current", title="custom", command="sleep 0.8; exit 3")
        handle = t["terminal"]["handle"]
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        with self.prov.state._connect() as conn:  # what dispatch_inject records (tmux/cmux only)
            conn.execute(
                "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, created_at, updated_at) "
                "VALUES ('disp_inj', ?, 'default', '/w', 'custom', ?, 'ready', 0, 0)",
                (task["id"], handle),
            )
        self.assertTrue(_wait_for(lambda: self.prov.state.dispatch_state("disp_inj") == "died"))
        subjects = [m["subject"] for m in self.prov.check_messages(terminal="coordinator")["messages"]]
        self.assertTrue(any(sub.startswith("worker_died:disp_inj") for sub in subjects), subjects)

    def test_fence_of_finished_dispatch_never_kills_a_reused_pid(self):
        bystander = subprocess.Popen(["sleep", "30"], start_new_session=True)
        self.addCleanup(bystander.wait)  # reap it (cleanups run last-in, first-out)
        self.addCleanup(bystander.kill)
        with self.prov.state._connect() as conn:
            conn.execute(
                "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, pid, backend, created_at, updated_at) "
                "VALUES ('disp_old', 't', 'default', '/w', 'claude', 'term_old', 'completed', ?, 'setsid', 0, 0)",
                (bystander.pid,),
            )
        out = self.prov.worker_fence("release", "disp_old")
        self.assertEqual(out["termination"], {"skipped": "dispatch already finished"})
        self.assertIsNone(bystander.poll(), "an unrelated process group was signalled")

    def test_signing_seed_never_reaches_a_worker(self):
        out = Path(self.tmp.name) / "seed.txt"
        self.env["OPEN_FLEET_SIGNING_SEED"] = "00" * 32
        self.env["ORCA_DISPATCH_SIGNING_SEED"] = "11" * 32
        self.prov = self.providers.get_provider("posix", env=self.env)
        self.fake_agent("claude", f'echo "[$OPEN_FLEET_SIGNING_SEED][$ORCA_DISPATCH_SIGNING_SEED]" > "{out}"')
        self.start()
        self.assertTrue(_wait_for(out.is_file))
        self.assertEqual(out.read_text().strip(), "[][]")

    def test_retain_during_startup_does_not_cancel_the_launch(self):
        ran = Path(self.tmp.name) / "retained-ran"
        self.fake_agent("claude", f'touch "{ran}"')
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        real = self.prov._spawn_process

        def retain_then_spawn(**kw):
            self.prov.worker_fence("retain", kw["dispatch_id"])
            return real(**kw)

        self.prov._spawn_process = retain_then_spawn
        res = self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude", profile="rw")
        self.assertEqual(res["state"], "ready")
        self.assertTrue(_wait_for(ran.exists, timeout=30), "retaining a dispatch must not cancel its work")
        self.assertTrue(self.wait_monitor_done(res["dispatchId"]))

    def test_monitor_strips_secrets_inherited_from_its_own_environment(self):
        """A tmux server started with a seed hands it to the monitor's os.environ."""
        out = Path(self.tmp.name) / "inherited.txt"
        self.fake_agent("claude", f'echo "[$OPEN_FLEET_SIGNING_SEED][$ORCA_DISPATCH_SIGNING_SEED]" > "{out}"')
        captured = {}
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        real = self.prov._spawn_process
        self.prov._spawn_process = lambda **kw: (captured.update(kw), {"pid": 0, "backend": "dry-run"})[1]
        self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude", profile="rw")
        self.prov._spawn_process = real
        self.prov.backend = "setsid"
        real(**captured)  # writes run_worker.py (then launches a first copy without secrets)
        disp = captured["dispatch_id"]
        self.assertTrue(_wait_for(out.is_file, timeout=30))
        # Wait for the first monitor's FINAL write (the dispatch state) before re-arming, or its
        # late `died` lands after the re-arm and the launch gate rightly refuses the re-run.
        self.assertTrue(self.wait_monitor_done(disp))
        out.unlink(missing_ok=True)
        script = Path(captured["lane_dir"]) / "run_worker.py"
        # The first run finished (and was recorded); re-arm the dispatch for the inherited-env run.
        with self.prov.state._connect() as _c:
            _c.execute(
            "UPDATE dispatches SET state = 'ready' WHERE lane_dir = ?", (str(captured["lane_dir"]),))
        env = {**os.environ, "PATH": self.env["PATH"], "OPEN_FLEET_SIGNING_SEED": "aa" * 32,
               "ORCA_DISPATCH_SIGNING_SEED": "bb" * 32}
        subprocess.run([sys.executable, "-I", str(script)], env=env, cwd=captured["wt_path"], timeout=120)
        self.assertTrue(out.is_file(), "the re-run is synchronous: its agent has already written")
        self.assertEqual(out.read_text().strip(), "[][]")

    def test_vanished_monitor_is_detected_by_liveness_sweep(self):
        self.fake_agent("claude", "sleep 30")
        _, res = self.start()
        disp = res["dispatchId"]
        with self.prov.state._connect() as conn:
            pid = conn.execute("SELECT pid FROM dispatches WHERE dispatch_id = ?", (disp,)).fetchone()["pid"]
        self.assertGreater(pid, 0)
        os.killpg(pid, 9)
        self.assertTrue(_wait_for(lambda: self.prov.worker_show(disp)["worker"]["state"] == "died"))
        mail = self.prov.check_messages(terminal="coordinator")
        self.assertEqual(len([m for m in mail["messages"] if disp in m["subject"]]), 1)

    def test_setsid_input_is_refused_not_faked(self):
        self.fake_agent("claude", "sleep 5")
        _, res = self.start()
        with self.assertRaises(self.providers.ProviderError) as ctx:
            self.prov.terminal_send(res["agentTerminalHandle"], "hello")
        self.assertEqual(ctx.exception.code, "unsupported_operation")

    def _hermes_user_home(self, config_text):
        user_home = Path(self.tmp.name) / "hermes-user"
        user_home.mkdir(exist_ok=True)
        if config_text is not None:
            (user_home / "config.yaml").write_text(config_text, encoding="utf-8")
        (user_home / ".env").write_text("KEY=secret\n", encoding="utf-8")
        self.env["HERMES_HOME"] = str(user_home)
        self.prov = self.providers.get_provider("posix", env=self.env)
        return user_home

    def _run_fake_hermes(self):
        out = Path(self.tmp.name) / "hermes.txt"
        self.fake_agent("hermes", f'cat "$HERMES_HOME/config.yaml" > "{out}"; echo "ACCEPT=$HERMES_ACCEPT_HOOKS ENV=$(cat "$HERMES_HOME/.env")" >> "{out}"')
        _, res = self.start(agent="hermes")
        self.assertTrue(_wait_for(lambda: out.is_file() and "ACCEPT=" in out.read_text()))
        text = out.read_text()
        cfg = json.loads(text.split("ACCEPT=")[0])  # written as JSON: valid YAML, no emitter needed
        hook = cfg["hooks"]["pre_tool_call"][0]
        self.assertTrue(hook["fail_closed"])
        self.assertIn("ORCA_HOOK_STRICT_EXIT=1", hook["command"])
        self.assertIn(str(self.posix.CANONICAL_DENY_HOOK), hook["command"])
        self.assertIn("ACCEPT=1 ENV=KEY=secret", text)
        return cfg, res

    def test_hermes_gets_fail_closed_hook_in_private_home(self):
        # PyYAML present on the coordinator (stubbed: CI installs no test dependencies).
        stub = types.SimpleNamespace(safe_load=lambda t: json.loads(t) if t.strip() else None)
        user_home = self._hermes_user_home('{"model": "my-model", "hooks": {"pre_tool_call": [{"command": "mine"}]}}')
        with mock.patch.dict(sys.modules, {"yaml": stub}):
            cfg, res = self._run_fake_hermes()
        self.assertEqual(cfg["model"], "my-model", "user config preserved")
        self.assertEqual(cfg["hooks"]["pre_tool_call"][1], {"command": "mine"}, "user's own hooks kept, ours first")
        self.assertNotIn("deny-hook", (user_home / "config.yaml").read_text(), "user's own config untouched")
        self.assertFalse(str(Path(cfg["hooks"]["pre_tool_call"][0]["command"].split("sh ")[-1])).startswith(res["worker"]["worktree"]))

    def test_hermes_without_user_config_needs_no_yaml_parser(self):
        self._hermes_user_home(None)
        with mock.patch.dict(sys.modules, {"yaml": None}):  # `import yaml` raises ImportError
            cfg, _ = self._run_fake_hermes()
        self.assertEqual(list(cfg), ["hooks"])

    def test_hermes_config_parsed_with_hermes_own_interpreter(self):
        stubdir = Path(self.tmp.name) / "yamlstub"
        stubdir.mkdir()
        (stubdir / "yaml.py").write_text("import json\ndef safe_load(f):\n    return json.load(f)\n", encoding="utf-8")
        wrapper = Path(self.tmp.name) / "hermes-python"
        # Stands in for the venv Python Hermes ships with (which has PyYAML).
        wrapper.write_text(f'#!/bin/sh\n[ "$1" = "-I" ] && shift\nPYTHONPATH={stubdir} exec {sys.executable} "$@"\n', encoding="utf-8")
        wrapper.chmod(0o755)
        (self.bin / "hermes").write_text(f"#!{wrapper}\nprint('hermes')\n", encoding="utf-8")
        (self.bin / "hermes").chmod(0o755)
        cfg_file = Path(self.tmp.name) / "c.yaml"
        cfg_file.write_text('{"model": "via-hermes-python"}', encoding="utf-8")
        with mock.patch.dict(sys.modules, {"yaml": None}):
            loaded = self.posix._load_hermes_config(cfg_file, self.env)
        self.assertEqual(loaded, {"model": "via-hermes-python"})

    def test_hermes_with_a_config_and_no_parser_is_refused(self):
        self._hermes_user_home("model: my-model\n")
        self.fake_agent("hermes", "exit 0")  # a shell launcher: no Python to borrow PyYAML from
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        with mock.patch.dict(sys.modules, {"yaml": None}):
            with self.assertRaises(self.providers.ProviderError) as ctx:
                self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="hermes")
        self.assertEqual(ctx.exception.code, "hermes_hooks_unavailable")
        self.assertEqual(self.prov.task_list()["tasks"][0]["status"], "ready", "claim released")

    def test_missing_spec_is_refused_before_claim(self):
        task = self.prov.state.task_create(spec="")["task"]
        with self.assertRaises(self.providers.ProviderError) as ctx:
            self.prov.worker_start(task_id=task["id"], worktree="new-child", agent="claude")
        self.assertEqual(ctx.exception.code, "missing_task_spec")
        self.assertEqual(self.prov.task_list()["tasks"][0]["status"], "ready")

    def test_terminal_create_runs_and_exits_without_worker_died(self):
        t = self.prov.terminal_create(worktree="current", title="custom", command="echo hello-term")
        handle = t["terminal"]["handle"]
        self.assertTrue(_wait_for(lambda: self.prov.terminal_show(handle)["terminal"]["state"] == "exited"))
        self.assertIn("hello-term", "\n".join(self.prov.terminal_read(handle)["terminal"]["tail"]))
        self.assertEqual(self.prov.check_messages(terminal="coordinator")["count"], 0)


class TestTmuxWorkerLifecycle(PosixRealProcessBase):
    """The worker env travels inside the monitor script, so a tmux server that is ALREADY
    running (which ignores the client's env — the original bug) still hands it over."""

    backend = "tmux"

    def setUp(self):
        super().setUp()
        self.has_tmux = bool(shutil.which("tmux"))
        if not self.has_tmux:
            # No tmux on this host: exercise the same env-file mechanism through setsid.
            self.env["OPEN_FLEET_POSIX_BACKEND"] = "setsid"
        else:
            self.env["TMUX_TMPDIR"] = self.tmp.name
            os.environ["TMUX_TMPDIR"] = self.tmp.name
            self.addCleanup(lambda: os.environ.pop("TMUX_TMPDIR", None))
            subprocess.run(["tmux", "new-session", "-d", "-s", "preexisting"], env={**os.environ}, check=True)
            self.addCleanup(lambda: subprocess.run(["tmux", "kill-server"], capture_output=True))
        self.prov = self.providers.get_provider("posix", env=self.env)

    def test_env_survives_preexisting_tmux_server_and_stop_kills(self):
        out = Path(self.tmp.name) / "env.txt"
        self.fake_agent(
            "claude",
            f'echo "$OPEN_FLEET_DENY_HOOK|$OPEN_FLEET_SANDBOX_PROFILE" > "{out}"; trap "" HUP TERM; while :; do sleep 0.1; done',
        )
        _, res = self.start()
        self.assertTrue(_wait_for(out.is_file))
        hook, profile = out.read_text().strip().split("|")
        self.assertEqual(hook, str(self.posix.CANONICAL_DENY_HOOK))
        self.assertEqual(profile, "rw")
        with self.prov.state._connect() as conn:
            lane = Path(conn.execute("SELECT lane_dir FROM dispatches WHERE dispatch_id = ?", (res["dispatchId"],)).fetchone()["lane_dir"])
        env_file = lane / "worker_env.json"
        self.assertEqual(json.loads(env_file.read_text())["OPEN_FLEET_DENY_HOOK"], hook)
        self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
        self.prov.worker_fence("stop", res["dispatchId"])
        stamp = out.stat().st_mtime
        if self.has_tmux:
            sess = f"openfleet-{res['agentTerminalHandle']}"
            self.assertNotEqual(subprocess.run(["tmux", "has-session", "-t", sess], capture_output=True).returncode, 0)
        self.assertEqual(self.prov.worker_show(res["dispatchId"])["worker"]["state"], "stopped")
        self.assertEqual(out.stat().st_mtime, stamp)


class TestWorktreeSafety(PosixRealProcessBase):
    def test_hook_artifacts_are_git_excluded(self):
        wt = Path(self.prov.worktree_create("art")["worktree"]["path"])
        self.posix.install_worktree_hooks(wt, "claude", "rw")
        status = _git("status", "--porcelain", cwd=wt).stdout
        self.assertEqual(status.strip(), "", f"hook artifacts leak into git status: {status}")
        self.assertFalse((wt / ".open-fleet" / "hooks").exists())

    def test_rm_refuses_main_checkout_even_with_force_and_dotdot(self):
        with self.assertRaises(self.providers.ProviderError):
            self.prov.worktree_rm(f"path:{self.repo}/../{self.repo.name}", force=True)
        self.assertTrue((self.repo / "README.md").is_file())

    def test_rm_keeps_dirty_worktree_and_removes_clean_one(self):
        wt = Path(self.prov.worktree_create("dirty")["worktree"]["path"])
        self.posix.install_worktree_hooks(wt, "claude", "rw")
        (wt / "unsaved.txt").write_text("work", encoding="utf-8")
        with self.assertRaises(self.providers.ProviderError) as ctx:
            self.prov.worktree_rm(f"path:{wt}")
        self.assertEqual(ctx.exception.code, "worktree_dirty")
        self.assertTrue((wt / "unsaved.txt").is_file())
        (wt / "unsaved.txt").unlink()
        self.assertTrue(self.prov.worktree_rm(f"path:{wt}")["removed"], "hook artifacts alone must not count as dirty")

    def test_only_exact_generated_files_count_as_disposable(self):
        ext = importlib.import_module("runtime.providers._external")
        ov = importlib.import_module("runtime.providers.overstory")
        wt = Path(self.prov.worktree_create("exact")["worktree"]["path"])
        self.posix.install_worktree_hooks(wt, "claude", "rw")
        for rel in ("AGENTS.md", ".claude/CLAUDE.md", "AGENTS.md.backup", ".claude/commands/mine.md", ".codex/config.toml"):
            (wt / rel).parent.mkdir(parents=True, exist_ok=True)
            (wt / rel).write_text("x", encoding="utf-8")

        def run(argv):
            return subprocess.run(argv, capture_output=True, text=True).stdout

        dirty = ext.foreign_dirty_paths(run, str(wt), ov.OV_ARTIFACTS)
        self.assertIn("AGENTS.md.backup", dirty)
        self.assertIn(".claude/commands/mine.md", dirty)
        self.assertIn(".codex/config.toml", dirty, "a user file in .codex/ is never exempted (nor git-excluded)")
        self.assertNotIn("AGENTS.md", dirty)
        self.assertNotIn(".claude/CLAUDE.md", dirty)
        self.assertNotIn(".claude/settings.local.json", dirty)

    def test_rm_refuses_paths_outside_provider_base(self):
        stray = Path(self.tmp.name) / "stray"
        stray.mkdir()
        (stray / "keep").write_text("x", encoding="utf-8")
        with self.assertRaises(self.providers.ProviderError):
            self.prov.worktree_rm(f"path:{stray}", force=True)
        self.assertTrue((stray / "keep").exists())

    def test_create_never_resets_existing_branch(self):
        wt = Path(self.prov.worktree_create("keep")["worktree"]["path"])
        (wt / "f.txt").write_text("1", encoding="utf-8")
        _git("add", "f.txt", cwd=wt)
        _git("commit", "-qm", "unit work", cwd=wt)
        head = _git("rev-parse", "HEAD", cwd=wt).stdout.strip()
        _git("worktree", "remove", str(wt), cwd=self.repo)
        again = Path(self.prov.worktree_create("keep")["worktree"]["path"])
        self.assertEqual(_git("rev-parse", "HEAD", cwd=again).stdout.strip(), head)

    def test_create_refuses_stale_non_worktree_dir(self):
        base = self.prov._worktree_base_dir() / "stale"
        base.mkdir(parents=True)
        with self.assertRaises(self.providers.ProviderError):
            self.prov.worktree_create("stale")

    def test_bad_base_raises(self):
        with self.assertRaises(self.providers.ProviderError) as ctx:
            self.prov.worktree_create("bad", base="no-such-ref")
        self.assertEqual(ctx.exception.code, "worktree_create_failed")


class TestSandboxGitRoundTrip(PosixRealProcessBase):
    """The container's private git dir: commits reach the host, the host repo stays untouched."""

    def _sandbox(self):
        wt = Path(self.prov.worktree_create("sbx")["worktree"]["path"])
        lane = Path(self.tmp.name) / "lane"
        lane.mkdir()
        meta = self.posix.prepare_sandbox_git(str(wt), lane)
        cenv = {**os.environ, "GIT_DIR": meta["sandbox_git"], "GIT_WORK_TREE": str(wt),
                "GIT_AUTHOR_NAME": "w", "GIT_AUTHOR_EMAIL": "w@x", "GIT_COMMITTER_NAME": "w", "GIT_COMMITTER_EMAIL": "w@x"}
        return wt, meta, cenv

    def test_commit_inside_sandbox_reaches_host_branch(self):
        wt, meta, cenv = self._sandbox()
        self.assertTrue((wt / ".git").is_file(), "host pointer untouched")
        (wt / "feature.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "feature.txt"], cwd=wt, env=cenv, check=True)
        subprocess.run(["git", "commit", "-qm", "feature"], cwd=wt, env=cenv, check=True)
        new = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, env=cenv, check=True, capture_output=True, text=True).stdout.strip()
        res = self.posix.sync_sandbox_git(meta, "disp_x")
        self.assertEqual(res["head"], new)
        self.assertTrue(res["branchUpdated"])
        self.assertEqual(_git("rev-parse", "refs/heads/fleet/sbx", cwd=self.repo).stdout.strip(), new)
        self.assertEqual(_git("rev-parse", "refs/open-fleet/sandbox/disp_x", cwd=self.repo).stdout.strip(), new)
        self.assertEqual(_git("status", "--porcelain", cwd=wt).stdout.strip(), "", "host index refreshed")
        _git("merge-base", "--is-ancestor", "main", new, cwd=self.repo)

    def test_planted_hooks_and_config_are_stripped_before_host_reads(self):
        wt, meta, cenv = self._sandbox()
        sb = Path(meta["sandbox_git"])
        pwned = Path(self.tmp.name) / "pwned"
        (sb / "hooks").mkdir(exist_ok=True)
        for hook in ("post-checkout", "reference-transaction", "pre-auto-gc"):
            (sb / "hooks" / hook).write_text(f"#!/bin/sh\ntouch {pwned}\n", encoding="utf-8")
            (sb / "hooks" / hook).chmod(0o755)
        with open(sb / "config", "a", encoding="utf-8") as fh:
            fh.write(f"[core]\n\tfsmonitor = touch {pwned}\n\thooksPath = {sb / 'hooks'}\n")
        self.posix.sync_sandbox_git(meta, "disp_y")
        self.assertFalse(pwned.exists(), "host git executed sandbox-planted code")
        self.assertFalse((sb / "hooks").exists())

    def test_symlink_planted_in_sandbox_is_refused_and_host_untouched(self):
        wt, meta, cenv = self._sandbox()
        victim = Path(self.tmp.name) / "victim.txt"
        victim.write_text("precious\n", encoding="utf-8")
        cfg = Path(meta["sandbox_git"]) / "config"
        cfg.unlink()
        cfg.symlink_to(victim)
        with self.assertRaises(self.providers.ProviderError) as ctx:
            self.posix.sync_sandbox_git(meta, "disp_s")
        self.assertEqual(ctx.exception.code, "sandbox_git_tampered")
        self.assertEqual(victim.read_text(), "precious\n")
        info = Path(meta["sandbox_git"]) / "info"
        shutil.rmtree(info, ignore_errors=True)
        cfg.unlink()
        cfg.write_text("[core]\n\tbare = true\n", encoding="utf-8")
        info.symlink_to(Path(self.tmp.name))
        with self.assertRaises(self.providers.ProviderError):
            self.posix.sync_sandbox_git(meta, "disp_s2")
        self.assertTrue(victim.exists())

    def test_decoy_dot_git_cannot_choose_the_recorded_commit(self):
        wt, meta, cenv = self._sandbox()
        (wt / "real.txt").write_text("real\n", encoding="utf-8")
        subprocess.run(["git", "add", "real.txt"], cwd=wt, env=cenv, check=True)
        subprocess.run(["git", "commit", "-qm", "real"], cwd=wt, env=cenv, check=True)
        real = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, env=cenv, check=True, capture_output=True, text=True).stdout.strip()
        decoy = Path(meta["sandbox_git"]) / ".git"
        subprocess.run(["git", "init", "-q", "--bare", str(decoy)], check=True)
        dwt = Path(self.tmp.name) / "decoy-wt"
        dwt.mkdir()
        denv = {**cenv, "GIT_DIR": str(decoy), "GIT_WORK_TREE": str(dwt)}
        (dwt / "evil.txt").write_text("evil\n", encoding="utf-8")
        subprocess.run(["git", "add", "evil.txt"], cwd=dwt, env=denv, check=True)
        subprocess.run(["git", "commit", "-qm", "evil"], cwd=dwt, env=denv, check=True)
        res = self.posix.sync_sandbox_git(meta, "disp_d")
        self.assertEqual(res["head"], real)
        self.assertEqual(_git("rev-parse", "refs/open-fleet/sandbox/disp_d", cwd=self.repo).stdout.strip(), real)

    def test_stopping_a_sandboxed_worker_still_syncs_its_commits(self):
        """Stop = remove the container, let the host monitor finish the sync, THEN kill it."""
        wt, meta, cenv = self._sandbox()
        (wt / "work.txt").write_text("done\n", encoding="utf-8")
        subprocess.run(["git", "add", "work.txt"], cwd=wt, env=cenv, check=True)
        subprocess.run(["git", "commit", "-qm", "work"], cwd=wt, env=cenv, check=True)
        new = subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, env=cenv, check=True, capture_output=True, text=True).stdout.strip()
        docker_log = Path(self.tmp.name) / "docker.log"
        self.fake_agent("docker", f'echo "$*" >> "{docker_log}"')
        lane = Path(meta["sandbox_git"]).parent
        with self.prov.state._connect() as conn:
            conn.execute(
                "INSERT INTO dispatches(dispatch_id, task_id, run_id, worktree, agent, terminal_handle, state, created_at, updated_at) "
                "VALUES ('disp_sbx', 't', 'default', ?, 'claude', 'term_sbx', 'ready', 0, 0)",
                (str(wt),),
            )
        # The "agent" stands in for `docker run`: it returns once the container is removed.
        spawn = self.prov._spawn_process(
            dispatch_id="disp_sbx", term_handle="term_sbx", wt_path=str(wt), command="sleep 1",
            env_vars={}, lane_dir=lane, run_id="default", sandbox_meta=meta,
        )
        time.sleep(0.4)  # monitor is waiting on the agent
        report = self.prov._terminate_backend(
            "setsid", "term_sbx", spawn["pid"], container="openfleet-disp_sbx", lane_dir=str(lane), grace_s=0.5,
        )
        self.assertIn("rm -f openfleet-disp_sbx", docker_log.read_text())
        self.assertEqual(report["sandboxSync"].get("headSha"), new, report)
        self.assertEqual(_git("rev-parse", "refs/heads/fleet/sbx", cwd=self.repo).stdout.strip(), new)

    def test_history_rewrite_does_not_move_host_branch(self):
        wt, meta, cenv = self._sandbox()
        base = _git("rev-parse", "refs/heads/fleet/sbx", cwd=self.repo).stdout.strip()
        subprocess.run(["git", "commit", "-q", "--amend", "-m", "rewritten", "--allow-empty"], cwd=wt, env=cenv, check=True)
        res = self.posix.sync_sandbox_git(meta, "disp_z")
        self.assertTrue(res["nonFastForward"])
        self.assertEqual(_git("rev-parse", "refs/heads/fleet/sbx", cwd=self.repo).stdout.strip(), base)

    def test_danger_refuses_main_checkout_and_foreign_paths(self):
        task = self.prov.dispatch(["orchestration", "task-create", "--spec", "x"])["task"]
        for wt in ("current", f"path:{self.repo}"):
            with self.assertRaises(self.providers.ProviderError) as ctx:
                self.prov.worker_start(task_id=task["id"], worktree=wt, agent="claude", profile="danger", on_env="img")
            self.assertEqual(ctx.exception.code, "danger_requires_linked_worktree")
        self.assertEqual(self.prov.task_list()["tasks"][0]["status"], "ready", "claim released on refusal")


class TestPosixDoctorFailsClosed(PosixRealProcessBase):
    def test_doctor_reports_fail_without_docker(self):
        env = {**self.env, "PATH": str(self.bin)}
        prov = self.providers.get_provider("posix", env=env)
        res = prov.vm_recipe_doctor("img:latest")
        self.assertFalse(res["ok"])
        self.assertTrue(res["failures"])

    def test_base_provider_doctor_never_certifies(self):
        base = importlib.import_module("runtime.providers.base")
        with self.assertRaises(base.ProviderError):
            base.RuntimeProvider().vm_recipe_doctor("anything")


if __name__ == "__main__":
    unittest.main()
