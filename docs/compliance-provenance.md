# Compliance provenance — supporting evidence for AI-system changes

The [evidence manifest](../runtime/evidence-manifest.md) records change scope, revisions,
commands and review references. Its optional `provenance` block adds context for an audit;
these are supporting records, not a regulatory conformance guarantee. The verifier checks
that required provenance strings are present when a standard is named. It does not validate
their truth or establish that the operating AI system meets that standard. The one exception is
the retention anchor: when its binding is claimed, the verifier checks the retention receipt
offline against a signed inventory and a key the coordinator supplies
([below](#retention-receipt-v1--what-the-offline-check-proves-608)).

## Applicability checked 2026-09-12

Determine the system's scope, operator role, risk category and exceptions before selecting
obligations. Under Article 113(c), Chapter III Sections 1–3 (except Article 6(5)) apply from
**2 December 2027** for Article 6(2)/Annex III systems and **2 August 2028** for Article 6(1)/Annex I
systems. Articles 12 and 26 fall within those sections; Article 111 adds existing-system
transitions. [Consolidated AI Act, Articles 111 and 113](https://eur-lex.europa.eu/eli/reg/2024/1689/2026-07-27/eng).

Article 50 generally applies from **2 August 2026**, with obligation-specific exceptions.
Article 111(4) gives providers of covered synthetic-content systems placed on the market before
that date until **2 December 2026** to comply with Article 50(2).
[Consolidated AI Act](https://eur-lex.europa.eu/eli/reg/2024/1689/2026-07-27/eng);
[Commission applicability FAQ](https://digital-strategy.ec.europa.eu/en/faqs/navigating-ai-act).

## What the manifest can support

| Change evidence | Field | Limit |
|---|---|---|
| Revision and recorded checks | `base_sha`, `head_sha`, `commands[]`, artifact hashes | Hashes bind retained bytes; the coordinator still owns clean-environment reruns |
| Frozen acceptance scope | `contract.source`, `contract.digest`, `criteria[]` | Scope completeness needs comparison with the authoritative contract |
| Governing policy and implementing model | `provenance.spec_version`, `provenance.model` | Declared context; a model name does not characterize the deployed AI system |
| Review attribution | `provenance.reviewer`, `pr.reviewed_sha`, `reviewer_mode` | Review identity and SHA require independent verification |
| Retention anchor | `provenance.retention` — the path, committed beside the run-close inventory, of a Rekor-style transparency-log RECEIPT (v1 below): `log_index`, `entry_uuid`, the signed inventory's digest (`inventory.py sign`'s `inventory_sha256`), the unit and source revision, all signed by the coordinator's key | Uploading is an OPTIONAL coordinator-side step recorded with an `egress.py` receipt — never a gate dependency, and no gate script makes a network call for it. Unclaimed, `retention` is checked for presence only, as before. Claimed, `verify.py` checks the receipt OFFLINE against a key the coordinator supplies and proves that this key bound the log entry's identifiers to exactly these inventory bytes, this unit and this revision. Not proven: that the log entry exists, is reachable, or is trustworthy — that needs a live lookup of `entry_uuid` the maintainer runs out of band. A receipt provides no storage, retention enforcement or access controls |
| Intended assessment | `provenance.standard` | Naming `EU-AI-Act-Art-12`, `SOC2` or `SSDF` does not establish conformance |

## Retention receipt v1 — what the offline check proves (#608)

**Shape.** The receipt is a JSON `{record, sig_b64}` envelope, the one used by the signed dispatch
record, the verifier transcript and the inventory signature. Its `record` has exactly these
fields, and a v1 verifier refuses a missing or extra field, so nothing can ride along unsigned:

| Field | Value |
|---|---|
| `schema` | `open-fleet/retention-receipt/v1` — the version, signed, so a v2 record cannot pass as v1 |
| `unit`, `source_revision` | the graded manifest's `unit` and `head_sha` (a full commit id) |
| `inventory` | the repo-relative document whose run-close inventory the receipt binds |
| `inventory_sha256` | that inventory's signed digest — the `inventory_sha256` its `inventory-signature` signs |
| `log_index`, `entry_uuid` | what the transparency log returned (64 hex, or 80 with a tree-id prefix) |
| `signer` | `ed25519:` + the sha256 of the signing public key |

**Signed payload.** The Ed25519 signature covers `dispatch-sign.py`'s canonical form of those eight
fields: sorted keys, no whitespace, every field signed (`inventory.py`'s `receipt_payload`).

**Produce it** after the optional upload, with the coordinator's seed, from the signed report:
`inventory.py receipt <report> --key <seed> --unit <unit> --source-revision <head_sha>
--log-index <n> --entry-uuid <uuid> --out <path named by provenance.retention>`. The signer
refuses an unsigned inventory, one signed by another key, and one that no longer re-derives from
disk. It makes no network call: it records identifiers the upload already returned.

**When the binding is claimed.** The manifest claims it with
`"retention_receipt": "open-fleet/retention-receipt/v1"` in `provenance`, or the coordinator
claims it by passing `verify.py --retention-pubkey <key>` — normally
`.orca/dispatch-pubkey@refs/remotes/origin/main`, the FULL remote-tracking name (a short
`origin/main` is a local name a tag or branch can shadow, and a lane claiming soundness refuses
it), followed through any symbolic ref and read at the one commit it resolves to. That ref is
trustworthy only where the worker cannot write refs — the coordinator's own fetch or a CI
checkout; in a worker's own clone `git update-ref refs/remotes/…` succeeds, so there the check is
advisory ([the verify gate](verify-gate.md#signed-dispatch--what-it-binds-and-where-the-key-comes-from-135)).
A run's graded manifest is
final before its inventory is signed and before the receipt exists, so the usual path is the
second one: the manifest names the receipt's path, and the post-close audit re-run supplies the
key.

| Manifest claim | `--retention-pubkey` | Result |
|---|---|---|
| none | none | Presence only, exactly as before #608: the receipt is never read |
| `retention_receipt` set | none | Refused: a key inside a receipt never establishes trust, and no other key was supplied |
| either | supplied | `retention` must name a v1 receipt that passes every check below |

**What the check verifies.** It runs offline and needs no network. It refuses the receipt unless
every link holds:

1. The receipt path, and the inventory path inside it, are repo-relative and stay inside the
   evidence root, like all evidence (#267). A missing, unreadable or non-v1 receipt is refused.
2. `signer` is the supplied key's identity, and the signature verifies under that key. A key
   declared inside the receipt is refused and is never used.
3. `unit` and `source_revision` equal the manifest's `unit` and `head_sha`. This refuses a receipt
   replayed from another run or revision.
4. The named document carries an `inventory-signature` that verifies under the same key over
   exactly its entries. An unsigned inventory, or one altered after signing, is refused.
5. The receipt's `inventory_sha256` is that signed digest. This refuses a receipt replayed
   against another inventory.
6. That inventory pins this manifest's exact bytes. This refuses a manifest edited after close.
7. It pins them **under this manifest's own path**: the matching entry must resolve (repo root
   first, then the inventory's directory, as `inventory.py check` resolves it) to the file the
   verifier read. A byte-copy at another path is refused (2026-10-27 audit, W3-04).

The verdict NOTE names the signer, the unit, the revision, the digest that were bound, the
inventory entry that pinned the manifest, and where the trust key was read (W3-03).

**What it does not verify.** Each of these needs separate evidence, and the NOTE says so:

- **Log inclusion.** The check does not show that the log entry exists, is included in any log,
  or that the log is trustworthy. That needs a live lookup of `entry_uuid` the maintainer runs out
  of band.
- **Retention.** The check does not show retention for any period, or any storage or access
  control.
- **The inventoried files.** The check does not re-hash them. `inventory.py check` and
  `run_report.py` do that.
- **Legal compliance.** The check makes no legal or regulatory determination.

## Obligations for the operating AI system need separate evidence

| Scoped obligation | Evidence the change manifest does not supply |
|---|---|
| Article 12: automatic lifetime event logging for high-risk systems | Runtime logging capability and operational records |
| Article 26(6): deployers retain controlled system logs appropriately, at least six months unless applicable law provides otherwise | Actual retained logs and retention enforcement |
| Article 50(2): providers mark covered synthetic outputs in machine-readable form | Output marking and detectability checks; `claim` and `provenance.model` do not mark outputs |
| Article 50(1), (3)–(5): applicable interaction/content disclosures | Recipient-facing disclosures at interaction or exposure, subject to the specified exceptions |

These obligations concern the operating system and its outputs, independently of build records.
[Consolidated AI Act, Articles 12, 26 and 50](https://eur-lex.europa.eu/eli/reg/2024/1689/2026-07-27/eng).
A full [attest-it](missions/attest-it.md) run must freeze the applicable obligations and obtain
separate evidence for each; missing capability or evidence remains an explicit gap. This mapping
is an engineering evidence aid, not an assessment of a particular deployment's legal compliance.
