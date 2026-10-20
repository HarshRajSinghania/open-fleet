#!/usr/bin/env python3
"""Contract tests and negative controls for multi-harness hooks, local session search,
portable sandbox doctor, predictive merge, privilege narrowing, and CI nudge dedup
(#577, #581, #585, #590).
"""
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"
PROVIDERS = ROOT / "runtime" / "providers"
DENY_HOOK = SCRIPTS / "deny-hook.sh"
WTREE_SH = SCRIPTS / "wtree.sh"
SEARCH_PY = SCRIPTS / "search_sessions.py"
DOCTOR_PY = SCRIPTS / "sandbox_doctor.py"
DIFF_SCOPE_PY = SCRIPTS / "diff_scope.py"
DISPATCH_SIGN_PY = SCRIPTS / "dispatch-sign.py"
WATCHDOG_PY = SCRIPTS / "watchdog.py"
LOCAL_STATE_PY = PROVIDERS / "local_state.py"


def _load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestMultiHarnessDenyHook(unittest.TestCase):
    """#577 & #590: multi-harness PreToolUse normalization, patch headers, strict mode,
    --verify-settings across harnesses, and LocalStateStore.record_file_touch."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.wt = self.tmp / "worktree"
        self.wt.mkdir()
        self.outside = self.tmp / "outside"
        self.outside.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_hook(self, payload, extra_env=None):
        env = dict(os.environ)
        for k in (
            "ORCA_UNIT_WORKTREE",
            "OPEN_FLEET_UNIT_WORKTREE",
            "ORCA_EGRESS_LEDGER",
            "OPEN_FLEET_EGRESS_LEDGER",
            "OPEN_FLEET_STATE_DB",
            "ORCA_FLEET_STATE_DB",
            "JCODE_HOOK_TOOL_NAME",
            "GOOSE_MODE",
            "CODEX_CI",
            "CODEX_SANDBOX",
            "OPEN_FLEET_HEADLESS_STRICT",
            "ORCA_HOOK_STRICT_EXIT",
            "OPEN_FLEET_HOOK_EXIT2",
        ):
            env.pop(k, None)
        if extra_env:
            env.update(extra_env)
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            ["sh", str(DENY_HOOK)],
            input=text,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.wt),
            timeout=30,
        )

    def test_shell_tool_aliases_and_cmd_field_enforced(self):
        for tool_name, field in (
            ("bash", "command"),
            ("shell", "command"),
            ("terminal", "command"),
            ("exec_command", "cmd"),
        ):
            with self.subTest(tool=tool_name, field=field):
                res = self.run_hook(
                    {"tool_name": tool_name, "tool_input": {field: "rm -rf /"}},
                    {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
                )
                # Non-Claude shell tool names are strict (#577): a deny exits 2, so harnesses
                # that ignore the JSON decision (Codex/Goose/Hermes) still block.
                self.assertEqual(res.returncode, 2)
                parsed = json.loads(res.stdout)
                self.assertEqual(parsed["decision"], "deny")
                self.assertEqual(
                    parsed["hookSpecificOutput"]["permissionDecision"], "deny"
                )

                # Negative control: redirect outside OPEN_FLEET_UNIT_WORKTREE is denied
                esc = self.outside / "pwn.txt"
                res_redir = self.run_hook(
                    {
                        "tool_name": tool_name,
                        "tool_input": {field: f"echo hi > {esc}"},
                    },
                    {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
                )
                self.assertEqual(
                    json.loads(res_redir.stdout)["hookSpecificOutput"][
                        "permissionDecision"
                    ],
                    "deny",
                )

    def test_write_and_edit_tool_aliases_and_path_fields_enforced(self):
        inside_file = str(self.wt / "ok.py")
        outside_file = str(self.outside / "escape.py")
        cases = [
            ("write", {"path": outside_file}, {"path": inside_file}),
            ("edit", {"filePath": outside_file}, {"filePath": inside_file}),
            ("replace", {"file_path": outside_file}, {"file_path": inside_file}),
            ("write_file", {"path": outside_file}, {"path": inside_file}),
            (
                "multiedit",
                {"edits": [{"path": inside_file}, {"path": outside_file}]},
                {"edits": [{"path": inside_file}]},
            ),
            (
                "file_editor",
                {"command": "str_replace", "path": outside_file},
                {"command": "str_replace", "path": inside_file},
            ),
        ]
        for tool_name, bad_input, good_input in cases:
            with self.subTest(tool=tool_name):
                bad = self.run_hook(
                    {"tool_name": tool_name, "tool_input": bad_input},
                    {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
                )
                self.assertEqual(
                    json.loads(bad.stdout)["hookSpecificOutput"]["permissionDecision"],
                    "deny",
                )
                good = self.run_hook(
                    {"tool_name": tool_name, "tool_input": good_input},
                    {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
                )
                self.assertEqual(good.stdout.strip(), "")

        # OpenHands file_editor view command is read-only and allowed outside worktree
        view_res = self.run_hook(
            {
                "tool_name": "file_editor",
                "tool_input": {"command": "view", "path": outside_file},
            },
            {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
        )
        self.assertEqual(view_res.stdout.strip(), "")

    def test_apply_patch_and_unified_diff_headers_enforced(self):
        inside_file = str(self.wt / "patched.py")
        outside_file = str(self.outside / "escaped.py")

        codex_bad_patch = (
            f"*** Begin Patch\n"
            f"*** Update File: {inside_file}\n"
            f"@@\n-old\n+new\n"
            f"*** Add File: {outside_file}\n"
            f"+escaped\n"
            f"*** End Patch\n"
        )
        r_bad = self.run_hook(
            {"tool_name": "apply_patch", "tool_input": {"patch": codex_bad_patch}},
            {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
        )
        self.assertEqual(
            json.loads(r_bad.stdout)["hookSpecificOutput"]["permissionDecision"], "deny"
        )

        unified_bad_patch = (
            f"--- a/{inside_file}\n"
            f"+++ b/{outside_file}\n"
            f"@@ -1 +1 @@\n-a\n+b\n"
        )
        r_ubad = self.run_hook(
            {"tool_name": "patch", "tool_input": {"diff": unified_bad_patch}},
            {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
        )
        self.assertEqual(
            json.loads(r_ubad.stdout)["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )

        codex_good_patch = (
            f"*** Begin Patch\n"
            f"*** Update File: {inside_file}\n"
            f"@@\n-old\n+new\n"
            f"*** End Patch\n"
        )
        r_good = self.run_hook(
            {"tool_name": "apply_patch", "tool_input": {"patch": codex_good_patch}},
            {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
        )
        self.assertEqual(r_good.stdout.strip(), "")

    def test_jcode_goose_and_strict_headless_modes(self):
        # JCode passes raw tool_input on stdin with JCODE_HOOK_TOOL_NAME and expects exit 2 on deny
        jcode_res = self.run_hook(
            {"command": "rm -rf /"},
            {
                "JCODE_HOOK_TOOL_NAME": "bash",
                "OPEN_FLEET_UNIT_WORKTREE": str(self.wt),
            },
        )
        self.assertEqual(jcode_res.returncode, 2)
        self.assertIn("refused", jcode_res.stderr)
        self.assertEqual(json.loads(jcode_res.stdout)["decision"], "deny")

        # Goose mode emits top-level decision="block"
        goose_res = self.run_hook(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            {"GOOSE_MODE": "1"},
        )
        self.assertEqual(goose_res.returncode, 0)
        goose_json = json.loads(goose_res.stdout)
        self.assertEqual(goose_json["decision"], "block")
        self.assertEqual(
            goose_json["hookSpecificOutput"]["permissionDecision"], "deny"
        )

        # Strict headless modes convert Never-list "ask" to "deny"
        for env_var in ("CODEX_CI", "CODEX_SANDBOX", "OPEN_FLEET_HEADLESS_STRICT"):
            with self.subTest(env_var=env_var):
                strict_res = self.run_hook(
                    {
                        "tool_name": "Bash",
                        "tool_input": {"command": "git reset --hard"},
                    },
                    {env_var: "1"},
                )
                parsed = json.loads(strict_res.stdout)
                self.assertEqual(parsed["decision"], "deny")
                self.assertEqual(
                    parsed["hookSpecificOutput"]["permissionDecision"], "deny"
                )

    def test_local_state_store_records_allowed_file_touches_only(self):
        db_file = self.tmp / "state.db"
        inside_a = str(self.wt / "a.py")
        inside_b = str(self.wt / "b.py")
        outside_c = str(self.outside / "c.py")

        # Allowed MultiEdit records both files
        res_ok = self.run_hook(
            {
                "tool_name": "MultiEdit",
                "tool_input": {
                    "edits": [{"file_path": inside_a}, {"file_path": inside_b}]
                },
            },
            {
                "OPEN_FLEET_UNIT_WORKTREE": str(self.wt),
                "OPEN_FLEET_STATE_DB": str(db_file),
                "OPEN_FLEET_WORKER_ID": "w-touch-1",
                "OPEN_FLEET_RUN_ID": "run-99",
            },
        )
        self.assertEqual(res_ok.returncode, 0)
        self.assertEqual(res_ok.stdout.strip(), "")

        # Negative control: denied write outside worktree must NOT be recorded
        res_deny = self.run_hook(
            {"tool_name": "Write", "tool_input": {"file_path": outside_c}},
            {
                "OPEN_FLEET_UNIT_WORKTREE": str(self.wt),
                "OPEN_FLEET_STATE_DB": str(db_file),
                "OPEN_FLEET_WORKER_ID": "w-touch-1",
                "OPEN_FLEET_RUN_ID": "run-99",
            },
        )
        self.assertIn("deny", res_deny.stdout)

        with sqlite3.connect(str(db_file)) as conn:
            rows = conn.execute(
                "SELECT file_path FROM file_touches WHERE run_id = 'run-99' ORDER BY id"
            ).fetchall()
        touched_paths = [r[0] for r in rows]
        # Recorded RELATIVE to the unit worktree so two workers' edits to the same repo file
        # collide across worktrees (#590).
        self.assertEqual(touched_paths, ["a.py", "b.py"])
        self.assertNotIn(outside_c, touched_paths)

    def test_verify_settings_multi_harness_configs(self):
        # 1. Codex .codex/hooks.json
        codex_hooks = self.tmp / "codex-hooks.json"
        codex_hooks.write_text(
            json.dumps(
                {
                    "env": {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "exec_command|apply_patch",
                                "hooks": [
                                    {"type": "command", "command": str(DENY_HOOK)}
                                ],
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        r_codex = subprocess.run(
            ["sh", str(DENY_HOOK), "--verify-settings", str(codex_hooks)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r_codex.returncode, 0, r_codex.stderr)

        # 2. OpenHands .openhands/hooks.json
        oh_hooks = self.tmp / "openhands-hooks.json"
        oh_hooks.write_text(
            json.dumps(
                {
                    "env": {"OPEN_FLEET_UNIT_WORKTREE": str(self.wt)},
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "terminal|file_editor",
                                "hooks": [
                                    {"type": "command", "command": str(DENY_HOOK)}
                                ],
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        r_oh = subprocess.run(
            ["sh", str(DENY_HOOK), "--verify-settings", str(oh_hooks)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r_oh.returncode, 0, r_oh.stderr)

        # 3. OpenCode .opencode/plugin/deny-hook.ts
        oc_plugin = self.tmp / "deny-hook.ts"
        oc_plugin.write_text(
            f'export const plugin = {{\n'
            f'  "tool.execute.before": async () => {{\n'
            f'    const OPEN_FLEET_UNIT_WORKTREE = "{self.wt}";\n'
            f'    const cmd = "sh {DENY_HOOK}";\n'
            f'  }}\n'
            f'}};\n',
            encoding="utf-8",
        )
        r_oc = subprocess.run(
            ["sh", str(DENY_HOOK), "--verify-settings", str(oc_plugin)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(r_oc.returncode, 0, r_oc.stderr)


class TestMultiHarnessSearchSessions(unittest.TestCase):
    """#581: 10-harness local session search and guard_text.py untrusted-data fencing."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("search_sessions", SEARCH_PY)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._populate_all_10_harnesses()

    def tearDown(self):
        self._tmp.cleanup()

    def _populate_all_10_harnesses(self):
        # Real upstream record shapes (one fixture builder, shared with
        # tests/test_search_sessions_multi_harness.py, which cites each source).
        fixtures = _load_module(
            "search_fixtures", ROOT / "tests" / "test_search_sessions_multi_harness.py")
        self.fixtures = fixtures
        self._env = fixtures.build_fixtures(self.tmp)
        self._cwd = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self._cwd)

    def _harness_env(self):
        return dict(self._env)

    def test_searches_all_10_harnesses_and_fences_snippets(self):
        import contextlib
        import io
        from unittest import mock

        env = dict(os.environ)
        env.update(self._harness_env())
        with mock.patch.dict(os.environ, env, clear=True):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = self.mod.main(["zeta_token", "--local-harnesses", "--limit", "20"])
            self.assertEqual(rc, 0)
            self.assertIn("HITS=10", buf.getvalue())
            buf2 = io.StringIO()
            with contextlib.redirect_stdout(buf2):
                rc2 = self.mod.main(
                    [
                        "zeta_token",
                        "--local-harnesses",
                        "--agent",
                        "opencode",
                        "--path",
                        "/workspace/alpha",
                        "--since",
                        "2026-10-01T00:00:00Z",
                    ]
                )
            self.assertEqual(rc2, 0)
            self.assertIn("HITS=1", buf2.getvalue())

        res = subprocess.run(
            [
                "python3",
                str(SEARCH_PY),
                "zeta_token",
                "--local-harnesses",
                "--limit",
                "20",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("HITS=10", res.stdout)
        for agent, sid in self.fixtures.EXPECTED.items():
            self.assertIn(f"HIT {agent}:{sid} ", res.stdout)

        # Negative control: snippets are wrapped in guard_text untrusted fences
        # and prompt-injection lines are labeled while forged banners are defused
        self.assertIn(">>> UNTRUSTED ", res.stdout)
        self.assertIn("<<< END UNTRUSTED ", res.stdout)
        self.assertIn("[INJECTION-PATTERN:", res.stdout)

        # Filter by --agent and --path
        res_filtered = subprocess.run(
            [
                "python3",
                str(SEARCH_PY),
                "zeta_token",
                "--local-harnesses",
                "--agent",
                "opencode",
                "--path",
                "/workspace/alpha",
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(res_filtered.returncode, 0, res_filtered.stderr)
        self.assertIn("HITS=1", res_filtered.stdout)
        self.assertIn(f"opencode:{self.fixtures.OPENCODE_SID}", res_filtered.stdout)


class TestPortableSandboxDoctor(unittest.TestCase):
    """#585: portable danger-mode attestation across docker, bwrap, gondolin,
    superset-cloud, and openhands-docker."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("sandbox_doctor", DOCTOR_PY)

    def test_portable_backends_pass_when_attestation_complete(self):
        for backend in (
            "docker",
            "bwrap",
            "gondolin",
            "superset-cloud",
            "openhands-docker",
        ):
            with self.subTest(backend=backend):
                doc = {
                    "ok": True,
                    "backend": backend,
                    "ephemeral": True,
                    "credential_mounts": [],
                    "prelaunch_placement_bound": True,
                    "checks": [{"id": "isolation", "status": "pass"}],
                }
                # Per-backend isolation attestation is required (#585).
                if backend in ("docker", "openhands-docker"):
                    doc["isolation"] = {"capDrop": ["ALL"], "noNewPrivileges": True, "pidsLimit": 256}
                elif backend == "bwrap":
                    doc.update(networkScope="deny", filesystemScope="workspace")
                elif backend == "gondolin":
                    doc["mounts"] = [{"source": "/srv/wt", "target": "/workspace"}]
                self.assertEqual(self.mod.portable_findings(doc), [])

    def test_portable_backends_fail_closed_on_missing_fields_or_credential_mounts(self):
        base = {
            "ok": True,
            "backend": "docker",
            "ephemeral": True,
            "credential_mounts": [],
            "prelaunch_placement_bound": True,
            "checks": [{"id": "isolation", "status": "pass"}],
        }
        # Missing ephemeral
        bad_eph = dict(base, ephemeral=False)
        self.assertTrue(
            any("ephemeral" in f for f in self.mod.portable_findings(bad_eph))
        )

        # Non-empty credential_mounts
        bad_cred = dict(base, credential_mounts=["/home/user/.ssh:/root/.ssh"])
        self.assertTrue(
            any("credential_mount" in f for f in self.mod.portable_findings(bad_cred))
        )

        # Hidden credential path in mounts
        bad_mount = dict(base, mounts=["/Users/dev/.config/gh:/mnt/gh:ro"])
        self.assertTrue(
            any("credential_mount" in f for f in self.mod.portable_findings(bad_mount))
        )

        # Missing prelaunch_placement_bound
        bad_place = dict(base, prelaunch_placement_bound=False)
        self.assertTrue(
            any(
                "prelaunch_placement_bound" in f
                for f in self.mod.portable_findings(bad_place)
            )
        )


class TestPredictMerge(unittest.TestCase):
    """#590: wtree.sh predict-merge and diff_scope.py --predict-merge."""

    @classmethod
    def setUpClass(cls):
        cls.ds_mod = _load_module("diff_scope", DIFF_SCOPE_PY)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name) / "repo"
        self.repo.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test")
        (self.repo / "shared.txt").write_text("line1\n", encoding="utf-8")
        self._git("add", "shared.txt")
        self._git("commit", "-m", "initial")

        # Clean feature branch
        self._git("checkout", "-b", "feat-clean")
        (self.repo / "clean.txt").write_text("clean\n", encoding="utf-8")
        self._git("add", "clean.txt")
        self._git("commit", "-m", "add clean")

        # Conflicting feature branch
        self._git("checkout", "main")
        (self.repo / "shared.txt").write_text("main-change\n", encoding="utf-8")
        self._git("add", "shared.txt")
        self._git("commit", "-m", "main change")

        self._git("checkout", "-b", "feat-conflict", "HEAD~1")
        (self.repo / "shared.txt").write_text("branch-change\n", encoding="utf-8")
        self._git("add", "shared.txt")
        self._git("commit", "-m", "branch change")
        self._git("checkout", "main")

    def tearDown(self):
        self._tmp.cleanup()

    def _git(self, *args):
        subprocess.run(
            ["git", "-C", str(self.repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_predict_merge_clean_and_conflict_via_wtree_and_diff_scope(self):
        import contextlib
        import io

        # In-process coverage for diff_scope.predict_merge and main
        clean_inproc = self.ds_mod.predict_merge(self.repo, "main", "feat-clean")
        self.assertTrue(clean_inproc["clean"])
        conf_inproc = self.ds_mod.predict_merge(self.repo, "main", "feat-conflict")
        self.assertFalse(conf_inproc["clean"])
        self.assertIn("shared.txt", conf_inproc["conflicts"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                self.ds_mod.main(
                    ["--predict-merge", "main", "feat-clean", "--repo", str(self.repo)]
                ),
                0,
            )
            self.assertEqual(
                self.ds_mod.main(
                    [
                        "--predict-merge",
                        "main",
                        "feat-conflict",
                        "--repo",
                        str(self.repo),
                    ]
                ),
                1,
            )

        # Clean merge via wtree.sh
        r_clean = subprocess.run(
            ["sh", str(WTREE_SH), "predict-merge", "main", "feat-clean", str(self.repo)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(r_clean.returncode, 0, r_clean.stderr)
        clean_doc = json.loads(r_clean.stdout)
        self.assertIs(clean_doc["clean"], True)
        self.assertTrue(clean_doc["tree_oid"])
        self.assertEqual(clean_doc["conflicts"], [])

        # Negative control: conflicting merge exits 1 and names shared.txt
        r_conf = subprocess.run(
            [
                "sh",
                str(WTREE_SH),
                "predict-merge",
                "main",
                "feat-conflict",
                str(self.repo),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(r_conf.returncode, 1)
        conf_doc = json.loads(r_conf.stdout)
        self.assertIs(conf_doc["clean"], False)
        self.assertIsNone(conf_doc["tree_oid"])
        self.assertIn("shared.txt", conf_doc["conflicts"])


class TestPrivilegeNarrowingAndWatchdogDedup(unittest.TestCase):
    """#590: dispatch-sign.py monotonic privilege narrowing and watchdog CI failure dedup."""

    @classmethod
    def setUpClass(cls):
        cls.ds = _load_module("dispatch_sign", DISPATCH_SIGN_PY)
        cls.wd = _load_module("watchdog", WATCHDOG_PY)

    def test_privilege_narrowing_allows_equal_or_narrower_and_rejects_escalation(self):
        import contextlib
        import io
        from unittest import mock

        seed = "11" * 32
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "signed.json"

            env = dict(os.environ)
            env.pop("ORCA_DISPATCH_SIGNING_SEED", None)
            env["OPEN_FLEET_SIGNING_SEED"] = seed

            with mock.patch.dict(os.environ, env, clear=True):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc_sign = self.ds.main(
                        [
                            "sign",
                            "--manifest-id",
                            "m-1",
                            "--contract-digest",
                            "a" * 64,
                            "--unit-class",
                            "code",
                            "--parent-profile",
                            "danger",
                            "--profile",
                            "rw",
                        ]
                    )
                self.assertEqual(rc_sign, 0)
                with contextlib.redirect_stderr(io.StringIO()):
                    rc_esc = self.ds.main(
                        [
                            "sign",
                            "--manifest-id",
                            "m-1",
                            "--contract-digest",
                            "a" * 64,
                            "--unit-class",
                            "code",
                            "--parent-profile",
                            "ro",
                            "--profile",
                            "rw",
                        ]
                    )
                self.assertEqual(rc_esc, 2)

            # Allowed narrowing: danger -> rw
            r_ok = subprocess.run(
                [
                    "python3",
                    str(DISPATCH_SIGN_PY),
                    "sign",
                    "--manifest-id",
                    "m-1",
                    "--contract-digest",
                    "a" * 64,
                    "--unit-class",
                    "code",
                    "--parent-profile",
                    "danger",
                    "--profile",
                    "rw",
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_ok.returncode, 0, r_ok.stderr)
            out_path.write_text(r_ok.stdout, encoding="utf-8")

            r_ver = subprocess.run(
                ["python3", str(DISPATCH_SIGN_PY), "verify", "--record", str(out_path)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_ver.returncode, 0, r_ver.stderr)

            # Negative control: escalation ro -> rw fails closed (exit 2)
            r_esc = subprocess.run(
                [
                    "python3",
                    str(DISPATCH_SIGN_PY),
                    "sign",
                    "--manifest-id",
                    "m-1",
                    "--contract-digest",
                    "a" * 64,
                    "--unit-class",
                    "code",
                    "--parent-profile",
                    "ro",
                    "--profile",
                    "rw",
                ],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(r_esc.returncode, 2)
            self.assertIn("escalation refused", r_esc.stderr)

    def test_watchdog_ci_failure_signature_and_deduplication(self):
        checks_run1 = [
            {
                "name": "unit-tests",
                "step": "pytest",
                "conclusion": "failure",
                "exit_code": 1,
                "run_id": 1001,
                "timestamp": "2026-10-19T10:00:00Z",
                "log_url": "https://ci.example/logs/1001",
            }
        ]
        checks_run2_same_error = [
            {
                "name": "unit-tests",
                "step": "pytest",
                "conclusion": "failure",
                "exit_code": 1,
                "run_id": 1002,
                "timestamp": "2026-10-19T10:05:00Z",
                "log_url": "https://ci.example/logs/1002",
            }
        ]
        sig1 = self.wd.ci_failure_signature(checks_run1)
        sig2 = self.wd.ci_failure_signature(checks_run2_same_error)
        self.assertEqual(sig1, sig2)

        seen = {}
        # Waiting for human input suppresses nudge without burning signature
        nudge_wait, _ = self.wd.should_nudge_ci(
            "w1", checks_run1, seen, waiting_input=True
        )
        self.assertFalse(nudge_wait)

        # First active failure nudges
        nudge_first, _ = self.wd.should_nudge_ci(
            "w1", checks_run1, seen, waiting_input=False
        )
        self.assertTrue(nudge_first)

        # Duplicate failure signature is suppressed
        nudge_dup, _ = self.wd.should_nudge_ci(
            "w1", checks_run2_same_error, seen, waiting_input=False
        )
        self.assertFalse(nudge_dup)

        # Distinct failure signature nudges again
        checks_new_error = [
            {
                "name": "lint",
                "step": "ruff",
                "conclusion": "failure",
                "exit_code": 2,
            }
        ]
        nudge_new, sig3 = self.wd.should_nudge_ci(
            "w1", checks_new_error, seen, waiting_input=False
        )
        self.assertTrue(nudge_new)
        self.assertNotEqual(sig1, sig3)

        # Issue 3: decide() enforces CI nudge limits (max_ci_nudges_per_dispatch, hourly cap, nudge_window_s)
        from datetime import datetime, timedelta, timezone

        now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=timezone.utc)
        worker_payload = {
            "worker_id": "w1",
            "dispatch_id": "d1",
            "dispatched_at": (now - timedelta(seconds=30)).isoformat(),
            "last_movement_at": (now - timedelta(seconds=5)).isoformat(),
            "ci_checks": checks_run1,
        }
        cfg_zero = {**self.wd.DEFAULTS, "max_ci_nudges_per_dispatch": 0}
        cls_z, act_z, ev_z, note_z = self.wd.decide(worker_payload, now, cfg_zero, {"workers": {}})
        self.assertEqual(cls_z, "OK")
        self.assertEqual(act_z, "none")
        self.assertIn("withheld", note_z)

        state_store = {"workers": {}}
        cls_ok, act_ok, ev_ok, _ = self.wd.decide(worker_payload, now, self.wd.DEFAULTS, state_store)
        self.assertEqual(cls_ok, "OK")
        self.assertEqual(act_ok, "nudge")
        self.assertEqual(ev_ok["ci_signature"], sig1)

        # Record first nudge and verify a DIFFERENT failure signature is withheld by default budget (1/1)
        self.wd.record_nudge(state_store, "w1", "d1", now, ci_signature=sig1)
        worker_payload_2 = {**worker_payload, "ci_checks": checks_new_error}
        cls_bud, act_bud, _, note_bud = self.wd.decide(
            worker_payload_2, now + timedelta(seconds=10), self.wd.DEFAULTS, state_store
        )
        self.assertEqual(cls_bud, "OK")
        self.assertEqual(act_bud, "none")
        self.assertIn("nudge budget spent", note_bud)

        # With higher per-dispatch budget, verify hourly cap (1/1) withholds a DIFFERENT failure signature
        cfg_hourly = {**self.wd.DEFAULTS, "max_ci_nudges_per_dispatch": 3}
        cls_hr, act_hr, _, note_hr = self.wd.decide(
            worker_payload_2, now + timedelta(seconds=10), cfg_hourly, state_store
        )
        self.assertEqual(cls_hr, "OK")
        self.assertEqual(act_hr, "none")
        self.assertIn("hourly cap reached", note_hr)

        # With higher per-dispatch and hourly caps, verify nudge_window_s cooldown withholds a DIFFERENT failure signature
        cfg_multi = {
            **self.wd.DEFAULTS,
            "max_ci_nudges_per_dispatch": 3,
            "max_nudges_per_hour_per_worker": 3,
        }
        cls_win, act_win, _, note_win = self.wd.decide(
            worker_payload_2, now + timedelta(seconds=10), cfg_multi, state_store
        )
        self.assertEqual(cls_win, "OK")
        self.assertEqual(act_win, "none")
        self.assertIn("nudge window holds", note_win)

        # A spent CI budget never spends the hang budget: a later real hang still gets its nudge.
        hung_payload = {
            **worker_payload,
            "ci_checks": [],
            "last_movement_at": (now - timedelta(seconds=7200)).isoformat(),
        }
        cls_h, act_h, _, _ = self.wd.decide(
            hung_payload, now + timedelta(seconds=7200), self.wd.DEFAULTS, state_store
        )
        self.assertEqual(cls_h, "HUNG")
        self.assertEqual(act_h, "nudge")


if __name__ == "__main__":
    unittest.main()
