# Re-pin delta inventory — 1.4.215 pin → 1.4.224 candidate (refreshed 2026-10-13)

Status: RE-WITNESS IN PROGRESS. The pin does NOT move in this branch state.
`runtime/orca-pin.md` and `runtime/pins.json` still name v1.4.215.

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
| D224-2 | `send`/`ask` can return `consumer_fenced` when run from another party's terminal | Already taught for `check` (dispatch-lifecycle.md, liveness-resume.md); send/ask wording is additive | receipts-linux-live task-lifecycle.txt: cross-terminal `check --peek` and a heartbeat `send` from a second terminal both succeeded (neither consumes a Dispatch) | PARTIALLY REPLAYED: fencing on a dispatched worker's mailbox still needs an agent-backed Dispatch; no fleet wording contradicts the observed shapes |
| D224-3 | OpenCode accepts `--model` in an existing worktree (new-worktree override and effort unsupported) | No fleet doctrine claims OpenCode rejects `--model` (spawn_worker.sh opencode notes concern the autonomous launch flag) | guides/orchestration--coordinator-loop.md | CURRENT — no fleet claim to patch |
| D224-4 | `worker-abandon` settle retains an owned terminal; new cancel-Task recipe (`task-update --status failed --result cancelled`) | liveness-resume.md / dispatch-lifecycle.md recovery paths | receipts-linux-live task-lifecycle.txt: a ready task was cancelled with exactly `--status failed --result cancelled` (ok, result "cancelled") | Cancel recipe CURRENT; worker-abandon terminal retention PARKED-LIVE (needs a dispatched worker) |
| D224-5 | `task-update --result` usage changed `<json>` → `<text>` | task_ops.py passes a JSON string as the result | receipts-linux-live task-lifecycle.txt: `--result {"probe":"json-result"}` completed; the receipt's task.result is the verbatim TEXT string, so fleet JSON text remains parseable downstream | CURRENT; task_ops.py docstring updated to `<text>` in this branch |
| D224-6 | `status --json` can carry `caller.orcaSessionId` | No fleet claim reads it | receipts-linux-live status-linux.json: absent for an external CLI caller (field is in-session only) | PARKED-LIVE: needs an in-session caller to observe it present |
| D224-7 | Additive commands/flags only: `account rm/select`, `environment *` (8), `repo set`, worktree `--pr/--gitlab-*/--unread`, automations `--extra-agent-args` | Fleet teaches none of these; 0 commands removed | agent-context diff; receipts-refresh worktree-create-help.txt | CURRENT — no fleet claim to patch |
| D224-8 | Summary-only wording: `check`, `run-current`, `run-use`; `terminal` help identical. `worker-start` usage/flags unchanged (its notes changed — see D224-3 and D224-9) | Fleet command shapes unchanged | receipts-refresh worker-start-help.txt; terminal-help.txt identical per starter diff | CURRENT |
| D224-9 | Additive, verified in agent-context diff: `profile state exports` gains `--profile-id`; `profile state rollback` gains `--latest-json` + `--profile-id` (with multi-profile downgrade notes); `worker-start --model` now also supports OMP (model only, `--effort` unsupported — companion to the OpenCode change in D224-3) | No fleet doctrine teaches profile-state commands (orca-pin.md lists them as additive surface with no doctrine claims); spawn_worker.sh makes no OMP `--model` claim | agent-context 215 vs receipts-refresh agent-context (usage/flags/notes diffs recomputed 2026-10-13) | CURRENT — no fleet claim to patch; record at pin close if the orca-pin additive-surface list is rewritten |

## What finishing this re-pin still needs

1. An agent-backed Dispatch to finish D224-2 (consumer fencing) and the
   worker-abandon half of D224-4, an in-session caller for D224-6, plus the
   inherited park register from the 2026-09-28 run (P40, P27, D9-execute).
   The Linux serve substrate above can host these once an agent account is
   signed in inside the VM; a mac run also still owes app/CLI co-residency.
2. Only then: rewrite the witness/version fields of `runtime/orca-pin.md`,
   bump `runtime/pins.json` (`orca.binary`, `fleet_floor.binary`, `triple`),
   and re-check the receiver half (`validate.py` pin claims + `pins.py`).
3. Land as its own merge after a build-blind review of the doctrine patches,
   per orca-pin.md §How to re-pin steps 6–7, closing or carrying #508.
