#!/usr/bin/env python3
"""Contract tests for VF-Bench's held-out protocol and leakage check (#601).

The protocol file is predeclared and versioned: its development pins must equal gate.py's and
the corpus's, its dates must say they are planned, and the holder role it records must be filled
by a person or left unfilled — never a placeholder name. The leakage check is exercised against a
SYNTHETIC holder made at test time in a temp dir: held-out cases are generated, digested and
planted into throwaway repositories, and nothing held-out ever touches this checkout.
"""
import base64
import contextlib
import gzip
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench" / "vf-bench"
HELDOUT = BENCH / "heldout.py"
PROTOCOL = BENCH / "heldout-protocol.json"


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


heldout = _load(HELDOUT, "vfbench_heldout")
gate = _load(BENCH / "gate.py", "vfbench_gate_for_heldout")
# The synthetic split's canary is minted per run: a fixed one would be committed in this file,
# and the leakage check run against this repository would rightly report it (#601).
CANARY = str(uuid.uuid4())


def _cli(*args):
    return subprocess.run([sys.executable, str(HELDOUT), *args], capture_output=True, text=True,
                          cwd=ROOT, timeout=300)


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=vf", "-c", "user.email=vf@vf.invalid", "-c", "commit.gpgsign=false",
         "commit", "-qm", message, "--no-verify", "--allow-empty")


def _protocol():
    return json.loads(PROTOCOL.read_text(encoding="utf-8"))


class TheCommittedProtocolIsComplete(unittest.TestCase):
    def test_it_validates(self):
        self.assertEqual(heldout.validate(_protocol()), [])
        r = _cli("validate")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("holder OpenAI Codex", r.stdout)

    def test_the_development_split_is_the_shipped_corpus(self):
        dev = _protocol()["splits"]["development"]
        self.assertEqual(dev["corpus_sha256"], gate.EXPECTED_CORPUS_SHA256)
        self.assertEqual(dev["corpus_sha256"], gate.corpus_digest())
        self.assertEqual(dev["version"], gate.EXPECTED_VERSION)
        self.assertEqual(dev["canary_guid"], gate.EXPECTED_CANARY_GUID)
        self.assertEqual(dev["location"], "bench/vf-bench/traps/*.json")

    def test_held_out_content_is_uncommitted_and_only_its_digests_are_published(self):
        # #601: held-out v1's digests are published; its content is not committed anywhere.
        held = _protocol()["splits"]["heldout"]
        self.assertIs(held["committed"], False)
        digests = heldout.load_digests(ROOT / held["published_digests"])
        self.assertEqual(held["cases"], len(digests["cases"]))
        self.assertEqual(set(digests), {"kind", "protocol", "canary_sha256", "cases"})

    def test_this_repository_carries_none_of_the_published_held_out_cases(self):
        # The leakage check run for real: digests, canonical forms, embedded objects and the
        # held-out canary, against every blob committed at HEAD (#601).
        held = _protocol()["splits"]["heldout"]
        r = _cli("check", "--digests", held["published_digests"], "--rev", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"against {held['cases']} held-out case digest(s)", r.stdout)

    def test_the_holder_is_the_designated_ai_system_with_its_limits(self):
        # #601: the owner designated OpenAI Codex on 2026-10-24. It is an AI system, not a person,
        # and the role says so with who designated it, the independence evidence and its limits.
        holder = _protocol()["holder"]
        self.assertEqual((holder["assigned"], holder["kind"]), ("OpenAI Codex", "ai-system"))
        self.assertEqual(holder["state"], "assigned")
        self.assertTrue(holder["role"])

    def test_every_date_is_planned_or_done_with_evidence(self):
        dates = _protocol()["release_dates"]
        self.assertIn("PLANNED", dates["label"])
        self.assertTrue(dates["milestones"])
        self.assertTrue(all(m["status"] == "planned" or m.get("evidence") for m in dates["milestones"]))

    def test_the_declared_leakage_commands_exist(self):
        for check in _protocol()["leakage_checks"]:
            if "heldout.py" in check["command"]:
                self.assertIn("python3 bench/vf-bench/heldout.py check", check["command"])
        self.assertTrue(HELDOUT.is_file())


class ValidateRefusesADishonestProtocol(unittest.TestCase):
    """Each mutation of the committed protocol is one way it could lie; each must be refused."""

    def _errors(self, mutate):
        doc = _protocol()
        mutate(doc)
        return heldout.validate(doc)

    def test_each_lie_is_named(self):
        def holder(name, state):
            return lambda d: d["holder"].update(assigned=name, state=state)
        cases = {
            "a placeholder holder": (holder("TBD", "assigned"), "placeholder"),
            "a fake name kept unfilled": (holder("Jane Doe", "unfilled"), "placeholder"),
            "a real-looking name still marked unfilled": (holder("A. Person", "unfilled"),
                                                          "must be 'assigned'"),
            "nobody, but marked assigned": (holder(None, "assigned"), "must be 'unfilled'"),
            "a stale development digest": (
                lambda d: d["splits"]["development"].update(corpus_sha256="0" * 64), "corpus_sha256"),
            "a stale case count": (
                lambda d: d["splits"]["development"].update(cases=1), "development split cases"),
            "held-out content committed": (
                lambda d: d["splits"]["heldout"].update(committed=True), "committed: false"),
            "dates not labelled planned": (
                lambda d: d["release_dates"].update(label="release dates"), "labelled as planned"),
            "a done milestone without evidence": (
                lambda d: d["release_dates"]["milestones"][-1].update(status="done"), "without evidence"),
            "a malformed date": (
                lambda d: d["release_dates"]["milestones"][0].update(date="Q1 2027"), "YYYY-MM-DD"),
            "a leakage check dropped": (
                lambda d: d.update(leakage_checks=d["leakage_checks"][1:]), "'digest-scan'"),
            "no temporal rule": (lambda d: d.update(temporal={}), "temporal rule"),
            "missing published digests": (
                lambda d: d["splits"]["heldout"].update(published_digests="bench/vf-bench/none.json"),
                "does not exist"),
        }
        for label, (mutate, needle) in cases.items():
            with self.subTest(lie=label):
                errors = self._errors(mutate)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_a_named_assigned_holder_is_valid(self):
        self.assertEqual(self._errors(lambda d: d["holder"].update(assigned="A. Person",
                                                                    state="assigned")), [])


def _holder_cases(where, n=3):
    """A synthetic holder's unseen cases: development-shaped, each carrying the split's canary."""
    where.mkdir(parents=True)
    for i in range(n):
        case = {"id": f"heldout-{i}", "class": f"unseen-{i}", "sound_expected": "RED",
                "canary": CANARY, "manifest": {"unit": "ship-it", "criteria": [{"id": f"AC-{i}"}]}}
        (where / f"case-{i}.json").write_text(json.dumps(case, indent=2) + "\n", encoding="utf-8")
    return sorted(where.glob("*.json"))


