# Silent-skip gate audit — 2026-10-14

Dated snapshot: findings describe the tree as audited on 2026-10-14; re-derive
before citing after that date.

The rule, imported from Agent Baseline's own repo tooling: **a gate that reports
success when it did not run is worse than no gate.** Every CI workflow, gate script,
and validator check in this repo was swept for the shapes that produce a green
result without the check having run. Outcome first: the sweep found **two** real
silent skips, both in `scripts/validate.py`, both fixed in the same change that
lands this record. Everything else audited was already honest — several gates
encode this exact rule in so many words (`scripts/shard-tests.py`'s coverage check
calls an empty shard "a CI job that runs zero tests and passes").

## Fixed

| Gate | Silent skip | Fix |
|---|---|---|
| `check_doc_counts` | A file listed in `COUNT_LINT_FILES` that no longer exists was `continue`d past — deleting a linted surface silently removed it from the lint | Missing listed surface is now a failure ("restore it or remove it from the list deliberately") |
| `check_ledger_rows` | Returned `[]` (pass) when `skills/` was absent | Returns a failure naming that the check did not run. The CLI path already exited 2 earlier; importers no longer get a free pass |

Both pinned by `TestGatesDoNotSilentlySkip` in `tests/test_architecture.py`.

## Audited and already honest

- **CI workflows**: no `continue-on-error` anywhere. The three `if: always()`
  steps are a summary publisher that echoes FAILED lines while a separate step
  gates (`validate.yml`), a teardown that asserts nothing is left behind
  (`fixture-target-app.yml`), and a health summary that still tests the verdict
  (`main-health.yml`). The one `|| true` is inside a grep normalizer where empty
  output is the legitimate result.
- **Shard selection** (`scripts/shard-tests.py`): `check()` errors on an empty
  shard, a doubled module, an unsharded module, and a sharded-but-deleted one;
  unknown modules take a fallback weight so coverage never degrades.
- **floor_guard / bind_check** on an unresolvable base: exit 2 with the reason
  (probed). Without `--base`, floor_guard compares against HEAD — its documented
  default, not a skip.
- **Validator siblings**: `check_pin_version_claims` and `check_manifest_keywords`
  fail on unreadable inputs. `check_proof_ratchet` skips unparseable missions in
  its denominator, but the per-mission validation in `main()` fails on those same
  files — covered, noted, left as is.
- **Test suite skips**: every `SkipTest`/`skipIf` carries a reason and unittest
  reports skip counts in the job output — visible, not silent. All 60 test files
  carry `unittest.main`; no import-guard suppresses a test module.
- **The `verdict` check's SKIPPED state** is the designed "no verdict yet" signal
  and renders as its own check status, not a pass.
- **negative-control workflow**: checks `PIPESTATUS` explicitly and diffs against
  pinned output; a dead demo fails rather than drifting.
- **deny-hook / verify-gate polarity**: unparseable payloads deny/exit 2
  (pre-existing, test-pinned).

## Not covered by this audit

Whether a gate's *logic* is right (only whether it ran), and gates that run
outside CI (operator-wired hooks — see #562's arming check for the spawn side).
