#!/usr/bin/env python3
"""bundle.py --out deletes only what it can vouch for from outside --out (#623; 2026-10-23 review, P2-21;
2026-10-27 audit, W5-10).

build() used to rmtree <out>/.claude-plugin, hooks, runtime and skills whenever they were not
the source's own tree, so `--out ~/.claude` deleted the user's own skills/ (where the README's
symlink install puts missions), hooks/ and runtime/ with exit 0. A build now records what it
writes in <out>/.open-fleet-bundle.json, and anything else where the build would write makes it
refuse — exit 2, nothing deleted, nothing written. That marker lives in --out, so it only names
candidates: a listed file is the bundle's only when the build record kept OUTSIDE --out holds its
exact bytes, when the source repository committed them at the path the build copies it from, or
when they are the bytes this build writes there anyway.
"""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bundle_out", ROOT / "scripts" / "bundle.py")
bundle = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bundle)


_RECORDS = []


def setUpModule():
    # Build records go to a scratch directory, never the source checkout's git directory.
    records = tempfile.TemporaryDirectory()
    patcher = mock.patch.dict(os.environ, {bundle.RECORDS_ENV: records.name})
    patcher.start()
    _RECORDS.extend([patcher, records])


def tearDownModule():
    patcher, records = _RECORDS
    patcher.stop()
    records.cleanup()


