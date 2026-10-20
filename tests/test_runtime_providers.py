#!/usr/bin/env python3
"""#578 acceptance: the shipped wrappers run UNMODIFIED against a non-Orca runtime with no
`orca` binary on PATH, and their receipts carry real values (not `unknown`)."""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"


class TestWrappersOnPosixWithoutOrca(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "i"],
            check=True,
        )
        # Only system dirs: no `orca`, `orca-ide` or `orca-dev` anywhere on PATH.
        path = os.pathsep.join(d for d in ("/usr/bin", "/bin") if Path(d).is_dir())
        self.env = {
            "PATH": path,
            "HOME": str(base / "home"),
            "OPEN_FLEET_RUNTIME": "posix",
            "OPEN_FLEET_STATE_DB": str(base / "state.db"),
            "OPEN_FLEET_POSIX_BACKEND": "dry-run",
            "OPEN_FLEET_CLI_CWD": str(self.repo),
        }

    def run_script(self, name, *args, env=None, expect=0):
        p = subprocess.run(
            ["python3", str(SCRIPTS / name), *args],
            cwd=self.repo,
            env={**self.env, **(env or {})},
            capture_output=True,
            text=True,
            timeout=120,
        )
        self.assertEqual(p.returncode, expect, f"{name} {args}: rc={p.returncode}\n{p.stdout}\n{p.stderr}")
        return p.stdout

    def field(self, out, key):
        m = re.search(rf"^{key}=(\S+)", out, re.M)
        self.assertIsNotNone(m, f"no {key}= in:\n{out}")
        return m.group(1)

    def test_full_wrapper_loop(self):
        out = self.run_script("task_ops.py", "create", "--spec", "wrapper spec")
        task = self.field(out, "CREATED")
        self.assertTrue(task.startswith("task_"))

        self.assertIn("ROWS=", self.run_script("worktree_ops.py", "list"))

        out = self.run_script("send_msg.py", "--type", "status", "--subject", "hi", "--to", "coordinator", "--from", "term_x")
        self.assertNotEqual(self.field(out, "MESSAGE_ID"), "unknown")

        out = self.run_script("check_reply.py", "check", "--terminal", "coordinator")
        self.assertIn("COUNT=1", out)

        # ask -> times out pending -> reply by message id -> resume returns the answer
        out = self.run_script("hitl_ask.py", "--question", "ship?", "--timeout-ms", "200", "--from", "term_x", expect=1)
        mid = re.search(r"--resume (\S+)", out + "").group(1) if "--resume" in out else None
        if mid is None:
            check = self.run_script("check_reply.py", "check", "--terminal", "coordinator", "--types", "question")
            mid = re.search(r"--- (msg_\w+) \(question\)", check).group(1)
        self.run_script("check_reply.py", "reply", "--id", mid, "--body", "yes", "--from", "coordinator")
        out = self.run_script("hitl_ask.py", "--resume", mid, "--timeout-ms", "200")
        self.assertIn("yes", out)

        out = self.run_script("terminal_ops.py", "create", "--title", "t", "--command", "echo hi")
        handle = self.field(out, "HANDLE")
        self.assertIn(handle, self.run_script("terminal_ops.py", "list"))

    def test_worker_ops_show_and_read_receipts(self):
        out = self.run_script("task_ops.py", "create", "--spec", "do it")
        task = self.field(out, "CREATED")
        cli = ["python3", str(SCRIPTS / "orca_cli.py"), "orchestration", "worker-start", "--task", task,
               "--worktree", "new-child", "--agent", "claude", "--json"]
        p = subprocess.run(cli, cwd=self.repo, env=self.env, capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        disp = re.search(r'"dispatchId": "(disp_\w+)"', p.stdout).group(1)
        out = self.run_script("worker_ops.py", "show", "--dispatch", disp)
        self.assertIn(f"DISPATCH={disp}", out)
        self.assertNotIn("STATE=unknown", out)
        out = self.run_script("worker_ops.py", "read", "--dispatch", disp, "--source", "transcript")
        self.assertIn("SOURCE=transcript", out)
        self.run_script("worker_ops.py", "stop", "--dispatch", disp)
        self.assertIn("STATE=stopped", self.run_script("worker_ops.py", "show", "--dispatch", disp))

    def test_unknown_runtime_is_refused(self):
        p = subprocess.run(
            ["python3", str(SCRIPTS / "orca_cli.py"), "--path"],
            env={**self.env, "OPEN_FLEET_RUNTIME": "nope"},
            capture_output=True,
            text=True,
        )
        self.assertEqual(p.returncode, 2)

    def test_explicit_runtime_beats_inherited_cli_command(self):
        out = self.run_script("task_ops.py", "create", "--spec", "x", env={"ORCA_CLI_COMMAND": "/nonexistent/orca"})
        self.assertTrue(self.field(out, "CREATED").startswith("task_"))


if __name__ == "__main__":
    unittest.main()
