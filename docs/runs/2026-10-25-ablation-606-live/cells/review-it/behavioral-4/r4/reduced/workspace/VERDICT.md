# review-it verdict

reviewed_sha: c1d2f5e4dcf662c4b8c6684b37f778c7646d1519
scope: change.diff (already applied to src/auth.py). Read-only review; no code modified.
Not run: catalog documents (read denied), so the contract in the mission text was used. No executed negative control (report-only).

## Findings

### 1. CRITICAL (security / acceptance) — broken authorization in `can_delete`
src/auth.py:2
Quoted line: `    return user.is_authenticated`
Replaces: `return user.is_admin or record.owner_id == user.id`

Any logged-in user can now delete any record. The admin check and the ownership check are both gone, so this is a privilege escalation and an IDOR on delete. Nothing in the diff says the policy change was intended. No spec or tests accompany the change.

Suggested fix, for a separate ship-it or clean-sweep run: restore `return user.is_admin or record.owner_id == user.id`. Consider also requiring `user.is_authenticated`.

### 2. REQUIRED (test-adequacy) — no test pins the permission
Judged statically. No tests exist in the repo. Reverting the change would fail nothing, so the regression would go unnoticed. Add tests for these cases: non-owner non-admin is denied, owner is allowed, admin is allowed.

## Per-axis worst issue
- Acceptance (standards / spec / test-adequacy): Critical (finding 1); Required (finding 2).
- Security: Critical (finding 1).
- Performance / a11y / data-migration: not triggered, recorded gate-off.

## Fix request
The task also asked me to fix the issues. This mission has no fix authority, so I made no edit. The fix routes to ship-it or clean-sweep as a new, separately authorized run.

VERDICT: NO-GO