def remember(out, files):
    """Add {rel: bytes} to --out's build record, as the build that wrote them would have."""
    path = bundle._record_path(out)
    doc = (json.loads(path.read_text(encoding="utf-8")) if path.is_file()
           else {"out": os.path.realpath(out), "files": {}})
    doc["files"].update({rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


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

    def test_a_directory_where_a_bundle_file_goes_refuses_the_build(self):
        """PR #681 review (Codex at db5023703c): an empty directory at README.md took the copy
        inside it, README.md/bundle-README.md, and the build passed with no README. A directory
        at any file destination, on a first build or a rebuild, refuses and changes nothing."""
        for rebuild in (False, True):
            for rel in ("README.md", ".claude-plugin/icon.png", "hooks/hooks.json", "LICENSE"):
                with self.subTest(rel=rel, rebuild=rebuild), tempfile.TemporaryDirectory() as tmp:
                    out = Path(tmp)
                    if rebuild:
                        self.assertEqual(bundle.build(out), (22, []))
                        (out / rel).unlink()
                    (out / rel).mkdir(parents=True)
                    before = snapshot(out)
                    code, err = run_main("--out", tmp)
                    self.assertEqual(code, 2, err)
                    self.assertIn(rel, err)
                    self.assertEqual(snapshot(out), before, "a refused build changed the tree")
                    self.assertTrue((out / rel).is_dir())

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
            # A retired mission's vendored runtime copy: committed bytes of its source path, which
            # is what lets a rebuild delete it (Codex review of 82a2d00c: a digest in the marker
            # is no proof; the source repository's history is).
            retired = out / "skills" / "retired-it" / "runtime" / "scripts" / "verify.py"
            retired.parent.mkdir(parents=True)
            retired.write_bytes(committed_bytes("runtime/scripts/verify.py"))
            # A build records each file it wrote WITH the digest of its bytes (2026-10-27 audit,
            # W5-10): the retired file and the stale copy are what an earlier build wrote.
            data["files"].append("skills/retired-it/runtime/scripts/verify.py")
            data["sha256"]["skills/retired-it/runtime/scripts/verify.py"] = hashlib.sha256(
                retired.read_bytes()).hexdigest()
            stale = out / "skills" / "ship-it" / "references" / "README.md"
            stale.write_text("stale copy\n", encoding="utf-8")
            data["sha256"]["skills/ship-it/references/README.md"] = hashlib.sha256(b"stale copy\n").hexdigest()
            marker.write_text(json.dumps(data), encoding="utf-8")
            # ...and its build record, kept outside --out, says so too (re-attack of 4b24dfde: the
            # marker alone vouches for nothing, not even inside a mission directory).
            remember(out, {"skills/ship-it/references/README.md": b"stale copy\n"})
            self.assertEqual(bundle.build(out), (22, []))
            self.assertFalse((out / "skills" / "retired-it").exists(), "an owned dir was kept")
            self.assertEqual((out / "skills" / "mine" / "SKILL.md").read_text(), "mine\n")
            self.assertNotEqual(stale.read_text(encoding="utf-8"), "stale copy\n")
            self.assertEqual(run_main("--out", tmp)[0], 0)


class AForgedMarkerDeletesNothing(unittest.TestCase):
    """2026-10-27 audit, W5-10 / W5-11 (verify-v3 §C3). The marker sits inside the tree it
    authorises deleting, and a well-formed list was obeyed: two forged names deleted
    ~/.claude/settings.json and CLAUDE.md with exit 0, and a symlinked marker was followed and
    its target rewritten. The tests above covered only malformed markers."""

    def built(self, tmp):
        code, err = run_main("--out", tmp)
        self.assertEqual(code, 0, err)
        return Path(tmp)

    def forge(self, out, names, digests=()):
        marker = out / bundle.MARKER
        data = json.loads(marker.read_text(encoding="utf-8"))
        data["files"] += names
        data.setdefault("sha256", {}).update(dict(digests))
        marker.write_text(json.dumps(data), encoding="utf-8")

    def test_forged_names_outside_what_a_build_writes_delete_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            mine = {"settings.json": b"the completion-gate hook wiring\n", "CLAUDE.md": b"my instructions\n"}
            for rel, data in mine.items():
                (out / rel).write_bytes(data)
            # The right digests too: a forger who can read a file can hash it.
            self.forge(out, list(mine), {rel: hashlib.sha256(data).hexdigest() for rel, data in mine.items()})
            before = snapshot(out)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("settings.json", err)
            for rel, data in mine.items():
                self.assertEqual((out / rel).read_bytes(), data, f"{rel} was deleted on a forged marker's word")
            self.assertEqual(snapshot(out), before, "a refused rebuild changed --out")

    def test_a_listed_file_the_build_did_not_write_is_not_deleted(self):
        # A user's own skill sits where missions go, so its name alone cannot tell it apart: the
        # recorded digest of what the build wrote must match its bytes.
        for digests in ({}, {"skills/mine/SKILL.md": "0" * 64}):
            with self.subTest(digests=digests), tempfile.TemporaryDirectory() as tmp:
                out = self.built(tmp)
                mine = out / "skills" / "mine" / "SKILL.md"
                mine.parent.mkdir()
                mine.write_text("mine\n", encoding="utf-8")
                self.forge(out, ["skills/mine/SKILL.md"], digests)
                before = snapshot(out)
                code, err = run_main("--out", tmp)
                self.assertEqual(code, 2, err)
                self.assertIn("skills/mine/SKILL.md", err)
                self.assertEqual(mine.read_text(encoding="utf-8"), "mine\n")
                self.assertEqual(snapshot(out), before)

    def test_a_changed_bundle_file_is_not_deleted_on_the_markers_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            note = out / "skills" / "ship-it" / "SKILL.md"
            note.write_text("edited by hand\n", encoding="utf-8")
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertEqual(note.read_text(encoding="utf-8"), "edited by hand\n")

    def test_a_marker_without_digests_refuses_rather_than_deletes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            marker = out / bundle.MARKER
            data = json.loads(marker.read_text(encoding="utf-8"))
            data.pop("sha256", None)
            marker.write_text(json.dumps(data), encoding="utf-8")
            before = snapshot(out)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("digest", err)
            self.assertEqual(snapshot(out), before)

    def test_a_digested_entry_behind_a_symlinked_directory_still_refuses(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            out, elsewhere = self.built(tmp), Path(other)
            (elsewhere / "SKILL.md").write_text("another checkout's mission\n", encoding="utf-8")
            (out / "skills" / "retired-mission").symlink_to(elsewhere, target_is_directory=True)
            self.forge(out, ["skills/retired-mission/SKILL.md"],
                       {"skills/retired-mission/SKILL.md": hashlib.sha256(b"another checkout's mission\n").hexdigest()})
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertEqual((elsewhere / "SKILL.md").read_text(encoding="utf-8"), "another checkout's mission\n")

    def test_a_symlinked_marker_is_never_followed(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            out, outside = self.built(tmp), Path(other) / "marker.json"
            (out / "settings.json").write_text("mine\n", encoding="utf-8")
            data = json.loads((out / bundle.MARKER).read_text(encoding="utf-8"))
            data["files"].append("settings.json")
            outside.write_text(json.dumps(data), encoding="utf-8")
            (out / bundle.MARKER).unlink()
            (out / bundle.MARKER).symlink_to(outside)
            before = outside.read_bytes()
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("symlink", err)
            self.assertEqual((out / "settings.json").read_text(encoding="utf-8"), "mine\n")
            self.assertEqual(outside.read_bytes(), before, "the build wrote through the marker's link")

    def test_the_marker_is_replaced_never_written_through(self):
        # A link planted at the marker between the claim and the record is replaced, not followed.
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            out, victim = Path(tmp), Path(other) / "victim.json"
            victim.write_text("victim\n", encoding="utf-8")
            (out / bundle.MARKER).symlink_to(victim)
            tree = bundle._Tree(out)
            self.addCleanup(tree.close)
            bundle._record(tree, set())
            self.assertEqual(victim.read_text(encoding="utf-8"), "victim\n")
            self.assertFalse((out / bundle.MARKER).is_symlink())


def committed_bytes(rel):
    """The bytes the source repository has COMMITTED at `rel` (HEAD), not the working tree's."""
    return subprocess.run(["git", "-C", str(ROOT), "cat-file", "blob", f"HEAD:{rel}"],
                          capture_output=True, check=True).stdout


class ADigestInTheMarkerIsNoProof(unittest.TestCase):
    """Codex review of 82a2d00c (P1): a digest written into the marker proves nothing, because the
    marker sits in the tree it governs. A forger who can read a user's file under a generated name
    (`skills/<anything>/…`, `runtime/**`) lists it with its TRUE sha256, and the rebuild deleted it.
    The authority to delete comes from outside --out: a stale file goes only when the build record
    holds its exact bytes (re-attack of 2d254d0f: committed bytes vouched for any `skills/<x>/` copy)."""

    built = AForgedMarkerDeletesNothing.built
    forge = AForgedMarkerDeletesNothing.forge

    def test_a_user_file_under_a_generated_name_survives_a_forged_true_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            mine = {"skills/mine/SKILL.md": b"---\nname: mine\n---\nmy own skill\n",
                    "runtime/scripts/mine.py": b"print('mine')\n"}
            for rel, data in mine.items():
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                (out / rel).write_bytes(data)
            self.forge(out, list(mine), {rel: hashlib.sha256(data).hexdigest() for rel, data in mine.items()})
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            for rel, data in mine.items():
                self.assertEqual((out / rel).read_bytes(), data, f"{rel} was deleted on the marker's word")
                self.assertIn(rel, err, "a candidate left in place is not reported")
            owned = json.loads((out / bundle.MARKER).read_text(encoding="utf-8"))["files"]
            self.assertFalse(set(mine) & set(owned), "a file left in place was re-recorded as the bundle's")

    def test_a_user_file_at_a_path_the_build_copies_is_not_overwritten_on_a_forged_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            (out / "README.md").write_bytes(b"my own README\n")
            self.forge(out, [], {"README.md": hashlib.sha256(b"my own README\n").hexdigest()})
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("README.md", err)
            self.assertEqual((out / "README.md").read_bytes(), b"my own README\n")

    def test_a_retired_missions_committed_files_are_still_cleaned_up(self):
        # Cleaned up on the build record's word, and only on it (re-attack of 2d254d0f, W5-10): a
        # retired mission is in no source mapping of this build, so its copies of committed files
        # are indistinguishable from a user's own skill holding the same bytes, and without a
        # record they are left and reported (test_a_user_skills_copies_of_committed_files_survive).
        for recorded in (True, False):
            with self.subTest(recorded=recorded), tempfile.TemporaryDirectory() as tmp:
                out = self.built(tmp)
                retired = {"skills/retired-it/runtime/scripts/verify.py": committed_bytes("runtime/scripts/verify.py"),
                           "skills/retired-it/evals/evals.json": committed_bytes("skills/ship-it/evals/evals.json"),
                           "runtime/scripts/retired.py": committed_bytes("runtime/scripts/egress.py")}
                generated = {"skills/retired-it/SKILL.md": b"a generated copy no commit holds\n"}
                for rel, data in {**retired, **generated}.items():
                    (out / rel).parent.mkdir(parents=True, exist_ok=True)
                    (out / rel).write_bytes(data)
                both = {**retired, **generated}
                self.forge(out, list(both), {rel: hashlib.sha256(data).hexdigest() for rel, data in both.items()})
                if recorded:
                    remember(out, {"skills/retired-it/runtime/scripts/verify.py":
                                   retired["skills/retired-it/runtime/scripts/verify.py"]})
                code, err = run_main("--out", tmp)
                self.assertEqual(code, 0, err)
                if recorded:
                    self.assertFalse((out / "skills/retired-it/runtime/scripts/verify.py").exists(),
                                     "a retired mission's recorded copy was kept")
                else:
                    self.assertTrue((out / "skills/retired-it/runtime/scripts/verify.py").exists(),
                                    "a stale file deleted on history alone, with no record vouching for it")
                    self.assertIn("skills/retired-it/runtime/scripts/verify.py", err)
                self.assertTrue((out / "skills/retired-it/evals/evals.json").exists(),
                                "a file deleted on bytes committed at a different path")
                self.assertTrue((out / "runtime/scripts/retired.py").exists(),
                                "a root runtime file deleted on bytes committed at a different path")
                self.assertEqual((out / "skills/retired-it/SKILL.md").read_bytes(),
                                 generated["skills/retired-it/SKILL.md"])
                self.assertIn("skills/retired-it/SKILL.md", err)

    def test_a_user_skills_copies_of_committed_files_survive_a_forged_true_digest(self):
        # Re-attack of 2d254d0f (W5-10): a user's own skill holding a copy of docs/install.md under
        # references/ and of runtime/scripts/verify.py under runtime/scripts/, both listed with their
        # true sha256s, were deleted with rc 0 and nothing said -- any `skills/<x>/references/<name>`
        # was matched to any committed file of that basename, and `skills/<x>/runtime/**` to the
        # repository's runtime, though no build of this checkout writes skills/my-notes at all.
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            mine = {"skills/my-notes/references/install.md": committed_bytes("docs/install.md"),
                    "skills/my-notes/runtime/scripts/verify.py": committed_bytes("runtime/scripts/verify.py"),
                    "skills/ship-it/references/install.md": committed_bytes("docs/install.md")}
            for rel, data in mine.items():
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                (out / rel).write_bytes(data)
            self.forge(out, list(mine), {rel: hashlib.sha256(data).hexdigest() for rel, data in mine.items()})
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            for rel, data in mine.items():
                self.assertEqual((out / rel).read_bytes(), data, f"{rel} was deleted on committed bytes")
                self.assertIn(rel, err, "a candidate left in place is not reported")

    def test_an_overwrite_is_vouched_for_only_at_the_exact_source_this_build_copies(self):
        # The history that vouches for a file the build overwrites is that of the one path this
        # build copies it from: references/threat-model.md comes from runtime/threat-model.md, and
        # docs/runs/…/threat-model.md (the same basename, committed) proves nothing about it.
        rel = next(f"skills/{d.name}/references/threat-model.md" for d in sorted(bundle.SKILLS_DIR.iterdir())
                   if (d / "SKILL.md").is_file() and "threat-model" in bundle.protocol_docs(
                       (d / "SKILL.md").read_text(encoding="utf-8"), bundle.validate.known_protocol_names()))
        elsewhere = committed_bytes("docs/runs/2026-10-27-security-audit/threat-model.md")
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            bundle._record_path(out).unlink()
            (out / rel).write_bytes(elsewhere)
            self.forge(out, [], {rel: hashlib.sha256(elsewhere).hexdigest()})
            before = snapshot(out)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn(rel, err)
            self.assertEqual(snapshot(out), before, "a file overwritten on bytes committed at another path")
        # An earlier commit of the exact source path does vouch: the rebuild after an upgrade.
        rel = "skills/ship-it/runtime/scripts/verify.py"
        older = subprocess.run(["git", "-C", str(ROOT), "log", "-2", "--format=%H", "--", "runtime/scripts/verify.py"],
                               capture_output=True, text=True, check=True).stdout.split()[-1]
        earlier = subprocess.run(["git", "-C", str(ROOT), "cat-file", "blob", f"{older}:runtime/scripts/verify.py"],
                                 capture_output=True, check=True).stdout
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            bundle._record_path(out).unlink()
            (out / rel).write_bytes(earlier)
            self.forge(out, [], {rel: hashlib.sha256(earlier).hexdigest()})
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertEqual((out / rel).read_bytes(), (ROOT / "runtime/scripts/verify.py").read_bytes())

    def test_history_is_the_checked_out_commits_and_a_path_is_literal(self):
        # `git log --all` let any ref vouch -- a branch a worker made in a shared clone -- and a
        # pathspec was a glob. Only HEAD's history counts, at the literal path.
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            def git(*args):
                return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
                                       *args], capture_output=True, text=True, check=True).stdout.strip()

            git("init", "-q", "-b", "main")
            (repo / "a.txt").write_bytes(b"on HEAD\n")
            git("add", "a.txt")
            git("commit", "-qm", "head")
            git("checkout", "-qb", "side")
            (repo / "a.txt").write_bytes(b"only on a side branch\n")
            git("commit", "-qam", "side")
            git("checkout", "-q", "main")
            seen = bundle.committed_blobs(["a.txt"], repo=repo)
            ids = {blob for data in (b"on HEAD\n",) for blob in bundle._blob_ids(data)}
            self.assertTrue(ids & set(seen), "HEAD's own blob is not found")
            side = bundle._blob_ids(b"only on a side branch\n")
            self.assertFalse(side & set(seen), "a blob committed only on another ref vouched for bytes")
            self.assertFalse(bundle.committed_blobs(["*.txt"], repo=repo), "a path was read as a glob")

    def test_without_git_provenance_nothing_stale_is_deleted_and_that_is_said(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            rel = "skills/retired-it/runtime/scripts/verify.py"
            data = committed_bytes("runtime/scripts/verify.py")
            (out / rel).parent.mkdir(parents=True)
            (out / rel).write_bytes(data)
            self.forge(out, [rel], {rel: hashlib.sha256(data).hexdigest()})
            with mock.patch.object(bundle.gitexec, "GIT", None):
                code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertEqual((out / rel).read_bytes(), data)
            self.assertIn("provenance", err)


class TheBuildRecordIsTheAuthority(unittest.TestCase):
    """Re-attack of 4b24dfde (W5-10, the Codex P1 class): inside a mission directory the build
    writes whole, the marker was still trusted, so a forged TRUE digest deleted a user's
    skills/ship-it/my-notes.md and overwrote a user's own skills/review-it/SKILL.md with exit 0.
    A listed file is now the bundle's only on the word of the build record kept OUTSIDE --out,
    the source repository's history, or because the build writes those exact bytes anyway."""

    built = AForgedMarkerDeletesNothing.built
    forge = AForgedMarkerDeletesNothing.forge

    def test_a_forged_true_digest_inside_a_bundled_mission_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            note = out / "skills" / "ship-it" / "my-notes.md"
            note.write_bytes(b"my notes inside a bundled mission\n")
            self.forge(out, ["skills/ship-it/my-notes.md"],
                       {"skills/ship-it/my-notes.md": hashlib.sha256(note.read_bytes()).hexdigest()})
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertEqual(note.read_bytes(), b"my notes inside a bundled mission\n",
                             "a user's file in a mission directory was deleted on the marker's word")
            self.assertIn("skills/ship-it/my-notes.md", err)
            owned = json.loads((out / bundle.MARKER).read_text(encoding="utf-8"))["files"]
            self.assertNotIn("skills/ship-it/my-notes.md", owned)

    def test_a_forged_true_digest_never_overwrites_a_users_skill_under_a_missions_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            mine = out / "skills" / "review-it" / "SKILL.md"
            mine.write_bytes(b"---\nname: review-it\n---\nMY OWN review-it skill\n")
            self.forge(out, [], {"skills/review-it/SKILL.md": hashlib.sha256(mine.read_bytes()).hexdigest()})
            before = snapshot(out)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("skills/review-it/SKILL.md", err)
            self.assertEqual(snapshot(out), before, "a refused rebuild changed --out")

    def test_what_the_record_says_a_build_wrote_is_replaced_and_cleaned_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            earlier = {"skills/ship-it/SKILL.md": b"an earlier build's generated SKILL.md\n",
                       "skills/retired-it/SKILL.md": b"a retired mission's generated SKILL.md\n"}
            for rel, data in earlier.items():
                (out / rel).parent.mkdir(parents=True, exist_ok=True)
                (out / rel).write_bytes(data)
            self.forge(out, ["skills/retired-it/SKILL.md"],
                       {rel: hashlib.sha256(data).hexdigest() for rel, data in earlier.items()})
            remember(out, earlier)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertNotEqual((out / "skills/ship-it/SKILL.md").read_bytes(), earlier["skills/ship-it/SKILL.md"])
            self.assertFalse((out / "skills" / "retired-it").exists(), "a recorded retired mission was kept")

    def test_without_a_record_a_changed_generated_file_refuses_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            bundle._record_path(out).unlink()
            old = b"an earlier build's generated SKILL.md\n"
            (out / "skills/ship-it/SKILL.md").write_bytes(old)
            self.forge(out, [], {"skills/ship-it/SKILL.md": hashlib.sha256(old).hexdigest()})
            before = snapshot(out)
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("no build record", err)
            self.assertEqual(snapshot(out), before)

    def test_a_record_for_another_out_or_behind_a_link_vouches_for_nothing(self):
        for shape in ("other-out", "symlink", "fifo"):
            with self.subTest(shape=shape), tempfile.TemporaryDirectory() as tmp, \
                    tempfile.TemporaryDirectory() as other:
                out = self.built(tmp)
                mine = out / "skills" / "ship-it" / "my-notes.md"
                mine.write_bytes(b"mine\n")
                self.forge(out, ["skills/ship-it/my-notes.md"],
                           {"skills/ship-it/my-notes.md": hashlib.sha256(b"mine\n").hexdigest()})
                remember(out, {"skills/ship-it/my-notes.md": b"mine\n"})
                record = bundle._record_path(out)
                doc = json.loads(record.read_text(encoding="utf-8"))
                record.unlink()
                if shape == "other-out":
                    doc["out"] = os.path.realpath(other)
                    record.write_text(json.dumps(doc), encoding="utf-8")
                elif shape == "symlink":
                    (Path(other) / "record.json").write_text(json.dumps(doc), encoding="utf-8")
                    record.symlink_to(Path(other) / "record.json")
                else:
                    os.mkfifo(record)
                code, err = run_main("--out", tmp)
                self.assertEqual(code, 0, err)
                self.assertEqual(mine.read_bytes(), b"mine\n")
                self.assertIn("skills/ship-it/my-notes.md", err)

    def test_a_records_directory_inside_out_is_never_trusted(self):
        # Whatever can write --out could write a record kept there, so one there vouches for nothing.
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            mine = out / "skills" / "ship-it" / "my-notes.md"
            mine.write_bytes(b"mine\n")
            self.forge(out, ["skills/ship-it/my-notes.md"],
                       {"skills/ship-it/my-notes.md": hashlib.sha256(b"mine\n").hexdigest()})
            inside = out / "records"
            inside.mkdir()
            name = hashlib.sha256(os.fsencode(os.path.realpath(out))).hexdigest() + ".json"
            (inside / name).write_text(json.dumps({"out": os.path.realpath(out), "files": {
                "skills/ship-it/my-notes.md": hashlib.sha256(b"mine\n").hexdigest()}}), encoding="utf-8")
            with mock.patch.dict(os.environ, {bundle.RECORDS_ENV: str(inside)}):
                self.assertIsNone(bundle._record_path(out))
                code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertEqual(mine.read_bytes(), b"mine\n", "a record kept inside --out was trusted")
            self.assertIn("kept no build record", err)

    def test_the_record_lives_outside_out_and_check_keeps_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            record = bundle._record_path(out)
            self.assertTrue(record.is_file())
            self.assertFalse(str(record.resolve()).startswith(os.path.realpath(out) + os.sep))
            self.assertEqual(stat.S_IMODE(record.stat().st_mode), 0o600)
            files = json.loads(record.read_text(encoding="utf-8"))["files"]
            self.assertEqual(files["skills/ship-it/SKILL.md"],
                             hashlib.sha256((out / "skills/ship-it/SKILL.md").read_bytes()).hexdigest())
        records = Path(os.environ[bundle.RECORDS_ENV])
        before = sorted(records.iterdir())
        self.assertEqual(run_main("--check")[0], 0)
        self.assertEqual(sorted(records.iterdir()), before, "--check kept a build record")


class NothingIsReResolvedAfterItsCheck(unittest.TestCase):
    """Re-attack of 82a2d00c (W5-10/W5-11). A directory swapped for a symlink to an outside tree
    AFTER the checks aimed the deletes and the writes outside --out (5/5 on each). Every delete
    and write now walks --out from one directory fd, a component at a time, never following a
    link. A FIFO at the marker hung the build, and a NUL in a listed name tracebacked after
    deleting what sorted before it."""

    built = AForgedMarkerDeletesNothing.built
    forge = AForgedMarkerDeletesNothing.forge

    def swap_after_claim(self, out, mission, victim):
        real = bundle._claim

        def claim_then_swap(*args, **kwargs):
            decided = real(*args, **kwargs)
            (out / "skills" / mission).rename(out / f"{mission}.aside")
            (out / "skills" / mission).symlink_to(victim, target_is_directory=True)
            return decided

        return mock.patch.object(bundle, "_claim", claim_then_swap)

    def test_a_directory_swapped_after_the_checks_never_aims_a_write_outside(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            out, victim = self.built(tmp), Path(other)
            (victim / "SKILL.md").write_text("PRECIOUS user file outside --out\n", encoding="utf-8")
            with self.swap_after_claim(out, "speed-it", victim):
                code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertEqual(sorted(p.name for p in victim.iterdir()), ["SKILL.md"], "the build wrote outside --out")
            self.assertEqual((victim / "SKILL.md").read_text(encoding="utf-8"), "PRECIOUS user file outside --out\n")

    def test_a_directory_swapped_after_the_checks_gets_no_new_file_outside(self):
        # The test above swaps in a directory already holding the first name the build writes there
        # (SKILL.md), so the exchange's own check refused it even with every lookup following links:
        # with O_NOFOLLOW dropped from _Tree.dirs that mutant wrote 105 files outside --out and the
        # suite stayed green (re-attack of 2d254d0f). Here nothing outside holds a name the build
        # writes, so only the directory walk itself can stop a write landing there.
        for swapped in ("skills/speed-it", "runtime"):
            with self.subTest(swapped=swapped), tempfile.TemporaryDirectory() as tmp, \
                    tempfile.TemporaryDirectory() as other:
                out, victim = self.built(tmp), Path(other)
                (victim / "keep.txt").write_text("a user's own file outside --out\n", encoding="utf-8")
                real = bundle._claim

                def claim_then_swap(*args, swapped=swapped, **kwargs):
                    decided = real(*args, **kwargs)
                    (out / swapped).rename(out / f"{swapped}.aside")
                    (out / swapped).symlink_to(victim, target_is_directory=True)
                    return decided

                with mock.patch.object(bundle, "_claim", claim_then_swap):
                    code, err = run_main("--out", tmp)
                self.assertEqual(code, 2, err)
                self.assertEqual(sorted(p.relative_to(victim).as_posix() for p in victim.rglob("*")), ["keep.txt"],
                                 "the build wrote through a directory swapped for a symlink")
                self.assertEqual((victim / "keep.txt").read_text(encoding="utf-8"), "a user's own file outside --out\n")

    def test_a_directory_swapped_after_the_checks_never_aims_a_delete_outside(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as other:
            out, victim = self.built(tmp), Path(other)
            stale = out / "skills" / "speed-it" / "old-reference.md"
            stale.write_bytes(b"a stale copy\n")
            self.forge(out, ["skills/speed-it/old-reference.md"],
                       {"skills/speed-it/old-reference.md": hashlib.sha256(b"a stale copy\n").hexdigest()})
            remember(out, {"skills/speed-it/old-reference.md": b"a stale copy\n"})  # a delete IS planned
            (victim / "old-reference.md").write_text("PRECIOUS\n", encoding="utf-8")
            (victim / "id_ed25519").write_text("PRECIOUS\n", encoding="utf-8")
            self.forge(out, ["skills/speed-it/id_ed25519"], {"skills/speed-it/id_ed25519": "0" * 64})
            with self.swap_after_claim(out, "speed-it", victim):
                code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertEqual((victim / "old-reference.md").read_text(encoding="utf-8"), "PRECIOUS\n")
            self.assertEqual((victim / "id_ed25519").read_text(encoding="utf-8"), "PRECIOUS\n")

    def test_a_fifo_at_the_marker_or_a_listed_path_refuses_without_hanging(self):
        for rel in (bundle.MARKER, "LICENSE"):
            with self.subTest(rel=rel), tempfile.TemporaryDirectory() as tmp:
                out = self.built(tmp)
                (out / rel).unlink()
                os.mkfifo(out / rel)
                try:
                    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "bundle.py"), "--out", tmp],
                                          capture_output=True, text=True, timeout=120)
                except subprocess.TimeoutExpired:
                    self.fail(f"a FIFO at {rel} hung the build")
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertTrue(stat.S_ISFIFO(os.lstat(out / rel).st_mode))

    def test_every_listed_name_is_checked_before_anything_changes(self):
        for bad in ("skills/a\u0000b/c", "skills/x/./y", "skills/x//y", "skills/x/y/"):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as tmp:
                out = self.built(tmp)
                stale = out / "skills" / "ship-it" / "a-stale.md"   # sorts before the bad name
                stale.write_bytes(b"stale\n")
                self.forge(out, ["skills/ship-it/a-stale.md", bad],
                           {"skills/ship-it/a-stale.md": hashlib.sha256(b"stale\n").hexdigest(), bad: "0" * 64})
                before = snapshot(out)
                code, err = run_main("--out", tmp)
                self.assertEqual(code, 2, err)
                self.assertEqual(snapshot(out), before, "a refused build changed --out")


class TheActIsTheCheck(unittest.TestCase):
    """Codex round 2 on e281e130 (P1, W5-10's class): after _claim checked a file, the overwrite
    renamed the staged copy over whatever held the name by then, and the delete re-read the bytes
    and then unlinked the name, so a file swapped in after the check was destroyed unchecked. Each
    act is now one atomic step (an exchange, or a rename to quarantine) and what it displaced is
    verified through its own descriptor, inode and sha256, before it is destroyed; anything else is
    put back and the build refuses. The hook replaces the FINAL file between check and act."""

    built = AForgedMarkerDeletesNothing.built
    forge = AForgedMarkerDeletesNothing.forge
    USER = b"---\nname: review-it\n---\nTHE USER'S OWN BYTES, written after the check\n"

    def replace_after_claim(self, target, how):
        real = bundle._claim

        def claim_then_replace(*args, **kwargs):
            decided = real(*args, **kwargs)
            if how == "new file":
                fresh = target.with_name(target.name + ".user")
                fresh.write_bytes(self.USER)
                os.replace(fresh, target)
            elif how == "in place":
                with open(target, "r+b") as fh:
                    fh.write(self.USER)
                    fh.truncate()
            else:  # the very bytes that were checked, in another file: still not the file checked
                fresh = target.with_name(target.name + ".user")
                fresh.write_bytes(target.read_bytes())
                os.replace(fresh, target)
            return decided

        return mock.patch.object(bundle, "_claim", claim_then_replace)

    def test_a_file_replaced_after_the_check_is_never_overwritten(self):
        for how in ("new file", "in place", "same bytes, another file"):
            with self.subTest(how=how), tempfile.TemporaryDirectory() as tmp:
                out = self.built(tmp)
                target = out / "skills" / "review-it" / "SKILL.md"
                with self.replace_after_claim(target, how):
                    code, err = run_main("--out", tmp)
                self.assertEqual(code, 2, err)
                self.assertIn("changed after it was checked", err)
                expected = self.USER if how != "same bytes, another file" else None
                if expected is not None:
                    self.assertEqual(target.read_bytes(), expected, "the replacement was overwritten unchecked")
                self.assertFalse(target.is_symlink())
                strays = [p for p in target.parent.iterdir() if ".open-fleet-" in p.name]
                self.assertEqual(strays, [], "the act left a temp or quarantine file behind")

    def test_a_file_replaced_after_the_check_is_never_deleted(self):
        for how in ("new file", "in place"):
            with self.subTest(how=how), tempfile.TemporaryDirectory() as tmp:
                out = self.built(tmp)
                stale = out / "skills" / "speed-it" / "old-reference.md"
                stale.write_bytes(b"a stale copy\n")
                self.forge(out, ["skills/speed-it/old-reference.md"],
                           {"skills/speed-it/old-reference.md": hashlib.sha256(b"a stale copy\n").hexdigest()})
                remember(out, {"skills/speed-it/old-reference.md": b"a stale copy\n"})  # a delete IS planned
                with self.replace_after_claim(stale, how):
                    code, err = run_main("--out", tmp)
                self.assertEqual(code, 2, err)
                self.assertIn("changed after it was checked", err)
                self.assertEqual(stale.read_bytes(), self.USER, "the replacement was deleted unchecked")
                strays = [p for p in stale.parent.iterdir() if ".open-fleet-" in p.name]
                self.assertEqual(strays, [], "the act left a temp or quarantine file behind")

    def test_a_file_put_at_the_name_inside_the_delete_is_never_deleted(self):
        # The window Codex named inside the delete itself: the act checked the bytes, then unlinked
        # the NAME. The hook puts the user's file there right before the delete's own unlink runs.
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            stale = out / "skills" / "speed-it" / "old-reference.md"
            stale.write_bytes(b"a stale copy\n")
            self.forge(out, ["skills/speed-it/old-reference.md"],
                       {"skills/speed-it/old-reference.md": hashlib.sha256(b"a stale copy\n").hexdigest()})
            remember(out, {"skills/speed-it/old-reference.md": b"a stale copy\n"})
            real_unlink, fired = os.unlink, []

            def unlink(path, *args, **kwargs):
                if not fired and os.fsdecode(path).startswith(("old-reference.md", ".old-reference.md.")):
                    fired.append(path)
                    fresh = stale.with_name("user-copy")
                    fresh.write_bytes(self.USER)
                    os.replace(fresh, stale)
                return real_unlink(path, *args, **kwargs)

            with mock.patch.object(bundle.os, "unlink", unlink):
                code, err = run_main("--out", tmp)
            self.assertTrue(fired, "the delete never ran")
            self.assertTrue(stale.is_file(), "the user's file put at the name was deleted unchecked")
            self.assertEqual(stale.read_bytes(), self.USER)
            self.assertIn(code, (0, 2), err)

    def test_an_unchanged_file_is_still_replaced_and_a_stale_one_still_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            stale = out / "skills" / "speed-it" / "old-reference.md"
            stale.write_bytes(b"a stale copy\n")
            self.forge(out, ["skills/speed-it/old-reference.md"],
                       {"skills/speed-it/old-reference.md": hashlib.sha256(b"a stale copy\n").hexdigest()})
            remember(out, {"skills/speed-it/old-reference.md": b"a stale copy\n"})
            target = out / "skills" / "review-it" / "SKILL.md"
            before = os.stat(target).st_ino
            code, err = run_main("--out", tmp)
            self.assertEqual(code, 0, err)
            self.assertFalse(stale.exists())
            self.assertNotEqual(os.stat(target).st_ino, before, "the overwrite did not put a new file in place")
            self.assertEqual([p for p in out.rglob("*") if ".open-fleet-" in p.name and p.name != bundle.MARKER], [])

    def test_without_an_atomic_exchange_an_overwrite_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.built(tmp)
            before = snapshot(out)
            with mock.patch.object(bundle, "_RENAME", None):
                code, err = run_main("--out", tmp)
            self.assertEqual(code, 2, err)
            self.assertIn("no atomic rename exchange", err)
            self.assertEqual({k: v for k, v in snapshot(out).items() if k != bundle.MARKER},
                             {k: v for k, v in before.items() if k != bundle.MARKER})


class GitControlFilesNeverShip(unittest.TestCase):
    """2026-10-27 audit, W6-04 (the bundle half): the publish job commits the bundle with
    `git add -A`, which obeys a `.gitignore` inside it. A mission carrying one shipped a `dist`
    missing every file it matched while bundle-files.json still listed them, and --check, which
    reads the filesystem, stayed green."""

    def test_a_mission_carrying_a_git_control_file_fails_the_check(self):
        for name, is_dir in ((".gitignore", False), (".gitattributes", False), (".gitmodules", False),
                             (".git", True)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as src:
                skills = Path(src) / "skills"
                shutil.copytree(bundle.SKILLS_DIR / "ship-it", skills / "ship-it")
                planted = skills / "ship-it" / name   # the audit's PoC: skills/<mission>/.gitignore
                if is_dir:
                    planted.mkdir()
                    (planted / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
                else:
                    planted.write_text("*.md\n", encoding="utf-8")
                with mock.patch.object(bundle, "SKILLS_DIR", skills):
                    code, err = run_main("--check")
                self.assertEqual(code, 1, err)
                self.assertIn(f"ship-it: ships {name},", err)


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
