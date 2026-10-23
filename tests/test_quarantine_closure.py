#!/usr/bin/env python3
"""One composition set at every quarantine gate (2026-10-23 review, P1-10 / P2-11).

quarantine_check.py's mission view — which validate.py's catalog gate and `preflight.py
--mission` both read — resolved the mission's own clause only. A quarantined playbook reached
through another playbook (acceptance-review → risk-review), named in the body, or named in a
DEFERRED READS paragraph started a run. These fixtures build throwaway catalogs; the live
runtime/quarantine.json is never touched.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "runtime" / "scripts" / "quarantine_check.py"
PREFLIGHT = ROOT / "runtime" / "scripts" / "preflight.py"

_spec = importlib.util.spec_from_file_location("quarantine_check_closure", SCRIPT)
qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qc)


def entry(component):
    return {"component": component, "ref": "*", "reason": "compromised upstream",
            "date": "2026-10-23", "by": "human:maintainer"}


def catalog(root, skill_body, quarantined=(), playbooks=None, layout="catalog"):
    """A minimal catalog: ship-it plus the playbooks given as {name: text}."""
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "quarantine.json").write_text(
        json.dumps({"quarantined": [entry(c) for c in quarantined]}))
    (root / "runtime" / "evidence-manifest.md").write_text("# policy\n")
    skill = root / "skills" / "ship-it"
    skill.mkdir(parents=True)
    docs = root / "playbooks" if layout == "catalog" else skill / "references"
    docs.mkdir(parents=True)
    if layout != "catalog":
        (docs / "evidence-manifest.md").write_text("# policy\n")
    for name, text in (playbooks or {}).items():
        (docs / f"{name}.md").write_text(text)
    (skill / "SKILL.md").write_text(skill_body)
    return skill


PLAYBOOKS = {
    "acceptance-review": "# acceptance-review\n\nOn a risky surface, run `risk-review`.\n",
    "risk-review": "# risk-review\n\nLenses.\n",
    "build-change": "# build-change\n",
}


class ReachedPlaybooksAreChecked(unittest.TestCase):
    def composes(self, body, layout="catalog"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog(root, body, playbooks=PLAYBOOKS, layout=layout)
            return qc.mission_view(root, "ship-it")["composes"]["ship-it"]

    def test_a_playbook_called_by_a_composed_playbook_is_composed(self):
        for layout in ("catalog", "bundle"):
            with self.subTest(layout=layout):
                found = self.composes("Composes `acceptance-review`; rides `evidence-manifest`.\n",
                                      layout)
                self.assertIn("risk-review", found)

    def test_a_body_mention_and_a_deferred_read_are_composed(self):
        body = ("Composes `build-change`; rides `evidence-manifest`.\n\n"
                "DEFERRED READS, never at activation: acceptance-review at REVIEW.\n\n"
                "## Related\n\nThe lens protocol is `risk-review`.\n")
        found = self.composes(body)
        self.assertTrue({"build-change", "acceptance-review", "risk-review"} <= found, found)

    def test_a_clause_name_md_is_composed(self):
        self.assertIn("build-change", self.composes("Composes build-change.md.\n"))

    def test_runtime_policies_and_unknown_words_are_not_playbooks(self):
        found = self.composes("Composes `build-change`; rides `evidence-manifest`.\n\n"
                              "DEFERRED READS: nothing-here at any phase.\n")
        self.assertEqual(found, {"build-change"})

    def test_a_missing_deferred_declaration_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog(root, "Composes `build-change`.\n\nDEFERRED READS: gone-away.md at LAND.\n",
                    playbooks=PLAYBOOKS)
            with self.assertRaises(qc.QuarantineError) as caught:
                qc.mission_view(root, "ship-it")
        self.assertIn("gone-away.md", str(caught.exception))

    def test_an_unreadable_reached_playbook_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog(root, "Composes `acceptance-review`.\n", playbooks=PLAYBOOKS)
            (root / "playbooks" / "risk-review.md").write_bytes(b"\xff\xfe")
            with self.assertRaises(qc.QuarantineError):
                qc.mission_view(root, "ship-it")


class EveryGateRefusesAReachedQuarantine(unittest.TestCase):
    BODY = "Composes `acceptance-review`; rides `evidence-manifest`.\n"

    def test_cli_mission_and_catalog_modes_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            catalog(Path(tmp), self.BODY, ["playbook:risk-review"], PLAYBOOKS)
            for mode in (["--mission", "ship-it"], ["--catalog"]):
                with self.subTest(mode=mode):
                    result = subprocess.run(
                        [sys.executable, str(SCRIPT), "--root", tmp, *mode],
                        capture_output=True, text=True, timeout=60)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn("composes quarantined playbook risk-review", result.stdout)

    def test_preflight_refuses_the_mission_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            catalog(root, self.BODY, ["playbook:risk-review"], PLAYBOOKS)
            subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=60)
            env = {**os.environ, "OPEN_FLEET_ROOT": str(root)}
            result = subprocess.run(
                [sys.executable, str(PREFLIGHT), "--mode", "readonly", "--mission", "ship-it"],
                capture_output=True, text=True, cwd=root, env=env, timeout=60)
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("risk-review", result.stderr)


class TheLiveCatalogClears(unittest.TestCase):
    def test_every_mission_resolves_its_whole_composition(self):
        view = qc.catalog_view(ROOT)  # raises on any missing or unreadable declared dependency
        self.assertGreaterEqual(len(view["composes"]), 22)
        # The transitive edge the review named is in the set (acceptance-review → risk-review).
        callers = [m for m, found in view["composes"].items() if "acceptance-review" in found]
        self.assertTrue(callers)
        for mission in callers:
            self.assertIn("risk-review", view["composes"][mission], mission)


if __name__ == "__main__":
    unittest.main()
