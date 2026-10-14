#!/usr/bin/env python3
"""Contract tests for runtime/scripts/quarantine_check.py (#558).

The properties that make the deny-list a switch rather than a suggestion:
entries are human acts (shape refuses anything else), a malformed list never
reads as an empty one, the matching rule is the same function every gate
calls, and the shipped (empty) list is clean against the real catalog.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "runtime" / "scripts" / "quarantine_check.py"

_spec = importlib.util.spec_from_file_location("quarantine_check", SCRIPT)
qc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(qc)


def entry(component="pack:gstack", ref="*", **over):
    base = {"component": component, "ref": ref, "reason": "compromised upstream",
            "date": "2026-10-14", "by": "human:maintainer"}
    base.update(over)
    return base


class Shape(unittest.TestCase):
    def parse(self, entries):
        return qc.parse_quarantine({"quarantined": entries})

    def test_valid_entry(self):
        entries, errors = self.parse([entry()])
        self.assertEqual(errors, [])
        self.assertEqual(entries[0]["kind"], "pack")

    def test_non_human_by_is_refused(self):
        _, errors = self.parse([entry(by="coordinator")])
        self.assertTrue(any("human" in e for e in errors))

    def test_bare_human_prefix_and_agent_roles_are_refused(self):
        for by in ("human:", "human:agent", "human:coordinator", "human:Worker"):
            _, errors = self.parse([entry(by=by)])
            self.assertTrue(errors, by)

    def test_missing_reason_is_refused(self):
        _, errors = self.parse([entry(reason="  ")])
        self.assertTrue(errors)

    def test_unknown_kind_is_refused(self):
        _, errors = self.parse([entry(component="widget:thing")])
        self.assertTrue(errors)

    def test_bad_date_is_refused(self):
        _, errors = self.parse([entry(date="next week")])
        self.assertTrue(errors)

    def test_short_ref_is_refused(self):
        _, errors = self.parse([entry(ref="abc123")])
        self.assertTrue(errors)

    def test_top_level_shape_is_refused(self):
        _, errors = qc.parse_quarantine({"nope": []})
        self.assertTrue(errors)


class Matching(unittest.TestCase):
    VIEW = {
        "missions": {"ship-it", "review-it"},
        "composes": {"ship-it": {"build-change", "risk-review"}, "review-it": set()},
        "pins": {"gstack": "71f6048e", "orca": "2bb20586ebc39d605e16d95f57420e20a16e7485"},
    }

    def found(self, entries, view=None):
        parsed, errors = qc.parse_quarantine({"quarantined": entries})
        self.assertEqual(errors, [])
        return qc.violations(parsed, view or self.VIEW)

    def test_mission_present(self):
        self.assertTrue(self.found([entry(component="mission:ship-it")]))

    def test_mission_absent(self):
        self.assertEqual(self.found([entry(component="mission:nope")]), [])

    def test_playbook_composed(self):
        self.assertTrue(self.found([entry(component="playbook:risk-review")]))

    def test_playbook_not_composed(self):
        self.assertEqual(self.found([entry(component="playbook:other")]), [])

    def test_pack_star_matches_any_pin(self):
        self.assertTrue(self.found([entry(component="pack:gstack", ref="*")]))

    def test_pack_ref_prefix_both_ways(self):
        self.assertTrue(self.found([entry(component="pack:gstack", ref="71f6048e")]))
        self.assertTrue(self.found(
            [entry(component="pack:orca", ref="2bb20586")]))

    def test_pack_other_commit_is_clean(self):
        self.assertEqual(self.found([entry(component="pack:gstack", ref="deadbeef")]), [])

    def test_pack_unpinned_is_clean(self):
        self.assertEqual(self.found([entry(component="pack:nope")]), [])


def write_catalog(root: Path, quarantined):
    (root / "runtime").mkdir(parents=True)
    (root / "runtime" / "quarantine.json").write_text(
        json.dumps({"quarantined": quarantined}))
    (root / "playbooks").mkdir()
    (root / "playbooks" / "risk-review.md").write_text("# x\n")
    skill = root / "skills" / "ship-it"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("Composes `risk-review`; rides `evidence-manifest`.\n")


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(SCRIPT), *argv],
                              capture_output=True, text=True, timeout=60)

    def test_mission_mode_refuses_quarantined_playbook(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_catalog(Path(tmp), [entry(component="playbook:risk-review")])
            result = self.run_cli("--root", tmp, "--mission", "ship-it")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_catalog_mode_clean_when_nothing_routes(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_catalog(Path(tmp), [entry(component="mission:ship-it")])
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("present in the catalog", result.stdout)

    def test_malformed_file_cannot_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            (root / "runtime" / "quarantine.json").write_text("{broken")
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 3)

    def test_directory_at_deny_list_path_cannot_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "runtime" / "quarantine.json").mkdir(parents=True)
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 3)

    def test_invalid_utf8_cannot_evaluate_not_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            (root / "runtime" / "quarantine.json").write_bytes(b"\xff\xfe{}")
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 3)
            self.assertNotIn("Traceback", result.stderr)

    def test_broken_pins_beside_pack_entry_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_catalog(root, [entry(component="pack:gstack")])
            (root / "runtime" / "pins.json").write_text("{broken")
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("cannot be cleared", result.stdout)

    def test_broken_pins_without_pack_entries_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_catalog(root, [])
            (root / "runtime" / "pins.json").write_text("{broken")
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bundle_layout_playbooks_are_checked(self):
        # The dist bundle vendors playbooks under skills/<m>/references/ and
        # has no playbooks/ dir; a playbook quarantine must still refuse there.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            (root / "runtime" / "quarantine.json").write_text(
                json.dumps({"quarantined": [entry(component="playbook:risk-review")]}))
            refs = root / "skills" / "ship-it" / "references"
            refs.mkdir(parents=True)
            (refs / "risk-review.md").write_text("# x\n")
            (root / "skills" / "ship-it" / "SKILL.md").write_text(
                "Composes `risk-review`.\n")
            result = self.run_cli("--root", tmp, "--mission", "ship-it")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)

    def test_missing_mission_cannot_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            (root / "runtime" / "quarantine.json").write_text(
                json.dumps({"quarantined": []}))
            result = self.run_cli("--root", tmp, "--mission", "ghost")
            self.assertEqual(result.returncode, 3)
            self.assertNotIn("Traceback", result.stderr)

    def test_absent_file_says_no_quarantine_in_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli("--root", tmp, "--catalog")
            self.assertEqual(result.returncode, 0)
            self.assertIn("no quarantine in force", result.stderr)


class ShippedTree(unittest.TestCase):
    def test_shipped_deny_list_is_well_formed_and_clean(self):
        entries, errors, present = qc.load_quarantine(ROOT)
        self.assertTrue(present, "runtime/quarantine.json must ship in this repo")
        self.assertEqual(errors, [])
        view = qc.catalog_view(ROOT)
        self.assertEqual(
            qc.violations(entries, {**view, "missions": set()}), [])

    def test_every_mission_start_names_itself_to_preflight(self):
        # The refusal only fires where a mission start passes --mission; a
        # mission that drops it would silently un-quarantine itself.
        for skill_dir in sorted((ROOT / "skills").iterdir()):
            if skill_dir.is_dir():
                text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn(f"--mission {skill_dir.name}", text, skill_dir.name)


if __name__ == "__main__":
    unittest.main()
