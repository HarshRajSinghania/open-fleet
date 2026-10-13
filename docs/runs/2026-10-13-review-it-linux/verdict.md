# Verdict — review-it on stablyai/orca#28206 @ 6dcd957a65daf77fe49f15afbb998b262427224c

**NO-GO** — 0 Critical, 2 Required (both security lens, one root cause).
Fixed point re-checked at verdict time: PR still OPEN at the same head.
Verdict retained in this record only; nothing was posted upstream.

## Worst finding per axis (no cross-axis rerank)

| Axis | Worst | One line |
|---|---|---|
| Standards | Optional | New i18n key only in en.json; other locales fall back to English |
| Spec | Nit | Same single-locale key; the issue's criteria are otherwise met via the "offer Force Delete" branch |
| Test-adequacy | Optional | No precedence test (submodules vs dirty); one test passes with or without the change |
| Security (lens) | **Required ×2** | Submodule toast hides superproject data loss: branch order + copy never mention uncommitted work outside submodules |

Full per-axis reports (worker-written, retained verbatim): `axis-standards.md`,
`axis-spec.md`, `axis-test-adequacy.md`, `lens-security.md` in this directory.
Findings below are the aggregate after the coordinator anti-FP gate; severity
counts: Critical 0 · Required 2 · Nit 4 · Optional 5 · FYI 7 (+appendix).

## Why NO-GO (the two Required, one root)

1. `src/shared/worktree/removal.ts:146` — the new `submodules` branch sits
   before `dirty`, and Git itself reports the submodule refusal first
   (coordinator-verified empirically in `quote-check.txt`: a dirty superproject
   with an initialized submodule gets only "working trees containing
   submodules cannot be moved or removed", exit 128).
2. `src/renderer/src/components/sidebar/delete-worktree-toast.ts:110` — the
   copy warns only about submodule checkouts/unpushed submodule commits. A user
   with uncommitted superproject edits who clicks Force Delete loses them via
   `git worktree remove --force` (`src/main/git/worktree-removal.ts:79`) with
   no warning naming that loss. Fix shape (for the fix missions, not applied
   here): mention uncommitted changes in the copy, or test dirtiness
   separately before offering.

## Anti-false-positive gate (coordinator, at head)

Every quoted line in the four worker reports was re-read at `6dcd957a`
(transcript: `quote-check.txt`): 14/14 verbatim. Multi-axis same-line boosts:
`removal.ts:146` (standards Nit / spec FYI / test-adequacy Optional / security
Required — the line is real; severities differ by lens mandate, not reranked)
and `en.json:6169` (standards Optional / spec Nit — confirmed).
Demoted to appendix: test-adequacy FYI on the classifier caller (no quoted
line; worker self-flagged), plus each worker's own appendix items as filed.

## Risk-lens gating (diff_scope.py --strict, retained in diff-scope.json)

Flags: FRONTEND, BACKEND, TESTS, AUTH. Security RAN (auth/destructive-path
surface; NEVER_GATE). Recorded gate-offs: performance (no signal),
accessibility (no markup/component files per classifier — toast is a `.ts`
module + i18n copy), data-migration (no schema), api-contract (no public
contract change), privacy (no personal data stored/logged/forwarded),
simplification (no unneeded structure; the standards axis's duplication Nit
covers the one candidate). Lens tally deviation: risk-review keeps tallies in
the target repo's DECISIONS log; this is a read-only external review, so the
tally lives here instead — security dispatched 1, findings 6 (2 Required);
no lens was gate-eligible for auto-off.

## Boundary check

Target checkout `git status --porcelain` empty at close; workers ran
PROFILE=ro (plan mode; coordinator approved each worker's read-only plan
in-pane to let it write its report + send worker_done — recorded deviation,
scope verified per plan before approval). No upstream posting (one-way gate
not requested).
