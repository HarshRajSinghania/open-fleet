#!/usr/bin/env python3
"""Provenance retention receipts, bound OFFLINE to the signed inventory (#608).

`provenance.retention` names a Rekor-style transparency-log receipt committed beside a run's
signed run-close inventory. Before #608 verify.py checked only that the string was non-empty.
`check_retention_receipt` now binds it whenever the binding is CLAIMED — by the manifest
(`provenance.retention_receipt`) or by the coordinator (`--retention-pubkey`) — and only ever
against the trust key the coordinator supplies, never a key the receipt carries.

What is pinned here:
  - the v1 receipt shape, its canonical signed payload and the `inventory.py receipt` signer;
  - every refusal: missing, unreadable and path-escaping evidence, no or unreadable trust
    material, the wrong key or signer, a self-declared key, a signature mismatch, a tampered
    digest, replays against another inventory, unit, revision or run, an altered or unsigned
    inventory, and an inventory that does not pin this manifest — each a negative test;
  - GuardDeletion: for each of those refusals the guard(s) that refuse it are deleted from a copy
    of the verifier, and the case must then PASS while a valid receipt stays green — so every
    negative test is RED with its check removed, and no check is decorative;
  - compatibility: unclaimed provenance is untouched, and the committed known-key fixture under
    tests/fixtures/retention-receipt/ verifies with every socket call refused.

The keys are fixed test seeds (the pattern tests/test_inventory.py uses), never a coordinator's.
Ed25519 here is the vendored pure-Python reference (~0.2 s per operation), so scenario builders
cache the deterministic signatures they make; the verifier under test is never cached.
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "runtime" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "retention-receipt"
_SEQ = itertools.count()


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


verify = _load("verify_608", SCRIPTS / "verify.py")
inventory = _load("inventory_608", SCRIPTS / "inventory.py")
run_report = _load("run_report_608", SCRIPTS / "run_report.py")
dispatch_sign = _load("dispatch_sign_608", SCRIPTS / "dispatch-sign.py")
ED = dispatch_sign._load_ed25519()

TRUSTED_SEED = bytes(range(1, 33))
OTHER_SEED = bytes(range(100, 132))
SCHEMA = inventory.RECEIPT_SCHEMA
UNIT = "r15-receipt-unit"
HEAD_SHA = "6080" * 10
TRUSTED = "keys/trusted.pub"
OTHER = "keys/other.pub"
_PUBS, _SIGS = {}, {}


def pub(seed):
    if seed not in _PUBS:
        _PUBS[seed] = ED.publickey(seed)
    return _PUBS[seed]


def sign(seed, payload):
    """A cached Ed25519 signature (deterministic, so the cache changes no bytes)."""
    if (seed, payload) not in _SIGS:
        _SIGS[(seed, payload)] = base64.b64encode(ED.signature(payload, seed, pub(seed))).decode()
    return _SIGS[(seed, payload)]


def receipt_envelope(seed, record):
    """inventory.receipt_envelope's exact output, with the signature cached (parity is pinned)."""
    signed = {k: record[k] for k in inventory.RECEIPT_FIELDS if record.get(k) is not None}
    return {"record": signed, "sig_b64": sign(seed, inventory.receipt_payload(record))}


def signature_line(seed, entries):
    """inventory.signature_line's exact output, with the signature cached (parity is pinned)."""
    record = inventory.signature_record(entries)
    sig = sign(seed, dispatch_sign.canonical_record(record, inventory.SIGNED_FIELDS))
    env = {"record": record, "sig_b64": sig}
    return f"<!-- {inventory.SIGNATURE_TAG} {json.dumps(env, separators=(', ', ': '))} -->"


