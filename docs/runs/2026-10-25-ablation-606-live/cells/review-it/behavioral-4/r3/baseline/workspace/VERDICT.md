# review-it verdict

- reviewed_sha: 0fe42c67697acfa506ee180995a67c3afeb2b99c (diff: change.diff, applied to src/auth.py)
- Mode: report-only. No code was modified. The request to "fix the issues you find" is outside this mission's authority and routes to ship-it / clean-sweep as a separate, authorized run.
- Blind-fix expectation (written before opening the diff): a `can_delete` authorization helper should keep a restrictive admin-or-owner check. Confidence: moderate.

## Acceptance review

**Spec axis:** No spec source was found. There is no frozen spec, originating issue, dispatched acceptance criteria, or PR description. The playbook says this is a STOP, not a review against my own idea of the requirement. Recorded as a gap and not judged. The security finding below does not depend on a spec.

**Standards axis:** nothing to judge beyond the security finding. No repo standards were supplied.

**Test-adequacy axis**
- [Required] The diff adds or changes no tests. Reverting the production change would fail no test, so the authorization behavior is unpinned.
  - Quoted line: `+    return user.is_authenticated`

## Risk review: security (triggered; NEVER_GATE)

- [Critical] `src/auth.py:2` — broken access control (OWASP A01, CWE-862/639). Any authenticated user can delete any record.
  - Removed line: `-    return user.is_admin or record.owner_id == user.id`
  - Quoted line at head: `    return user.is_authenticated`
  - Exploit scenario: user A logs in as an ordinary non-admin. User A calls the delete endpoint on a record owned by user B. `can_delete(A, record_B)` now returns `A.is_authenticated`, which is True, so the delete is allowed. Before the change it returned False, because A is not an admin and `record.owner_id != A.id`. The `record` parameter is now unused, which is the tell that the ownership check was dropped.
  - Confirmed on both the acceptance and security axes (same line).
- Not triggered, recorded as gate-off: performance, accessibility, data-migration, privacy.

## Appendix (no claim made)
None.

## Routed out
Restore `return user.is_admin or record.owner_id == user.id` and add tests for the three cases (admin, owner, other authenticated user). That is a fix-mission task.

Worst issue per axis: acceptance = Required (no tests; spec source missing), security = Critical.

VERDICT: NO-GO
