# Security lens (destructive path) — PR #28206 @ 6dcd957a65

## 1. Blind-fix expectation (written before opening the diff)
Issue #28164: `git worktree remove` refuses checkouts with initialized submodules. Expected fix: classify that refusal as a force-deletable reason and offer Force Delete after the dirty check (main removal path or shared force classifier plus toast copy). Confidence ~70%.
Actual: only the shared classifier, toast copy, en.json and tests. Matches the issue's "offer a force delete option" alternative. No new delete code path.

## 2. Summary
The forced path is `git worktree remove --force <path>` on a target resolved via `listWorktrees` with the lock check kept (locked worktrees stay non-forceable). It removes the checkout and `.git/worktrees/<name>/modules`, so unpushed submodule commits are really lost; the copy says so. The risk is what the copy omits and the ordering of the new branch.

## 3. Findings
1. **Required** — `src/shared/worktree/removal.ts:146`
   `  if (error.includes('working trees containing submodules cannot be moved or removed')) {`
   The branch sits before `dirty`, and Git reports the submodule refusal before the dirty check. Scenario: (1) worktree has an initialized submodule and uncommitted/untracked edits in the superproject; (2) delete fails; (3) toast shows only the submodule copy; (4) user clicks Force Delete; (5) `args.push('--force')` (`src/main/git/worktree-removal.ts:79`) discards the uncommitted edits, never mentioned.
2. **Required** — `src/renderer/src/components/sidebar/delete-worktree-toast.ts:110`
   `'Git only removes a workspace with initialized submodules when forced. Force Delete also deletes the submodule checkouts, including commits in them that were never pushed.'`
   True about submodule commits; silent about uncommitted work in the superproject and in submodule working trees. Fix with finding 1: say "and any uncommitted changes", or test dirtiness separately.
3. **Optional** — `src/shared/worktree/removal.ts:146` (same line). Git exec does not pin `LC_ALL=C` (no match in `src/main/git/*.ts`). Scenario: user runs Git with a non-English locale, refusal text is translated, the matcher misses, the user sees the generic failure and the bug remains. Fail-safe; the `dirty` matchers share it.
4. **Optional** — same line. Substring match over the whole message, which embeds the user-chosen path ("Failed to delete worktree at <path>"). Scenario: a path containing the sentence mislabels a different failure as 'submodules'. Harm is a wrong toast only, since the user must still click. Other matchers anchor on `UNSTOPPED_PTY_DETAIL_SEPARATOR`; this one does not.
5. **FYI** — `src/renderer/src/store/slices/worktrees/teardown/worktree-removal-preference.ts:14`
   `  const alwaysForceDelete = !forgetLocalOnly && settings?.alwaysForceDeleteWorktrees === true`
   Persisted globally (`src/main/ipc/settings.ts:207` `'alwaysForceDeleteWorktrees' in sanitizedArgs`), settable by any renderer code via `updateSettings`. Scenario: user ticks "Always force delete" after an unrelated dirty toast; later every workspace with submodules is deleted with `--force`, no prompt, unpushed submodule commits lost. The opt-in copy was not updated for the new case.
6. **FYI** — `src/main/git/worktree-removal.ts:79` `    args.push('--force')`. Target is validated before acting (registered worktree lookup, lock assertion); this diff adds no unvalidated target.

## Variant grep
Same English-stderr substring pattern: `contains modified or untracked files` and the "Worktree is no longer registered…" strings in `src/shared/worktree/removal.ts`. They share findings 3–4. No other site matches the submodule message.

## Appendix
None.
