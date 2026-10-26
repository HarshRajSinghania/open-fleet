#!/usr/bin/env python3
"""Negative-path fixtures for the catalog grammar fixes of the 2026-10-23 review (#622).

One frontmatter reader for every gate (P1-9, P2-16, §5), one composition set (P1-10), and the
validator rules the review found escapable: the one-point paraphrase (P2-17), misspelt clause
tokens (P2-18), hidden mission directories (P2-19), the hand-kept mutating list (P2-20), a BOM
in front of a playbook's frontmatter and file-relative `../` paths (§5). Each test is written
to fail against the code the review read.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


validate = load(ROOT / "scripts" / "validate.py", "_grammar_validate")
fixtures = load(TESTS / "test_validate.py", "_grammar_fixtures")
make_skill, FIXTURE_IDENTITY = fixtures.make_skill, fixtures.FIXTURE_IDENTITY
PROTOCOLS = {"diagnose"}
READERS = {
    "validate.py": lambda text: validate.parse_frontmatter(text)[0],
    "proof_status.py": lambda text: load(ROOT / "runtime" / "scripts" / "proof_status.py",
                                         "_grammar_ps").parse_frontmatter(text)[0],
}


def frontmatter(identity, top=""):
    meta = "".join(f"  {k}: {v}\n" for k, v in identity.items())
    return f"---\nname: demo-skill\ndescription: A fixture. Use when testing.\n{top}metadata:\n{meta}---\n"


class OneFrontmatterReader(unittest.TestCase):
    """P1-9: `unit: >-` under metadata read as the literal `>-`; P2-16: a plain multi-line scalar
    was cut at its first line. Every reader reads the same full value now."""

    TEXT = ("---\nname: demo-skill\ndescription: first line of a plain scalar\n  second line\n"
            "compatibility: >-\n  folded compat\n  text\nmetadata:\n  proof: doctrine-only\n"
            "  unit: >-\n    one finite backlog item\n    drained to zero\n"
            "  oracle: |\n    the tracker query\n  ordering: plain nested\n    continued\n---\n")

    def test_block_and_plain_scalars_read_in_full_at_every_depth(self):
        for reader, parse in READERS.items():
            with self.subTest(reader=reader):
                data = parse(self.TEXT)
                self.assertEqual(data["description"], "first line of a plain scalar second line")
                self.assertEqual(data["compatibility"], "folded compat text")
                self.assertEqual(data["metadata"]["unit"], "one finite backlog item drained to zero")
                self.assertEqual(data["metadata"]["oracle"], "the tracker query")
                self.assertEqual(data["metadata"]["ordering"], "plain nested continued")

    def test_eval_reader_agrees_on_top_level_strings(self):
        evalmod = load(ROOT / "scripts" / "eval.py", "_grammar_eval")
        fields = evalmod.parse_frontmatter(self.TEXT)
        self.assertEqual(fields["description"], "first line of a plain scalar second line")
        self.assertNotIn("metadata", fields)

    def test_release_check_reads_only_metadata_proof(self):
        rc = load(ROOT / "scripts" / "release_check.py", "_grammar_rc")
        self.assertEqual(rc.frontmatter_proof(self.TEXT), "doctrine-only")
        # An indented `proof:` under some other key is not metadata.proof.
        other = "---\nname: x\nextra:\n  proof: self-run\nmetadata:\n  autonomy: L4\n---\n"
        self.assertIsNone(rc.frontmatter_proof(other))

    def test_a_folded_identity_point_is_measured_and_compared(self):
        long_point = " ".join(f"word{i}" for i in range(validate.IDENTITY_POINT_MAX_TOKENS + 3))
        with tempfile.TemporaryDirectory() as tmp:
            d = make_skill(tmp, "Composes `diagnose`.\n", identity=dict(FIXTURE_IDENTITY))
            md = d / "SKILL.md"
            md.write_text(md.read_text(encoding="utf-8").replace(
                "  unit: one fixture item\n", f"  unit: >-\n    {long_point}\n"), encoding="utf-8")
            errs = validate.validate_skill(d, PROTOCOLS)
        self.assertTrue(any("metadata.unit" in e and "content words" in e for e in errs), errs)

    def test_a_folded_metadata_value_is_held_to_the_length_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_skill(tmp, "Composes `diagnose`.\n")
            md = d / "SKILL.md"
            md.write_text(md.read_text(encoding="utf-8").replace(
                "  parking: FIXTURE-PARKED\n",
                "  parking: >-\n" + "    PARKED for a reason\n" * 12), encoding="utf-8")
            errs = validate.validate_skill(d, PROTOCOLS)
        self.assertTrue(any("metadata.parking is" in e and "chars >" in e for e in errs), errs)

    def test_caps_measure_the_whole_plain_multiline_scalar(self):
        for key, cap in (("description", 1024), ("compatibility", 500)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as tmp:
                d = make_skill(tmp, "Composes `diagnose`.\n")
                md = d / "SKILL.md"
                text = md.read_text(encoding="utf-8")
                value = f"{key}: Use when the first line is short\n" + "  continued words\n" * 80
                if key == "description":
                    text = text.replace("description: A fixture. Use when testing.\n", value)
                else:
                    text = text.replace("metadata:\n", value + "metadata:\n", 1)
                md.write_text(text, encoding="utf-8")
                errs = validate.validate_skill(d, PROTOCOLS)
                self.assertTrue(any(f"{key} length" in e and f"1-{cap}" in e for e in errs), errs)

    def test_the_a2a_export_carries_the_folded_value(self):
        a2a = load(ROOT / "scripts" / "a2a_export.py", "_grammar_a2a")
        with tempfile.TemporaryDirectory() as tmp:
            d = make_skill(tmp, "Composes `diagnose`.\n", name="demo-skill")
            md = d / "SKILL.md"
            md.write_text(md.read_text(encoding="utf-8").replace(
                "  unit: one fixture item\n", "  unit: >-\n    one folded\n    fixture item\n"),
                encoding="utf-8")
            card = a2a.build_mission_card(d, door_ids=set())
        self.assertIn("one folded fixture item", str(card))
        self.assertNotIn("'>-'", str(card))

    def test_a_map_nested_under_a_metadata_key_is_an_error_not_a_crash(self):
        # The shared reader reads nested maps at any depth; a dict must never reach a check that
        # hashes or strips a string (proof/autonomy membership, the identity tokenizer).
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "skills").mkdir()
            for name in ("alpha-it", "beta-it"):
                d = make_skill(Path(tmp) / "skills", "Composes `diagnose`.\n", name=name)
                md = d / "SKILL.md"
                md.write_text(md.read_text(encoding="utf-8").replace(
                    "  proof: doctrine-only\n", "  proof:\n    nested: map\n").replace(
                    "  unit: one fixture item\n", "  unit:\n    x: y\n"), encoding="utf-8")
            errs = validate.validate_skill(d, PROTOCOLS)
            self.assertIn("metadata.proof must be a non-empty string", errs)
            self.assertIn("metadata.unit must be a non-empty string", errs)
            self.assertEqual(validate.identity_collisions(root=Path(tmp)), ([], []))

    def test_a_fence_inside_a_value_is_content(self):
        data, err = validate.parse_frontmatter(
            "---\nname: x\ndescription: >-\n  a --- b\n  ---\nmetadata:\n  proof: self-run\n---\nbody\n")
        self.assertIsNone(err)
        self.assertEqual(data["description"], "a --- b ---")
        self.assertEqual(data["metadata"]["proof"], "self-run")


class MisspeltClauseTokens(unittest.TestCase):
    """P2-18: BACKTICK_RE reads lowercase-hyphen names only, so a misspelt clause token was
    neither resolved nor flagged."""

    def test_case_underscore_and_path_spellings_are_flagged(self):
        for token in ("Diagnose", "diag_nose", "playbooks/diagnose", "DIAGNOSE"):
            body = f"Composes `diagnose`, `{token}`.\n"
            with self.subTest(token=token), tempfile.TemporaryDirectory() as tmp:
                errs = validate.validate_skill(make_skill(tmp, body), PROTOCOLS | {"diag-nose"})
                self.assertTrue(any("misspelt composition" in e and token in e for e in errs),
                                errs)

    def test_correct_spellings_and_non_protocol_tokens_are_left_alone(self):
        body = "Composes `diagnose` (run `--mission demo`, `PROFILE=rw`).\n"
        with tempfile.TemporaryDirectory() as tmp:
            errs = validate.validate_skill(make_skill(tmp, body), PROTOCOLS)
        self.assertEqual(errs, [])

    def test_a_dangling_backticked_deferred_read_is_flagged(self):
        body = "Composes `diagnose`.\n\nDEFERRED READS, never at activation: `no-such-doc` at X.\n"
        with tempfile.TemporaryDirectory() as tmp:
            errs = validate.validate_skill(make_skill(tmp, body), PROTOCOLS)
        self.assertTrue(any("dangling deferred read" in e and "no-such-doc" in e for e in errs),
                        errs)


class MutatingIsDerivedFromComposition(unittest.TestCase):
    """P2-20: MUTATING_MISSIONS was the only way in, so a renamed code-landing mission that
    dropped its evidence-manifest / sandbox-policy rides passed."""

    PROTOCOLS = {"build-change", "remediate-finding", "merge-serialization", "evidence-manifest",
                 "sandbox-policy", "diagnose"}

    def test_an_unlisted_code_landing_mission_owes_both_rides_and_the_list(self):
        for clause in ("Composes `build-change`.\n", "Composes `remediate-finding`.\n",
                       "Composes `diagnose`; rides `merge-serialization`.\n",
                       "Composes `diagnose`.\n\nDEFERRED READS: build-change at LAND.\n"):
            with self.subTest(clause=clause), tempfile.TemporaryDirectory() as tmp:
                d = make_skill(tmp, clause, name="land-it")
                errs = validate.validate_skill(d, self.PROTOCOLS)
                self.assertTrue(any("must ride `evidence-manifest`" in e for e in errs), errs)
                self.assertTrue(any("must ride `sandbox-policy`" in e for e in errs), errs)
                self.assertTrue(any("not in MUTATING_MISSIONS" in e for e in errs), errs)

    def test_a_report_only_mission_is_not_mutating(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = make_skill(tmp, "Composes `diagnose`.\n", name="look-it")
            self.assertEqual(validate.validate_skill(d, self.PROTOCOLS), [])

    def test_the_live_catalog_derivation_matches_the_declared_list(self):
        for d in sorted((ROOT / "skills").iterdir()):
            if d.is_dir() and not d.name.startswith((".", "_")):
                lands = validate.code_landing_refs((d / "SKILL.md").read_text(encoding="utf-8"))
                if lands:
                    self.assertIn(d.name, validate.MUTATING_MISSIONS, (d.name, lands))


class OnePointParaphrase(unittest.TestCase):
    """P2-17: rewording five points and moving ONE out of the concept table's vocabulary scored
    that point 0.0, so the all-six rule passed the pair with no error and no WARN."""

    ORIGINAL = {
        "unit": "one finite backlog item drained to zero with evidence",
        "state_machine": "triage then remediate then verify then close",
        "convergence": "a full re-enumeration finds no open item remaining",
        "ordering": "highest severity finding first, then oldest",
        "parking": "PARKED with a named blocking reason recorded",
        "oracle": "the tracker query that returns no open items",
    }
    PARAPHRASE = {
        "unit": "one finite backlog item emptied to zero with evidence",
        "state_machine": "triage then remediate then check then close",
        "convergence": "a full re-enumeration finds no open item outstanding",
        "ordering": "highest severity finding first, then earliest",
        "parking": "PARKED with a named blocking cause recorded",
        # the escape: one point in words the concept table has never heard of
        "oracle": "whatever ledger lookup yields a blank roster",
    }

    def _collide(self, a, b):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "skills").mkdir()
            make_skill(root / "skills", "Composes `diagnose`.\n", name="alpha-it", identity=a)
            make_skill(root / "skills", "Composes `diagnose`.\n", name="beta-it", identity=b)
            return validate.identity_collisions(root=root)

    def test_the_fixture_is_the_attack(self):
        sims = validate._identity_sims(tuple(self.ORIGINAL.values()),
                                       tuple(self.PARAPHRASE.values()))
        near = sum(s >= validate.IDENTITY_POINT_NEAR for s in sims)
        same = sum(s >= validate.IDENTITY_POINT_SAME for s in sims)
        self.assertEqual((near, sims[-1]), (5, 0.0), sims)
        self.assertLess(same, 5, "five SAME points would be the legal WARN, not the attack")

    def test_five_reworded_points_and_one_out_of_vocabulary_is_refused(self):
        errors, _warnings = self._collide(self.ORIGINAL, self.PARAPHRASE)
        self.assertTrue(any("restate 5 of 6 identity points" in e for e in errors), errors)

    def test_five_verbatim_points_and_one_genuine_difference_stays_a_warn(self):
        other = dict(self.ORIGINAL, oracle="whatever ledger lookup yields a blank roster")
        errors, warnings = self._collide(self.ORIGINAL, other)
        self.assertEqual(errors, [])
        self.assertTrue(any("differ on only oracle" in w for w in warnings), warnings)


class LayersAndPaths(unittest.TestCase):
    def test_a_bom_cannot_smuggle_frontmatter_into_playbooks(self):
        for opening in ("\ufeff---\n", "---\r\n", "\ufeff---\r\n"):
            with self.subTest(opening=repr(opening)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "playbooks").mkdir()
                eol = "\r\n" if "\r" in opening else "\n"
                (root / "playbooks" / "probe.md").write_text(
                    f"{opening}name: probe{eol}description: index me{eol}---{eol}# body{eol}",
                    encoding="utf-8", newline="")
                self.assertEqual(validate.check_lower_layer_frontmatter(root),
                                 ["playbooks/probe.md"])

    def test_a_dot_dot_path_resolves_from_the_file_that_holds_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            notes = Path(tmp) / "notes"
            notes.mkdir()
            (notes / "local-note.md").write_text("x\n", encoding="utf-8")
            d = make_skill(tmp, "Composes `diagnose`. See ../notes/local-note.md for context.\n")
            self.assertEqual(validate.validate_skill(d, PROTOCOLS), [])
            d2 = make_skill(tmp, "Composes `diagnose`. See ../notes/missing-note.md.\n",
                            name="other-skill")
            errs = validate.validate_skill(d2, PROTOCOLS)
        self.assertTrue(any("dangling path: ../notes/missing-note.md" in e for e in errs), errs)

    def test_hidden_mission_directories_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("_draft", ".hidden", "ok-it"):
                (root / "skills" / name).mkdir(parents=True)
                (root / "skills" / name / "SKILL.md").write_text("---\nname: x\n---\n")
            (root / "skills" / "_notes").mkdir()  # no SKILL.md: not a mission, not refused
            found = validate.check_hidden_missions(root)
        self.assertEqual(len(found), 2, found)
        self.assertTrue(found[0].startswith("skills/.hidden/SKILL.md"), found)
        self.assertTrue(found[1].startswith("skills/_draft/SKILL.md"), found)
        self.assertEqual(validate.check_hidden_missions(), [], "the live catalog has none")


class OneCompositionGrammar(unittest.TestCase):
    """§5: quarantine_check.py carried its own copy of COMPOSE_CLAUSE_RE."""

    def test_the_quarantine_matcher_has_no_private_clause_grammar(self):
        source = (ROOT / "runtime" / "scripts" / "quarantine_check.py").read_text(encoding="utf-8")
        self.assertNotIn("Composes|COMPOSES", source)
        qc = load(ROOT / "runtime" / "scripts" / "quarantine_check.py", "_grammar_qc")
        self.assertEqual(qc._grammar.COMPOSE_CLAUSE_RE.pattern, validate.COMPOSE_CLAUSE_RE.pattern)
        self.assertIs(validate._grammar, validate._quarantine._grammar)

    def test_the_activation_set_counts_clause_name_md_tokens(self):
        text = "Composes `diagnose`, observe.md; rides `evidence-manifest`.\n\nSee `release`.\n"
        self.assertEqual(validate._grammar.clause_refs(text),
                         {"diagnose", "observe", "evidence-manifest"})


if __name__ == "__main__":
    unittest.main()


class TheReaderRefusesWhatSkillsRefRefuses(unittest.TestCase):
    """2026-10-26 review (tooling track): shapes the local validator passed that the CI reference
    validator (skills-ref) refuses, or that read as a string they are not — a YAML sequence under a
    string field became the `<object>` sentinel and passed every length check; a duplicate key was
    last-wins; a top-level line the key grammar could not read was skipped; a BOM priced the whole
    frontmatter as body."""

    def _skill(self, tmp, edit):
        d = make_skill(tmp, "Composes `diagnose`.\n", name="demo-skill")
        md = d / "SKILL.md"
        md.write_text(edit(md.read_text(encoding="utf-8")), encoding="utf-8")
        return d

    def test_a_sequence_under_a_metadata_key_is_not_a_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._skill(tmp, lambda t: t.replace("  unit: one fixture item\n",
                                                     "  unit:\n    - one\n    - two\n"))
            errs = validate.validate_skill(d, PROTOCOLS)
        self.assertIn("metadata.unit must be a non-empty string", errs)
        self.assertFalse(any("<object>" in e and "length" in e for e in errs), errs)

    def test_a_sequence_as_the_description_is_not_a_string(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = self._skill(tmp, lambda t: t.replace("description: A fixture. Use when testing.\n",
                                                     "description:\n  - a\n  - b\n"))
            errs = validate.validate_skill(d, PROTOCOLS)
        self.assertTrue(any("description must be a string" in e for e in errs), errs)

    def test_a_duplicate_key_is_an_error_not_last_wins(self):
        data, err = validate.parse_frontmatter(
            "---\nname: x\nname: y\ndescription: d\nmetadata:\n  proof: self-run\n---\nbody\n")
        self.assertIsNone(data)
        self.assertIn("duplicate frontmatter key 'name'", err)
        data, err = validate.parse_frontmatter(
            "---\nname: x\ndescription: d\nmetadata:\n  proof: a\n  proof: b\n---\nbody\n")
        self.assertIsNone(data)
        self.assertIn("duplicate frontmatter key 'proof'", err)

    def test_an_unreadable_top_level_line_is_an_error_not_silence(self):
        for line in ('"quoted key": x', "foo.bar: x", "- item"):
            with self.subTest(line=line):
                data, err = validate.parse_frontmatter(
                    f"---\nname: x\n{line}\ndescription: d\n---\nbody\n")
                self.assertIsNone(data, line)
                self.assertIn("unreadable top-level frontmatter line", err)

    def test_a_bom_does_not_price_the_frontmatter_as_body(self):
        text = "---\nname: x\ndescription: d\n---\nbody line\n"
        self.assertEqual(validate.split_budget("﻿" + text), validate.split_budget(text))
        self.assertEqual(validate.split_budget(text), (4, 1))
