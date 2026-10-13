# Axis: TEST ADEQUACY (static) — stablyai/orca PR #28206 @ 6dcd957a65

## 1. Blind-fix expectation (written before the diff)
Issue #28164: non-force `git worktree remove` fails with "working trees containing submodules cannot be moved or removed". Expected fix: a branch in `classifyWorktreeForceDeleteReason` (`src/shared/worktree/removal.ts`) matching that message, a new force reason, and toast copy so the UI offers Force Delete. Alternative (issue's other suggestion): automatic `--force` retry after the dirty check. Confidence ~65% classifier+toast, ~35% auto-retry.

## 2. Claims vs. guarding tests (static judgment; nothing run or reverted)
| Claim | Test | Verdict |
|---|---|---|
| C1 classifier returns `'submodules'` | `removal-force-classification.test.ts:75` "offers force for the refusal Git gives a checkout with submodules"; `worktree-removal-real-git.test.ts:132` | Guarded: revert of removal.ts:146-148 yields null, both fail |
| C2 not re-offered once forced | `removal-force-classification.test.ts:78` | Weak: `if (force) return null` sits above the new branch, passes on revert |
| C3 toast shows submodule copy, non-destructive | `delete-worktree-toast.test.ts:149` | Guarded: revert falls to generic raw-error copy (`isDestructive: true`) |
| C4 real Git emits the matched string | `worktree-removal-real-git.test.ts:132` | Guarded (real binary) |
| C5 force then removes | `worktree-removal-real-git.test.ts:101` second half | Unguarded by diff: force already worked pre-PR |
| C6 en.json key | none (`translate()` falls back to inline default) | Unguarded |
| C7 other locales (es/fr/ja/ko/zh) | none | Unguarded; diff touches only en.json; any i18n parity gate not checked |

## 3. Findings
- **Nit** `src/shared/worktree/removal-force-classification.test.ts:78` — `  it('does not re-offer force once the removal was already forced', () => {` — passes with or without the production change; not evidence for the claim.
- **Optional** `src/shared/worktree/removal.ts:146` — `  if (error.includes('working trees containing submodules cannot be moved or removed')) {` — no test for precedence versus the `orphan-directory`/`missing-registration`/`dirty` branches; reordering would still pass.
- **Optional** `src/main/git/worktree-removal-real-git.test.ts:101` — `  it('offers force for a clean checkout with initialized submodules, which force then removes', async () => {` — validates wording only for the host Git; Git messages can be localized and the 2.25 baseline is not exercised. The matcher is English-only.
- **FYI** `src/shared/worktree/removal.ts:146` — same line — error text passes through SSH/relay unchanged, but no test covers a remote-originated error.
- **FYI** `src/renderer/src/store/slices/worktrees/teardown/remove-worktree.ts` (caller of the classifier) — the ordinary desktop delete passes `force:true`, which the classifier's `if (force)` guard maps to null. No test drives the real caller, so whether the offer actually surfaces in the UI is not test-verified. (Caller file located by grep; line not quoted.)

## 4. Appendix (cannot quote a line)
- C7: no non-English locale additions exist in the diff.
- The issue's auto-retry-with-`--force` suggestion is not implemented, so it has no test; not a test gap.
