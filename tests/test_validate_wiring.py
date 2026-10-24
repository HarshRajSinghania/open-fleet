#!/usr/bin/env python3
"""validate.py's main() really runs each gate — driven through the entry point on a copied tree.

Calling a check function proves the function works, NOT that validate.py runs it: a mutant that
deletes the call from main() leaves every engine-level test green. That is why
ValidatePyRunsTheLayerChecks (#303) exists, and check_quarantine() and check_evals() had no such
fixture (2026-10-23 review, P2-25). The same copied tree also replays the review's two
reproductions end to end (P1-9, P1-10) and the hidden-mission refusal (P2-19).

The tree is a COPY in a tempdir (scripts, skills, playbooks, runtime, evals, hooks, the plugin
manifest and the root docs). The copy omits docs/ and assets/, so its run fails for unrelated
reasons; each test asserts its message is ABSENT before the edit and PRESENT after — the edit,
and nothing else, produced it. runtime/quarantine.json is only ever edited in the copy: the
live deny-list is a human-only file.
"""
import contextlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPIED = ("scripts", "skills", "playbooks", "runtime", "evals", "hooks", ".claude-plugin")


def quarantine_entry(component):
    return {"component": component, "ref": "*", "reason": "fixture: compromised upstream",
            "date": "2026-10-23", "by": "human:fixture"}


class ValidatePyRunsEveryGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name) / "catalog"
        cls.root.mkdir()
        for rel in COPIED:
            if (ROOT / rel).exists():
                shutil.copytree(ROOT / rel, cls.root / rel,
                                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for doc in ROOT.glob("*.md"):
            shutil.copy2(doc, cls.root / doc.name)
        git = ["git", "-C", str(cls.root), "-c", "user.name=probe", "-c", "user.email=p@x",
               "-c", "commit.gpgsign=false"]
        for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "copy"]):
            subprocess.run(git + argv, check=True, capture_output=True, timeout=120)
        cls.baseline = cls._validate().stdout

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    @classmethod
    def _validate(cls):
        return subprocess.run([sys.executable, str(cls.root / "scripts" / "validate.py")],
                              capture_output=True, text=True, timeout=180)

    @contextlib.contextmanager
    def edited(self, rel, edit):
        path = self.root / rel
        saved = path.read_bytes() if path.exists() else None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(edit(saved.decode("utf-8") if saved is not None else ""), encoding="utf-8")
        try:
            yield
        finally:
            if saved is None:
                path.unlink()
            else:
                path.write_bytes(saved)

    def assert_reported(self, run, *messages):
        for message in messages:
            self.assertNotIn(message, self.baseline,
                             "the copied tree already reports this — the probe would prove nothing")
            self.assertIn(message, run.stdout, f"not reported:\n{run.stdout}")
        self.assertNotEqual(run.returncode, 0)

    def test_main_runs_the_quarantine_gate(self):
        deny = {"quarantined": [quarantine_entry("playbook:build-change")]}
        with self.edited("runtime/quarantine.json", lambda _old: json.dumps(deny)):
            run = self._validate()
        self.assert_reported(run, "FAIL quarantine",
                             "composes quarantined playbook build-change")

    def test_main_runs_the_load_budget_gate(self):
        def squeeze(text):
            data = json.loads(text)
            data["budgets"]["root-cause"] = 1000
            return json.dumps(data)

        with self.edited("scripts/mission-load-budgets.json", squeeze):
            run = self._validate()
        self.assert_reported(run, "FAIL activation-load budgets",
                             "root-cause: activation load")

    def test_main_runs_the_eval_gate(self):
        with self.edited("evals/routing.json", lambda _old: "{ not json"):
            run = self._validate()
        self.assert_reported(run, "FAIL eval schema", "invalid JSON in evals/routing.json")

    def test_a_clause_respelled_name_md_is_quarantined_like_the_cli_sees_it(self):
        # The review's reproduction (P1-10): ship-it's clause respelled from `build-change` to
        # build-change.md. The activation-load measure charged it; this gate cleared ship-it while
        # `quarantine_check.py --mission ship-it` refused it.
        skill = "skills/ship-it/SKILL.md"

        def respell(text):
            clause = re.search(r"Composes .+?(?:\n\n)", text, re.S).group(0)
            self.assertIn("`build-change`", clause, "fixture premise: ship-it composes it")
            return text.replace(clause, clause.replace("`build-change`", "build-change.md"), 1)

        deny = {"quarantined": [quarantine_entry("playbook:build-change")]}
        with self.edited(skill, respell), \
                self.edited("runtime/quarantine.json", lambda _old: json.dumps(deny)):
            run = self._validate()
            cli = subprocess.run(
                [sys.executable, str(self.root / "runtime" / "scripts" / "quarantine_check.py"),
                 "--root", str(self.root), "--mission", "ship-it"],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assert_reported(run, "mission ship-it composes quarantined playbook build-change")

    def test_folded_identity_points_cannot_restate_another_mission(self):
        # The review's reproduction (P1-9): oss-contribute carrying clean-sweep's six points
        # verbatim, each folded as `>-`, printed "All 22 missions valid".
        def points(text):
            block = re.search(r"(?ms)^metadata:\n(.*?)^---", text).group(1)
            return dict(re.findall(r"(?m)^  (\w+): (.+)$", block))

        donor = points((self.root / "skills" / "clean-sweep" / "SKILL.md").read_text("utf-8"))

        def fold(text):
            for key in ("unit", "state_machine", "convergence", "ordering", "parking", "oracle"):
                text = re.sub(rf"(?m)^  {key}: .+$",
                              lambda _m, k=key: f"  {k}: >-\n    {donor[k]}", text, count=1)
            return text

        with self.edited("skills/oss-contribute/SKILL.md", fold):
            run = self._validate()
        self.assert_reported(run, "FAIL mission identity",
                             "clean-sweep and oss-contribute declare the same six identity points")

    def test_a_hidden_mission_directory_is_refused(self):
        body = "---\nname: draft\ndescription: x\n---\n" + "an unchecked line\n" * 400
        with self.edited("skills/_draft/SKILL.md", lambda _old: body):
            run = self._validate()
        shutil.rmtree(self.root / "skills" / "_draft", ignore_errors=True)
        self.assert_reported(run, "FAIL hidden missions", "skills/_draft/SKILL.md")


    def test_main_runs_the_changelog_fragment_gate(self):
        # CI speed and bookkeeping change: entries are changelog.d/ fragments the release cut
        # folds; main() must report one the cut could not fold, whatever else the copy lacks.
        with self.edited("changelog.d/zz-probe.md", lambda _: "### Added\n"):
            run = self._validate()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assert_reported(run, "changelog.d/zz-probe.md:1: a heading would split the release section")

    def test_main_runs_the_run_index_gate(self):
        # A run report filed without its docs/runs/index/<run>.json row is an unindexed run.
        with self.edited("docs/runs/2026-12-30-probe-it-self-run.md", lambda _: "# probe\n"):
            run = self._validate()
        self.assertEqual(run.returncode, 1, run.stdout + run.stderr)
        self.assert_reported(run, "docs/runs/2026-12-30-probe-it-self-run.md has no row")


if __name__ == "__main__":
    unittest.main()
