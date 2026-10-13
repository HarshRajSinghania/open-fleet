#!/usr/bin/env python3
"""Contract tests for runtime/scripts/chain_check.py (mission-chaining.md).

The classification was prose until the full review: ABANDONED matched no
degraded marker, so a rolled-back migration leg read as clean. These tests
pin the executable rule and audit the live catalog's labels against it.
"""
import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "chain_check", ROOT / "runtime" / "scripts" / "chain_check.py")
chain_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chain_check)
SCRIPT = ROOT / "runtime" / "scripts" / "chain_check.py"


class TestClassify(unittest.TestCase):
    def test_abandoned_is_degraded(self):
        self.assertEqual(chain_check.classify("ABANDONED"), "degraded")

    def test_every_degraded_suffix_stops(self):
        for name in ("X-WITH-PARKED", "X-WITH-OPEN-ITEMS", "X-WITH-GAPS",
                     "X-WITH-MANUAL-PARKED", "X-WITH-BLOCKED", "X-WITH-QUARANTINE",
                     "X-WITH-PINNED", "NO-GO", "INCONCLUSIVE"):
            self.assertEqual(chain_check.classify(name), "degraded", name)

    def test_handoffs_and_clean_terminals(self):
        self.assertEqual(chain_check.classify("DIAGNOSED-WITH-HANDOFF"), "handoff")
        self.assertEqual(chain_check.classify("awaiting-maintainer-merge"), "handoff")
        for name in ("CLEAN", "DRY", "COVERED", "BUILT", "GO", "WITHIN-BUDGET"):
            self.assertEqual(chain_check.classify(name), "clean", name)


class TestGate(unittest.TestCase):
    def test_degraded_never_proceeds_even_if_named(self):
        proceed, why = chain_check.gate("ABANDONED", {"ABANDONED", "MIGRATED"})
        self.assertFalse(proceed)
        self.assertIn("degraded", why)

    def test_clean_proceeds_only_when_declared(self):
        self.assertTrue(chain_check.gate("CLEAN", {"CLEAN"})[0])
        self.assertFalse(chain_check.gate("CLEAN", {"COVERED"})[0])
        self.assertTrue(chain_check.gate("DIAGNOSED-WITH-HANDOFF",
                                         {"DIAGNOSED-WITH-HANDOFF"})[0])

    def test_cli_exit_codes(self):
        stop = subprocess.run([sys.executable, str(SCRIPT), "gate",
                               "--allowed", "MIGRATED", "ABANDONED"],
                              capture_output=True, text=True)
        self.assertEqual(stop.returncode, 1)
        self.assertIn("STOP", stop.stdout)
        go = subprocess.run([sys.executable, str(SCRIPT), "gate",
                             "--allowed", "MIGRATED", "MIGRATED"],
                            capture_output=True, text=True)
        self.assertEqual(go.returncode, 0, go.stderr)
        self.assertIn("PROCEED", go.stdout)


class TestCatalogAudit(unittest.TestCase):
    def test_live_catalog_labels_agree(self):
        self.assertEqual(chain_check.audit(ROOT), [])


if __name__ == "__main__":
    unittest.main()