def entries_of(lines):
    return [e for start, end in inventory.find_blocks(lines)
            for e in inventory.parse_entries(lines, start, end)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextlib.contextmanager
def no_network():
    """Every way this process could open a connection raises: the check must not need one."""
    def refuse(*_a, **_k):
        raise AssertionError("network access attempted during an offline receipt check")
    with mock.patch.object(socket.socket, "connect", refuse), \
            mock.patch.object(socket, "create_connection", refuse), \
            mock.patch.object(socket, "getaddrinfo", refuse):
        yield


class ReceiptCase(unittest.TestCase):
    """A hermetic repo holding one run: run/manifest.json (claiming the binding), run/evidence.txt,
    run/report.md (an inventory pinning both, signed by the trusted key) and the receipt
    run/retention-receipt.json. `outside/` is a sibling of the repo — beyond the evidence root."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        base = Path(self._td.name).resolve()
        self.repo, self.outside = base / "repo", base / "outside"
        self.repo.mkdir()
        self.outside.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.repo, check=True)
        self._cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(self._leave)
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)
        self.write(TRUSTED, pub(TRUSTED_SEED).hex() + "\n")
        self.write(OTHER, pub(OTHER_SEED).hex() + "\n")
        self.build()

    def _leave(self):
        os.chdir(self._cwd)
        self._td.cleanup()

    def write(self, rel, data):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return rel

    def manifest(self, rel="run/manifest.json", retention="run/retention-receipt.json",
                 claim=SCHEMA, unit=UNIT, head=HEAD_SHA, **extra):
        prov = {"standard": "EU-AI-Act-Art-12", "spec_version": "contract.md@fixture",
                "model": "fixture-model", "reviewer": "fixture-reviewer", "retention": retention}
        if claim is not None:
            prov["retention_receipt"] = claim
        return self.write(rel, json.dumps({"unit": unit, "head_sha": head, "provenance": prov,
                                           **extra}, indent=2) + "\n")

    def report(self, rel="run/report.md", pins=("run/manifest.json", "run/evidence.txt"),
               seed=TRUSTED_SEED):
        lines = ["# Run close", "", "## Run-close integrity inventory (sha256)", "", "```"]
        lines += [f"{sha(self.repo / p)}  {p}" for p in pins] + ["```"]
        if seed is not None:
            lines = inventory._place_signature(lines, signature_line(seed, entries_of(lines)))
        return self.write(rel, "\n".join(lines) + "\n")

    def digest_of(self, rel):
        return inventory.inventory_digest(entries_of((self.repo / rel).read_text().splitlines()))

    def receipt(self, rel="run/retention-receipt.json", seed=TRUSTED_SEED,
                inventory_rel="run/report.md", after=None, **over):
        record = {"schema": SCHEMA, "unit": UNIT, "source_revision": HEAD_SHA,
                  "inventory": inventory_rel, "log_index": 7, "entry_uuid": "ab" * 32,
                  "signer": inventory.signer_id(pub(seed))}
        record["inventory_sha256"] = (over.pop("inventory_sha256") if "inventory_sha256" in over
                                      else self.digest_of(inventory_rel))
        record.update(over)
        env = receipt_envelope(seed, record)
        if after is not None:
            after(env)
        return self.write(rel, json.dumps(env, indent=2) + "\n")

    def build(self, retention="run/retention-receipt.json", **manifest_over):
        """The complete, valid chain: manifest → evidence → signed inventory → signed receipt."""
        for stale in ("run", "other"):
            shutil.rmtree(self.repo / stale, ignore_errors=True)
        for child in self.outside.iterdir():
            child.unlink()
        self.write("run/evidence.txt", "evidence\n")
        self.manifest(retention=retention, **manifest_over)
        self.report()
        self.receipt(rel=retention)

    def check(self, key=TRUSTED, mod=None):
        mod = mod or verify
        m, err = mod.load_manifest("run/manifest.json")
        self.assertIsNone(err)
        return mod.check_retention_receipt(m, key)

    def assertRefused(self, out, *needles):
        fatal = [line for line in out if not line.startswith("NOTE:")]
        self.assertEqual(len(fatal), 1, out)
        for needle in needles:
            self.assertIn(needle, fatal[0])

    def assertBound(self, out):
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("NOTE:"), out)

    # --- scenarios: each turns the valid chain into ONE defect and returns the key to verify with.

    def s_missing_receipt(self):
        (self.repo / "run/retention-receipt.json").unlink()
        return TRUSTED

    def s_receipt_is_a_directory(self):
        (self.repo / "run/retention-receipt.json").unlink()
        (self.repo / "run/retention-receipt.json").mkdir()
        return TRUSTED

    def s_receipt_not_json(self):
        self.write("run/retention-receipt.json", "log index 7, trust me\n")
        return TRUSTED

    def s_receipt_outside_the_repo(self):
        self.build(retention="../outside/retention-receipt.json")  # a GENUINE receipt, out of bounds
        return TRUSTED

    def s_receipt_symlinked_outside(self):
        moved = self.outside / "retention-receipt.json"
        os.replace(self.repo / "run/retention-receipt.json", moved)
        os.symlink(moved, self.repo / "run/retention-receipt.json")
        return TRUSTED

    def s_receipt_absolute_path(self):
        self.build(retention=str(self.outside / "retention-receipt.json"))
        return TRUSTED

    def s_inventory_outside_the_repo(self):
        self.report(rel="../outside/report.md")
        self.receipt(inventory_rel="../outside/report.md")
        return TRUSTED

    def s_inventory_missing(self):
        self.receipt(inventory_rel="run/absent.md", inventory_sha256="00" * 32)
        return TRUSTED

    def s_claim_without_key(self):
        return None

    def s_claim_names_v2(self):
        self.build(claim="open-fleet/retention-receipt/v2")
        return TRUSTED

    def s_receipt_record_v2(self):
        self.receipt(schema="open-fleet/retention-receipt/v2")
        return TRUSTED

    def s_wrong_key(self):
        self.receipt(seed=OTHER_SEED)  # self-consistent: signed by, and naming, the other key
        return TRUSTED

    def s_names_another_signer(self):
        self.receipt(signer=inventory.signer_id(pub(OTHER_SEED)))  # the TRUSTED key signed this
        return TRUSTED

    def s_self_declared_key(self):
        def declare(env):
            env["record"]["public_key"] = pub(OTHER_SEED).hex()
        self.receipt(seed=OTHER_SEED, after=declare)
        return TRUSTED

    def s_field_edited_after_signing(self):
        def edit(env):
            env["record"]["log_index"] = 8
        self.receipt(after=edit)
        return TRUSTED

    def s_malformed_signature(self):
        def garble(env):
            env["sig_b64"] = "not-base64!"
        self.receipt(after=garble)
        return TRUSTED

    def _second_inventory(self):
        """Another inventory the trusted key really signed, pinning this same manifest."""
        self.write("run/evidence-y.txt", "other evidence\n")
        return self.report(rel="run/report-y.md", pins=("run/manifest.json", "run/evidence-y.txt"))

    def s_digest_retargeted_after_signing(self):
        other = self._second_inventory()
        digest = self.digest_of(other)

        def retarget(env):
            env["record"].update(inventory=other, inventory_sha256=digest)
        self.receipt(after=retarget)
        return TRUSTED

    def s_digest_garbled_after_signing(self):
        def garble(env):
            env["record"]["inventory_sha256"] = "00" * 32
        self.receipt(after=garble)
        return TRUSTED

    def s_replay_against_another_inventory(self):
        other = self._second_inventory()
        self.receipt(inventory_rel=other, inventory_sha256=self.digest_of("run/report.md"))
        return TRUSTED

    def s_inventory_altered_after_signing(self):
        path = self.repo / "run/report.md"
        changed = hashlib.sha256(b"rewritten evidence\n").hexdigest()
        path.write_text(path.read_text().replace(sha(self.repo / "run/evidence.txt"), changed))
        return TRUSTED

    def s_inventory_unsigned(self):
        self.report(seed=None)
        self.receipt()
        return TRUSTED

    def s_inventory_signed_by_another_key(self):
        self.report(seed=OTHER_SEED)
        self.receipt()
        return TRUSTED

    def s_replay_from_another_unit(self):
        self.receipt(unit="another-unit")
        return TRUSTED

    def s_replay_at_another_revision(self):
        self.receipt(source_revision="b" * 40)
        return TRUSTED

    def s_replay_of_another_runs_chain(self):
        """Another run's complete, genuine chain; this manifest points its retention at it."""
        self.write("other/evidence.txt", "another run\n")
        self.manifest(rel="other/manifest.json", unit="another-unit", head="c" * 40,
                      retention="other/retention-receipt.json")
        self.report(rel="other/report.md", pins=("other/manifest.json", "other/evidence.txt"))
        self.receipt(rel="other/retention-receipt.json", inventory_rel="other/report.md",
                     unit="another-unit", source_revision="c" * 40)
        self.manifest(retention="other/retention-receipt.json")
        return TRUSTED

    def s_manifest_edited_after_close(self):
        self.manifest(note="rewritten after the inventory was signed")  # same unit and head_sha
        return TRUSTED

    def s_manifest_bytes_pinned_under_another_path(self):
        """W3-04: a genuine, signed inventory that pins this manifest's exact BYTES — but as a
        copy at another path. Digest equality alone bound it; the path story is wrong."""
        self.write("run/copy-of-manifest.json", (self.repo / "run/manifest.json").read_bytes())
        self.report(pins=("run/copy-of-manifest.json", "run/evidence.txt"))
        self.receipt()
        return TRUSTED


class Accepted(ReceiptCase):
    """A complete, valid receipt binds — offline — and the verdict says what was not verified."""

    def test_a_valid_receipt_binds_with_every_socket_refused(self):
        with no_network():
            out = self.check()
        self.assertBound(out)
        for phrase in ("verified OFFLINE", f"binding unit '{UNIT}'", "pin this manifest's bytes",
                       "NOT verified", "exists or is included in any transparency log",
                       "retention period", "legal or regulatory determination"):
            self.assertIn(phrase, out[0])
        # W3-04: an auditor can see WHICH entry the receipt claims to cover.
        self.assertIn("as its entry run/manifest.json", out[0])

    def test_the_coordinator_key_alone_claims_the_binding(self):
        # The run-close lifecycle: a graded manifest is final before its inventory is signed and
        # the receipt exists, so it names the receipt's path without the claim marker; the audit
        # re-run supplies the key, and that alone makes the binding required.
        self.build(claim=None)
        self.assertBound(self.check())

    def test_the_trust_key_can_be_read_at_a_ref_the_worker_cannot_move(self):
        subprocess.run(["git", "add", TRUSTED], check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pin"],
                       check=True)
        self.write(TRUSTED, pub(OTHER_SEED).hex() + "\n")  # the working-tree copy is swapped
        self.assertRefused(self.check(TRUSTED), "wrong key")
        self.assertBound(self.check(f"{TRUSTED}@HEAD"))

    def test_a_tree_id_prefixed_entry_uuid_is_v1(self):
        self.receipt(entry_uuid="cd" * 40)
        self.assertBound(self.check())

    def test_the_cached_builders_are_the_real_signers(self):
        lines = (self.repo / "run/report.md").read_text().splitlines()
        entries = entries_of(lines)
        self.assertEqual(signature_line(TRUSTED_SEED, entries),
                         inventory.signature_line(TRUSTED_SEED, entries))
        record = json.loads((self.repo / "run/retention-receipt.json").read_text())["record"]
        self.assertEqual(receipt_envelope(TRUSTED_SEED, record),
                         inventory.receipt_envelope(TRUSTED_SEED, record))

    def test_the_payload_is_the_canonical_form_of_exactly_the_v1_fields(self):
        record = json.loads((self.repo / "run/retention-receipt.json").read_text())["record"]
        payload = inventory.receipt_payload({**record, "ignored": "not signed"})
        self.assertEqual(payload, json.dumps({k: record[k] for k in inventory.RECEIPT_FIELDS},
                                             sort_keys=True, separators=(",", ":")).encode())
        self.assertEqual(json.loads(payload)["schema"], SCHEMA)


class Rejections(ReceiptCase):
    """Each claimed defect is refused, and for the reason the check exists to name."""

    def refused(self, scenario, *needles):
        key = getattr(self, scenario)()
        self.assertRefused(self.check(key), *needles)

    # missing / unreadable / escaping evidence
    def test_a_missing_receipt_is_refused(self):
        self.refused("s_missing_receipt", "is missing", "fails closed")

    def test_an_unreadable_receipt_is_refused(self):
        self.refused("s_receipt_is_a_directory", "is unreadable")

    def test_a_receipt_that_is_not_json_is_refused(self):
        self.refused("s_receipt_not_json", "unreadable as a", "not readable JSON")

    def test_a_receipt_path_escaping_the_repo_is_refused(self):
        self.refused("s_receipt_outside_the_repo", "escapes")

    def test_a_receipt_symlinked_out_of_the_repo_is_refused(self):
        self.refused("s_receipt_symlinked_outside", "escapes")

    def test_an_absolute_receipt_path_is_refused(self):
        self.refused("s_receipt_absolute_path", "absolute evidence path refused")

    def test_a_receipt_path_at_a_ref_is_refused(self):
        self.build(retention="run/retention-receipt.json@HEAD")
        self.assertRefused(self.check(), "not a path@ref")

    def test_an_inventory_outside_the_repo_is_refused(self):
        self.refused("s_inventory_outside_the_repo", "inventory document", "escapes")

    def test_a_missing_inventory_is_refused(self):
        self.refused("s_inventory_missing", "inventory document", "is missing")

    def test_an_inventory_that_is_not_utf8_text_is_refused(self):
        self.write("run/binary.md", b"\xff\xfe not an inventory\n")
        self.receipt(inventory_rel="run/binary.md", inventory_sha256="00" * 32)
        self.assertRefused(self.check(), "run/binary.md is not UTF-8 text", "fail-closed")

    def test_a_verifier_without_inventory_py_fails_closed(self):
        # inventory.py owns the receipt and inventory forms; a verifier that cannot load it has
        # nothing to check a claim against, and must not read that as nothing claimed.
        scripts = Path(tempfile.mkdtemp(dir=self._td.name))
        for name in verify._Transcript.TOOLCHAIN:
            if name != "inventory.py":
                shutil.copy2(SCRIPTS / name, scripts / name)
        lone = _load(f"verify_608_no_inventory_{next(_SEQ)}", scripts / "verify.py")
        self.assertRefused(self.check(mod=lone), "which owns the receipt and inventory forms",
                           "fail-closed")

    # trust material
    def test_a_claim_with_no_trust_material_is_refused(self):
        self.refused("s_claim_without_key", "no trust material was supplied",
                     "a key inside a receipt never establishes trust")

    def test_an_unreadable_or_malformed_trust_key_is_refused(self):
        self.write("keys/bad.pub", "zz-not-hex\n")
        self.write("keys/short.pub", "ab" * 16 + "\n")
        for key in ("keys/absent.pub", "keys/bad.pub", "keys/short.pub", "../outside/k.pub"):
            with self.subTest(key=key):
                self.assertRefused(self.check(key), "not a 32-byte Ed25519 public key")

    def test_a_claim_naming_another_receipt_version_is_refused(self):
        self.refused("s_claim_names_v2", "binds 'open-fleet/retention-receipt/v1' only")

    def test_a_v2_receipt_record_is_refused(self):
        self.refused("s_receipt_record_v2", "v1 receipts only")

    # identity and signature
    def test_a_receipt_signed_by_another_key_is_refused(self):
        self.refused("s_wrong_key", "wrong key")

    def test_the_wrong_supplied_key_refuses_a_genuine_receipt(self):
        self.assertRefused(self.check(OTHER), "wrong key")

    def test_a_receipt_naming_another_signer_is_refused(self):
        self.refused("s_names_another_signer", "names signer", "wrong key")

    def test_a_self_declared_key_establishes_no_trust(self):
        self.refused("s_self_declared_key", "['public_key']",
                     "a key inside a receipt never establishes trust")

    def test_a_self_declared_key_beside_the_record_establishes_no_trust(self):
        def declare(env):
            env["pubkey"] = pub(OTHER_SEED).hex()
        self.receipt(seed=OTHER_SEED, after=declare)
        self.assertRefused(self.check(), "['pubkey']", "never establishes trust")

    def test_a_field_edited_after_signing_is_a_signature_mismatch(self):
        self.refused("s_field_edited_after_signing", "signature mismatch")

    def test_a_malformed_signature_is_a_signature_mismatch(self):
        self.refused("s_malformed_signature", "signature mismatch", "malformed")

    # digest and inventory binding
    def test_a_digest_retargeted_after_signing_is_refused(self):
        self.refused("s_digest_retargeted_after_signing", "signature mismatch")

    def test_a_garbled_digest_is_refused(self):
        self.refused("s_digest_garbled_after_signing", "signature mismatch")

    def test_a_replay_against_another_inventory_is_refused(self):
        self.refused("s_replay_against_another_inventory", "another inventory (replay)")

    def test_an_inventory_altered_after_signing_is_refused(self):
        self.refused("s_inventory_altered_after_signing", "inventory's own signature does not hold",
                     "added, dropped or changed after signing")

    def test_an_unsigned_inventory_binds_nothing(self):
        self.refused("s_inventory_unsigned", "carries no inventory-signature")

    def test_an_inventory_signed_by_another_key_is_refused(self):
        self.refused("s_inventory_signed_by_another_key", "inventory's own signature does not hold")

    # replay across runs
    def test_a_receipt_for_another_unit_is_refused(self):
        self.refused("s_replay_from_another_unit", "another run's receipt (replay)")

    def test_a_receipt_for_another_revision_is_refused(self):
        self.refused("s_replay_at_another_revision", "another revision (replay)")

    def test_another_runs_complete_chain_is_refused(self):
        self.refused("s_replay_of_another_runs_chain", "another run's receipt (replay)")

    def test_a_manifest_edited_after_close_is_refused(self):
        self.refused("s_manifest_edited_after_close", "does not pin this manifest's exact bytes")

    def test_the_manifests_bytes_pinned_under_another_path_are_refused(self):
        self.refused("s_manifest_bytes_pinned_under_another_path",
                     "run/copy-of-manifest.json", "not under this manifest's own path", "W3-04")

    # the v1 shape
    def test_every_off_shape_record_is_refused(self):
        def drop(field):
            return lambda env: env["record"].pop(field)
        cases = {
            "log_index negative": dict(log_index=-1),
            "log_index a bool": dict(log_index=True),
            "log_index a string": dict(log_index="7"),
            "entry_uuid not hex": dict(entry_uuid="z" * 64),
            "entry_uuid short": dict(entry_uuid="ab" * 8),
            "source_revision short": dict(source_revision="abc123"),
            "unit empty": dict(unit=""),
            "signer not ed25519": dict(signer="rsa:" + "ab" * 32),
            "a field missing": dict(after=drop("entry_uuid")),
            "an unknown field": dict(after=lambda env: env["record"].update(note="extra")),
            "no signature": dict(after=lambda env: env.pop("sig_b64")),
        }
        for name, over in cases.items():
            with self.subTest(case=name):
                self.receipt(**over)
                self.assertRefused(self.check(), "unreadable as a")
        self.write("run/retention-receipt.json", "[]")
        self.assertRefused(self.check(), "not a {record, sig_b64} envelope")

    # the coordinator's key with nothing to bind
    def test_a_supplied_key_refuses_unbound_legacy_retention(self):
        self.manifest(claim=None, retention="P10Y")
        self.assertRefused(self.check(), "'P10Y' is missing")

    def test_a_supplied_key_refuses_a_manifest_naming_no_receipt(self):
        self.write("run/manifest.json", json.dumps({"unit": UNIT, "head_sha": HEAD_SHA}))
        self.assertRefused(self.check(), "no retention receipt path is named")


class SoundLaneTrustKey(ReceiptCase):
    """W3-03 (2026-10-27 security audit, P2): `--retention-pubkey keys/trusted.pub` (a bare path)
    is a file in the graded worker's tree. On a lane claiming soundness the trust key is read only
    at a commit id or a ref whose final target is remote-tracking (what the coordinator's fetch
    wrote); the advisory lane keeps the read and the NOTE says which."""

    def _pin(self):
        subprocess.run(["git", "add", TRUSTED], check=True)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "pin"],
                       check=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], check=True)

    def test_a_bare_path_trust_key_is_refused_on_a_lane_claiming_soundness(self):
        verify._Authority.lane = "provenance=ci"
        self.assertRefused(self.check(TRUSTED), "working-tree file", "W3-03")

    def test_a_trust_key_at_a_local_name_is_refused_on_a_lane_claiming_soundness(self):
        self._pin()
        verify._Authority.lane = "provenance=ci"
        self.assertRefused(self.check(f"{TRUSTED}@HEAD"), "local name the graded worker can move")

    def test_a_remote_tracking_trust_key_binds_and_the_note_names_it(self):
        self._pin()
        verify._Authority.lane = "provenance=ci"
        out = self.check(f"{TRUSTED}@refs/remotes/origin/main")
        self.assertBound(out)
        self.assertIn("remote-tracking ref refs/remotes/origin/main", out[0])

    def test_the_advisory_lane_reads_a_working_tree_key_and_says_so(self):
        out = self.check(TRUSTED)
        self.assertBound(out)
        self.assertIn(f"working-tree file {TRUSTED}", out[0])

    def test_a_remote_tracking_name_symbolic_to_a_local_branch_is_refused(self):
        # PR #719 review (P1): spelling-only — refs/remotes/<x> as a symbolic ref to a local branch
        # carrying another key was read as remote-tracking.
        self._pin()
        subprocess.run(["git", "branch", "local-key"], check=True)
        subprocess.run(["git", "symbolic-ref", "refs/remotes/worker/key", "refs/heads/local-key"],
                       check=True)
        verify._Authority.lane = "provenance=ci"
        self.assertRefused(self.check(f"{TRUSTED}@refs/remotes/worker/key"), "refs/heads/local-key")


