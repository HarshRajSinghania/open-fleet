#!/usr/bin/env python3
"""Routing coverage is a row the mission WINS (2026-10-23 review, §5).

validate_routing_eval() counted every mission named in a positive row as covered. An
`expected_any` row accepts several winners and the prompt goes to one of them, so a mission
named only there was "covered" by a row it never takes — the gate said every mission routes
while one of them had no prompt that reaches it.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_coverage", ROOT / "scripts" / "eval.py")
eval_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_mod)

SKILLS = {
    "speed-it": "Make the app fast: latency budgets, slow pages, performance regressions. "
                "Use when \"the app is slow\", \"make it fast\".",
    "access-it": "Accessibility conformance: screen readers, contrast, keyboard. "
                 "Use when \"accessibility\", \"a11y\".",
}


def catalog(rows):
    tmp = tempfile.TemporaryDirectory()
    base = Path(tmp.name)
    for name, description in SKILLS.items():
        (base / "skills" / name).mkdir(parents=True)
        (base / "skills" / name / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: {description}\n---\n# {name}\n", encoding="utf-8")
    routing = base / "routing.json"
    routing.write_text(json.dumps({"evals": rows}), encoding="utf-8")
    patches = [patch.object(eval_mod, "ROOT", base),
               patch.object(eval_mod, "SKILLS_DIR", base / "skills"),
               patch.object(eval_mod, "ROUTING_EVAL", routing)]
    return tmp, patches


class CoverageIsAWin(unittest.TestCase):
    def errors(self, rows):
        tmp, patches = catalog(rows)
        try:
            for p in patches:
                p.start()
            eval_mod._CORPUS_CACHE.clear()
            return eval_mod.validate_routing_eval()
        finally:
            for p in patches:
                p.stop()
            eval_mod._CORPUS_CACHE.clear()
            tmp.cleanup()

    STRADDLE = {"id": "straddle", "type": "positive", "reason": "fixture",
                "prompt": "make the slow app fast and fix accessibility",
                "expected_any": ["speed-it", "access-it"]}

    def test_the_fixture_straddles_and_speed_it_wins(self):
        tmp, patches = catalog([self.STRADDLE])
        try:
            for p in patches:
                p.start()
            eval_mod._CORPUS_CACHE.clear()
            ranked = dict(eval_mod.classify_prompt(self.STRADDLE["prompt"]))
            self.assertEqual(eval_mod.route_prompt(self.STRADDLE["prompt"]), "speed-it")
            self.assertIn("access-it", ranked, "both must score, or the row is over-broad")
        finally:
            for p in patches:
                p.stop()
            eval_mod._CORPUS_CACHE.clear()
            tmp.cleanup()

    def test_a_mission_named_only_in_a_row_it_never_wins_is_uncovered(self):
        errors = self.errors([self.STRADDLE])
        self.assertTrue(any("no positive routing examples" in e and "access-it" in e
                            for e in errors), errors)
        self.assertFalse(any("no positive routing examples" in e and "speed-it" in e
                             for e in errors), errors)

    def test_a_row_the_mission_wins_covers_it(self):
        own = {"id": "own", "type": "positive", "reason": "fixture",
               "prompt": "screen reader accessibility and contrast", "expected_mission": "access-it"}
        errors = self.errors([self.STRADDLE, own])
        self.assertFalse(any("no positive routing examples" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
