# review-it — external run: a NO-GO verdict on stablyai/orca PR #28206 (2026-10-13)

`review-it` took a live pull request on a repository other than this catalog —
[stablyai/orca#28206](https://github.com/stablyai/orca/pull/28206), implementing issue #28164 —
and returned a read-only, SHA-bound **NO-GO** verdict at the reviewed head `6dcd957a`, from an
Ubuntu 24.04 witness VM driven by `orca-ide` 1.4.224 (the #527 Linux witness).

Bindable core: [`docs/runs/2026-10-13-review-it-linux.md`](../../runs/2026-10-13-review-it-linux.md)

`RUN: mission=review-it tier=external-run inventory_at=314d63feafff694ffc51df10c21e15da288fed83 manifest=docs/runs/2026-10-13-review-it-linux/manifest.json verifier=GREEN waves=1`

## The run in one page

- **Fixed point:** head `6dcd957a` and merge-base `cbeb5371`, pinned from two routes (GitHub
  API and a VM clone) before dispatch and re-checked unchanged at the verdict.
- **Shape:** four read-only workers (`PROFILE=ro`), one per axis — standards, spec, test
  adequacy (matt pack) — plus the security lens (addy pack), which the diff scope gated in.
  Other lenses were gated off with recorded reasons.
- **Verdict:** NO-GO — 0 Critical, 2 Required (security lens: the submodule Force Delete copy
  and ordering hide superproject data loss). Retained, not posted to the PR; the target
  checkout was clean at close.
- **Verification:** `verify.py` OK against the frozen contract and a coordinator-signed
  dispatch record (`--unit-class report-only`), recorded through `evidence-run.py`.
- **Filed** at `doctrine-only` as #527 substrate evidence; the `external-run` tier was claimed
  on 2026-10-14 after `run_report.py` bound it unchanged at that tier (see the core report's
  *Tier amendment*).

## Negative control

A report-only unit's negative-control analogue is SOURCE-BINDING (`runtime/evidence-manifest.md`
§3): every quoted line must exist at the reviewed head. The coordinator re-read all 14 distinct
quoted lines at `6dcd957a` — 14/14 verbatim — and reproduced the Required pair's git precedence
empirically (dirty superproject + initialized submodule → only the submodule refusal, exit 128).
Transcript: [`negctrl.txt`](negctrl.txt), a verbatim copy of the inventory-pinned
`docs/runs/2026-10-13-review-it-linux/quote-check.txt`.

## Runner credit

Runner: Ravindra Kumar (@ravidsrk) · independent.
Bindable core: `docs/runs/2026-10-13-review-it-linux.md`.
