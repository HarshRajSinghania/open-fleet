#!/usr/bin/env python3
"""Guard-deletion mutation controls for VF-Bench's isolated invariant traps (#600).

A trap that goes RED proves the gate refused it. It does not prove WHICH guard refused it, nor
that the guard is the only thing between the trap and a GREEN — a trap that seven unrelated legs
refuse moves no score when the leg it names is deleted, which is how the bench's early skeletal
traps measured nothing (#369). So for every corpus case that declares the refusal it exists to
earn (`expect_reason`), this module deletes the ONE verify.py guard the trap names, in a
throwaway copy of the verifier's own toolchain, and requires:

  - the trap now PASSES — the guard was load-bearing, nothing else catches the planted defect;
  - its declared `neighbour`, a valid control on the same fixture, still PASSES — the deletion
    did not just break the verifier, and the control never leaned on that guard to be green.

The other half — with the guard in place the trap is RED for its declared reason and the
neighbour GREEN — is the bench run itself (bench/vf-bench/gate.py; tests/test_vfbench.py).
Each recipe is an exact-text edit that must match verify.py exactly once, so a refactor that
moves a guard fails here by name instead of silently mutating nothing.

A pair the bench cannot score on THIS host (vfbench.skip_reason: a pinned commit a shallow clone
lacks, or no system-custody git for a signed-dispatch case) is not run at all. It fails under the
host's cause instead, so it never reads as a guard that does not isolate its trap (PR #643 review).
"""
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"
_spec = importlib.util.spec_from_file_location("vfbench_guards", ROOT / "bench" / "vf-bench" / "vfbench.py")
vfbench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vfbench)

# A layered guard (one invariant refused at several sites) is deleted at EVERY site, or the next
# layer refuses the trap and the control proves nothing about the layer under test.
PR_NUMBER = [
    ("    if not (type(number) is int and number > 0):\n",
     "    if False:\n"),
    ("    if not (type(pr_number) is int and pr_number > 0):  # a path segment, never a path (P3)\n",
     "    if False:  # a path segment, never a path (P3)\n"),
    ("    if _Authority.gh is None or not (type(pr_number) is int and pr_number > 0):\n",
     "    if _Authority.gh is None:\n"),
]

