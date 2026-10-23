#!/usr/bin/env python3
"""bundle.py --out never deletes what it did not write (#623; 2026-10-23 review, P2-21).

build() used to rmtree <out>/.claude-plugin, hooks, runtime and skills whenever they were not
the source's own tree, so `--out ~/.claude` deleted the user's own skills/ (where the README's
symlink install puts missions), hooks/ and runtime/ with exit 0. A build now records what it
writes in <out>/.open-fleet-bundle.json, a rebuild deletes only those files, and anything else
where the build would write makes it refuse — exit 2, nothing deleted, nothing written.
"""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bundle_out", ROOT / "scripts" / "bundle.py")
bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bundle)


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink()}


def run_main(*argv):
    err = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
        code = bundle.main(list(argv))
    return code, err.getvalue()


class UserContentSurvives(unittest.TestCase):
    def test_a_users_own_skill_hook_and_runtime_file_survive_a_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            mine = {"skills/mine/SKILL.md": "---\nname: mine\n---\nmy own skill\n",
                    "hooks/my-hook.sh": "echo mine\n",
                    "runtime/my-notes.txt": "mine\n",
                    "settings.json": "{}\n"}
            for rel, text in mine.items():
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                (out / rel).write_text(text, encoding="utf-8")
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            for rel, text in mine.items():
                self.assertEqual((out / rel).read_text(encoding="utf-8"), text, rel)
            self.assertTrue((out / "skills" / "ship-it" / "SKILL.md").is_file())
            owned = json.loads((out / bundle.MARKER).read_text(encoding="utf-8"))["files"]
            self.assertNotIn("skills/mine/SKILL.md", owned)
            self.assertIn("skills/ship-it/SKILL.md", owned)

    def test_unmarked_content_where_the_bundle_writes_refuses_and_deletes_nothing(self):
        collisions = (
            "skills/ship-it/SKILL.md",          # a user's own skill under a mission's name
            "hooks/hooks.json",                 # a user's own hook manifest
            ".claude-plugin/plugin.json",
            "runtime/scripts/verify.py",
        )
        for rel in collisions:
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                (out / "skills" / "mine").mkdir(parents=True)
                (out / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                (out / rel).write_text("not the bundle's\n", encoding="utf-8")
                before = snapshot(out)
                code, err = run_main("--out", tmp)
                self.assertEqual(code, 2, err)
                self.assertIn(rel, err)
                self.assertEqual(snapshot(out), before, "a refused build changed --out")

    def test_a_symlink_install_at_the_target_refuses(self):
        # The README's symlink install: ~/.claude/skills/ship-it -> <clone>/skills/ship-it.
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as clone:
            out = Path(tmp)
            (Path(clone) / "ship-it").mkdir()
            (Path(clone) / "ship-it" / "SKILL.md").write_text("linked\n", encoding="utf-8")
            (out / "skills").mkdir()
            (out / "skills" / "ship-it").symlink_to(Path(clone) / "ship-it")
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertTrue((out / "skills" / "ship-it").is_symlink())
            self.assertEqual((Path(clone) / "ship-it" / "SKILL.md").read_text(), "linked\n")

    def test_a_user_file_inside_a_bundled_mission_refuses_the_rebuild(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(bundle.build(out), (22, []))
            note = out / "skills" / "ship-it" / "my-note.md"
            note.write_text("mine\n", encoding="utf-8")
            with self.assertRaises(bundle.BundleRefused):
                bundle.build(out)
            self.assertEqual(note.read_text(encoding="utf-8"), "mine\n")

    def test_a_retired_missions_symlinked_directory_is_never_followed(self):
        """PR #631 review, P1: a mission the catalog dropped stays in the marker. With its
        directory swapped for a symlink into another checkout, the rebuild's unlink followed it
        and deleted that checkout's SKILL.md. The rebuild must refuse and delete nothing."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            out, elsewhere = Path(tmp), Path(other)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            marker = out / bundle.MARKER
            data = json.loads(marker.read_text(encoding="utf-8"))
            data["files"].append("skills/retired-mission/SKILL.md")
            marker.write_text(json.dumps(data), encoding="utf-8")
            (elsewhere / "SKILL.md").write_text("another checkout's mission\n", encoding="utf-8")
            (out / "skills" / "retired-mission").symlink_to(elsewhere, target_is_directory=True)
            before = snapshot(out)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("retired-mission", err)
            self.assertEqual((elsewhere / "SKILL.md").read_text(encoding="utf-8"),
                             "another checkout's mission\n")
            self.assertEqual(snapshot(out), before, "a refused rebuild changed the tree")

    def test_a_tree_marked_before_the_rename_still_rebuilds(self):
        """PR #633 review, P2: a bundle an earlier build marked with the pre-rename marker name
        must rebuild, not read as foreign; the rebuild migrates it to the new marker."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            (out / bundle.MARKER).rename(out / bundle.LEGACY_MARKER)
            (out / "notes.txt").write_text("mine\n", encoding="utf-8")
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertTrue((out / bundle.MARKER).is_file())
            self.assertFalse((out / bundle.LEGACY_MARKER).exists())
            self.assertEqual((out / "notes.txt").read_text(encoding="utf-8"), "mine\n")
            self.assertTrue((out / "skills" / "ship-it" / "SKILL.md").is_file())

    def test_a_malformed_marker_refuses(self):
        for contents in ("{", "[]", '{"files": "x"}', '{"files": ["../../etc/passwd"]}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / bundle.MARKER).write_text(contents, encoding="utf-8")
                with self.assertRaises(bundle.BundleRefused):
                    bundle.build(tmp)


class RebuildsStillWork(unittest.TestCase):
    def test_a_rebuild_over_a_previous_bundle_replaces_only_what_it_wrote(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(bundle.build(out), (22, []))
            (out / "skills" / "mine").mkdir()
            (out / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")
            # A file the previous build wrote and this one will not (a retired mission).
            marker = out / bundle.MARKER
            data = json.loads(marker.read_text(encoding="utf-8"))
            (out / "skills" / "retired-it").mkdir()
            (out / "skills" / "retired-it" / "SKILL.md").write_text("old\n", encoding="utf-8")
            data["files"].append("skills/retired-it/SKILL.md")
            marker.write_text(json.dumps(data), encoding="utf-8")
            stale = out / "skills" / "ship-it" / "references" / "README.md"
            stale.write_text("stale copy\n", encoding="utf-8")
            self.assertEqual(bundle.build(out), (22, []))
            self.assertFalse((out / "skills" / "retired-it").exists(), "an owned dir was kept")
            self.assertEqual((out / "skills" / "mine" / "SKILL.md").read_text(), "mine\n")
            self.assertNotEqual(stale.read_text(encoding="utf-8"), "stale copy\n")
            self.assertEqual(run_main("--out", tmp)[0], 0)


class ReadsAreUtf8(unittest.TestCase):
    def test_missing_inputs_never_reads_with_the_locale_codec(self):
        real = Path.read_text
        bare = []

        def read_text(path, *args, **kwargs):
            if not args and "encoding" not in kwargs:
                bare.append(str(path))
            return real(path, *args, **kwargs)

        with mock.patch.object(Path, "read_text", read_text):
            bundle.missing_inputs(bundle.validate.known_protocol_names())
        self.assertEqual(bare, [], "bundle.py:107 read a catalog file with the locale's codec")


if __name__ == "__main__":
    unittest.main()
