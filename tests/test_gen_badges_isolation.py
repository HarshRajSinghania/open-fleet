#!/usr/bin/env python3
"""The suite never rewrites the live tree through scripts/gen-badges.py (2026-10-23 review, P2-24).

gen-badges' write() ends by refreshing four generated surfaces: assets/badges/, the mission
guides' Activation load callouts, ARCHITECTURE.md's table and README.md's proof sentence. Tests
that patched some of those paths and not the rest rewrote the others in the checkout whenever
they were stale — a no-op on a clean tree, so CI never showed it, and a silent edit to tracked
files on any tree mid-change (observed: 18 docs/missions callouts and the ARCHITECTURE.md table).

The guard here runs the generator-writing tests with every LIVE generated file made to READ as
stale and made unwritable, so a test that leaves one path pointing at the checkout fails loudly
instead of depending on the tree happening to be current. It also pins the one-reader fix for
proof_tiers(): a `---` inside a description no longer crashes the badge check.
"""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent

# The tests that call gen-badges' write(), by module file and class.
WRITERS = {
    "test_architecture.py": ("TheActivationLoadTableIsGenerated", (
        "test_the_generator_actually_refreshes_a_guide_callout",
        "test_the_generator_actually_refreshes_the_block",
    )),
    "test_validate.py": ("TestCountAgnosticGuards", (
        "test_badge_inventory_is_honest_for_failing_and_passing_suites",
        "test_badge_inventory_refreshes_counts_and_rejects_success_claims",
    )),
}


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def live_generated():
    return [ROOT / "README.md", ROOT / "ARCHITECTURE.md",
            *sorted((ROOT / "docs" / "missions").glob("*.md")),
            *sorted((ROOT / "assets" / "badges").glob("*.json"))]


def digest(paths):
    return {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


class GeneratorTestsNeverWriteTheLiveTree(unittest.TestCase):
    def _writer_suite(self):
        suite = unittest.TestSuite()
        for filename, (cls_name, methods) in WRITERS.items():
            module = load(TESTS / filename, f"_isolation_{filename[:-3]}")
            cls = getattr(module, cls_name)
            suite.addTests(cls(method) for method in methods)
        return suite

    def test_writer_tests_target_copies_even_when_every_live_surface_is_stale(self):
        gen = load(ROOT / "scripts" / "gen-badges.py", "_isolation_gen")
        live = {p.resolve() for p in live_generated()}
        real_read, real_write = Path.read_text, Path.write_text
        attempts = []

        def stale(path, text):
            # Every generated region of a live file reads as out of date, so any writer still
            # pointed at the checkout WILL try to write it.
            if path.name == "README.md":
                return gen.README_BLOCK_RE.sub(f"{gen.README_BEGIN}\nstale\n{gen.README_END}", text)
            if path.name == "ARCHITECTURE.md":
                return gen.ARCH_BLOCK_RE.sub(f"{gen.ARCH_BEGIN}\nstale\n{gen.ARCH_END}", text)
            if path.parent.name == "missions":
                return gen.LOAD_CALLOUT_RE.sub("> **Activation load:** ~1 tokens — stale", text)
            return text

        def read_text(path, *args, **kwargs):
            text = real_read(path, *args, **kwargs)
            return stale(path, text) if Path(path).resolve() in live else text

        def write_text(path, *args, **kwargs):
            if Path(path).resolve() in live:
                attempts.append(str(path))
                raise PermissionError(f"test wrote the live tree: {path}")
            return real_write(path, *args, **kwargs)

        before = digest(live_generated())
        result = unittest.TestResult()
        with mock.patch.object(Path, "read_text", read_text), \
                mock.patch.object(Path, "write_text", write_text):
            self._writer_suite().run(result)
        self.assertEqual(attempts, [], "a generator test wrote a live generated file")
        self.assertTrue(result.wasSuccessful(),
                        [str(err) for _test, err in result.errors + result.failures])
        self.assertEqual(result.testsRun, sum(len(m) for _c, m in WRITERS.values()))
        self.assertEqual(digest(live_generated()), before, "a live generated file changed")


class ProofTiersReadTheFrontmatterOnce(unittest.TestCase):
    def test_a_fence_inside_a_description_does_not_crash_the_check(self):
        # `text.split("---")[1]` ended the frontmatter at the first `---` anywhere, the proof tier
        # vanished, and the RuntimeError took validate.py down before its quarantine gate ran.
        gen = load(ROOT / "scripts" / "gen-badges.py", "_isolation_gen_fence")
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "skills" / "demo-it"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: demo-it\ndescription: before --- after. Use when testing.\n"
                "metadata:\n  proof: self-run\n---\nbody\n", encoding="utf-8")
            with mock.patch.object(gen, "SKILLS_DIR", Path(tmp) / "skills"):
                self.assertEqual(gen.proof_tiers()["self-run"], ["demo-it"])

    def test_an_unreadable_tier_is_reported_not_raised(self):
        gen = load(ROOT / "scripts" / "gen-badges.py", "_isolation_gen_tier")
        with tempfile.TemporaryDirectory() as tmp:
            skill = Path(tmp) / "skills" / "demo-it"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: demo-it\n---\nbody\n", encoding="utf-8")
            readme = Path(tmp) / "README.md"
            readme.write_text(f"{gen.README_BEGIN}\nx\n{gen.README_END}\n", encoding="utf-8")
            with mock.patch.object(gen, "SKILLS_DIR", Path(tmp) / "skills"), \
                    mock.patch.object(gen, "README", readme):
                errors = gen.check_readme()
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("no legal metadata.proof tier", errors[0])


if __name__ == "__main__":
    unittest.main()
