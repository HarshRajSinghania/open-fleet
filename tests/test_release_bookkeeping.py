#!/usr/bin/env python3
"""What pull requests stopped writing, and the release cut now writes (CI speed and bookkeeping).

Every PR changed the test count, so every PR rewrote assets/badges/tests.json and, with strict
up-to-date branches, every merge put every other open PR into conflict. Between releases the
tests badge is now held to its SHAPE (an "N in source" inventory, never a pass/fail claim), not
to today's count, and the README badge says it is the last release's;
`gen-badges.py --release` and `--check --release` are the cut's full write and check.

    python3 -m unittest tests.test_release_bookkeeping -v
"""
import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TheTestsBadgeBetweenReleases(unittest.TestCase):
    def setUp(self):
        self.gb = load("scripts/gen-badges.py", "_bookkeeping_gen")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        where = Path(self.tmp.name)
        self.badges = where / "badges"
        self.badges.mkdir()
        # Every generated surface points at a copy, never the live tree (2026-10-23 review, P2-24).
        shutil.copytree(ROOT / "docs" / "missions", where / "missions")
        for name in ("ARCHITECTURE.md", "README.md"):
            shutil.copy2(ROOT / name, where / name)
        patch = mock.patch.multiple(self.gb, BADGES_DIR=self.badges, GUIDES_DIR=where / "missions",
                                    ARCH=where / "ARCHITECTURE.md", README=where / "README.md")
        patch.start()
        self.addCleanup(patch.stop)
        self.current = self.gb.compute()
        for name, data in self.current.items():
            (self.badges / name).write_text(json.dumps(data), encoding="utf-8")

    def tests_badge(self, **fields):
        data = {**self.current["tests.json"], **fields}
        (self.badges / "tests.json").write_text(json.dumps(data), encoding="utf-8")

    def test_an_older_count_passes_between_releases_and_fails_at_the_cut(self):
        self.tests_badge(message="12 in source")
        self.assertEqual(self.gb.check(include_test_count=False), [])
        errors = self.gb.check()
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("tests.json is stale", errors[0])
        self.assertIn("gen-badges.py --release", errors[0])

    def test_validate_holds_the_badge_to_its_shape_only(self):
        validate = load("scripts/validate.py", "_bookkeeping_validate")
        self.tests_badge(message="12 in source")
        self.assertEqual(validate.check_badge_freshness(self.gb), [])
        self.tests_badge(message="12 passing")
        self.assertTrue(validate.check_badge_freshness(self.gb))

    def test_a_badge_that_reads_as_a_verdict_fails_even_between_releases(self):
        for label, fields, why in (
                ("a pass claim", {"message": "4714 passing"}, "message"),
                ("a green verdict colour", {"color": "2ea043"}, "color"),
                ("another label", {"label": "tests"}, "label"),
                ("an extra field", {"isError": False}, "isError"),
                ("no count", {"message": "many in source"}, "message")):
            with self.subTest(case=label):
                self.tests_badge(**fields)
                errors = self.gb.check(include_test_count=False)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn("tests.json is malformed", errors[0])
                self.assertIn(why, errors[0])
        (self.badges / "tests.json").write_text("[]", encoding="utf-8")
        self.assertIn("not a badge object", self.gb.check(include_test_count=False)[0])
        (self.badges / "tests.json").unlink()
        self.assertIn("tests.json missing", self.gb.check(include_test_count=False)[0])

    def test_a_pull_request_write_keeps_the_release_count(self):
        self.tests_badge(message="12 in source")
        (self.badges / "missions.json").write_text("{}", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.gb.write(include_tests=False)
        self.assertIn("kept assets/badges/tests.json", out.getvalue())
        self.assertEqual(json.loads((self.badges / "tests.json").read_text())["message"],
                         "12 in source")
        self.assertEqual(json.loads((self.badges / "missions.json").read_text()),
                         self.current["missions.json"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.gb.write(include_tests=True)
        self.assertEqual(json.loads((self.badges / "tests.json").read_text()),
                         self.current["tests.json"])
        self.assertEqual(self.gb.check(), [])

    def test_the_cli_maps_release_to_the_count(self):
        # Read-only against the live tree: --check is the PR check, --check --release the cut's.
        script = str(ROOT / "scripts" / "gen-badges.py")
        pr = subprocess.run([sys.executable, script, "--check"], capture_output=True, text=True)
        self.assertEqual(pr.returncode, 0, pr.stderr)
        cut = subprocess.run([sys.executable, script, "--check", "--release"],
                             capture_output=True, text=True)
        live = load("scripts/gen-badges.py", "_bookkeeping_gen_live")
        self.assertEqual(cut.returncode, 1 if live.check() else 0, cut.stderr)

    def test_the_readme_badge_says_whose_count_it_is(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        badge = [ln for ln in readme.splitlines() if "assets/badges/tests.json" in ln]
        self.assertEqual(len(badge), 1, badge)
        self.assertIn("label=test%20functions%20at%20last%20release", badge[0])
        self.assertIn('alt="contract test functions at the last release"', badge[0])


if __name__ == "__main__":
    unittest.main()
