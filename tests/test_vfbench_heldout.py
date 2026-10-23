#!/usr/bin/env python3
"""Contract tests for VF-Bench's held-out protocol and leakage check (#601).

The protocol file is predeclared and versioned: its development pins must equal gate.py's and
the corpus's, its dates must say they are planned, and the holder role it records must be filled
by a person or left unfilled — never a placeholder name. The leakage check is exercised against a
SYNTHETIC holder made at test time in a temp dir: held-out cases are generated, digested and
planted into throwaway repositories, and nothing held-out ever touches this checkout.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
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
CANARY = "6c1d2e3f-4a5b-4c6d-8e7f-a0b1c2d3e601"


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
