#!/usr/bin/env python3
"""Contract tests for VF-Bench's held-out protocol and leakage check (#601).

The protocol file is predeclared and versioned: its development pins must equal gate.py's and
the corpus's, its dates must say they are planned, and the holder role it records must be filled
by a person or left unfilled — never a placeholder name. The leakage check is exercised against a
SYNTHETIC holder made at test time in a temp dir: held-out cases are generated, digested and
planted into throwaway repositories, and nothing held-out ever touches this checkout.
"""
import base64
import gzip
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

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
        self.assertIn("holder UNFILLED", r.stdout)

    def test_the_development_split_is_the_shipped_corpus(self):
        dev = _protocol()["splits"]["development"]
        self.assertEqual(dev["corpus_sha256"], gate.EXPECTED_CORPUS_SHA256)
        self.assertEqual(dev["corpus_sha256"], gate.corpus_digest())
        self.assertEqual(dev["version"], gate.EXPECTED_VERSION)
        self.assertEqual(dev["canary_guid"], gate.EXPECTED_CANARY_GUID)
        self.assertEqual(dev["location"], "bench/vf-bench/traps/*.json")

    def test_held_out_content_is_declared_uncommitted_and_unpublished(self):
        held = _protocol()["splits"]["heldout"]
        self.assertIs(held["committed"], False)
        self.assertIsNone(held["published_digests"])
        self.assertIsNone(held["cases"])

    def test_the_holder_is_an_unfilled_role_not_a_name(self):
        holder = _protocol()["holder"]
        self.assertIsNone(holder["assigned"])
        self.assertEqual(holder["state"], "unfilled")
        self.assertTrue(holder["role"])

    def test_every_date_is_labelled_planned(self):
        dates = _protocol()["release_dates"]
        self.assertIn("PLANNED", dates["label"])
        self.assertTrue(dates["milestones"])
        self.assertTrue(all(m["status"] == "planned" for m in dates["milestones"]))

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
                lambda d: d["release_dates"]["milestones"][0].update(status="done"), "without evidence"),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