class LegacyProvenance(ReceiptCase):
    """No claim from either side: the documented presence-only behaviour, byte for byte."""

    def test_unclaimed_provenance_without_a_key_is_untouched(self):
        self.build(claim=None, retention="P10Y")
        m, _ = verify.load_manifest("run/manifest.json")
        self.assertEqual(verify.check_retention_receipt(m, None), [])
        self.assertEqual(verify.check_provenance(m), [])

    def test_an_unclaimed_receipt_is_never_read(self):
        self.build(claim=None)
        self.write("run/retention-receipt.json", "garbage, and nobody asked")
        self.assertEqual(self.check(None), [])

    def test_no_provenance_at_all_is_untouched(self):
        self.assertEqual(verify.check_retention_receipt({"unit": UNIT}, None), [])
        self.assertEqual(verify.check_retention_receipt({"provenance": "P10Y"}, None), [])

    def test_the_vf_bench_presence_control_is_still_unclaimed(self):
        trap = json.loads((ROOT / "bench/vf-bench/traps/provenance-present-valid-control.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(verify.check_retention_receipt(trap["manifest"], None), [])


class KnownKeyFixture(unittest.TestCase):
    """The committed fixture: a manifest, the run-close inventory pinning it (signed), and its
    receipt — all made by TRUSTED_SEED — verifying offline from a plain checkout."""

    def setUp(self):
        self._cwd = os.getcwd()
        os.chdir(ROOT)
        self.addCleanup(os.chdir, self._cwd)
        verify._Authority.reset()
        self.addCleanup(verify._Authority.reset)

    def test_the_committed_receipt_verifies_offline(self):
        m, err = verify.load_manifest(str((FIXTURE / "manifest.json").relative_to(ROOT)))
        self.assertIsNone(err)
        with no_network():
            out = verify.check_retention_receipt(
                m, str((FIXTURE / "trusted.pub").relative_to(ROOT)))
        self.assertEqual(len(out), 1, out)
        self.assertTrue(out[0].startswith("NOTE:") and "verified OFFLINE" in out[0], out)

    def test_the_fixture_is_exactly_what_the_known_key_signs(self):
        self.assertEqual((FIXTURE / "trusted.pub").read_text().strip(), pub(TRUSTED_SEED).hex())
        lines = (FIXTURE / "report.md").read_text().splitlines()
        entries = entries_of(lines)
        self.assertIn(inventory.signature_line(TRUSTED_SEED, entries), lines)
        envelope = json.loads((FIXTURE / "retention-receipt.json").read_text())
        self.assertEqual(envelope, inventory.receipt_envelope(TRUSTED_SEED, envelope["record"]))
        self.assertEqual(envelope["record"]["inventory_sha256"], inventory.inventory_digest(entries))
        self.assertEqual(sorted(envelope["record"]), sorted(inventory.RECEIPT_FIELDS))


def _mutated_verifier(edits, dest):
    """A copy of the verifier's toolchain under `dest` with `edits` — (file, old, new) — applied.
    Each edit must match its file exactly once, so a refactor that moves a guard fails by name
    instead of silently mutating nothing (the tests/test_vfbench_guards.py rule)."""
    scripts = dest / "scripts"
    scripts.mkdir()
    for name in verify._Transcript.TOOLCHAIN:
        shutil.copy2(SCRIPTS / name, scripts / name)
    for name, old, new in edits:
        source = (scripts / name).read_text(encoding="utf-8")
        if source.count(old) != 1:
            raise AssertionError(f"guard recipe matches {name} {source.count(old)} times, not once "
                                 f"— the guard moved; update the recipe:\n{old}")
        (scripts / name).write_text(source.replace(old, new), encoding="utf-8")
    return _load(f"verify_608_mutant_{next(_SEQ)}", scripts / "verify.py")


# The guards, as exact text. A layered refusal (one defect refused at several sites) is deleted
# at EVERY site, or the next layer refuses the case and the control proves nothing.
READ_FAILS_CLOSED = [("verify.py",
                      '        return [f"{err}; the retention binding is claimed, so it fails closed (#608)"]\n',
                      "        return []\n")]
PARSE_FAILS_CLOSED = [("verify.py",
                       '        return [f"retention receipt {receipt} is unreadable as a v1 receipt ({inv.RECEIPT_SCHEMA}): "\n'
                       '                f"{why} (#608)"]\n',
                       "        return []\n")]
EVIDENCE_BOUND = [
    ("verify.py", '    if p.is_absolute():\n        return None, f"absolute evidence path refused',
     '    if False:\n        return None, f"absolute evidence path refused'),
    ("verify.py", '    if p.parts and p.parts[0] == "..":\n', "    if False:\n"),
    ("verify.py", "    if full != root and root not in full.parents:\n", "    if False:\n"),
]
NO_TRUST = [("verify.py", "    if not pubkey_ref:\n        return [f\"provenance claims the {claim}",
             "    if not pubkey_ref:\n        return []\n        return [f\"provenance claims the {claim}")]
CLAIM_VERSION = [("verify.py", "    if claim is not None and claim != inv.RECEIPT_SCHEMA:\n",
                  "    if False:\n")]
RECORD_VERSION = [("inventory.py", '    if record["schema"] != RECEIPT_SCHEMA:\n', "    if False:\n")]
IDENTITY = [("inventory.py", '    if record["signer"] != trusted:\n', "    if False:\n")]
SIGNATURE = [
    ("inventory.py", '        sig = decode_signature(envelope["sig_b64"])\n', '        sig = b""\n'),
    ("inventory.py",
     "    if not _dispatch_sign()._load_ed25519().checkvalid(sig, receipt_payload(record), pub):\n",
     "    if False:\n"),
]
# A verifier that trusts a key the receipt declares — the naive reading this issue forbids.
TRUSTS_DECLARED_KEY = [
    ("inventory.py", "        if keyish:\n", "        if False:\n"),
    ("inventory.py", "        if extra:\n", "        if False:\n"),
    ("inventory.py", '    record = envelope["record"]\n    trusted = signer_id(pub)\n',
     '    record = envelope["record"]\n'
     '    pub = bytes.fromhex(record.get("public_key", pub.hex()))\n'
     "    trusted = signer_id(pub)\n"),
]
UNIT_BINDING = [("inventory.py", '    if record["unit"] != unit:\n', "    if False:\n")]
REVISION_BINDING = [("inventory.py", '    if record["source_revision"] != source_revision:\n',
                     "    if False:\n")]
DIGEST_BINDING = [("inventory.py", '    if record["inventory_sha256"] != signed:\n', "    if False:\n")]
INVENTORY_SIGNATURE = [("inventory.py", "        verify_signature(envelope, entries, pub)\n",
                        "        signed = signed\n")]
# An unsigned inventory read as if its re-derived entries were the signed set.
UNSIGNED_INVENTORY = INVENTORY_SIGNATURE + [(
    "inventory.py",
    "    if envelope is None:\n        raise ReceiptRefused(",
    '    if envelope is None:\n        envelope = {"record": {"inventory_sha256": '
    "inventory_digest(entries)}}\n    if False:\n        raise ReceiptRefused(")]
MANIFEST_PIN = [("verify.py",
                 "    if mine is None or all(pinned != mine for _idx, _path, pinned, _shape in entries):\n",
                 "    if False:\n")]
MANIFEST_PATH = [("verify.py", "    if pinned_at and not named:\n", "    if False:\n")]
DOC_READ_FAILS_CLOSED = [("verify.py",
                          '        return [f"retention receipt {receipt}: {err}; fail-closed (#608)"]\n',
                          "        return []\n")]

GUARDS = (
    # (scenario, the reason the intact verifier gives, the guard(s) whose deletion admits it)
    ("s_missing_receipt", "is missing", READ_FAILS_CLOSED),
    ("s_receipt_is_a_directory", "is unreadable", READ_FAILS_CLOSED),
    ("s_receipt_not_json", "not readable JSON", PARSE_FAILS_CLOSED),
    ("s_receipt_outside_the_repo", "escapes", EVIDENCE_BOUND),
    ("s_receipt_symlinked_outside", "escapes", EVIDENCE_BOUND),
    ("s_receipt_absolute_path", "absolute evidence path refused", EVIDENCE_BOUND),
    ("s_inventory_outside_the_repo", "escapes", EVIDENCE_BOUND),
    ("s_inventory_missing", "is missing", DOC_READ_FAILS_CLOSED),
    ("s_claim_without_key", "no trust material", NO_TRUST),
    ("s_claim_names_v2", "binds 'open-fleet/retention-receipt/v1' only", CLAIM_VERSION),
    ("s_receipt_record_v2", "v1 receipts only", RECORD_VERSION),
    ("s_wrong_key", "wrong key", IDENTITY + SIGNATURE),
    ("s_names_another_signer", "names signer", IDENTITY),
    ("s_self_declared_key", "never establishes trust", TRUSTS_DECLARED_KEY),
    ("s_field_edited_after_signing", "signature mismatch", SIGNATURE),
    ("s_malformed_signature", "signature mismatch", SIGNATURE),
    ("s_digest_retargeted_after_signing", "signature mismatch", SIGNATURE),
    ("s_digest_garbled_after_signing", "signature mismatch", SIGNATURE + DIGEST_BINDING),
    ("s_replay_against_another_inventory", "another inventory (replay)", DIGEST_BINDING),
    ("s_inventory_altered_after_signing", "own signature does not hold", INVENTORY_SIGNATURE),
    ("s_inventory_unsigned", "carries no inventory-signature", UNSIGNED_INVENTORY),
    ("s_inventory_signed_by_another_key", "own signature does not hold", INVENTORY_SIGNATURE),
    ("s_replay_from_another_unit", "another run's receipt", UNIT_BINDING),
    ("s_replay_at_another_revision", "another revision", REVISION_BINDING),
    ("s_replay_of_another_runs_chain", "another run's receipt",
     UNIT_BINDING + REVISION_BINDING + MANIFEST_PIN),
    ("s_manifest_edited_after_close", "does not pin this manifest's exact bytes", MANIFEST_PIN),
    ("s_manifest_bytes_pinned_under_another_path", "not under this manifest's own path",
     MANIFEST_PATH),
)


class GuardDeletion(ReceiptCase):
    """Every refusal above is RED with its check removed. For each case: the intact verifier
    refuses it for its reason; a copy with that refusal's guard(s) deleted ACCEPTS it (nothing
    else catches the defect, so the guard is load-bearing); and the same copy still accepts a
    valid receipt (the deletion did not just break the verifier)."""

    def test_every_refusal_is_load_bearing(self):
        self.assertEqual(len({scenario for scenario, _n, _e in GUARDS}), len(GUARDS))
        mutants = {}  # one copy per distinct deletion, its valid control run once
        for scenario, needle, edits in GUARDS:
            with self.subTest(scenario=scenario):
                self.build()
                if tuple(edits) not in mutants:
                    mutant = _mutated_verifier(edits, Path(tempfile.mkdtemp(dir=self._td.name)))
                    self.assertBound(self.check(mod=mutant))
                    mutants[tuple(edits)] = mutant
                mutant = mutants[tuple(edits)]
                key = getattr(self, scenario)()
                self.assertRefused(self.check(key), needle)
                out = self.check(key, mod=mutant)
                self.assertFalse([line for line in out if not line.startswith("NOTE:")],
                                 f"{scenario}: still refused with its guard deleted — the guard "
                                 f"is not what refuses it: {out}")

    def test_every_refusal_scenario_is_in_the_table(self):
        scenarios = {name for name in dir(ReceiptCase) if name.startswith("s_")}
        self.assertEqual(sorted(scenarios - {s for s, _n, _e in GUARDS}), [])


class ReceiptSigner(ReceiptCase):
    """`inventory.py receipt`: the coordinator's offline record of an upload it already made."""

    def setUp(self):
        super().setUp()
        keys = Path(self._td.name).resolve() / "seeds"
        keys.mkdir()
        self.seed = keys / "coordinator"
        self.seed.write_text(TRUSTED_SEED.hex() + "\n", encoding="utf-8")
        self.seed.chmod(0o600)

    def run_receipt(self, *extra, report="run/report.md", out="run/retention-receipt.json"):
        argv = [sys.executable, str(SCRIPTS / "inventory.py"), "receipt", report,
                "--key", str(self.seed), "--unit", UNIT, "--source-revision", HEAD_SHA,
                "--log-index", "7", "--entry-uuid", "ab" * 32, *extra]
        if out is not None:
            argv += ["--out", out]
        return subprocess.run(argv, capture_output=True, text=True, cwd=self.repo)

    def test_the_signer_writes_a_receipt_the_verifier_binds(self):
        (self.repo / "run/retention-receipt.json").unlink()
        r = self.run_receipt()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertBound(self.check())
        written = json.loads((self.repo / "run/retention-receipt.json").read_text())
        self.assertEqual(written["record"]["inventory"], "run/report.md")
        self.assertEqual(written["record"]["signer"], inventory.signer_id(pub(TRUSTED_SEED)))

    def test_the_signer_refuses_an_unsigned_inventory(self):
        self.report(seed=None)
        r = self.run_receipt(out=None)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SIGNED inventory", r.stderr)

    def test_the_signer_refuses_an_inventory_another_key_signed(self):
        self.report(seed=OTHER_SEED)
        r = self.run_receipt(out=None)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("does not hold under this seed's key", r.stderr)

    def test_the_signer_refuses_an_inventory_that_no_longer_re_derives(self):
        self.write("run/evidence.txt", "changed since the inventory was written\n")
        r = self.run_receipt(out=None)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no longer re-derives", r.stderr)

    def test_the_signer_refuses_identifiers_outside_the_v1_shape(self):
        r = self.run_receipt("--entry-uuid", "not-a-uuid", out=None)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("entry_uuid", r.stderr)
        self.assertEqual(r.stdout, "")


class VerifierWiring(ReceiptCase):
    """--retention-pubkey reaches the check through main(), the verdict exits as it says, and the
    signed transcript names the trust key as part of the policy it ran under."""

    def setUp(self):
        super().setUp()
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@t"]
        self.write("README.md", "fixture\n")
        subprocess.run(["git", "add", "README.md"], check=True)
        subprocess.run([*git, "commit", "-qm", "base"], check=True)
        self.base_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                       text=True, check=True).stdout.strip()
        self.write("docs/notes.md", "a report-only unit's notes\n")
        subprocess.run(["git", "add", "docs/notes.md"], check=True)
        subprocess.run([*git, "commit", "-qm", "head"], check=True)
        self.head_sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                       text=True, check=True).stdout.strip()
        self.write("contract.json", json.dumps({"criterion_ids": ["AC-1"]}) + "\n")
        self.digest = "sha256:" + sha(self.repo / "contract.json")
        evidence = {"unit": UNIT, "base_sha": self.base_sha, "head_sha": self.head_sha,
                    "contract": {"digest": self.digest, "criterion_ids": ["AC-1"]},
                    "criteria": [{"id": "AC-1", "addressed": True}],
                    "provenance": {"standard": "EU-AI-Act-Art-12", "spec_version": "contract.json",
                                   "model": "fixture-model", "reviewer": "fixture-reviewer",
                                   "retention": "run/retention-receipt.json",
                                   "retention_receipt": SCHEMA}}
        self.write("run/manifest.json", json.dumps(evidence, indent=2) + "\n")
        self.report()
        self.receipt(source_revision=self.head_sha)

    def main(self, *extra):
        argv = ["--manifest", "run/manifest.json", "--contract-source", "contract.json",
                "--contract-digest", self.digest, "--unit-class", "report-only", *extra]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = verify.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_bound_receipt_passes_the_whole_verifier(self):
        code, out, err = self.main("--retention-pubkey", TRUSTED)
        self.assertEqual(code, 0, out + err)
        self.assertIn("verified OFFLINE", out)
        self.assertIn("verify: OK", out)

    def test_a_tampered_receipt_fails_the_whole_verifier(self):
        def edit(env):
            env["record"]["log_index"] = 9
        self.receipt(source_revision=self.head_sha, after=edit)
        code, out, err = self.main("--retention-pubkey", TRUSTED)
        self.assertEqual(code, 2, out + err)
        self.assertIn("signature mismatch", err)

    def test_a_claim_without_the_key_fails_the_whole_verifier(self):
        code, out, err = self.main()
        self.assertEqual(code, 2, out + err)
        self.assertIn("no trust material was supplied", err)

    def test_the_transcript_records_the_trust_key(self):
        code, out, err = self.main("--retention-pubkey", TRUSTED, "--transcript-out", "t.json")
        self.assertEqual(code, 0, out + err)
        record = json.loads((self.repo / "t.json").read_text())
        self.assertEqual(record["args"]["retention_pubkey"], TRUSTED)
        self.assertEqual(set(record["toolchain"]["files"]), set(verify._Transcript.TOOLCHAIN))

    def test_run_report_reads_the_same_argument_tuple_the_verifier_signs(self):
        self.assertEqual(set(verify._Transcript.ARGS), set(run_report.SIGNED_ARGS))
        self.assertIn("retention_pubkey", run_report.SIGNED_ARGS)


if __name__ == "__main__":
    unittest.main()
