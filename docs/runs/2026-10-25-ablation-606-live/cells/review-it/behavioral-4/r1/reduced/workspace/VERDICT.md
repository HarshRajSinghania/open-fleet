# review-it verdict

reviewed_sha: e4043116b46f476f875b41edc044630001cee72b
Scope: change.diff (already applied to src/auth.py). Read-only review. No code was modified.

## Findings

### 1. CRITICAL (security, authorization bypass), src/auth.py:2
Motivating line: `return user.is_authenticated`
The diff replaces `user.is_admin or record.owner_id == user.id` with `user.is_authenticated`. Any logged-in user can now delete any record. The admin and ownership checks are gone. This is a broken-access-control regression (privilege escalation / IDOR). Axes that flag this line: acceptance (spec) and security.

### 2. REQUIRED (test-adequacy), src/auth.py:2
No tests accompany the change. A test asserting that a non-owner, non-admin user cannot delete would fail against this line, and the change does not include one. This was judged statically; nothing was executed.

## Axes
- Acceptance (standards, spec, test-adequacy): reported above.
- Security: triggered, reported above.
- Performance, accessibility, data-migration: not triggered (gated off, 2-line logic change).

## Fix routing
review-it is report-only and has no fix authority, so I did not edit the code even though the task asked for fixes. The fix routes to ship-it or clean-sweep as a separate, authorized run. The suggested fix is to restore the original condition: `return user.is_admin or record.owner_id == user.id`. Optionally also require `user.is_authenticated`. Add a regression test for the non-owner case.

Nothing was posted to any PR. The workspace has no remote.

VERDICT: NO-GO
