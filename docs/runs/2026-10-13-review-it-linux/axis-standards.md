# Axis: STANDARDS — stablyai/orca PR #28206 @ 6dcd957a65

## 1. Blind-fix expectation (written before opening the diff)
Issue #28164: `git worktree remove` without `--force` is refused for checkouts with initialized submodules. Expected fix: classify that git error in `src/shared/worktree/removal.ts` (`classifyWorktreeForceDeleteReason`) as a forceable reason, add toast copy for it, and add an en.json string. The user then chooses Force Delete, rather than Orca silently adding `--force`. Confidence ~65%. The diff matches.

## 2. Conventions used
AGENTS.md (concise "Why" comments, reuse before reimplementing, SSH / folder-workspace / remote-wire / Git 2.25 baseline, no vague file names), docs/STYLEGUIDE.md, i18n locale layout (`src/renderer/src/i18n/locales/`). Tooling-enforced items skipped.

## 3. Findings
1. **Optional** — `src/renderer/src/i18n/locales/en.json:6169` — `"submodules": "Git only removes a workspace with initialized submodules when forced. Force Delete also deletes the submodule checkouts, including commits in them that were never pushed."`
   Only en.json gets the key. Sibling `runningAgentSessionLive` exists in es/fr/ja/ko/zh, so those locales fall back to English for this toast. Confirm that is the repo's accepted flow for new strings.
2. **Nit** (Duplicated Code) — `src/renderer/src/components/sidebar/delete-worktree-toast.ts:101` — `if (forceDeleteReason === 'submodules') {`
   The branch repeats the identical title `translate(...1d0fa5c0a5...)` block, now the sixth copy in the function. It follows the existing pattern, so a later hoist is the only suggestion.
3. **Nit** — `src/shared/worktree/removal.ts:146` — `if (error.includes('working trees containing submodules cannot be moved or removed')) {`
   Matches git's English stderr, so a localized git would miss it. Sibling matchers share this limit, so it is consistent. The real-git test pins the current wording.
4. **FYI** — `src/shared/worktree/removal.ts:145` — `// Why: Git refuses a non-force remove of any checkout with initialized submodules, clean or not.` Concise non-obvious "why", meets the comment standard.
5. **FYI** — `src/renderer/src/components/sidebar/delete-worktree-toast.ts:110` — `'Git only removes a workspace with initialized submodules when forced. Force Delete also deletes the submodule checkouts, including commits in them that were never pushed.'` Good warning about data loss. `isDestructive: false` matches sibling branches.
6. **FYI** — `src/main/git/worktree-removal-real-git.test.ts:101` — `it('offers force for a clean checkout with initialized submodules, which force then removes', async () => {` Covers refusal, classification, registration state and the forced retry against real git. It uses `protocol.file.allow=always`, which is fine on the 2.25 baseline.

## Appendix (no single quotable line)
- Nothing here touches SSH or relay code. Classification is on error text in the shared module. Not verified: whether remote hosts relay git's stderr unmodified, so the offer could fail to appear over SSH.
- Non-git providers: not applicable, since this is a local git refusal.

## Summary
The change follows repo standards. It is small and well commented, and it is tested at both the unit level and against real git. Open points are the single-locale string (1) and a deliberate-looking duplication (2).
