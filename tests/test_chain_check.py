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


class TestSpellingAndCaseCannotLaunderADegradedTerminal(unittest.TestCase):
    """2026-10-23 review, §5: classification was case- and spelling-sensitive, so
    `Done-With-Parked` read clean and PROCEEDED when the chain named it."""

    VARIANTS = ("Done-With-Parked", "done-with-parked", "DONE_WITH_PARKED", "done with parked",
                " DONE--WITH__PARKED ", "No-Go", "no_go", "Abandoned", "inconclusive",
                "Hardened-With-Open-Items", "stable_with_quarantine")

    def test_every_spelling_of_a_degraded_terminal_is_degraded(self):
        for name in self.VARIANTS:
            with self.subTest(name=name):
                self.assertEqual(chain_check.classify(name), "degraded")

    def test_a_degraded_variant_never_proceeds_even_when_declared(self):
        for name in self.VARIANTS:
            with self.subTest(name=name):
                proceed, why = chain_check.gate(name, {name, "CLEAN"})
                self.assertFalse(proceed, why)
        stop = subprocess.run([sys.executable, str(SCRIPT), "gate", "--allowed",
                               "Done-With-Parked", "Done-With-Parked"], capture_output=True, text=True)
        self.assertEqual(stop.returncode, 1, stop.stdout + stop.stderr)
        self.assertIn("STOP", stop.stdout)

    def test_handoffs_and_clean_names_match_across_spellings(self):
        self.assertEqual(chain_check.classify("Awaiting_Maintainer_Merge"), "handoff")
        self.assertEqual(chain_check.classify("diagnosed-with-handoff"), "handoff")
        self.assertTrue(chain_check.gate("promotion-ready", {"PROMOTION_READY"})[0])
        self.assertTrue(chain_check.gate("Clean", {"CLEAN"})[0])

    def test_an_unrecognised_terminal_fails_closed(self):
        for name in ("", "   ", "DONE-WITH-PARKD", "X-WITH-SOMETHING-NEW", "CLEAN!", "42", "--"):
            with self.subTest(name=name):
                self.assertEqual(chain_check.classify(name), "unknown")
                proceed, _ = chain_check.gate(name, {name})
                self.assertFalse(proceed)
        cli = subprocess.run([sys.executable, str(SCRIPT), "classify", "DONE-WITH-PARKD"],
                             capture_output=True, text=True)
        self.assertEqual((cli.returncode, cli.stdout.strip()), (1, "unknown"))


if __name__ == "__main__":
    unittest.main()
