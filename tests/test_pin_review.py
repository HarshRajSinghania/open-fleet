#!/usr/bin/env python3
"""Contract tests for runtime/scripts/pin_review.py (#559).

The class boundaries are the security content: an instruction file landing
in `code`, or a hook landing outside `permission-surface`, is exactly how a
rug-pull hides in a bump diff. These tests pin the classifier and the CLI's
fail-closed exits.
"""
import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "runtime" / "scripts" / "pin_review.py"

_spec = importlib.util.spec_from_file_location("pin_review", SCRIPT)
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)


class Classify(unittest.TestCase):
    def test_instruction_shapes(self):
        for path in ("skills/triage/SKILL.md", "AGENTS.md", "README.md",
                     "prompts/system.txt", "docs/guide.prompt"):
            self.assertEqual(pr.classify(path), "instruction", path)

    def test_permission_shapes(self):
        for path in ("hosts/claude/hooks/stop-hook.ts", ".claude-plugin/plugin.json",
                     "hooks/hooks.json", "package.json", "x/hook-extract.sh",
                     ".github/workflows/ci.yml"):
            self.assertEqual(pr.classify(path), "permission-surface", path)

    def test_code_shapes(self):
        for path in ("src/main.py", "lib/util.ts", "bin/tool"):
            self.assertEqual(pr.classify(path), "code", path)

    def test_hooks_win_over_markdown(self):
        # A Markdown file inside hooks/ ships beside executable hooks; it is
        # reviewed with the surface, not with prose.
        self.assertEqual(pr.classify("hooks/README.md"), "permission-surface")


def make_pack(tmp: Path):
    repo = tmp / "pack"
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "SKILL.md").write_text("# skill\n")
    (repo / "run.py").write_text("print(1)\n")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "commit", "-q", "-m", "one"], check=True)
    first = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=True).stdout.strip()
    (repo / "SKILL.md").write_text("# skill v2\n")
    (repo / "hooks").mkdir()
    (repo / "hooks" / "hooks.json").write_text("{}\n")
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "commit", "-q", "-m", "two"], check=True)
    second = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    return repo, first, second


class Cli(unittest.TestCase):
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, str(SCRIPT), *argv],
                              capture_output=True, text=True, timeout=60)

    def test_diff_classifies_bump(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, first, second = make_pack(Path(tmp))
            result = self.run_cli("--repo", str(repo), "--pack", "demo",
                                  "--from", first, "--to", second)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("### instruction (1)", result.stdout)
            self.assertIn("### permission-surface (1)", result.stdout)
            self.assertIn("Verdict: UNREVIEWED", result.stdout)

    def test_bad_commit_cannot_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, _, _ = make_pack(Path(tmp))
            result = self.run_cli("--repo", str(repo), "--pack", "demo",
                                  "--to", "0" * 40)
            self.assertEqual(result.returncode, 3)


if __name__ == "__main__":
    unittest.main()
