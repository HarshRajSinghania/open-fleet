# Axis: SPEC COMPLIANCE — PR #28206 vs issue #28164 (head 6dcd957a65)

## 1. Blind expectation (written from the issue before opening the diff)
Fix lives in the force-delete classifier (`src/shared/worktree/removal.ts`) plus delete-failure toast copy; shape: recognise git's "working trees containing submodules cannot be moved or removed" and offer Force Delete (or auto-retry `--force` after a dirty check). Confidence ~70%.

## 2. Verdict
The diff meets the issue's "Expected" section via its "or offers a force delete option" branch. No scope creep. The two gaps below are non-blocking.

## 3. Criteria
| Criterion (issue line) | Status |
|---|---|
| "Orca detects submodules (or this specific error)" | implemented |
| "retries with `--force` after its own dirty-check, or offers a 'force delete' option in the UI" | implemented (UI branch; auto-retry deliberately declined) |
| "so the workspace can never be deleted from the UI (repeated attempts fail the same way)" | implemented: toast now carries Force Delete, which uses the existing forced path |
| "`git submodule deinit -f --all` alone is not enough … `.git/worktrees/<name>/modules`" | n/a (informational); `--force` covers it |

## 4. Findings
1. **FYI** `src/shared/worktree/removal.ts:146` — `if (error.includes('working trees containing submodules cannot be moved or removed')) {`
   Detects the exact error the issue quotes (criterion "Orca detects … this specific error"). English-only match, so a localized git silently falls back to today's behavior (PR acknowledges this).
2. **FYI** `src/renderer/src/components/sidebar/delete-worktree-toast.ts:101` — `if (forceDeleteReason === 'submodules') {`
   Returns `isDestructive: false` with a description naming unpushed submodule commits. Satisfies "offers a 'force delete' option in the UI". Declining the auto-retry is a valid reading of the issue's "or", and is justified in the PR (clean `git status` can hide unpushed submodule commits).
3. **Nit** `src/renderer/src/i18n/locales/en.json:6169` — `"submodules": "Git only removes a workspace with initialized submodules when forced. Force Delete also deletes the submodule checkouts, including commits in them that were never pushed."`
   Key exists only in en.json. es/fr/ja/ko/zh were not updated (they all contain `unstoppedPtyLive`, so the sibling keys are translated there). Spec does not require translations, but non-English users get English fallback copy, assuming the repo's fallback works (not verified here).
4. **FYI** `src/shared/worktree/removal.ts:19` — `  | 'submodules'`
   Scope: the diff is 6 files, all on the issue's path (classifier, toast, copy, 3 tests). No unrelated changes.

## Appendix (no quotable head line)
- The PR claims `worktree-removal-real-git.test.ts` exercises refuse then force-remove against real git. I read only the diffstat for that file (+42), not its body, and did not run it. Treat the claim as unverified by this axis.
