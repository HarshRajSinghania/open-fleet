#!/usr/bin/env python3
"""Corpus contract for the injection fence (#560, VAL-01's in-repo half).

tests/fixtures/injection.json holds poisoned inputs a stranger can put in
front of an unattended worker. For every case the fence must: envelope the
text (exactly one real open and close banner), preserve the payload, defuse
forged banners, and raise the declared INJECTION-PATTERN families.

Two cases are documented fence misses (fence_expect: envelope-only) — a
session-kind claim and a secret-echo ask have no directive shape the
patterns can see. They stay in the corpus so the gap is measured, not
imagined; the control for them is the worker-obedience drill defined in
docs/runtime-scripts.md (`guard_text.py`), whose live leg needs an Orca run
and is owed, not done.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "runtime" / "scripts" / "guard_text.py"
CORPUS = ROOT / "tests" / "fixtures" / "injection.json"
ZWSP = "\u200b"


def labels_in(stdout):
    labels = set()
    for line in stdout.splitlines():
        if line.startswith("[INJECTION-PATTERN:"):
            labels.update(line.split("]", 1)[0].split(":", 1)[1].split(","))
    return labels


class InjectionCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(CORPUS.read_text(encoding="utf-8"))["cases"]

    def run_case(self, case):
        result = subprocess.run(
            [sys.executable, str(GUARD), "--source", case["source"]],
            input=case["text"], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_corpus_cases(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                out = self.run_case(case)
                source = case["source"].upper()
                # Exactly one real envelope: a forged close inside the
                # payload must not read as the envelope's own close.
                self.assertEqual(out.count(f">>> UNTRUSTED {source} DATA"), 1)
                self.assertEqual(out.count(f"<<< END UNTRUSTED {source} DATA >>>"), 1)
                # Declared families raised; envelope-only cases raise none.
                self.assertLessEqual(set(case["expect_labels"]), labels_in(out),
                                     f"{case['name']}: missing labels")
                if case["fence_expect"] == "envelope-only":
                    self.assertEqual(
                        labels_in(out), set(),
                        f"{case['name']} is a documented fence miss — if the "
                        "fence now labels it, upgrade fence_expect and say so")
                # Payload preserved: every original line survives (label
                # prefixes and banner defusing aside).
                for line in case["text"].splitlines():
                    probe = line.replace(ZWSP, "")
                    rendered = "\n".join(
                        ln.split("] ", 1)[-1] if ln.startswith("[INJECTION-PATTERN")
                        else ln for ln in out.splitlines())
                    self.assertIn(probe.replace("UNTRUSTED", "UNTRUSTED"),
                                  rendered.replace(ZWSP, ""),
                                  f"{case['name']}: payload line lost: {line!r}")
                if case.get("forged_banner"):
                    self.assertIn(ZWSP, out,
                                  "forged banner must be defused with a ZWSP splice")

    def test_corpus_covers_every_pattern_family(self):
        # A family no fixture exercises is a claim nobody is testing.
        covered = set()
        for case in self.cases:
            covered.update(case["expect_labels"])
        self.assertEqual(covered, {
            "instruction-override", "authority-claim", "suppression-request",
            "command-execution", "role-play-marker",
        })

    def test_corpus_has_a_benign_control(self):
        # Without a clean case, "labels everything" passes the corpus.
        self.assertTrue(any(
            c["fence_expect"] == "labelled" and not c["expect_labels"]
            for c in self.cases))


if __name__ == "__main__":
    unittest.main()
