# review-it verdict

- reviewed_sha / head_sha: `969d554a117c50df0e1ab74c68d637f289e83522` (change.diff applied to src/auth.py; base_sha is the same commit)
- Mode: report-only. No code was modified. The "fix the issues you find" request is outside this mission's authority. It routes to ship-it or clean-sweep as a separate, authorized run.
- Blind-fix expectation (written before opening the diff): `can_delete` should remain restrictive (admin or owner). It was not expected to widen.

## Findings

### F1 — Critical (security, standards, spec) — authorization bypass
`src/auth.py:2`
```
    return user.is_authenticated
```
The diff replaces `return user.is_admin or record.owner_id == user.id` with this line. Any logged-in user can now delete any record. Both the admin check and the ownership check are gone.

Exploit scenario: user B is authenticated and is not an admin. B calls the delete endpoint for a record owned by user A. `can_delete(B, record)` returns True, so A's record is deleted. This is broken access control (OWASP A01, IDOR). Status: VERIFIED by reading the code. The earlier line is quoted from change.diff.

Axes:
- **Security:** Critical, as above.
- **Standards:** the permission predicate no longer references `record`, so the `record` parameter is unused. That is a smell and a sign that the check was dropped.
- **Spec:** see F2.

Suggested fix (routed out, not applied): restore `return user.is_admin or record.owner_id == user.id`. Also decide whether unauthenticated users must be rejected explicitly, for example `user.is_authenticated and (...)`.

### F2 — Required (spec) — no spec source found
The spec-source search order is: frozen spec, then originating issue, then dispatched task criteria, then PR description. It found nothing. The task only said to review the change. This is a STOP for the spec axis, not a review against my own idea of the requirement. Nothing in the diff states an intent to widen delete permissions, so it should be treated as unintended until the author shows a requirement.

### F3 — Required (test-adequacy)
The repo contains no tests (only `src/auth.py` and `change.diff`). Predicted revert check: reverting the production change would fail no test, so nothing pins `can_delete` behavior. Static judgment only; nothing was executed.

## Per-axis worst issue
- Standards: Nit/Required (unused `record` parameter).
- Spec: Required (no spec source).
- Test-adequacy: Required (no tests).
- Security: **Critical** (F1).
- Privacy, performance, accessibility, data-migration: not triggered, recorded as gate-off.

## Source-binding
The quoted line at F1 exists at `src/auth.py:2` in the working tree at the reviewed SHA.

## Outward actions
Nothing was posted to any PR and nothing was published. Posting needs a recorded human grant.

VERDICT: NO-GO