GUARDS = {
    # check_lighting: legality, then the dispatch swap.
    "lighting-illegal-1": [
        ("    if not (isinstance(lighting, str) and lighting in LIGHTING_VALUES):\n",
         "    if False:\n")],
    "lighting-swap-1": [
        ("    if dispatch_lighting is not None and lighting != dispatch_lighting:\n",
         "    if False:\n")],
    # check_intent / check_reviewer_mode / check_provenance: presence and legality.
    "empty-intent-1": [
        ('    return [f"intent packet incomplete — non-empty {missing} required (mutation unit)"] '
         'if missing else []\n',
         "    return []\n")],
    "reviewer-mode-illegal-1": [
        ("    if not (isinstance(mode, str) and mode in REVIEWER_MODES):\n",
         "    if False:\n")],
    "provenance-incomplete-1": [
        ('            "(EU AI Act Art-12/50 record incomplete)"] if missing else []\n',
         '            "(EU AI Act Art-12/50 record incomplete)"] if False else []\n')],
    # check_review: the pr.number shape (layered) and review_ok's three independence rules.
    "pr-number-path-1": PR_NUMBER,
    "pr-number-bool-1": PR_NUMBER,
    "pr-number-negative-1": PR_NUMBER,
    "author-as-approver-1": [
        ("    independent = [r for who, r in latest.items() if author is None or who != author]\n",
         "    independent = list(latest.values())\n")],
    "non-member-approver-1": [
        ('               and r.get("author_association") in _Authority.INDEPENDENT_REVIEWER_ASSOCIATIONS\n',
         "")],
    "dismissed-approval-1": [
        # "Latest state per reviewer governs" deleted: every review at the relevant commits counts.
        ("    latest = {}\n"
         "    for r in reviews or []:\n"
         '        if r.get("commit_id") in relevant:\n'
         '            latest[(r.get("user") or {}).get("login")] = r\n'
         "    independent = [r for who, r in latest.items() if author is None or who != author]\n",
         "    latest = []\n"
         "    for r in reviews or []:\n"
         '        if r.get("commit_id") in relevant:\n'
         '            latest.append(((r.get("user") or {}).get("login"), r))\n'
         "    independent = [r for who, r in latest if author is None or who != author]\n")],
    # Evidence reads (#267): the containment bound, the pin, and redaction's unreadable artifact.
    "nc-artifact-symlink-escape-1": [
        ("    if full != root and root not in full.parents:\n",
         "    if False:\n")],
    "unpinned-artifact-1": [
        ("    want = artifact_inventory(m).get(path)\n    if not want:\n",
         "    want = artifact_inventory(m).get(path)\n    if not want:\n        return raw, None\n"
         "    if False:\n")],
    "missing-artifact-path-1": [
        ('            errs.append(f"redaction: artifact {path} unreadable: {err}")\n',
         "            continue\n")],
    # check_negative_control's corroboration of the pinned mutant's fate.
    "surviving-mutant-1": [
        ('        errs.append("negative_control.artifact reports the pinned mutant SURVIVED / was not '
         'killed")\n',
         "        errs.extend(())\n")],
    "zero-kill-artifact-1": [
        ("    if _NC_ZERO_KILL_RE.search(content):\n",
         "    if False:\n")],
    # check_scope: the coordinator's denominator against the manifest's claims about it.
    "criterion-unaddressed-1": [
        ("    unaddressed = sorted(authoritative - addressed)\n",
         "    unaddressed = []\n")],
    "criterion-ids-shrunk-1": [
        ("    undeclared = sorted(authoritative - declared)\n",
         "    undeclared = []\n")],
    "manifest-digest-swap-1": [
        ("    if mdigest and _norm_digest(mdigest) != want:\n",
         "    if False:\n")],
    # check_freshness: a review of other content.
    "stale-reviewed-sha-1": [
        ("    if reviewed and reviewed != head and not _wtree_bound(m):\n",
         "    if False:\n")],
    # check_scope: the hidden-criterion refusals (#296), text and JSON.
    "hidden-criterion-table-1": [
        ("        hidden = hidden_criterion_ids(text, authoritative)\n",
         "        hidden = {}\n")],
    "hidden-criterion-json-1": [
        ("        undeclared = sorted(listed - authoritative)\n",
         "        undeclared = []\n")],
    # check_oracle_scope: hand-only, production-free, and the authorized bytes.
    "oracle-scope-revert-1": [
        ('    if nc.get("tool") != "hand" or err:\n',
         "    if err:\n")],
    "oracle-scope-production-1": [
        ("    if any(_is_test_path(p) is not True and Path(p).suffix.lower() not in _PROSE_SUFFIXES\n"
         "           for p in prod + tests):\n",
         "    if False:\n")],
    "oracle-scope-artifact-swap-1": [
        ('    if hashlib.sha256(content).hexdigest() != scope.get("artifact_sha256"):\n',
         "    if False:\n")],
    # check_dispatch_provenance: signature, identity, substitution (#135).
    "dispatch-profile-tamper-1": [
        ("    if not ed.checkvalid(sig, _canonical_dispatch(record), pub):\n",
         "    if False:\n")],
    "dispatch-replay-1": [
        ("    if not signed_id or not manifest_id or signed_id != manifest_id:\n",
         "    if False:\n")],
    "dispatch-class-substitution-1": [
        ("        if signed != used:\n"
         '            return [f"dispatch substitution: the run used {field}={used!r} but the '
         'coordinator signed "\n',
         "        if False:\n"
         '            return [f"dispatch substitution: the run used {field}={used!r} but the '
         'coordinator signed "\n')],
}


def _corpus():
    return {t["id"]: t for t in (json.loads(p.read_text(encoding="utf-8"))
                                 for p in (ROOT / "bench" / "vf-bench" / "traps").glob("*.json"))}


def _mutated_verifier(edits, dest):
    """A copy of the verifier's toolchain under `dest` with `edits` applied to verify.py. The
    siblings verify.py loads by path come along, so the copy runs exactly as the original does."""
    scripts = dest / "scripts"
    scripts.mkdir()
    for name in vfbench._runtime_module("verify.py")._Transcript.TOOLCHAIN:
        shutil.copy2(SCRIPTS / name, scripts / name)
    source = (scripts / "verify.py").read_text(encoding="utf-8")
    for old, new in edits:
        if source.count(old) != 1:
            raise AssertionError(f"guard recipe matches verify.py {source.count(old)} times, not "
                                 f"once — the guard moved; update the recipe:\n{old}")
        source = source.replace(old, new)
    (scripts / "verify.py").write_text(source, encoding="utf-8")
    return scripts / "verify.py"


def _host_cause(trap, neighbour):
    """Why THIS HOST cannot measure the pair, or None (PR #643 review).

    The guard-deletion run builds the bench's own command (vfbench.fixture_command), so a case the
    bench declines to score here — skip_reason() names it, and the CI gate fails on that — would
    be refused for the host's sake whatever guard was deleted, and read as a trap that does not
    isolate its guard. The pair is therefore not run, and fails under the host's name. It is never
    skipped: an unmeasured control is not a passed one, and an unexpected skip is not green."""
    for case in (trap, neighbour):
        reason = vfbench.skip_reason(case)
        if reason:
            return (f"HOST, not a verifier regression: {case['id']} cannot run on this host "
                    f"({reason}). The guard-deletion control for {trap['id']} is UNMEASURED here, "
                    "not passed; run it where VF-Bench scores the case (CI does).")
    return None


