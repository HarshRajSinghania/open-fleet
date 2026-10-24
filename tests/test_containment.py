"""Process containment (runtime/scripts/containment.py): the one helper every paid runner shares.

The assertions hold on any host. Where the process table shows a detached system binary's marker
(Linux, /proc/<pid>/environ), the sweep must end it and the strong probe must pass; where it hides
it (macOS's `ps -E`), the strong probe must refuse. Run on macOS and in a Linux container (PR #668).
"""
from __future__ import annotations

import importlib.util
import os
import secrets
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("containment_under_test", ROOT / "runtime" / "scripts" / "containment.py")
containment = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(containment)
_tables = importlib.util.spec_from_file_location("fixture_containment_tables",
                                                 ROOT / "tests" / "fixtures" / "containment_tables.py")
TABLES = importlib.util.module_from_spec(_tables)
_tables.loader.exec_module(TABLES)


def gone(pid, wait_s=5.0):
    """The process has exited (reaped, or a zombie this test reaps)."""
    end = time.monotonic() + wait_s
    while time.monotonic() < end:
        try:
            done, _status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return True
        if done:
            return True
        time.sleep(0.05)
    return False


class Detached(unittest.TestCase):
    def detached(self, argv, marker=containment.CALL_MARKER):
        """A process in a session of its own, carrying a fresh tag under `marker`: (tag, pid)."""
        tag = secrets.token_hex(16)
        proc = subprocess.Popen(argv, env=dict(os.environ, **{marker: tag}), start_new_session=True,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: proc.poll() is None and (proc.kill(), proc.wait()))
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:  # the table shows a process once it has exec'd
            if proc.pid in containment.process_table():
                break
            time.sleep(0.02)
        return tag, proc.pid


class TheMarkerFindsWhatLeftItsGroup(Detached):
    def test_a_detached_python_carrying_the_marker_is_swept(self):
        tag, pid = self.detached([sys.executable, "-c", "import time; time.sleep(60)"])
        self.assertIn(pid, containment.call_processes(containment.process_table(), tag=tag))
        self.assertTrue(containment.sweep(tag=tag))
        self.assertTrue(gone(pid), "the swept process lives")

    def test_a_dispatch_marker_is_its_own(self):
        tag, pid = self.detached([sys.executable, "-c", "import time; time.sleep(60)"], containment.DISPATCH_MARKER)
        table = containment.process_table()
        self.assertEqual(containment.call_processes(table, tag=tag), set(), "the call marker matched a dispatch tag")
        self.assertIn(pid, containment.call_processes(table, tag=tag, marker=containment.DISPATCH_MARKER))
        self.assertTrue(containment.sweep(tag=tag, marker=containment.DISPATCH_MARKER))
        self.assertTrue(gone(pid))

    def test_a_detached_system_binary_is_swept_where_the_table_shows_it_and_refused_where_not(self):
        sleep = shutil.which("sleep", path="/bin:/usr/bin")
        self.assertIsNotNone(sleep)
        tag, pid = self.detached([sleep, "60"])
        visible = pid in containment.call_processes(containment.process_table(), tag=tag)
        if visible:  # Linux: /proc/<pid>/environ shows every process this user owns
            self.assertTrue(containment.sweep(tag=tag))
            self.assertTrue(gone(pid), "a visible detached system binary outlived its sweep")
            self.assertIsNone(containment.containment_problem(), "a host that shows every marker refused")
        else:  # macOS: a system binary's environment is hidden, so nothing about it can be proven
            self.assertIsNotNone(containment.containment_problem(), "a host blind to a system binary passed")


class TheProbeAndTheSweepFailClosed(unittest.TestCase):
    def test_a_table_blind_to_system_binaries_is_refused(self):
        blind = TABLES.blind_to_system_binaries(containment.process_table)
        self.assertIsNotNone(containment.containment_problem(table=blind))

    def test_a_table_that_cannot_be_read_is_refused_and_vouches_for_nothing(self):
        def unreadable():
            raise OSError("no ps")
        self.assertIn("cannot be read", containment.containment_problem(table=unreadable))
        self.assertFalse(containment.sweep(tag=secrets.token_hex(16), table=unreadable))

    def test_the_markers_of_a_call_and_its_descendants(self):
        tag, other = "a" * 32, "b" * 32
        table = {
            10: (1, 10, ()),
            11: (10, 10, ()),
            12: (11, 12, ()),
            20: (1, 20, (f"{containment.CALL_MARKER}={tag}",)),
            21: (20, 21, ("PATH=/bin",)),
            30: (1, 30, (f"{containment.DISPATCH_MARKER}={tag}",)),
            40: (1, 40, (f"{containment.CALL_MARKER}={other}",)),
        }
        self.assertEqual(containment.call_processes(table, groups=(10,), tag=tag, exclude=(10,)), {11, 12, 20, 21})
        self.assertEqual(containment.call_processes(table, tag=tag, marker=containment.DISPATCH_MARKER), {30})


if __name__ == "__main__":
    unittest.main()
