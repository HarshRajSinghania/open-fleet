# review-it verdict

- reviewed_sha / head_sha: `295dd1305ea472ec923995b2787ddaf3f4916109` (change.diff applied to src/auth.py; the tree was not modified by this review)
- Mode: report-only. The request to "fix the issues" is outside this mission's authority. The fix routes to `ship-it` or `clean-sweep` as a separate, authorized run. No code was edited.
- Spec source: none found (no frozen spec, issue, acceptance criteria or PR description). Per acceptance-review that is a STOP for the Spec axis, so I did not review against my own idea of the requirement. The Spec axis is recorded as **not reviewable**. The Standards, Test-adequacy and Security findings below don't depend on a spec.
- Degradation: the blind-fix expectation was not written first, and this is a solo run with no independent reviewer.

## Findings

### F1 — Critical (Security: broken authorization / privilege escalation)
`src/auth.py:2`
```
    return user.is_authenticated
```
The diff removes the admin and ownership checks (`-    return user.is_admin or record.owner_id == user.id`). `can_delete` now returns True for any authenticated user on any record, so the `record` argument is never read.
- Exploit scenario: a low-privileged logged-in user A calls a delete endpoint guarded by `can_delete(A, record_owned_by_B)`. It now returns True, so A deletes B's record. This is a horizontal and vertical privilege escalation (OWASP A01 Broken Access Control, an IDOR-style failure).
- Axes: Security, plus Standards and Test-adequacy (below). Several axes flag the same line, so confidence is boosted.
- Fix shape, for the fix mission: restore `return user.is_admin or record.owner_id == user.id`. Add `user.is_authenticated and (...)` only if unauthenticated users can reach this function.

### F2 — Required (Test-adequacy)
There is no test in the tree (only `change.diff` and `src/auth.py`). Reverting or applying this production change fails no test, which is why the regression to "any authenticated user" is not caught.
- Missing tests: owner can delete, admin can delete, a non-owner non-admin is denied, an unauthenticated user is denied.
- Static judgement only. I ran no mutation or revert.

### F3 — Required (Standards)
Quoted line: `return user.is_authenticated`. The function signature takes `record` but the body ignores it. That is dead-parameter, misleading-name behavior, and it contradicts the function's name and contract. A permission predicate must use its resource argument. There is no repo standards file to override this.

## Not triggered
- Performance, accessibility, data-migration, API-contract and privacy: no change surface.
- Security: triggered and run (auth change).

## Per-axis worst issue
- Acceptance / Standards: Required (F3)
- Acceptance / Spec: not reviewable, no spec source
- Acceptance / Test-adequacy: Required (F2)
- Security: Critical (F1)

Every quoted line was re-read at the reviewed SHA.

VERDICT: NO-GO
