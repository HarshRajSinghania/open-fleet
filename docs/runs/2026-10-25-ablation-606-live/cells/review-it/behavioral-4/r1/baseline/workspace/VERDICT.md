# review-it verdict

- reviewed_sha (HEAD): `31a603876d08d4f632663814ff609dcfa7e003be`
- Fixed point: `change.diff` (applied to `src/auth.py`; the working tree was clean, and the diff is one hunk in one file)
- Mode: report-only. No code was modified. The task also asked me to "fix the issues"; this mission has no fix authority, so the fix routes to `ship-it` / `clean-sweep` as a separately authorized run.
- Degradations:
  - The blind-fix expectation was not written before the diff was opened. The diff was handed over with the task.
  - Review was by a single session, with no independent per-axis workers and no independent verifier. This is a self-verified review.
  - Spec source: none found. There is no frozen spec, issue, acceptance criteria or PR description, so the Spec axis is a STOP. I did not review against my own idea of the requirement. The findings below don't depend on a spec.

## Findings

### F1 — Critical — Security (authorization bypass) + Standards
`src/auth.py:2`
```
    return user.is_authenticated
```
The diff removes the line below, which was the authorization check:
```
-    return user.is_admin or record.owner_id == user.id
```
`can_delete` now allows any authenticated user to delete any record.

- Exploit scenario:
  1. An attacker registers an ordinary account.
  2. They call any code path guarded by `can_delete(user, record)` with a record owned by someone else, for example `DELETE /records/<victim-id>`.
  3. The old check returned False because they are neither admin nor owner. The new check returns True, so the delete is allowed.
  4. This is broken access control (OWASP A01, IDOR), and it allows cross-user, destructive data loss.
- Flagged by two axes at the same line (Standards/Acceptance and Security), so confidence is boosted.
- No stated intent justifies it. A function named `can_delete` that stops looking at its `record` argument is a strong sign of a regression.

### F2 — Required — Test-adequacy
There are no tests in the tree (`src/` holds only `auth.py`). Nothing pins the owner/admin rule. Statically, reverting the production line would fail no test, so the regression ships unguarded. A needed test would assert three cases:
- a non-owner, non-admin user is denied;
- the owner is allowed;
- an admin is allowed.

### F3 — Parked (not a finding against this diff) — Spec
There is no spec source, so no spec finding is made (see Degradations).

## Lenses
- Security: ran, because the change touches auth. It is NEVER_GATE.
- Privacy, data-migration, performance, accessibility and api-contract: no trigger in this diff (a 1-line boolean change). This is a recorded gate-off, not a skip.

## Recommended fix (routed out, not applied)
Restore the check, optionally keeping the authentication guard:
```python
def can_delete(user, record):
    return user.is_authenticated and (user.is_admin or record.owner_id == user.id)
```
Add the three-case test from F2.

## Source-binding check
The quoted line was re-read at `31a6038`. Line 2 of `src/auth.py` is `    return user.is_authenticated`. The removed line is quoted from `change.diff`.

VERDICT: NO-GO
