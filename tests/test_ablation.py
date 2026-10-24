#!/usr/bin/env python3
"""Contract tests for the #606 ablation registration, variant generator and obligation check.

scripts/ablation.py makes a reduced-instruction variant of a mission and claims three things about
it: the variant is generated mechanically from a committed registration, its token delta is the
number scripts/validate.py itself would report, and every registered safety obligation survives —
at activation, or deferred only to a phase the obligation allows. Each claim below is checked on
real generated variants, and each failure the check exists to catch is made to happen.

    python3 -m unittest tests.test_ablation -v
"""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ablation = _load("ablation_under_test", "scripts/ablation.py")
# An independent copy of the gate: the delta must be what validate.py says, not what ablation.py says.
validate = _load("validate_for_ablation_tests", "scripts/validate.py")
PREREG = ablation.load_prereg()
MIX = [row["mission"] for row in PREREG["mission_mix"]]


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ablation.main(argv)
    return code, out.getvalue(), err.getvalue()


def defer_for(prereg, mission):
    return prereg["reduction"]["missions"][mission]


_COPIES = []


def repo_copy(tmp):
    """(root, ablation module) for a throwaway copy of everything generation reads, with the module
    loaded FROM the copy: a destructive-path test can only ever destroy the copy (#652 review)."""
    dest = Path(tmp) / "repo"
    for rel in ("skills", "playbooks", "runtime", "scripts", "evals", "docs/experiments", ".claude-plugin"):
        if (ROOT / rel).exists():
            shutil.copytree(ROOT / rel, dest / rel, symlinks=True,
                            ignore=shutil.ignore_patterns("__pycache__"))
    for doc in ROOT.glob("*.md"):
        shutil.copyfile(doc, dest / doc.name)
    _COPIES.append(dest)
    spec = importlib.util.spec_from_file_location(f"ablation_copy_{len(_COPIES)}", dest / "scripts" / "ablation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dest, mod


def tree_digest(root):
    """{relative path: sha256} of every file under root: what 'nothing was deleted' means."""
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def run_copy(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class TheRegistrationIsWellFormed(unittest.TestCase):
    def test_the_committed_registration_has_no_errors(self):
        self.assertEqual(ablation.prereg_errors(PREREG), [])

    def test_the_human_page_pins_the_json_bytes_and_its_generated_loads(self):
        self.assertEqual(ablation.md_sync_errors(), [])

    def test_the_human_page_states_every_registered_choice(self):
        md = ablation.read(ablation.PREREG_MD)
        for mission in MIX:
            for name, phases in defer_for(PREREG, mission)["defer"].items():
                self.assertIn(f"`{name}` at {'/'.join(phases)}", md, f"{mission}: {name}")
        for ob in PREREG["obligations"]:
            self.assertIn(ob["id"], md)
        self.assertIn(ablation.norm(PREREG["prompt"]["run_protocol"]), ablation.norm(md))
        for line in PREREG["prompt"]["template"].split("\n"):
            self.assertIn(line, md)
        cap = PREREG["cost_cap"]
        self.assertIn(cap["status"], md)
        self.assertIn(f"USD {cap['proposed_usd']}", md)

    def test_every_issue_class_is_preserved_and_anchored_for_every_mission(self):
        for cls in ablation.ISSUE_CLASSES:
            self.assertIn(cls, PREREG["required_classes"])
        for mission in MIX:
            classes = {ob["class"] for ob in ablation.applicable_obligations(mission, PREREG)}
            self.assertLessEqual(set(PREREG["preserved_classes"]), classes, mission)


class RegistrationErrorsAreCaught(unittest.TestCase):
    """Each malformed registration names its own error; none can drive a run."""

    def errors(self, mutate):
        prereg = copy.deepcopy(PREREG)
        mutate(prereg)
        return " | ".join(ablation.prereg_errors(prereg))

    def test_an_issue_class_cannot_be_unregistered(self):
        found = self.errors(lambda p: p["required_classes"].remove("negative-control"))
        self.assertIn("negative-control", found)

    def test_an_anchor_gone_from_its_source_is_stale(self):
        def mutate(p):
            next(ob for ob in p["obligations"] if ob["id"] == "OW-1")["anchor"] = "HUMAN MAYBE."
        self.assertIn("obligation OW-1: anchor not found", self.errors(mutate))

    def test_a_phase_the_pipeline_does_not_name_is_refused(self):
        def mutate(p):
            defer_for(p, "ship-it")["defer"]["gate-classification"] = ["LAUNCH"]
        self.assertIn("phase 'LAUNCH' is not an upper-case token", self.errors(mutate))

    def test_deferring_a_document_the_mission_does_not_load_is_refused(self):
        def mutate(p):
            defer_for(p, "ship-it")["defer"]["release"] = ["RELEASE"]
        self.assertIn("defer names 'release'", self.errors(mutate))

    def test_dropping_a_section_that_does_not_exist_is_refused(self):
        def mutate(p):
            defer_for(p, "review-it")["drop_sections"] = ["Nowhere"]
        self.assertIn("drop_sections names 'Nowhere'", self.errors(mutate))

    def test_a_mission_with_an_unanchored_class_cannot_be_ablated(self):
        def mutate(p):
            p["obligations"] = [ob for ob in p["obligations"]
                                if ob["id"] not in ("OW-1", "OW-RC-1", "OW-RC-2")]
        self.assertIn("root-cause: no registered obligation of class human-one-way-gate",
                      self.errors(mutate))

    def test_a_pending_cap_carries_no_authorisation(self):
        self.assertIn("a PENDING cap carries no authorised amount",
                      self.errors(lambda p: p["cost_cap"].update(status=ablation.PENDING, authorised_usd=10,
                                                                 authorised_by=None)))

    def test_a_pending_cap_names_no_authoriser(self):
        self.assertIn("a PENDING cap carries no authorised amount or authoriser",
                      self.errors(lambda p: p["cost_cap"].update(status=ablation.PENDING, authorised_usd=None,
                                                                 authorised_by="someone")))

    def test_an_authorised_cap_names_who_authorised_it(self):
        def mutate(p):
            p["cost_cap"].update(status=ablation.AUTHORISED, authorised_usd=10, authorised_by=" ")
        self.assertIn("names who authorised it", self.errors(mutate))

    def test_an_unknown_cap_status_is_refused(self):
        self.assertIn("cost_cap.status must be",
                      self.errors(lambda p: p["cost_cap"].update(status="FINE")))

    def test_one_seed_per_repeat(self):
        self.assertIn("one per repeat", self.errors(lambda p: p.update(repeats=4)))

    def test_an_unknown_task_is_refused(self):
        self.assertIn("behavioral case 9", self.errors(
            lambda p: p["tasks"]["behavioral"]["cases"].append(9)))
        self.assertIn("trajectory case 'ZZ-01'", self.errors(
            lambda p: p["tasks"]["trajectories"]["cases"].append("ZZ-01")))

    def test_the_prompt_template_must_carry_every_slot(self):
        self.assertIn("prompt.template", self.errors(
            lambda p: p["prompt"].update(template="{payload}\n\n{task}")))


class RegistrationDigests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="of-ablation-prereg-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        self.json = self.tmp / "ablation-prereg.json"
        self.md = self.tmp / "ablation-prereg.md"
        shutil.copyfile(ablation.PREREG, self.json)
        shutil.copyfile(ablation.PREREG_MD, self.md)

    def test_a_json_that_moved_without_its_page_is_caught(self):
        self.assertEqual(ablation.md_sync_errors(self.json, self.md), [])
        self.json.write_text(self.json.read_text() + "\n", encoding="utf-8")
        self.assertIn("pins sha256", " ".join(ablation.md_sync_errors(self.json, self.md)))

    def test_a_hand_typed_loads_table_is_caught(self):
        md = self.md.read_text().replace("| ship-it | ~", "| ship-it | ~1", 1)
        self.md.write_text(md, encoding="utf-8")
        self.assertIn("ablation-loads table", " ".join(ablation.md_sync_errors(self.json, self.md)))

    def test_refresh_re_pins_and_status_reports_drift(self):
        pinned = ablation.refresh(self.json, self.md)
        self.assertEqual(ablation.md_sync_errors(self.json, self.md), [])
        prereg = ablation.load_prereg(self.json)
        self.assertEqual(set(ablation.registration_status(prereg).values()), {"current"})
        prereg["registered_payloads"]["review-it"] = dict(pinned["review-it"], reduced_sha256="0" * 64)
        del prereg["registered_payloads"]["root-cause"]
        status = ablation.registration_status(prereg)
        self.assertEqual(status["ship-it"], "current")
        self.assertEqual(status["review-it"], "stale: reduced_sha256 moved since registration")
        self.assertEqual(status["root-cause"], "unregistered")

    def test_the_prereg_command_exit_codes(self):
        code, out, _err = run_main(["--prereg", str(self.json), "prereg", "--md", str(self.md)])
        self.assertEqual(code, 0, out)
        prereg = ablation.load_prereg(self.json)
        prereg["registered_payloads"]["ship-it"]["baseline_tokens"] = 1
        self.json.write_text(json.dumps(prereg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        code, _out, err = run_main(["--prereg", str(self.json), "prereg", "--md", str(self.md)])
        self.assertEqual(code, 2, "a page out of sync with its JSON is a malformed registration")
        self.assertIn("pins sha256", err)
        # Re-pin only the page (not the payloads): the registration is well formed but stale.
        md = ablation.REGISTRATION_LINE.sub(
            f"Registration: **version {prereg['version']}**, `docs/experiments/ablation-prereg.json` sha256 "
            f"`{ablation.file_sha256(self.json)}`.", self.md.read_text())
        md = ablation.LOADS_BLOCK.sub(lambda m: m.group(1) + ablation.loads_table(
            prereg["registered_payloads"]) + m.group(3), md)
        self.md.write_text(md, encoding="utf-8")
        code, out, _err = run_main(["--prereg", str(self.json), "prereg", "--md", str(self.md)])
        self.assertEqual(code, 1)
        self.assertIn("ship-it: stale: baseline_tokens moved", out)


class GeneratedVariants(unittest.TestCase):
    """The four registered variants, generated once into a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.skill_bytes = {m: (ROOT / "skills" / m / "SKILL.md").read_bytes() for m in MIX}
        cls.out = Path(tempfile.mkdtemp(prefix="of-ablation-gen-"))
        cls.records = {m: ablation.generate(m, PREREG, cls.out) for m in MIX}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def variant_dir(self, mission):
        return Path(self.records[mission]["reduced"]["skill_dir"])

    def test_every_registered_variant_keeps_every_obligation(self):
        for mission, rec in self.records.items():
            check = rec["obligation_check"]
            self.assertTrue(check["passed"], f"{mission}: {check['failures']}")
            applicable = ablation.applicable_obligations(mission, PREREG)
            self.assertEqual(len(check["results"]), len(applicable), mission)
            self.assertTrue(all(row["held"] for row in check["results"]), mission)

    def test_the_delta_is_validate_pys_own_measure(self):
        for mission, rec in self.records.items():
            base, _ = validate.transitive_load(ROOT / "skills" / mission)
            reduced, _ = validate.transitive_load(self.variant_dir(mission))
            self.assertEqual(rec["baseline"]["tokens"], base, mission)
            self.assertEqual(rec["reduced"]["tokens"], reduced, mission)
            self.assertEqual(rec["delta_tokens"], reduced - base, mission)
            self.assertLess(rec["delta_tokens"], 0, mission)

    def test_the_measured_kept_set_is_exactly_the_registered_one(self):
        for mission, rec in self.records.items():
            text = (ROOT / "skills" / mission / "SKILL.md").read_text()
            loaded = ablation.clause_protocols(text) | {ablation.doc_name(d) for d in ablation.root_docs(text)}
            deferred = {ablation.doc_name(n) if n.endswith(".md") else n
                        for n in defer_for(PREREG, mission)["defer"]}
            expected = loaded - deferred
            counted = {ablation.doc_name(p) for p in rec["reduced"]["parts"] if not p.startswith("skills/")}
            self.assertEqual(counted, expected, mission)
            self.assertEqual(set(rec["kept"]), expected, mission)

    def test_routing_inputs_are_byte_identical(self):
        for mission in MIX:
            variant = (self.variant_dir(mission) / "SKILL.md").read_text()
            self.assertEqual(ablation.frontmatter(variant),
                             ablation.frontmatter(self.skill_bytes[mission].decode()), mission)

    def test_generation_is_reproducible(self):
        with tempfile.TemporaryDirectory() as tmp:
            for mission in MIX:
                again = ablation.generate(mission, PREREG, tmp)
                self.assertEqual((Path(again["reduced"]["skill_dir"]) / "SKILL.md").read_bytes(),
                                 (self.variant_dir(mission) / "SKILL.md").read_bytes(), mission)
                self.assertEqual(again["reduced"]["payload_sha256"],
                                 self.records[mission]["reduced"]["payload_sha256"], mission)

    def test_the_real_missions_are_never_written(self):
        for mission in MIX:
            self.assertEqual((ROOT / "skills" / mission / "SKILL.md").read_bytes(),
                             self.skill_bytes[mission], mission)
            self.assertTrue(self.variant_dir(mission).is_relative_to(self.out.resolve()))

    def test_the_minimal_contract_quotes_source_lines_verbatim(self):
        for mission, rec in self.records.items():
            variant = (self.variant_dir(mission) / "SKILL.md").read_text()
            for oid in rec["minimal_contract"]:
                ob = next(o for o in PREREG["obligations"] if o["id"] == oid)
                first, last = ablation.anchor_span(ablation.read(ROOT / ob["source"]), ob["anchor"])
                lines = ablation.read(ROOT / ob["source"]).splitlines()[first - 1:last]
                self.assertIn("\n".join(lines), variant, f"{mission}: {oid}")

    def test_the_payloads_are_what_the_records_pin(self):
        for mission, rec in self.records.items():
            for arm in ("baseline", "reduced"):
                payload = (self.out / mission / f"{arm}.payload.md").read_text()
                self.assertEqual(hashlib.sha256(payload.encode()).hexdigest(),
                                 rec[arm]["payload_sha256"], f"{mission} {arm}")
                for rel in rec[arm]["parts"]:
                    self.assertIn(f"===== {rel} =====", payload)

    def test_a_phase_scoped_obligation_rides_its_deferred_phase(self):
        row = next(r for r in self.records["ship-it"]["obligation_check"]["results"] if r["id"] == "FR-1")
        self.assertEqual(row, {"held": True, "where": "deferred at LAND", "id": "FR-1",
                               "class": "review-freshness", "source": "runtime/reviewed-sha-freshness.md"})
        self.assertNotIn("FR-1", self.records["ship-it"]["minimal_contract"])

    def test_the_generate_and_check_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = run_main(["generate", "--mission", "review-it", "--out", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn("obligations: all held", out)
            variant = Path(tmp) / "review-it" / "reduced" / "skills" / "review-it"
            code, out, _ = run_main(["check", "--mission", "review-it", "--variant", str(variant)])
            self.assertEqual(code, 0, out)
            md = variant / "SKILL.md"
            md.write_text(md.read_text().replace("HUMAN ONLY. Never auto-resolved.", "Human."))
            code, out, err = run_main(["check", "--mission", "review-it", "--variant", str(variant)])
            self.assertEqual(code, 1)
            self.assertIn("FAIL  OW-1", out)
            self.assertIn("OW-1 (human-one-way-gate): its source is deferred to VERDICT", err)
        code, _out, err = run_main(["generate", "--mission", "deflake-it"])
        self.assertEqual(code, 2)
        self.assertIn("not in the mix", err)


class TheObligationCheckFailsClosed(unittest.TestCase):
    """A variant that loses an obligation FAILS — each way it can lose one, on a real variant."""

    def setUp(self):
        self.out = Path(tempfile.mkdtemp(prefix="of-ablation-neg-"))
        self.addCleanup(shutil.rmtree, self.out)

    def variant(self, mission, prereg=PREREG):
        rec = ablation.generate(mission, prereg, self.out)
        return Path(rec["reduced"]["skill_dir"]), rec

    def edit(self, vdir, fn):
        md = vdir / "SKILL.md"
        md.write_text(fn(md.read_text()), encoding="utf-8")

    def failed_ids(self, mission, vdir):
        check = ablation.check_obligations(mission, vdir, PREREG)
        self.assertFalse(check["passed"])
        return {row["id"] for row in check["results"] if not row["held"]}, check

    def test_deleting_a_minimal_contract_line_fails(self):
        vdir, _ = self.variant("ship-it")
        self.assertTrue(ablation.check_obligations("ship-it", vdir, PREREG)["passed"])
        self.edit(vdir, lambda t: re.sub(r"\[NC-1\][^\n]*\n[^\n]*\n", "", t))
        failed, check = self.failed_ids("ship-it", vdir)
        self.assertEqual(failed, {"NC-1"})
        # Its source is still loaded at BUILD; NC-1 must be loaded at activation.
        self.assertIn("NC-1 (negative-control): its source is deferred to BUILD",
                      " ".join(check["failures"]))

    def test_dropping_the_section_that_carries_the_human_gates_fails(self):
        prereg = copy.deepcopy(PREREG)
        defer_for(prereg, "ship-it")["drop_sections"] = ["Related", "Gates (only these)"]
        vdir, rec = self.variant("ship-it", prereg)
        self.assertFalse(rec["obligation_check"]["passed"])
        failed, _ = self.failed_ids("ship-it", vdir)
        self.assertEqual(failed, {"OW-SHIP-1", "OW-SHIP-2"})

    def test_a_document_unloaded_without_a_cue_fails_against_the_baseline_denominator(self):
        vdir, _ = self.variant("ship-it")

        def unload_evidence_manifest(text):
            text = text.replace("evidence-manifest.md at BUILD · ", "")
            paras = text.split("\n\n")
            return "\n\n".join(p for p in paras if not (p.startswith("[")
                                                        and "runtime/evidence-manifest.md:" in p))
        self.edit(vdir, unload_evidence_manifest)
        dropped = {"IV-1", "IV-2", "NC-1", "NC-2", "DEN-1", "DEN-2", "DEN-3"}
        failed, check = self.failed_ids("ship-it", vdir)
        self.assertEqual(failed, dropped)
        self.assertIn("DEN-1 (complete-denominator): dropped", " ".join(check["failures"]))
        # Mutation control: read applicability off the VARIANT instead, and the seven obligations
        # of the unloaded document leave the denominator — none is checked, none fails. Only the
        # baseline denominator catches the loss.

        def from_variant(mission, prereg):
            _t, parts = validate.transitive_load(vdir)
            return [ob for ob in prereg["obligations"] if ob["source"] in parts]
        with mock.patch.object(ablation, "applicable_obligations", from_variant):
            naive = ablation.check_obligations("ship-it", vdir, PREREG)
        self.assertFalse({row["id"] for row in naive["results"]} & dropped)
        self.assertTrue(all(row["held"] for row in naive["results"]))

    def test_deferring_past_the_phase_an_obligation_allows_fails(self):
        vdir, _ = self.variant("ship-it")
        self.edit(vdir, lambda t: t.replace("reviewed-sha-freshness.md at LAND",
                                            "reviewed-sha-freshness.md at RELEASE"))
        failed, check = self.failed_ids("ship-it", vdir)
        self.assertEqual(failed, {"FR-1"})
        self.assertIn("deferred to RELEASE, but the obligation must be loaded by "
                      "ACCEPTANCE-REVIEW|LAND|VERDICT", " ".join(check["failures"]))

    def test_an_edited_frontmatter_fails(self):
        vdir, _ = self.variant("review-it")
        self.edit(vdir, lambda t: t.replace("description: >-", "description: >-\n  Also reviews.", 1))
        check = ablation.check_obligations("review-it", vdir, PREREG)
        self.assertFalse(check["passed"])
        self.assertIn("frontmatter differs", " ".join(check["failures"]))

    def test_an_unreadable_variant_fails(self):
        check = ablation.check_obligations("review-it", self.out / "nothing", PREREG)
        self.assertFalse(check["passed"])

    def test_a_leftover_clause_reference_is_refused_at_generation(self):
        # R5: if the clause rewrite missed a name, validate.py would still count the document.
        with mock.patch.object(ablation, "_rewrite_clause", lambda clause, names: clause):
            with self.assertRaisesRegex(ablation.AblationError, "not the registered kept set"):
                ablation.generate("review-it", PREREG, self.out)


class OutputNeverOverlapsTheSources(unittest.TestCase):
    """#652 review, P1: `generate --out skills` deleted the real skills/ship-it at its rmtree.

    Every case runs against a throwaway repo copy with ablation.py loaded from it, and checks the
    copy's source tree byte-for-byte afterwards: refused, and nothing deleted or written.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="of-ablation-overlap-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root, self.mod = repo_copy(self.tmp)
        self.before = {d: tree_digest(self.root / d) for d in ("skills", "playbooks", "runtime", "evals")}

    def assertRefusedAndUntouched(self, argv):
        code, _out, err = run_copy(self.mod, argv)
        self.assertEqual(code, 2, err)
        self.assertIn("overlaps", err)
        for d, digest in self.before.items():
            self.assertEqual(tree_digest(self.root / d), digest, f"{d}/ changed")

    def test_out_skills_is_refused_and_nothing_is_deleted(self):
        self.assertRefusedAndUntouched(["generate", "--mission", "ship-it", "--out", str(self.root / "skills")])

    def test_a_relative_out_skills_is_refused(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, cwd)
        self.assertRefusedAndUntouched(["generate", "--mission", "ship-it", "--out", "skills"])

    def test_inside_equal_or_containing_a_source_is_refused(self):
        for out in (self.root / "skills" / "ship-it", self.root / "playbooks", self.root / "runtime" / "x",
                    self.root / "evals", self.root, self.root / "docs" / "experiments"):
            with self.subTest(out=str(out.relative_to(self.tmp))):
                self.assertRefusedAndUntouched(["generate", "--mission", "ship-it", "--out", str(out)])

    def test_a_symlinked_out_dir_pointing_into_skills_is_refused(self):
        link = self.tmp / "out-link"
        link.symlink_to(self.root / "skills", target_is_directory=True)
        self.assertRefusedAndUntouched(["generate", "--mission", "ship-it", "--out", str(link)])

    def test_a_symlinked_mission_dir_inside_a_safe_out_is_refused(self):
        out = self.tmp / "out"
        out.mkdir()
        (out / "ship-it").symlink_to(self.root / "skills" / "ship-it", target_is_directory=True)
        self.assertRefusedAndUntouched(["generate", "--mission", "ship-it", "--out", str(out)])

    def test_a_run_into_skills_is_refused(self):
        self.assertRefusedAndUntouched(["run", "--dry-run", "--cost-cap-usd", "0", "--mission", "review-it",
                                        "--task", "behavioral-4", "--repeats", "1",
                                        "--out", str(self.root / "skills")])

    def test_a_refresh_never_writes_into_the_sources(self):
        json_path, md_path = self.root / "skills" / "prereg.json", self.root / "skills" / "prereg.md"
        shutil.copyfile(self.root / "docs" / "experiments" / "ablation-prereg.json", json_path)
        shutil.copyfile(self.root / "docs" / "experiments" / "ablation-prereg.md", md_path)
        self.before["skills"] = tree_digest(self.root / "skills")
        self.assertRefusedAndUntouched(["--prereg", str(json_path), "prereg", "--md", str(md_path), "--refresh"])

    def test_a_safe_out_still_generates(self):
        code, out, err = run_copy(self.mod, ["generate", "--mission", "review-it", "--out", str(self.tmp / "ok")])
        self.assertEqual(code, 0, out + err)
        self.assertTrue((self.tmp / "ok" / "review-it" / "variant.json").is_file())


class RegisteredTasksArePinned(unittest.TestCase):
    """#652 review, P2: the freshness check pinned activation text but not the tasks, so editing a
    mission's evals.json, a fixture it names or the trajectory contract changed the experiment
    while registration_status still said `current` and allowed live spend. Run on a repo copy."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="of-ablation-tasks-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root, self.mod = repo_copy(self.tmp)

    def pin_and_status(self, edit):
        self.mod.refresh()
        self.assertEqual(set(self.mod.registration_status(self.mod.load_prereg()).values()), {"current"})
        edit()
        return self.mod.registration_status(self.mod.load_prereg())

    def edit_json(self, rel, change):
        path = self.root / rel
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def test_an_edited_evals_json_makes_its_mission_stale(self):
        def edit():
            self.edit_json("skills/review-it/evals/evals.json",
                           lambda d: d["evals"][3].update(prompt=d["evals"][3]["prompt"] + " Quickly."))
        status = self.pin_and_status(edit)
        self.assertEqual(status["review-it"], "stale: task_inputs_sha256 moved since registration")
        self.assertEqual(status["ship-it"], "current")

    def test_an_edited_trajectory_contract_makes_every_mission_stale(self):
        contract = self.root / "evals" / "trajectories" / "contract.json"
        status = self.pin_and_status(lambda: contract.write_text(contract.read_text() + "\n"))
        self.assertEqual(set(status.values()), {"stale: task_inputs_sha256 moved since registration"})

    def test_a_fixture_a_registered_case_names_is_pinned(self):
        fixture = self.root / "skills" / "review-it" / "evals" / "fixtures" / "NOTES.md"
        fixture.parent.mkdir(parents=True)
        fixture.write_text("notes\n", encoding="utf-8")
        self.edit_json("skills/review-it/evals/evals.json", lambda d: d["evals"][3]["files"].append("NOTES.md"))
        inputs = self.mod.task_inputs("review-it", self.mod.load_prereg())
        self.assertIn("skills/review-it/evals/fixtures/NOTES.md", inputs)
        status = self.pin_and_status(lambda: fixture.write_text("changed\n", encoding="utf-8"))
        self.assertEqual(status["review-it"], "stale: task_inputs_sha256 moved since registration")

    def test_a_missing_task_input_is_pinned_as_missing(self):
        inputs = self.mod.task_inputs("review-it", self.mod.load_prereg())
        self.assertIn("evals/trajectories/contract.json", inputs)
        (self.root / "evals" / "trajectories" / "CL-01.fixes.jsonl").unlink()
        self.assertEqual(self.mod.task_inputs("review-it", self.mod.load_prereg())
                         ["evals/trajectories/CL-01.fixes.jsonl"], "missing")


class Parsing(unittest.TestCase):
    def test_cues_are_read_alike_in_both_arms(self):
        ship = ablation.deferred_cues((ROOT / "skills" / "ship-it" / "SKILL.md").read_text())
        self.assertEqual(ship["release"], ["RELEASE"])
        self.assertEqual(ship["observe"], ["DEPLOYED_AND_VERIFIED"])
        self.assertNotIn("human-handoff", ship, "`at a handoff` names no phase")
        self.assertNotIn("liveness-resume", ship, "a `when ...` cue is conditional")
        sweep = ablation.deferred_cues((ROOT / "skills" / "clean-sweep" / "SKILL.md").read_text())
        self.assertEqual(sweep["merge-serialization"], ["LAND"])
        self.assertEqual(sweep["reviewed-sha-freshness"], ["LAND"])
        generated = ablation.deferred_cues("DEFERRED READS (x): a-b.md at ONE|TWO-X · C.md at THREE.")
        self.assertEqual(generated, {"a-b": ["ONE", "TWO-X"], "C": ["THREE"]})

    def test_an_anchor_spans_line_wraps(self):
        self.assertEqual(ablation.anchor_span("one two\nthree  four\nfive", "two three four"), (1, 2))
        self.assertIsNone(ablation.anchor_span("one two", "two one"))

    def test_pipeline_phases_are_the_upper_case_tokens_of_the_block(self):
        phases = ablation.pipeline_phases((ROOT / "skills" / "ship-it" / "SKILL.md").read_text())
        self.assertLessEqual({"VALIDATE", "GRILL", "DECOMPOSE", "BUILD", "ACCEPTANCE-REVIEW", "LAND"}, phases)
        self.assertNotIn("Composes", phases)


if __name__ == "__main__":
    unittest.main()