class TheLeakageCheckFindsHeldOutContent(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.cases = _holder_cases(self.tmp / "holder")
        self.digests = self.tmp / "digests.json"
        r = _cli("digest", str(self.tmp / "holder"), "--canary", CANARY, "--out", str(self.digests))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.repo = self.tmp / "solver"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("a solver repository\n", encoding="utf-8")
        _commit(self.repo, "base")

    def tearDown(self):
        self._tmp.cleanup()

    def _check(self, *extra):
        return _cli("check", "--digests", str(self.digests), "--repo", str(self.repo), *extra)

    def test_the_published_digests_carry_no_case_content(self):
        text = self.digests.read_text(encoding="utf-8")
        self.assertNotIn(CANARY, text)
        for case in self.cases:
            self.assertNotIn(json.loads(case.read_text(encoding="utf-8"))["id"], text)
        doc = json.loads(text)
        self.assertEqual(len(doc["cases"]), 3)
        self.assertEqual(set(doc), {"kind", "protocol", "canary_sha256", "cases"})

    def test_a_clean_repository_passes(self):
        r = self._check()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("clean:", r.stdout)

    def test_this_repository_carries_none_of_the_synthetic_cases(self):
        r = _cli("check", "--digests", str(self.digests), "--rev", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_each_way_of_committing_a_case_is_caught(self):
        case = json.loads(self.cases[1].read_text(encoding="utf-8"))
        bare = {k: v for k, v in case.items() if k != "canary"}
        plants = {
            "verbatim": ("copied.json", self.cases[0].read_bytes()),
            "canonical": ("pretty.json", json.dumps(case, indent=8, sort_keys=True).encode()),
            "embedded": ("corpus.json", json.dumps({"cases": [{"wrapped": case}]}).encode()),
            "canary": ("notes.py", f"# from the held-out set: {CANARY.upper()}\n".encode()),
        }
        for kind, (name, data) in plants.items():
            with self.subTest(kind=kind):
                (self.repo / name).write_bytes(data)
                _commit(self.repo, f"plant {kind}")
                r = self._check()
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn(f"LEAK {kind}: {name}", r.stdout)
                (self.repo / name).unlink()
                _commit(self.repo, f"remove {kind}")
        # A case stripped of its canary, re-serialized, is a different object: the digest scan is
        # not a similarity search, and says so by passing.
        (self.repo / "edited.json").write_text(json.dumps(bare), encoding="utf-8")
        _commit(self.repo, "an edited copy")
        self.assertEqual(self._check().returncode, 0)

    def test_history_holds_what_the_tree_dropped(self):
        (self.repo / "leak.json").write_bytes(self.cases[2].read_bytes())
        _commit(self.repo, "leak")
        (self.repo / "leak.json").unlink()
        _commit(self.repo, "hide the leak")
        self.assertEqual(self._check().returncode, 0)
        r = self._check("--all-history")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LEAK verbatim: leak.json", r.stdout)

    def test_the_scan_is_load_bearing(self):
        # With the scan reduced to nothing, the planted verbatim leak passes: the exit code above
        # comes from scan(), not from the CLI's plumbing.
        (self.repo / "copied.json").write_bytes(self.cases[0].read_bytes())
        _commit(self.repo, "plant")
        digests = heldout.load_digests(self.digests)
        leaks, scanned = heldout.check(self.repo, digests)
        self.assertTrue(leaks)
        original = heldout.scan
        try:
            heldout.scan = lambda blob, digests: []
            self.assertEqual(heldout.check(self.repo, digests)[0], [])
        finally:
            heldout.scan = original
        self.assertEqual(scanned, 2)


class TheHolderToolRefusesBadInput(unittest.TestCase):
    def test_a_case_without_the_canary_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-") as tmp:
            cases = Path(tmp) / "holder"
            cases.mkdir()
            (cases / "c.json").write_text(json.dumps({"id": "no-canary"}), encoding="utf-8")
            r = _cli("digest", str(cases), "--canary", CANARY, "--out", str(Path(tmp) / "d.json"))
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn("does not carry the split's canary GUID", r.stdout)
            self.assertFalse((Path(tmp) / "d.json").exists())

    def test_malformed_digests_are_a_usage_error(self):
        with tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-") as tmp:
            bad = Path(tmp) / "d.json"
            for doc in ({}, {"kind": heldout.DIGESTS_KIND, "protocol": heldout.PROTOCOL_ID,
                             "canary_sha256": "0" * 64, "cases": [{"raw_sha256": "x"}]}):
                bad.write_text(json.dumps(doc), encoding="utf-8")
                with self.subTest(doc=doc):
                    r = _cli("check", "--digests", str(bad))
                    self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_a_non_guid_canary_is_a_usage_error(self):
        r = _cli("digest", str(ROOT), "--canary", "not-a-guid", "--out", "/dev/null")
        self.assertEqual(r.returncode, 2)



# PR #645 review (P1): the encodings json.loads itself reads (RFC 8259 / 7159: UTF-8, UTF-16 and
# UTF-32, a BOM or the null-byte pattern of an ASCII first character). A held-out case saved in
# any of them is the same case, so the scan must find it as one.
ENCODINGS = {
    "utf-8 with a BOM": lambda text: b"\xef\xbb\xbf" + text.encode("utf-8"),
    "utf-16 with a BOM": lambda text: text.encode("utf-16"),
    "utf-16-le, no BOM": lambda text: text.encode("utf-16-le"),
    "utf-16-be, no BOM": lambda text: text.encode("utf-16-be"),
    "utf-32 with a BOM": lambda text: text.encode("utf-32"),
    "utf-32-le, no BOM": lambda text: text.encode("utf-32-le"),
    "utf-32-be, no BOM": lambda text: text.encode("utf-32-be"),
}


class EncodedCopiesOfACaseAreCaught(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.cases = _holder_cases(self.tmp / "holder")
        doc, problems = heldout.digest_cases(self.tmp / "holder", CANARY)
        self.assertEqual(problems, [])
        self.digests = doc
        self.case = json.loads(self.cases[0].read_text(encoding="utf-8"))

    def tearDown(self):
        self._tmp.cleanup()

    def _kinds(self, blob):
        return {kind for kind, _ in heldout.scan(blob, self.digests)}

    def test_each_encoding_json_reads_is_caught_as_the_case(self):
        text = json.dumps(self.case, indent=2)
        for label, encode in ENCODINGS.items():
            with self.subTest(encoding=label):
                blob = encode(text)
                self.assertEqual(json.loads(blob), self.case, "json.loads reads this copy")
                kinds = self._kinds(blob)
                self.assertIn("canonical", kinds)
                self.assertIn("canary", kinds)

    def test_an_encoded_case_inside_a_larger_document_is_embedded(self):
        text = json.dumps({"corpus": [self.case]})
        for label, encode in ENCODINGS.items():
            with self.subTest(encoding=label):
                self.assertIn("embedded", self._kinds(encode(text)))

    def test_the_canary_in_an_encoded_text_file_is_caught(self):
        text = f"# notes copied from the held-out set\nmarker {CANARY}\n"
        for label, encode in ENCODINGS.items():
            with self.subTest(encoding=label):
                self.assertEqual(self._kinds(encode(text)), {"canary"})

    def test_the_check_reports_an_encoded_commit(self):
        repo = self.tmp / "solver"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "case.utf16.json").write_bytes(json.dumps(self.case).encode("utf-16"))
        _commit(repo, "a held-out case, re-encoded")
        out = self.tmp / "digests.json"
        out.write_text(json.dumps(self.digests), encoding="utf-8")
        r = _cli("check", "--digests", str(out), "--repo", str(repo))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LEAK canonical: case.utf16.json", r.stdout)
        self.assertIn("LEAK canary: case.utf16.json", r.stdout)


class TheScanStatesWhatItDoesNotCatch(unittest.TestCase):
    """The protocol may promise only what the scan does. It decodes text, not containers: a
    compressed or base64-encoded copy is a stated limit, never an implied catch."""

    def _scan_checks(self):
        return [c for c in _protocol()["leakage_checks"] if "heldout.py" in c["command"]]

    def test_no_check_claims_any_format(self):
        for check in _protocol()["leakage_checks"]:
            with self.subTest(check=check["id"]):
                self.assertNotIn("any format", check["detects"])

    def test_every_scan_names_its_limits(self):
        checks = self._scan_checks()
        self.assertTrue(checks)
        for check in checks:
            with self.subTest(check=check["id"]):
                limits = check.get("limits", "")
                for word in ("gzip", "base64", "UTF-16"):
                    self.assertIn(word, limits + " " + check["detects"])

    def test_validate_refuses_a_scan_with_no_stated_limits(self):
        doc = _protocol()
        for check in doc["leakage_checks"]:
            if "heldout.py" in check["command"]:
                check.pop("limits", None)
        errors = heldout.validate(doc)
        self.assertTrue(any("limits" in e for e in errors), errors)

    def test_the_stated_limits_are_the_real_ones(self):
        with tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-") as tmp:
            _holder_cases(Path(tmp) / "holder", n=1)
            digests, _ = heldout.digest_cases(Path(tmp) / "holder", CANARY)
            raw = next((Path(tmp) / "holder").glob("*.json")).read_bytes()
        hidden = {"gzip": gzip.compress(raw),
                  "base64": json.dumps({"blob": base64.b64encode(raw).decode()}).encode()}
        for label, blob in hidden.items():
            with self.subTest(container=label):
                self.assertEqual(heldout.scan(blob, digests), [],
                                 "the scan now decodes this: update the protocol's limits")



def _escaped(text):
    """The canary written the way json.dumps(ensure_ascii) could write any character: every one
    as a \\uXXXX escape. The parsed value is the same GUID; the bytes no longer contain it."""
    return text.replace(CANARY, "".join(f"\\u{ord(c):04x}" for c in CANARY))


class NoBlobIsPassedUnscanned(unittest.TestCase):
    """PR #645 review (P1): a JSON document over the parse limit skipped the canonical and
    embedded checks and still reported clean, so a case inside it whose canary was written with
    JSON escapes escaped every check. A blob the scan cannot fully check is now reported, never
    passed — and an escaped canary is read as the GUID it is."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        _holder_cases(self.tmp / "holder", n=1)
        self.digests, problems = heldout.digest_cases(self.tmp / "holder", CANARY)
        self.assertEqual(problems, [])
        self.case = json.loads(next((self.tmp / "holder").glob("*.json")).read_text(encoding="utf-8"))
        (self.tmp / "digests.json").write_text(json.dumps(self.digests), encoding="utf-8")
        self.repo = self.tmp / "solver"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "README.md").write_text("a solver\n", encoding="utf-8")
        _commit(self.repo, "base")

    def tearDown(self):
        self._tmp.cleanup()

    def _plant(self, name, data):
        (self.repo / name).write_bytes(data)
        _commit(self.repo, f"plant {name}")

    def test_a_document_over_the_parse_limit_is_unscanned_not_clean(self):
        big = _escaped(json.dumps({"padding": "x" * 4096, "cases": [self.case]}, ensure_ascii=True))
        self._plant("bulk.json", big.encode("utf-8"))
        r = _cli("check", "--digests", str(self.tmp / "digests.json"), "--repo", str(self.repo),
                 "--max-json-bytes", "1024")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("UNSCANNED: bulk.json", r.stdout)
        # Raised past the document, the same check parses it and names the embedded case.
        r = _cli("check", "--digests", str(self.tmp / "digests.json"), "--repo", str(self.repo),
                 "--max-json-bytes", str(1 << 20))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LEAK embedded: bulk.json", r.stdout)
        self.assertNotIn("UNSCANNED", r.stdout)

    def test_an_escaped_canary_is_read_as_the_guid(self):
        edited = dict(self.case, sound_expected="GREEN")  # no digest matches an edited case
        for name, text in (
                ("lines.jsonl", json.dumps(edited) + "\n" + json.dumps({"other": 1}) + "\n"),
                ("source.py", "CASE = " + json.dumps(json.dumps(edited)) + "\n")):
            with self.subTest(file=name):
                kinds = {k for k, _ in heldout.scan(_escaped(text).encode("utf-8"), self.digests)}
                self.assertEqual(kinds, {"canary"})

    def test_content_kept_outside_the_repository_is_unscanned_not_clean(self):
        pointer = ("version https://git-lfs.github.com/spec/v1\n"
                   "oid sha256:" + "a" * 64 + "\nsize 4096\n")
        self._plant("heldout.json", pointer.encode("utf-8"))
        sub = self.tmp / "sub"
        sub.mkdir()
        _git(sub, "init", "-q", "-b", "main")
        _commit(sub, "empty")
        _git(self.repo, "update-index", "--add", "--cacheinfo",
             f"160000,{_git(sub, 'rev-parse', 'HEAD')},vendored")
        # Committed from the index as is: `add -A` would drop a gitlink with no working tree.
        _git(self.repo, "-c", "user.name=vf", "-c", "user.email=vf@vf.invalid", "-c",
             "commit.gpgsign=false", "commit", "-qm", "a submodule entry", "--no-verify")
        findings, _ = heldout.check(self.repo, self.digests)
        got = {(f["path"], f["kind"]) for f in findings}
        self.assertIn(("heldout.json", "unscanned"), got)
        self.assertIn(("vendored", "unscanned"), got)

    def test_the_protocol_states_the_parse_limit(self):
        digest_scan = next(c for c in _protocol()["leakage_checks"] if c["id"] == "digest-scan")
        self.assertIn("--max-json-bytes", digest_scan["limits"])
        self.assertIn("UNSCANNED", digest_scan["limits"])



class TheHolderToolAcceptsWhatTheScannerFinds(unittest.TestCase):
    """PR #645 review (P2): `digest` looked for the lowercase canary's UTF-8 bytes, so a valid case
    carrying its GUID in uppercase, in UTF-16 or behind JSON escapes was refused, though the scanner
    finds every one of those. The canary is now looked for in the PARSED case, normalized. And the
    reverse (sweep): a case the scanner could never find is refused instead of digested."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.case = {"id": "heldout-x", "class": "unseen", "sound_expected": "RED",
                     "canary": CANARY, "manifest": {"unit": "ship-it"}}

    def tearDown(self):
        self._tmp.cleanup()

    def _digest(self, name, data):
        where = self.tmp / name
        where.mkdir()
        (where / "case.json").write_bytes(data)
        return heldout.digest_cases(where, CANARY)

    def test_each_representation_the_scanner_finds_is_accepted(self):
        text = json.dumps(self.case)
        forms = {
            "uppercase GUID": text.replace(CANARY, CANARY.upper()).encode("utf-8"),
            "UTF-16": text.encode("utf-16"),
            "UTF-8 with a BOM": b"\xef\xbb\xbf" + text.encode("utf-8"),
            "JSON escapes": _escaped(text).encode("utf-8"),
        }
        for label, data in forms.items():
            with self.subTest(form=label):
                doc, problems = self._digest(label.replace(" ", "-"), data)
                self.assertEqual(problems, [])
                # ...and the scanner finds that very file once it is committed.
                kinds = {k for k, _ in heldout.scan(data, doc)}
                self.assertIn("verbatim", kinds)
                self.assertIn("canonical", kinds)

    def test_a_case_without_its_canary_is_still_refused(self):
        bare = dict(self.case, canary="none")
        _, problems = self._digest("bare", json.dumps(bare).encode("utf-8"))
        self.assertTrue(any("canary" in p for p in problems), problems)

    def test_a_case_the_scanner_cannot_match_is_refused(self):
        _, problems = self._digest("array", json.dumps([self.case]).encode("utf-8"))
        self.assertTrue(any("JSON object" in p for p in problems), problems)



def _nested(depth, inner="null"):
    """A JSON text `depth` arrays deep around `inner`."""
    return "[" * depth + inner + "]" * depth


class DeepJsonNeverStopsTheTools(unittest.TestCase):
    """PR #645 review (P2): a small, deeply nested JSON file raised RecursionError out of json.loads,
    the object walk or the canonical form, which nothing caught, so one unrelated file stopped the
    whole leakage check before it reported the rest. Every JSON read here now survives depth: the
    scan walks without recursion and names what it still cannot read UNSCANNED, and the holder's
    tool and the digests and protocol readers refuse such input instead of crashing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.cases = _holder_cases(self.tmp / "holder", n=1)
        self.digests, _ = heldout.digest_cases(self.tmp / "holder", CANARY)
        (self.tmp / "digests.json").write_text(json.dumps(self.digests), encoding="utf-8")
        self.case_text = self.cases[0].read_text(encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_document_too_deep_to_parse_is_unscanned(self):
        kinds = {k for k, _ in heldout.scan(_nested(100_000).encode(), self.digests)}
        self.assertEqual(kinds, {"unscanned"})

    def test_a_deep_document_around_a_case_is_never_clean(self):
        # Parseable on some interpreters, not on others; found or unscanned, never clean.
        kinds = {k for k, _ in heldout.scan(_nested(1_500, self.case_text).encode(), self.digests)}
        self.assertTrue(kinds & {"embedded", "unscanned"}, kinds)

    def test_one_deep_file_does_not_stop_the_check(self):
        repo = self.tmp / "solver"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "main")
        (repo / "deep.json").write_text(_nested(100_000), encoding="utf-8")
        (repo / "leak.json").write_text(self.case_text, encoding="utf-8")
        _commit(repo, "a deep file beside a leak")
        r = _cli("check", "--digests", str(self.tmp / "digests.json"), "--repo", str(repo))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("UNSCANNED: deep.json", r.stdout)
        self.assertIn("LEAK verbatim: leak.json", r.stdout)

    def test_the_holder_tool_refuses_a_case_too_deep_to_read(self):
        where = self.tmp / "deep-holder"
        where.mkdir()
        (where / "case.json").write_text(_nested(100_000, json.dumps(CANARY)), encoding="utf-8")
        _, problems = heldout.digest_cases(where, CANARY)
        self.assertTrue(any("too deep" in p for p in problems), problems)

    def test_deep_digests_and_protocol_files_are_usage_errors(self):
        deep = self.tmp / "deep.json"
        deep.write_text(_nested(100_000), encoding="utf-8")
        for args in (["check", "--digests", str(deep)], ["validate", "--protocol", str(deep)]):
            with self.subTest(args=args[0]):
                r = _cli(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertNotIn("Traceback", r.stderr)



class NoOneFileStopsTheCheck(unittest.TestCase):
    """PR #645 review (P2): `{"note":"\\ud800"}` is JSON json.loads accepts, but its lone surrogate
    cannot be encoded as UTF-8, so the canonical form raised UnicodeEncodeError, which nothing
    caught, and the check died before reporting the files after it. Any failure on one file now
    names that file UNSCANNED and the scan goes on; the siblings found in the sweep are pinned too."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.cases = _holder_cases(self.tmp / "holder", n=1)
        self.digests, _ = heldout.digest_cases(self.tmp / "holder", CANARY)
        self.digests_file = self.tmp / "digests.json"
        self.digests_file.write_text(json.dumps(self.digests), encoding="utf-8")
        self.case_text = self.cases[0].read_text(encoding="utf-8")
        self.repo = self.tmp / "solver"
        self.repo.mkdir()
        _git(self.repo, "init", "-q", "-b", "main")

    def tearDown(self):
        for p in self.tmp.rglob("*"):
            with contextlib.suppress(OSError):
                p.chmod(0o755)
        self._tmp.cleanup()

    def _check(self):
        return _cli("check", "--digests", str(self.digests_file), "--repo", str(self.repo))

    def _assert_reported(self, r, unscanned):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn(f"UNSCANNED: {unscanned}", r.stdout)
        self.assertIn("LEAK verbatim: zz-leak.json", r.stdout)

    def test_an_unencodable_document_beside_a_leak(self):
        (self.repo / "bad.json").write_text('{"note":"\\ud800"}', encoding="utf-8")
        (self.repo / "zz-leak.json").write_text(self.case_text, encoding="utf-8")
        _commit(self.repo, "an unencodable file beside a leak")
        self._assert_reported(self._check(), "bad.json")

    def test_an_unencodable_value_beside_an_embedded_case(self):
        case = json.loads(self.case_text)
        blob = json.dumps({"note": "\ud800", "cases": [case]}).encode("utf-8")
        kinds = {k for k, _ in heldout.scan(blob, self.digests)}
        self.assertIn("embedded", kinds)
        self.assertIn("unscanned", kinds)

    def test_valid_json_the_parser_cannot_convert_is_unscanned_not_clean(self):
        # A 5000-digit integer is valid JSON that json.loads refuses with a plain ValueError (the
        # int-conversion limit), unlike malformed text: the case beside it was passed as clean.
        case = json.loads(self.case_text)
        blob = ('{"n": ' + "1" * 5000 + ', "cases": [' + json.dumps(case) + "]}").encode()
        self.assertIn("unscanned", {k for k, _ in heldout.scan(blob, self.digests)})

    def test_a_missing_object_beside_a_leak(self):
        (self.repo / "gone.txt").write_text("an object a partial clone never fetched\n",
                                            encoding="utf-8")
        (self.repo / "zz-leak.json").write_text(self.case_text, encoding="utf-8")
        _commit(self.repo, "a blob to lose")
        sha = _git(self.repo, "rev-parse", "HEAD:gone.txt")
        (self.repo / ".git" / "objects" / sha[:2] / sha[2:]).unlink()
        self._assert_reported(self._check(), "gone.txt")

    def test_a_scan_that_raises_on_one_blob_names_it_and_goes_on(self):
        (self.repo / "boom.json").write_text("{}", encoding="utf-8")
        (self.repo / "zz-leak.json").write_text(self.case_text, encoding="utf-8")
        _commit(self.repo, "two files")
        original = heldout.scan

        def flaky(blob, digests):
            if blob == b"{}":
                raise OSError("the disk said no")
            return original(blob, digests)
        with mock.patch.object(heldout, "scan", flaky):
            findings, _ = heldout.check(self.repo, self.digests)
        got = {(f["path"], f["kind"]) for f in findings}
        self.assertIn(("boom.json", "unscanned"), got)
        self.assertIn(("zz-leak.json", "verbatim"), got)

    def test_the_holder_tool_names_an_unreadable_case_and_goes_on(self):
        where = self.tmp / "holder2"
        where.mkdir()
        (where / "good.json").write_text(self.case_text, encoding="utf-8")
        (where / "locked.json").write_text(self.case_text, encoding="utf-8")
        (where / "locked.json").chmod(0)
        (where / "dir.json").mkdir()
        (where / "loop-a.json").symlink_to(where / "loop-b.json")
        (where / "loop-b.json").symlink_to(where / "loop-a.json")
        (where / "surrogate.json").write_text('{"canary": "%s", "x": "\\ud800"}' % CANARY,
                                              encoding="utf-8")
        doc, problems = heldout.digest_cases(where, CANARY)
        for name in ("locked.json", "dir.json", "loop-a.json", "loop-b.json", "surrogate.json"):
            with self.subTest(file=name):
                self.assertTrue(any(p.startswith(name + ":") for p in problems), problems)
        self.assertEqual(len(doc["cases"]), 1)

    def test_validate_names_an_unreadable_trap_and_goes_on(self):
        traps = self.tmp / "traps"
        traps.mkdir()
        (traps / "good.json").write_text('{"sound_expected": "RED"}', encoding="utf-8")
        (traps / "broken.json").write_text("{not json", encoding="utf-8")
        errors = heldout.validate(_protocol(), traps_dir=traps)
        self.assertTrue(any("broken.json" in e for e in errors), errors)



class HistoryTheCloneNeverFetchedIsNeverClean(unittest.TestCase):
    """PR #645 review (P1): on a shallow clone, `check --all-history` stopped at the shallow
    boundary and reported clean, though a held-out case had been committed and deleted before it.
    A partial clone hid history the same way, or reached for its promisor remote to fetch it. What
    the repository does not hold is now named UNSCANNED and fails the check, while the history it
    does hold is still scanned, and no git call here ever fetches."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.cases = _holder_cases(self.tmp / "holder", n=1)
        self.digests = self.tmp / "digests.json"
        doc, _ = heldout.digest_cases(self.tmp / "holder", CANARY)
        self.digests.write_text(json.dumps(doc), encoding="utf-8")
        self.src = self.tmp / "src"
        self.src.mkdir()
        _git(self.src, "init", "-q", "-b", "main")
        _git(self.src, "config", "uploadpack.allowFilter", "true")
        (self.src / "case.json").write_bytes(self.cases[0].read_bytes())
        _commit(self.src, "a held-out case, committed")
        (self.src / "case.json").unlink()
        (self.src / "README.md").write_text("nothing to see\n", encoding="utf-8")
        _commit(self.src, "and deleted")

    def tearDown(self):
        self._tmp.cleanup()

    def _clone(self, name, *flags):
        dest = self.tmp / name
        subprocess.run(["git", "clone", "-q", *flags, self.src.as_uri(), str(dest)], check=True,
                       capture_output=True)
        return dest

    def _check(self, repo, *extra):
        return _cli("check", "--digests", str(self.digests), "--repo", str(repo), *extra)

    def test_the_full_history_holds_the_leak(self):
        r = self._check(self._clone("full"), "--all-history")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("LEAK verbatim: case.json", r.stdout)

    def test_a_shallow_clone_is_unscanned_history_not_clean(self):
        shallow = self._clone("shallow", "--depth", "1")
        self.assertEqual(_git(shallow, "rev-parse", "--is-shallow-repository"), "true")
        r = self._check(shallow, "--all-history")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("clean:", r.stdout)
        self.assertIn("UNSCANNED: (history before the shallow boundary)", r.stdout)
        # The tree at HEAD is whole in a shallow clone: the default scan still runs, and passes.
        self.assertEqual(self._check(shallow).returncode, 0)

    def test_a_partial_clone_names_what_it_never_fetched_and_fetches_nothing(self):
        partial = self._clone("partial", "--no-checkout", "--filter=blob:none")
        # The promisor is gone: any fetch would fail loudly, and the check must not need one.
        shutil.rmtree(self.src)
        r = self._check(partial, "--all-history")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertNotIn("clean:", r.stdout)
        self.assertIn("UNSCANNED:", r.stdout)
        self.assertIn("never fetched", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    def test_the_protocol_states_it(self):
        history = next(c for c in _protocol()["leakage_checks"] if c["id"] == "history-scan")
        self.assertIn("shallow", history["limits"])
        self.assertIn("UNSCANNED", history["limits"])

    def test_no_workflow_runs_the_history_scan_on_a_shallow_checkout(self):
        for wf in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = wf.read_text(encoding="utf-8")
            for job in re.split(r"(?m)^  (?=[A-Za-z0-9_-]+:\s*$)", text)[1:]:
                if "heldout.py check" in job and "--all-history" in job:
                    with self.subTest(workflow=wf.name, job=job.split(":", 1)[0]):
                        self.assertRegex(job, r"fetch-depth:\s*0\b")


class CiRunsTheLeakageCheckOnEveryPullRequest(unittest.TestCase):
    def test_the_replay_job_scans_all_history_with_the_published_digests(self):
        # The protocol says the digest scan runs on every PR once digests are published (#601).
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        held = _protocol()["splits"]["heldout"]
        self.assertIn(f"python3 bench/vf-bench/heldout.py check --digests "
                      f"{held['published_digests']} --all-history", workflow)


class TheRecordedEvaluationIsStatedAsMeasured(unittest.TestCase):
    """The held-out v1 evaluation's numbers are written in the VF-Bench README and the run record;
    both are pinned to the report the protocol binds, and the report carries no content (#601)."""

    @classmethod
    def setUpClass(cls):
        cls.protocol = _protocol()
        cls.ev = cls.protocol["evaluations"][0]
        cls.raw = (ROOT / cls.ev["report"]).read_bytes()
        cls.report = json.loads(cls.raw)

    def test_the_report_carries_ids_verdicts_and_metrics_only(self):
        self.assertEqual({k for c in self.report["corpus"]["cases"] for k in c}, {"id"})
        self.assertEqual(self.report["diagnostics"], {})
        digests = heldout.load_digests(ROOT / self.protocol["splits"]["heldout"]["published_digests"])
        self.assertEqual(heldout.scan(self.raw, digests), [])
        self.assertTrue(self.report["heldout"]["matches_published"])

    def test_the_prose_states_the_bound_numbers(self):
        sound = self.report["configurations"]["open-fleet verify.py (sound)"]
        naive = self.report["configurations"]["self-scoring (naive)"]["metrics"]
        m, cov = sound["metrics"], sound["runs"][0]["coverage"]
        readme = " ".join((BENCH / "README.md").read_text(encoding="utf-8").split(
            "**The held-out v1 evaluation", 1)[1].split("\n\n", 1)[0].split())
        record = (ROOT / Path(self.ev["report"]).parent / "README.md").read_text(encoding="utf-8")
        self.assertEqual((m["false_acceptance"]["spread"], m["false_rejection"]["spread"],
                          sound["unstable_cases"]), (0, 0, []))
        for phrase in (
                f"`{self.ev['revision'][:12]}`",
                f"verify.py {m['false_acceptance']['max']}/{m['false_acceptance']['of']} false "
                f"acceptance and {m['false_rejection']['max']}/{m['false_rejection']['of']} false "
                f"rejection in every run",
                f"{m['wrong_reason']['max']}/{m['wrong_reason']['of']} traps",
                f"{cov['sampled_rows']} of {cov['inventory_rows']} inventory rows",
                f"the synthetic baseline {naive['false_acceptance']['max']}/"
                f"{naive['false_acceptance']['of']} and {naive['false_rejection']['max']}/"
                f"{naive['false_rejection']['of']}"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, readme)
        for phrase in (self.ev["report_sha256"], self.ev["revision"],
                       f"| {m['false_acceptance']['max']}/{m['false_acceptance']['of']} | "
                       f"{m['false_rejection']['max']}/{m['false_rejection']['of']} | "
                       f"{m['wrong_reason']['max']}/{m['wrong_reason']['of']} | "
                       f"{cov['sampled_rows']} of {cov['inventory_rows']} |"):
            with self.subTest(record=phrase):
                self.assertIn(phrase, record)


class AFilledHolderIsValidatedNotTakenOnTrust(unittest.TestCase):
    """#601: a name alone does not fill the role. An assigned holder records who designated it
    and when, why it is independent and where that independence stops; an AI system also names
    its model, client and operator, so it cannot read as a person."""

    def _errors(self, mutate):
        doc = _protocol()
        mutate(doc)
        return heldout.validate(doc)

    def test_each_missing_field_is_named(self):
        for key in ("kind", "designated_by", "designated_on", "independence_evidence", "limits",
                    "model", "client", "operated_by"):
            with self.subTest(field=key):
                errors = self._errors(lambda d, k=key: d["holder"].pop(k))
                self.assertTrue(any(f"must record {key}" in e for e in errors), errors)

    def test_an_unknown_kind_and_a_malformed_date_are_refused(self):
        self.assertTrue(any("holder.kind" in e for e in
                            self._errors(lambda d: d["holder"].update(kind="robot"))))
        self.assertTrue(any("designated_on" in e for e in
                            self._errors(lambda d: d["holder"].update(designated_on="today"))))

    def test_a_person_needs_no_model(self):
        def person(d):
            d["holder"].update(kind="person", assigned="A. Person")
            for key in ("model", "client", "operated_by"):
                d["holder"].pop(key)
        self.assertEqual(self._errors(person), [])


class AMilestoneCannotDisagreeWithTheProtocol(unittest.TestCase):
    def _errors(self, mutate):
        doc = _protocol()
        mutate(doc)
        return heldout.validate(doc)

    def _milestone(self, doc, mid):
        return next(m for m in doc["release_dates"]["milestones"] if m["id"] == mid)

    def test_a_planned_milestone_that_happened_is_refused(self):
        errors = self._errors(lambda d: self._milestone(d, "holder-assigned").update(status="planned"))
        self.assertTrue(any("'holder-assigned' is still 'planned'" in e for e in errors), errors)

    def test_a_done_milestone_the_protocol_does_not_show_is_refused(self):
        def mutate(d):
            self._milestone(d, "revealed").update(status="done", evidence="said so")
            self._milestone(d, "revealed")["id"] = "evaluated"
            d.pop("evaluations", None)
            for m in d["release_dates"]["milestones"]:
                if m["id"] == "evaluated" and m.get("milestone", "").startswith("held-out v1 evaluated"):
                    m["status"] = "planned"
        errors = self._errors(mutate)
        self.assertTrue(any("'evaluated' is marked done, but" in e for e in errors), errors)


def _vet_set(where, pin, n=3):
    """A synthetic held-out set the vet accepts: development-shaped run-time fixture cases
    re-labelled with the held-out fields. Built at test time; none of it is the real set."""
    where.mkdir(parents=True)
    now = heldout.datetime.now(heldout.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sources = [("lighting-swap", "check_lighting", "lighting-swap"),
               ("mutation-valid-control", "check_lighting", None),
               ("stale-wtree", "check_commands", "no recorded command with exit 0")][:n]
    for i, (src, cls, site) in enumerate(sources, 1):
        case = json.loads((BENCH / "traps" / f"{src}.json").read_text(encoding="utf-8"))
        case.pop("neighbour", None)
        # Reworded, so no case is a copy of its development source (the vet refuses copies).
        case["manifest"]["criteria"][0]["text"] = "add(a, b) is the sum of a and b"
        case.update({"id": f"hv1-{i:03d}", "class": cls, "canary": CANARY, "authored_at": now,
                     "verifier_pin": {"commit": pin["commit"], "verify_blob": pin["verify_blob"]}})
        if site:
            case["inventory_site"] = site
            case.setdefault("expect_reason", site)
        (where / f"hv1-{i:03d}.json").write_text(json.dumps(case, indent=2), encoding="utf-8")
    return sorted(where.glob("*.json"))


class TheVetChecksWhatTheReplayWillRunAndQuotesNothing(unittest.TestCase):
    """`vet` is the holder's lint: it refuses a case the replay could not run as written, and
    names each problem by file without quoting the case (#601). It never runs the verifier."""

    @classmethod
    def setUpClass(cls):
        cls.pin = heldout.resolve_pin(ROOT, "HEAD")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.files = _vet_set(self.tmp / "cases", self.pin)

    def tearDown(self):
        self._tmp.cleanup()

    def _edit(self, n, edit):
        f = self.files[n]
        case = json.loads(f.read_text(encoding="utf-8"))
        edit(case)
        f.write_text(json.dumps(case), encoding="utf-8")

    def test_a_well_formed_set_is_ready(self):
        problems, cases = heldout.vet_cases(self.tmp / "cases", self.pin)
        self.assertEqual(problems, [])
        self.assertEqual(len(cases), 3)
        r = _cli("vet", str(self.tmp / "cases"), "--pin", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ready to digest", r.stdout)

    def test_each_defect_is_named_by_file_and_quotes_no_value(self):
        secret = "hv-secret-77"
        defects = {
            "a field the replay does not read": (0, lambda c: c.update({secret: 1}),
                                                 "field(s) the replay does not read"),
            "an id that is not opaque": (0, lambda c: c.update(id=secret), "id must be opaque"),
            "a category that is no check": (0, lambda c: c.update({"class": secret}),
                                            "class must be a check"),
            "a trap with no declared refusal": (0, lambda c: c.pop("expect_reason"),
                                                "expect_reason"),
            "a site that names no row": (0, lambda c: c.update(inventory_site=secret),
                                         "exactly one inventory row"),
            "a site two rows share": (0, lambda c: c.update({"class": "execute_negative_control",
                                                             "inventory_site": "Output was:"}),
                                      "exactly one inventory row"),
            "authored before the pin": (0, lambda c: c.update(authored_at="2020-01-01T00:00:00Z"),
                                        "not after the pinned verifier revision"),
            "another verifier pin": (0, lambda c: c["verifier_pin"].update(verify_blob="0" * 40),
                                     "verifier_pin must be"),
            "an unknown builder": (0, lambda c: c.update(fixture=secret), "no run-time builder"),
            "a placeholder no fixture fills": (
                0, lambda c: c["manifest"]["intent"].update(goal="{{" + secret + "}}"),
                "placeholder"),
            "a contract the fixture never writes": (
                0, lambda c: c.update(coordinator_contract=f"coordinator/{secret}.md"),
                "coordinator_contract names no contract"),
            "a neighbour that is no control": (0, lambda c: c.update(neighbour="hv1-003"),
                                               "neighbour must be the id of a valid control"),
            "a static case with fixture-only fields": (
                0, lambda c: c.pop("fixture"), "only a run-time fixture reads"),
            "a development case under new ids": (
                0, lambda c: c["manifest"]["criteria"][0].update(text="add(a, b) returns a + b"),
                "a copy of a development case"),
        }
        for label, (n, edit, needle) in defects.items():
            with self.subTest(defect=label):
                original = self.files[n].read_bytes()
                try:
                    self._edit(n, edit)
                    problems, _ = heldout.vet_cases(self.tmp / "cases", self.pin)
                    mine = [p for p in problems if p.startswith(self.files[n].name + ":")]
                    self.assertTrue(any(needle in p for p in mine), problems)
                    self.assertFalse(any(secret in p for p in problems), problems)
                finally:
                    self.files[n].write_bytes(original)

    def test_the_summary_publishes_counts_and_the_set_digest_only(self):
        digests, summary = self.tmp / "d.json", self.tmp / "s.json"
        r = _cli("digest", str(self.tmp / "cases"), "--canary", CANARY, "--out", str(digests),
                 "--summary", str(summary), "--pin", "HEAD")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        doc = json.loads(summary.read_text(encoding="utf-8"))
        self.assertEqual(set(doc), {"kind", "protocol", "set_sha256", "cases", "traps",
                                    "valid_controls", "by_category", "authored_from",
                                    "authored_to", "file_mtime_from", "file_mtime_to",
                                    "nearest_development_case", "pinned_verifier"})
        self.assertEqual(doc["nearest_development_case"]["copies"], 0)
        self.assertGreater(doc["nearest_development_case"]["differing_leaves_min"], 0)
        self.assertEqual(doc["set_sha256"], heldout.set_digest(heldout.load_digests(digests)))
        self.assertEqual(doc["by_category"], {"check_commands": {"traps": 1, "valid_controls": 0},
                                              "check_lighting": {"traps": 1, "valid_controls": 1}})
        text = summary.read_text(encoding="utf-8") + r.stdout
        for f in self.files:
            self.assertNotIn(json.loads(f.read_text(encoding="utf-8"))["id"], text)
        self.assertNotIn(CANARY, text)

    def test_the_summary_needs_a_vetted_set_and_a_pin(self):
        r = _cli("digest", str(self.tmp / "cases"), "--canary", CANARY, "--out",
                 str(self.tmp / "d.json"), "--summary", str(self.tmp / "s.json"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self._edit(0, lambda c: c.pop("expect_reason"))
        r = _cli("digest", str(self.tmp / "cases"), "--canary", CANARY, "--out",
                 str(self.tmp / "d.json"), "--summary", str(self.tmp / "s.json"), "--pin", "HEAD")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse((self.tmp / "s.json").exists())


class PublishedFiguresAndEvaluationsBind(unittest.TestCase):
    """validate binds what the protocol publishes to the digests file, the pin to git, and each
    recorded evaluation to its report's bytes, commit and verify.py blob (#601)."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        tmp = Path(cls._tmp.name)
        cls.pin = heldout.resolve_pin(ROOT, "HEAD")
        _vet_set(tmp / "cases", cls.pin)
        cls.digests = tmp / "digests.json"
        cls.summary = tmp / "summary.json"
        r = _cli("digest", str(tmp / "cases"), "--canary", CANARY, "--out", str(cls.digests),
                 "--summary", str(cls.summary), "--pin", "HEAD")
        assert r.returncode == 0, r.stdout + r.stderr
        s = json.loads(cls.summary.read_text(encoding="utf-8"))
        cls.report = tmp / "report.json"
        # The shape a real held-out report has (#601, PR #665 review): the whole published set
        # selected, every case scored in every run by the built-in gates.
        run = {"false_acceptance": {"count": 0, "of": s["traps"]},
               "false_rejection": {"count": 0, "of": s["valid_controls"]}}
        cls.report_doc = {
            "schema": "vf-bench-replay@1", "protocol": {"split": "heldout", "selection": None},
            "revision": {"commit": cls.pin["commit"]},
            "versions": {"blobs": {"runtime/scripts/verify.py": cls.pin["verify_blob"]}},
            "corpus": {"total": s["cases"], "traps": s["traps"],
                       "valid_controls": s["valid_controls"], "selected": s["cases"]},
            "configurations": {
                "open-fleet verify.py (sound)": {"tier": "measured", "runs": [run, run]},
                "self-scoring (naive)": {"tier": "synthetic-baseline", "runs": [run, run]}},
            "heldout": {"set_sha256": s["set_sha256"]}, "verdict": {"ok": True}}
        cls.report.write_text(json.dumps(cls.report_doc), encoding="utf-8")
        today = s["authored_to"][:10]
        doc = _protocol()
        doc["splits"]["heldout"].update(
            published_digests=str(cls.digests),
            **{k: s[k] for k in ("set_sha256", "cases", "traps", "valid_controls", "by_category",
                                 "authored_from", "authored_to")})
        doc["temporal"]["pinned_verifier"] = dict(cls.pin)
        doc["evaluations"] = [{
            "version": doc["splits"]["heldout"]["version"], "date": today,
            "revision": cls.pin["commit"], "verify_blob": cls.pin["verify_blob"],
            "report": str(cls.report),
            "report_sha256": heldout.sha256(cls.report.read_bytes()), "complete": True}]
        for m in doc["release_dates"]["milestones"]:
            if m["id"] in ("digests-published", "evaluated"):
                m.update(status="done", date=today, evidence="this test's synthetic set")
        cls.doc = doc

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _errors(self, mutate=None):
        doc = json.loads(json.dumps(self.doc))
        if mutate:
            mutate(doc)
        return heldout.validate(doc)

    def test_a_consistent_record_is_valid(self):
        self.assertEqual(self._errors(), [])

    def test_each_broken_binding_is_named(self):
        def held(d):
            return d["splits"]["heldout"]

        def ev(d):
            return d["evaluations"][0]
        cases = {
            "another set digest": (lambda d: held(d).update(set_sha256="0" * 64), "set_sha256"),
            "another case count": (lambda d: held(d).update(cases=99), "heldout cases is 99"),
            "categories that do not sum": (
                lambda d: held(d)["by_category"]["check_commands"].update(traps=5), "does not sum"),
            "no valid control": (lambda d: held(d).update(valid_controls=0, traps=3),
                                 "no valid control"),
            "authored before the pin": (
                lambda d: held(d).update(authored_from="2020-01-01T00:00:00Z"), "temporal rule"),
            "a pin git does not record": (
                lambda d: d["temporal"]["pinned_verifier"].update(verify_blob="1" * 40),
                "not what git records"),
            "published with no holder": (
                lambda d: d["holder"].update(assigned=None, state="unfilled"), "no holder is assigned"),
            "a report edited after the run": (
                lambda d: ev(d).update(report_sha256="0" * 64), "does not hash"),
            "a revision git does not hold": (lambda d: ev(d).update(revision="2" * 40),
                                             "git does not hold"),
            "another verify.py blob": (lambda d: ev(d).update(verify_blob="3" * 40),
                                       "not the pinned"),
            "a completeness the report denies": (lambda d: ev(d).update(complete=False),
                                                 "whose completeness is recorded"),
            "an evaluation with no published set": (
                lambda d: held(d).update(published_digests=None), "no held-out digests are published"),
            "an evaluated milestone on another date": (
                lambda d: next(m for m in d["release_dates"]["milestones"]
                               if m["id"] == "evaluated").update(date="2099-01-01"),
                "dated unlike every recorded evaluation"),
        }
        for label, (mutate, needle) in cases.items():
            with self.subTest(binding=label):
                errors = self._errors(mutate)
                self.assertTrue(any(needle in e for e in errors), errors)


class APartialRunIsNeverACompleteEvaluation(unittest.TestCase):
    """PR #665 review (P1, PRRT_kwDOTWxN9c6v2ijf): `replay.py run --heldout DIR --cases ID` checks
    every published digest but scores only the cases selected, and its report carries the whole
    set's digest, so a one-case run validated as a complete evaluation. A recorded evaluation is
    now the whole published set, selected in full and, when complete, scored in full by every
    built-in gate in every run, per split (#601)."""

    # The same consistent record, without rerunning that class's own tests.
    setUpClass = PublishedFiguresAndEvaluationsBind.__dict__["setUpClass"]
    tearDownClass = PublishedFiguresAndEvaluationsBind.__dict__["tearDownClass"]
    _errors = PublishedFiguresAndEvaluationsBind._errors

    def _errors_with_report(self, edit):
        report = json.loads(json.dumps(self.report_doc))
        edit(report)
        path = Path(self._tmp.name) / f"report-{self.id().rsplit('.', 1)[-1]}-{len(report)}.json"
        path.write_text(json.dumps(report), encoding="utf-8")

        def point(doc):
            doc["evaluations"][0].update(report=str(path),
                                         report_sha256=heldout.sha256(path.read_bytes()))
        return self._errors(point)

    def test_the_full_shaped_record_is_valid(self):
        self.assertEqual(self._errors_with_report(lambda r: None), [])

    def test_each_partial_run_is_named(self):
        sound = "open-fleet verify.py (sound)"

        def one_case(r):
            r["protocol"]["selection"] = ["hv1-001"]
            r["corpus"]["selected"] = 1
            for cfg in r["configurations"].values():
                cfg["runs"] = [{"false_acceptance": {"count": 0, "of": 1},
                                "false_rejection": {"count": 0, "of": 0}}] * 2

        def short_scored(r):
            r["configurations"][sound]["runs"][1] = {
                "false_acceptance": {"count": 0, "of": 1}, "false_rejection": {"count": 0, "of": 1}}

        def other_split(r):
            r["corpus"].update(traps=r["corpus"]["traps"] + 1,
                               valid_controls=r["corpus"]["valid_controls"] - 1)
            for cfg in r["configurations"].values():
                for run in cfg["runs"]:
                    run["false_acceptance"]["of"] += 1
                    run["false_rejection"]["of"] -= 1

        partial = {
            "a --cases subset run": (one_case, "is a subset run"),
            "a run that scored fewer cases than it selected": (short_scored, "scored 1 trap(s)"),
            "a report of another split": (other_split, "the published split is"),
            "a complete report with no measured verifier": (
                lambda r: r["configurations"].pop(sound), "no measured verifier"),
            "a report with no case counts": (lambda r: r.pop("corpus"), "selected"),
        }
        for label, (edit, needle) in partial.items():
            with self.subTest(report=label):
                errors = self._errors_with_report(edit)
                self.assertTrue(any(needle in e for e in errors), errors)

    def test_the_recorded_v1_evaluation_still_binds(self):
        self.assertEqual(heldout.validate(_protocol()), [])


# A pinned bench whose fixture builders are not the checkout's (PR #665 review): one builder this
# checkout's vfbench.py lacks, and none of the ones it has.
PINNED_VFBENCH = """import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def _render(obj, facts):
    if isinstance(obj, str):
        for key, value in facts.items():
            obj = obj.replace("{{" + key + "}}", str(value))
        return obj
    if isinstance(obj, list):
        return [_render(x, facts) for x in obj]
    if isinstance(obj, dict):
        return {k: _render(v, facts) for k, v in obj.items()}
    return obj


def _build(repo):
    repo.mkdir(parents=True)
    (repo / "contract.md").write_text("- AC-1: x\\n", encoding="utf-8")
    return {"contract_digest": "sha256:" + hashlib.sha256(b"- AC-1: x\\n").hexdigest(),
            "pinned_fact": "only the pinned builder supplies this"}


FIXTURES = {"pinned-only": _build}


def fixture_command(trap, facts, repo, holder):
    (repo / "vf-manifest.json").write_text(json.dumps(_render(trap["manifest"], facts)),
                                           encoding="utf-8")
    return ["true"], {}
"""
PINNED_README = """# pinned bench

## Verifier check inventory

| Check | Guard | Status | Corpus case, or why not |
|---|---|---|---|
| `check_a` | refuses a. Sites: `a refused`. | trap | `planted` |
"""


class TheVetJudgesAgainstThePinnedRevision(unittest.TestCase):
    """PR #665 review (P2, PRRT_kwDOTWxN9c6v2ZCr): `vet --pin` read the pinned README but built
    fixtures with the CHECKOUT's vfbench.py, and compared against the checkout's development
    corpus, so it could pass a case the pinned replay cannot run, or refuse one it can. The
    builders, the corpus and every repository path a case names now come from the pin (#601)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vfbench-heldout-test-")
        self.tmp = Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        bench = self.repo / "bench" / "vf-bench"
        (bench / "traps").mkdir(parents=True)
        (self.repo / "runtime" / "scripts").mkdir(parents=True)
        (self.repo / "runtime" / "scripts" / "verify.py").write_text("# a stand-in\n",
                                                                    encoding="utf-8")
        (bench / "vfbench.py").write_text(PINNED_VFBENCH, encoding="utf-8")
        (bench / "README.md").write_text(PINNED_README, encoding="utf-8")
        (bench / "traps" / "pinned-trap.json").write_text(json.dumps(self._move()), encoding="utf-8")
        _git(self.repo, "init", "-q", "-b", "main")
        _git(self.repo, "add", "-A")
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.name=vf", "-c",
                        "user.email=vf@vf.invalid", "-c", "commit.gpgsign=false", "commit", "-qm",
                        "the pin", "--no-verify"], check=True, capture_output=True,
                       env={**__import__("os").environ, "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
                            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"})
        self.pin = heldout.resolve_pin(self.repo, "HEAD")
        # After the pin, the checkout's working tree moves on: what it holds now is not the pin.
        (bench / "fixtures").mkdir()
        (bench / "fixtures" / "added-later.md").write_text("- AC-1: x\n", encoding="utf-8")
        (bench / "traps" / "pinned-trap.json").unlink()
        self.cases = self.tmp / "cases"
        self.cases.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _move(**extra):
        return {"sound_expected": "RED", "expect_reason": "a refused",
                "fixture": "pinned-only", "manifest": {"note": "{{pinned_fact}}"}, **extra}

    def _case(self, n, **extra):
        now = heldout.datetime.now(heldout.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        case = {"id": f"hv1-{n:03d}", "class": "check_a", "inventory_site": "planted",
                "canary": CANARY, "authored_at": now,
                "verifier_pin": {"commit": self.pin["commit"],
                                 "verify_blob": self.pin["verify_blob"]},
                **self._move(manifest={"note": "{{pinned_fact}}", "n": n}), **extra}
        case = {k: v for k, v in case.items() if v is not None}
        (self.cases / f"hv1-{n:03d}.json").write_text(json.dumps(case), encoding="utf-8")

    def _problems(self):
        problems, _ = heldout.vet_cases(self.cases, self.pin, self.repo)
        return problems

    def test_a_builder_only_the_pin_has_builds_and_renders(self):
        self._case(1)
        self.assertEqual(self._problems(), [])

    def test_a_builder_only_the_checkout_has_is_refused(self):
        self._case(1, fixture="mutation-revert")
        self.assertTrue(any("no run-time builder" in p for p in self._problems()))

    def test_a_copy_of_a_trap_the_pin_holds_is_refused(self):
        # Deleted from the checkout after the pin; still the pinned development corpus.
        case = {"id": "hv1-001", "class": "check_a", "inventory_site": "planted",
                "canary": CANARY, "verifier_pin": {"commit": self.pin["commit"],
                                                   "verify_blob": self.pin["verify_blob"]},
                "authored_at": heldout.datetime.now(heldout.timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"), **self._move()}
        (self.cases / "hv1-001.json").write_text(json.dumps(case), encoding="utf-8")
        self.assertTrue(any("a copy of a development case" in p for p in self._problems()))

    def test_a_static_contract_the_pin_lacks_is_refused(self):
        self._case(1, fixture=None, contract_source="bench/vf-bench/fixtures/added-later.md",
                   manifest={"n": 1})
        self.assertTrue(any("contract_source is not a file" in p for p in self._problems()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
