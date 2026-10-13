# Re-pin delta inventory — 1.4.215 pin → 1.4.224 candidate (refreshed 2026-10-13)

Status: CLOSED 2026-10-13 — PINNED-WITH-PARKED at v1.4.224. Every row below carries a
receipt-backed disposition; the run record is `docs/runs/2026-10-12-pin-it-224.md`.

## Refresh basis

- This worktree was fast-forwarded to main `00eee98e` (post-#544) on 2026-10-13;
  the 2026-10-12 starter files in this directory are kept and re-used.
- Installed binary: `orca --version` → 1.4.224, which is also the latest GitHub
  release and the newest tag in the source clone (`~/projects/orca`, fetched
  2026-10-13; tag `v1.4.224` package.json = 1.4.224). There is no newer target.
- Starter diff (`diff-vs-1.4.215.json`): agent-context 239 → 249 commands
  (10 added, 0 removed, 19 changed), 7 of 14 guide files changed, drift=true.
- Fresh repo-local receipts: `receipts-refresh-2026-10-13/` (version, status,
  agent-context at 1.4.224, help for send/ask/task-update/worktree-create/
  worker-start).
- Substrate today: the macOS receipt still reads app-not-running, but a
  bounded Linux substrate was built the same day (OrbStack Ubuntu 24.04
  arm64 machine `orca-linux-witness`, `orca-ide` 1.4.224 deb) and
  `orca-ide serve --no-pairing` reaches runtime **ready**. Live receipts:
  `receipts-linux-live-2026-10-13/` (status, terminal/worktree/run/task
  lifecycle under a real coordinator terminal). Claims needing a dispatched
  agent worker remain parked — no agent credentials exist in that VM.

## Changed-mechanics claims (delta over the frozen 1.4.215 inventory)

| id | Changed mechanic (215 → 224) | Fleet surface | Receipt | Disposition |
|---|---|---|---|---|
| D224-1 | Canonical worker `send`/`ask` forms drop `--dispatch-capability`; the guide now says carry any flag the preamble carries (an older host adds the capability). The flag itself is still accepted at 224, and `dispatch_capability_invalid` still exists. | dispatch-lifecycle.md, decompose-dag.md (both taught "every send carries --dispatch-capability") | guides/orchestration--worker-contract.md; receipts-refresh send-help.txt + ask-help.txt (flag still listed); source tag v1.4.224 `src/main/runtime/rpc/errors.ts:132` | PATCHED in this branch (conditional-capability wording) |
| D224-2 | `send`/`ask` can return `consumer_fenced` when run from another party's terminal | Already taught for `check` (dispatch-lifecycle.md, liveness-resume.md); send/ask wording is additive | receipts-linux-live dispatch-probes.txt on a real manual-terminal Dispatch (`ctx_b0037fd39d50`): wrong-party `worker_done` send → `worker_identity_changed`; consuming `check` from an unbound terminal → `consumer_fenced` verbatim | REPLAYED: fencing is live at 224; the send-side code for a wrong-party `worker_done` is `worker_identity_changed`, and no fleet wording claims otherwise |
| D224-3 | OpenCode accepts `--model` in an existing worktree (new-worktree override and effort unsupported) | spawn_worker.sh roster comment said opencode carries NO catalog and rejects `--model` — stale (caught in PR review) | guides/orchestration--coordinator-loop.md; source at tag: `agent-session-option-catalog-opencode.ts:8` (new file, flag + launchArgs) + `worker-launch-preferences.ts:73-86` caveats | PATCHED (roster comment, with D224-9) |
| D224-4 | `worker-abandon` settle retains an owned terminal; new cancel-Task recipe (`task-update --status failed --result cancelled`) | liveness-resume.md / dispatch-lifecycle.md recovery paths | task-lifecycle.txt: cancel recipe ok (result "cancelled"). dispatch-probes.txt: `worker-abandon --dispatch ctx_b0037fd39d50` → `state=abandoned`, `processAction=none`, warning "its unsupervised terminal process was retained"; `terminal list` still holds the worker; `worker-show` = `unsupervised` | REPLAYED, both halves — retention confirmed; the terminal survives by design, teardown stays the coordinator's job |
| D224-5 | `task-update --result` usage changed `<json>` → `<text>` | task_ops.py passes a JSON string as the result | receipts-linux-live task-lifecycle.txt: `--result {"probe":"json-result"}` completed; the receipt's task.result is the verbatim TEXT string, so fleet JSON text remains parseable downstream | CURRENT; task_ops.py docstring updated to `<text>` in this branch |
| D224-6 | `status --json` can carry `caller.orcaSessionId` | No fleet claim reads it | status-linux.json: absent for an external CLI caller. dispatch-probes.txt: `status --json` typed into a live Orca terminal still shows no `caller` field; the Dispatch record carries `assignee_orca_session_id` keys but no values surfaced | PARKED: observing it present needs a structured agent session (agent account in the witness VM); carried to the next re-pin |
| D224-7 | Additive commands/flags only: `account rm/select`, `environment *` (8), `repo set`, worktree `--pr/--gitlab-*/--unread`, automations `--extra-agent-args` | Fleet teaches none of these; 0 commands removed | agent-context diff; receipts-refresh worktree-create-help.txt | CURRENT — no fleet claim to patch |
| D224-8 | Summary-only wording: `check`, `run-current`, `run-use`; `terminal` help identical. `worker-start` usage/flags unchanged (its notes changed — see D224-3 and D224-9) | Fleet command shapes unchanged | receipts-refresh worker-start-help.txt; terminal-help.txt identical per starter diff | CURRENT |
| D224-9 | Additive, verified in agent-context diff: `profile state exports` gains `--profile-id`; `profile state rollback` gains `--latest-json` + `--profile-id` (with multi-profile downgrade notes); `worker-start --model` now also supports OMP (model only, `--effort` unsupported — companion to the OpenCode change in D224-3) | Profile-state: no fleet claim. OMP: spawn_worker.sh DID claim omp rejects `--model` — stale (caught in PR review; the earlier "no claim" reading was wrong) | agent-context diffs; source at tag: `agent-session-option-catalog-omp.ts:13` flag added since 215 (absent at v1.4.215), launchArgs line 20; gemini/grok catalogs still lack the flag | Profile flags CURRENT; OMP half PATCHED (roster comment) |
| D224-10 | Orchestration schema v42 → **v43**: stored `session:<id>` mail addresses respelled `orca_session_id:<id>` (`migrate-v43.ts`) | orca-dag-semantics.md taught "current schema line: v42"; no fleet code keys the old spelling (grep clean) | source at tag v1.4.224: `db/contract-constants.ts:23` `SCHEMA_VERSION = 43` + migrate-v43 frozen prefixes | PATCHED (dag-semantics schema line → v43 at 2bb20586); migration is storage-internal, live DB in the witness already runs it |
| D224-11 | #513 compass points shipped inside the range: `recipient_run_bound_redirect` (v1.4.217) and `dsh` in the upstream `--agent` set (v1.4.218) | dispatch-lifecycle.md addressing; spawn_worker.sh roster | tag-range `git tag --contains` (7438bc80f5 → v1.4.217; 45f3512a33 → v1.4.218); dispatch-probes.txt: redirect replayed live (warning code verbatim; parent-pinned `--run` → `recipient_run_mismatch`) | REPLAYED + PATCHED (addressing clause names the redirect); `dsh` NOTED, roster unchanged by choice |

## Close-out (2026-10-13)

A manual terminal Dispatch — no agent credential — finished the live queue:
D224-2 fencing and D224-4 abandon retention replayed; the inherited parks were
assessed against the same substrate (P40 doctor shapes answered with pass/warn/
fail transcripts + `sandbox_doctor.py` parity; D9-execute answered — `terminal
stop` executes; worker-list and send-no-sender re-probed; the owed mac app
update resolved — app + CLI co-resident 1.4.224). Remaining parks: P27
legacy-takeover replay (needs a legacy Run — the fresh 224 DB reports
`legacy: 0`), D224-6 `caller.orcaSessionId` (needs a structured agent session),
and the carried other-host/account probes. `runtime/orca-pin.md` +
`runtime/pins.json` moved together to v1.4.224 (`2bb20586`); README +
distribution floor lines and the pin-relative `test_spawn_worker` literals moved
with them. Lands via PR #547 after build-blind review; #508 carries the next
trigger (2026-12-28).