class EveryIsolatedTrapHasAGuardDeletionControl(unittest.TestCase):
    def test_the_recipes_cover_exactly_the_reasoned_traps(self):
        reasoned = {i for i, t in _corpus().items() if t.get("expect_reason")}
        self.assertEqual(sorted(reasoned - set(GUARDS)), [],
                         "a trap declares its refusal but no control deletes the guard behind it")
        self.assertEqual(sorted(set(GUARDS) - reasoned), [], "a recipe names no reasoned trap")

    def test_each_recipe_matches_one_site(self):
        source = (SCRIPTS / "verify.py").read_text(encoding="utf-8")
        for trap_id, edits in GUARDS.items():
            for old, new in edits:
                with self.subTest(trap=trap_id, site=old.strip()[:60]):
                    self.assertEqual(source.count(old), 1)
                    self.assertNotEqual(old, new)

    def test_each_neighbour_is_a_green_control_on_the_same_fixture(self):
        corpus = _corpus()
        for trap_id in GUARDS:
            with self.subTest(trap=trap_id):
                trap = corpus[trap_id]
                control = corpus[trap["neighbour"]]
                self.assertEqual(trap["sound_expected"], "RED")
                self.assertEqual(control["sound_expected"], "GREEN")
                self.assertEqual(control["fixture"], trap["fixture"])
                self.assertEqual(bool(control.get("execute_nc")), bool(trap.get("execute_nc")))


class DeletingTheGuardAdmitsItsTrap(unittest.TestCase):
    def test_deleting_each_guard_admits_its_trap_and_spares_its_neighbour(self):
        corpus = _corpus()
        for trap_id, edits in GUARDS.items():
            with self.subTest(trap=trap_id):
                trap = corpus[trap_id]
                host = _host_cause(trap, corpus[trap["neighbour"]])
                if host:  # fails this subtest by the host's name; the loop moves on
                    self.fail(host)
                with tempfile.TemporaryDirectory(prefix="vfbench-guard-") as tmp:
                    mutant = _mutated_verifier(edits, Path(tmp))
                    trap_detail, control_detail = {}, {}
                    admitted = vfbench.fixture_gate(trap, trap_detail, verify=mutant)
                    spared = vfbench.fixture_gate(corpus[trap["neighbour"]], control_detail,
                                                  verify=mutant)
                self.assertTrue(admitted, f"with its guard deleted {trap_id} is STILL refused — "
                                f"another leg catches it, so it does not isolate its guard: "
                                f"{trap_detail.get('fails')}")
                self.assertTrue(spared, f"deleting {trap_id}'s guard broke its neighbour "
                                f"{trap['neighbour']}: {control_detail.get('fails')}")


class AHostThatCannotRunAPairFailsUnderItsOwnName(unittest.TestCase):
    """PR #643 review: on a host with no system-custody git, the signed-dispatch pairs ran on the
    host's git and verify.py refused them for the HOST (h409 R2) whatever guard was deleted, so
    each failed as "STILL refused — another leg catches it": a verifier regression that was not
    one. Simulated through the seam skip_reason() itself consults (_system_git_dir), with the
    fixture runner recording instead of running: the dispatch pairs must fail BEFORE any fixture
    runs, each under the host's cause, and an ordinary pair beside them must run untouched."""

    def test_a_host_without_system_git_fails_the_dispatch_pairs_by_the_host_cause(self):
        corpus = _corpus()
        dispatch = sorted(i for i in GUARDS if corpus[i].get("dispatch"))
        self.assertEqual(len(dispatch), 3, "the signed-dispatch traps this pin is about")
        ordinary = next(i for i in sorted(GUARDS) if not corpus[i].get("dispatch"))
        ran = []

        def recording_gate(case, detail=None, verify=None):
            ran.append(case["id"])
            return True

        result = unittest.TestResult()
        with mock.patch.object(vfbench, "_system_git_dir", return_value=None), \
                mock.patch.object(vfbench, "fixture_gate", side_effect=recording_gate), \
                mock.patch.dict(GUARDS, {i: GUARDS[i] for i in dispatch + [ordinary]}, clear=True):
            DeletingTheGuardAdmitsItsTrap(
                "test_deleting_each_guard_admits_its_trap_and_spares_its_neighbour").run(result)

        failed = {sub.params["trap"]: text for sub, text in result.failures}
        self.assertEqual(result.errors, [])
        self.assertEqual(sorted(failed), dispatch, "only the pairs this host cannot run may fail")
        for trap_id, text in failed.items():
            with self.subTest(trap=trap_id):
                self.assertIn("HOST, not a verifier regression", text)
                self.assertIn("no system-custody git", text)
                self.assertIn("UNMEASURED", text)
                self.assertNotIn("STILL refused", text)
        self.assertEqual(ran, [ordinary, corpus[ordinary]["neighbour"]],
                         "a pair the host cannot run reached the fixture runner, or the "
                         "ordinary pair did not")
        self.assertEqual(len(result.skipped), 0, "a host cause is a named failure, never a skip")


if __name__ == "__main__":
    unittest.main(verbosity=2)
