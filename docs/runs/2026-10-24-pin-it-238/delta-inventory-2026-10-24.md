# Re-witness delta inventory — v1.4.229 pin → v1.4.238 candidate (2026-10-24)

Status: CLOSED 2026-10-24 — re-witnessed at v1.4.238; **pin HELD at v1.4.229**. Four rows in
#606-registered runtime docs drifted, and editing those docs before the #606 ablation runs
would make its registration stale (`python3 scripts/ablation.py prereg`). Their exact edits,
and the pin bump that depends on them, are listed below under "Deferred until after #606 runs".

## Scope & source

- Pin: `v1.4.229` (`a0cd1644f320f1327f7495650a816111b495f3cd`, witnessed 2026-10-17, live receipts
  carried from v1.4.224).
- Candidate: `v1.4.238` (tag object `ee4079b1df…` peeled to `e6f7fba58e8e47b45e4343f99101b3ca9e05a5da`,
  "release: v1.4.238", GitHub release 2026-10-23T21:47:22Z, the latest).
- Range: tag range `v1.4.229..v1.4.238`, 1040 commits (upstream builds from release branches; the
  tags are the release sources). Receipts: `receipts/oracle-2026-10-24.txt`.
- Diffed surfaces: `src/cli/specs/`, `skill-guides/`, `skills/`, `src/shared/orchestration-*`,
  `src/shared/tui-agent-*`, `src/shared/rpc-contract/`, `src/main/runtime/orchestration/`,
  `src/main/runtime/rpc/methods/orchestration/`, `src/main/agent-launch/agent-launch-mode.ts`,
  `src/cli/handlers/` (orchestration, terminal, vm), plus every upstream file a runtime doc or
  script cites (anchor table below). Receipts: `receipts/source-delta-v1.4.229-v1.4.238.txt`,
  `receipts/cli-command-paths-v1.4.229-v1.4.238.txt`.
- Installed binary: `/usr/local/bin/orca` 1.4.229 (= the pin). The app was not running
  (`orca status`: `not_running`), so every sender-bound or live probe is BLOCKED-BY-SUBSTRATE and
  parked; nothing was installed, upgraded or started. Receipt: `receipts/installed-1.4.229-probes.txt`.
- Guides: archived from the `v1.4.238` tag source (`guides/`), the method the 2026-10-17 run used.
  The installed 1.4.229 binary serves guides byte-identical to that run's tag-source archive (14/14),
  which is what makes the tag source a faithful stand-in for what a 1.4.238 binary serves.

## Per-item classification

| ID | Upstream change (v1.4.229 → v1.4.238) | Fleet surface | Source citation | Disposition |
|---|---|---|---|---|
| D238-1 | Global **Auto** permission switch: `AUTO_TUI_AGENT_ARGS` (claude `--permission-mode auto`, codex `--approve-for-me`); a host's `agentDefaultArgs` can now be YOLO, manual (`''`) or Auto. The YOLO map and `DEFAULT_TUI_AGENT_ARGS` (= the YOLO map) are byte-identical. | `sandbox-policy.md` "Say 'by default' precisely" (names two host modes); `spawn_worker.sh` ro/LAUNCHED_UNUSABLE comments | 8d0501622a (#30677); `src/shared/tui-agent-permissions.ts:6-10` (Auto), `:12-45` (YOLO) | **STALE (incomplete)** in `sandbox-policy.md` → DEFERRED E5. Behaviour CURRENT: an Auto host's `launch.effective` lacks the PROFILE flag, so `spawn_worker.sh` exits 5. **PATCHED** in `spawn_worker.sh` (comment) + `test_an_auto_mode_host_is_refused_like_a_manual_one`. |
| D238-2 | `--host` and `--project` accept the names `orca host list` / `orca project list` print; `--host` optional when a project has one host setup; a name two hosts share is refused with each exact flag (`selector_ambiguous` recovery). | `mission-scheduling.md:42-44` ("pass the id … never the environment's name") | 4940654793 (#30438); `src/cli/specs/automations.ts:59-60`, `core.ts:105-107`, `environment.ts:24` | **STALE** → DEFERRED E6. `spawn_worker.sh` refusing `--host` on orchestration verbs stays CURRENT (`specs/orchestration.ts` zero-diff). |
| D238-3 | `--surface chat\|terminal` on `agent launch` and `worktree create --agent`; per-agent chat providers (`isNativeChatDefaultFor`): orchestration workers follow the per-agent chat default too. `WorkerStartParams` has no `--surface` (zero-diff). | `dispatch-lifecycle.md:32` flag list + anchor `agent-launch.ts:6-33` | 251516de60 (#29071); `src/cli/specs/agent-launch.ts:6-35`; `src/main/agent-launch/agent-launch-mode.ts` | **ADDITIVE** — no listed flag removed; flag list + anchor → DEFERRED E1. |
| D238-4 | `linear comment edit\|delete` (+ alias `rm`), `linear_comment_not_found`, read-back rules for an unconfirmed delete; guides say "edit instead of posting a correction". | `playbooks/linear-enumeration.md` ("EXACTLY ONE completion comment") | `src/cli/specs/linear.ts:214-242`; `skill-guides/orca-linear.md`, `linear-tickets.md` | **ADDITIVE / CURRENT** — consistent with exactly-one (an edit fixes in place); no fleet path deletes comments. No patch. |
| D238-5 | `terminal set-pane-title`; terminal summaries carry optional `paneTitle`. | `terminal_ops.py` parked-verb list; `liveness-resume.md` terminal reads | `src/cli/specs/terminal-set-pane-title.ts`; `write-orchestration-pointer-pty.ts:113-117,159` | **ADDITIVE** — **PATCHED** `terminal_ops.py` docstring + `docs/runtime-scripts.md` (parked with the other mutating verbs); `paneTitle` is optional and unread. |
| D238-6 | `speech openai-key status\|set\|clear`; `profile state rollback --repair`; `file open` → `renderer_unavailable` on a windowless server; `automations run` needs the full UUID and a queued run may have no workspace yet; worktree listing scope note; managed-server wording; `worktree set --parent-worktree\|--no-parent` and cross-project parents in the guide; `active`/`current` not valid against a paired server. | none | `src/cli/specs/{speech,profile-state,file,automations,worktree-listing-scope-notes,managed-server}.ts`; `skill-guides/orca-cli.md` | **NOTED-ADDITIVE** — no fleet claim. Optional E6b wording for `automations run`. |
| D238-7 | Codex-specific `no_active_sender_terminal` text when `CODEX_THREAD_ID` is set without `ORCA_TERMINAL_HANDLE` (Codex's `shell_environment_policy` drops `ORCA_*`). Code unchanged. | `send_msg.py`, `check_reply.py` | `src/cli/handlers/orchestration/terminal-identity.ts:240-251` (#25775) | **CURRENT** — the refusal code is unchanged; `send_msg.py` refuses an identity-less `worker_done`/`heartbeat` before any call, and `check_reply.py` passes the runtime's typed refusal through. NOTED for codex workers. |
| D238-8 | Unreachable pre-mailbox terminal delivery and unimported `terminal-owned-mailboxes.ts` deleted; a terminal row's host-side `verdict` field — and a local worker status taken from it (`unverifiable`, `missing_liveness_verdict`) — exist only behind `ORCA_LAYOUT_OWNER` (off in every shipped build; the remote `unverifiable` path predates the range). | `liveness-resume.md`, `watchdog.py`, `worker_ops.py` | e7b60c155b (#30576), 6afbe49c17 (#30214); `src/shared/layout-owner-switch.ts`; `worker-observation.ts:118-138` | **CURRENT** (shipped behaviour unchanged). NOTED: re-witness when the layout-owner switch ships. |
| D238-9 | Orca's own background Claude runs (model list, chat naming, commit/PR/branch/Jira text) pass `--strict-mcp-config` + `disableAllHooks`. | `deny-hook.sh` | 36d13f14a5 (#30939) | **CURRENT** — worker terminals are not background runs; their hooks still load. NOTED. |
| D238-10 | Citations already stale at the v1.4.229 pin, found by this re-check. | `spawn_worker.sh:29`, `threat-model.md:35`, `dispatch-lifecycle.md:36`, `orca-dag-semantics.md:26`, `sandbox-policy.md:13,20,23,35,38` | anchor table below | **PATCHED** in `spawn_worker.sh` and `threat-model.md`; DEFERRED E2, E5, E7 in the registered docs. |
| — | Schema line; orchestration guides; agent catalog; worker-start params; orchestration CLI spec; recipient routing (`recipient_run_bound_redirect`). | `ledger-contract.md`, `orca-dag-semantics.md:6`, roster | `contract-constants.ts:23` (`SCHEMA_VERSION = 43`); zero-diff list in `receipts/source-delta-…` | **CURRENT** |

### The two #513 commits, re-checked

Both are ancestors of the `v1.4.229` tag (shipped in v1.4.217 / v1.4.218, dispositioned live at
v1.4.224). `recipient-routing.ts` is zero-diff over `v1.4.229..v1.4.238`, so the
`recipient_run_bound_redirect` addressing rule (`dispatch-lifecycle.md:130`) stays CURRENT. `dsh`
is in `TUI_AGENT_CONFIG` (`tui-agent-config.ts:322`, zero-diff) but not in `YOLO_TUI_AGENT_ARGS`:
Orca has no autonomous flag for it, so it stays off the `spawn_worker.sh` roster deliberately
(it would need `WORKER_CMD`, like omp/pi). No agent joined or left the catalog in the range.

## Complete `runtime/*.md` policy drift table (16 / 16 files)

| Policy file | Upstream Orca surface | v1.4.238 verdict | Notes |
|---|---|---|---|
| `runtime/attention-budget.md` | gate verbs (`specs/orchestration.ts:535-611`, zero-diff); `account list` (`handlers/account.ts`) | **CURRENT** | `account.ts:300-310` still covers the formatter (block now 297-307); optional tidy E8. |
| `runtime/conductor-close.md` | `worker-list`, `worker-release`, `terminal close`, `terminal stop`, `worktree rm` | **CURRENT** | Orchestration specs zero-diff; `terminal stop` still hidden + deprecated (`specs/core.ts:208-216`), handler present (`handlers/terminal.ts:145`). |
| `runtime/dispatch-lifecycle.md` | `worker-start`, `agent launch`, `reference`, refusal codes, addressing | **DEFERRED-#606** | E1 (`--surface`, anchor), E2 (stale stage-type anchor), E3 (`core.ts` +3), E4 (live-PIN lines move with the bump). Every other claim CURRENT. |
| `runtime/evidence-manifest.md` | fleet-owned manifest + verifier | **CURRENT** | No upstream surface. |
| `runtime/gate-classification.md` | gate verbs; `GateStatus` (`orchestration/types.ts:39`, `create-graph-tables-sql.ts:190`) | **CURRENT** | All zero-diff. |
| `runtime/ledger-contract.md` | orchestration SQLite ledger | **CURRENT** | `SCHEMA_VERSION = 43` at v1.4.238. |
| `runtime/liveness-resume.md` | `terminal list/read/wait`, `worker-list`, `--retry-of` | **CURRENT** | Shipped shapes unchanged; D238-8 dark path noted. |
| `runtime/merge-serialization.md` | conductor handle, `run:`/`dispatch:` addressing | **CURRENT** | `recipient-routing.ts` zero-diff. |
| `runtime/mission-chaining.md` | fleet-owned chain contract | **CURRENT** | No upstream surface. |
| `runtime/mission-scheduling.md` | `automations create/run/runs` | **DEFERRED-#606** | E6 (`--host` names, D238-2); optional E6b (`automations run` full UUID). Sleep-not-close holds (dd85af1434 extends it to headless). |
| `runtime/orca-dag-semantics.md` | task DAG, depth, `task_not_startable.failureCount` | **DEFERRED-#606** | Claims CURRENT (schema v43, refusal contract zero-diff); E7: `dispatch-depth.ts:41-51` names `recordedCreatorIdentity`, not the self-dispatch rule (`:60-70` at the pin, `:63-73` at v1.4.238). |
| `runtime/orca-pin.md` | pin record | **PATCHED** | Re-witness noted, pin held; next trigger machine-filed (`orca.next_review` + `review-date`); How-to-re-pin step 5. |
| `runtime/reviewed-sha-freshness.md` | fleet-owned | **CURRENT** | No upstream surface. |
| `runtime/sandbox-policy.md` | YOLO map, launch defaults, OS containment | **DEFERRED-#606** | E5: Auto host mode (D238-1) + four anchors (five lines) stale since before the pin. |
| `runtime/threat-model.md` | OS terminal containment env vars | **PATCHED** | `terminal-host/containment/` never existed; now `daemon/terminal-scopes.ts`, `terminal-memory-limits.ts`. |
| `runtime/worker-supervision.md` | `worker-read`, `worker-list --include-remote`, `worker-stop`, `send` | **CURRENT** | `orchestration-worker-specs.ts:125` zero-diff. |

Counts: CURRENT 10 · PATCHED 2 · DEFERRED-#606 4.

## Complete `runtime/scripts/` entry-point drift table (44 / 44 files)

| Script entry point | Upstream coupling | v1.4.238 verdict |
|---|---|---|
| `runtime/scripts/_catalog_grammar.py` | none (catalog grammar for validate/quarantine) | **CURRENT** |
| `runtime/scripts/_verify_sig.py` | none | **CURRENT** |
| `runtime/scripts/certification.py` | `pins.json#orca` freshness | **CURRENT** (pin held, record fresh; the bump re-records it — B6) |
| `runtime/scripts/chain_check.py` | none | **CURRENT** |
| `runtime/scripts/check_reply.py` | `check`/`reply` (specs/orchestration.ts, zero-diff); sender identity | **CURRENT** (D238-7 noted) |
| `runtime/scripts/decisions.py` | none (cites `args.ts` flag parsing; GLOBAL_FLAGS unchanged) | **CURRENT** |
| `runtime/scripts/deny-hook.sh` | worker harness hooks | **CURRENT** (D238-9) |
| `runtime/scripts/diff_scope.py` | none | **CURRENT** |
| `runtime/scripts/diffparse.py` | none | **CURRENT** |
| `runtime/scripts/dispatch-sign.py` | none | **CURRENT** |
| `runtime/scripts/ed25519.py` | none | **CURRENT** |
| `runtime/scripts/egress.py` | none (gh) | **CURRENT** |
| `runtime/scripts/events.py` | none | **CURRENT** |
| `runtime/scripts/evidence-run.py` | none | **CURRENT** |
| `runtime/scripts/first_run.py` | `orchestration worker-show` (zero-diff) | **CURRENT** |
| `runtime/scripts/floor_guard.py` | none | **CURRENT** |
| `runtime/scripts/gate-batch.py` | `gate_request` envelopes (zero-diff) | **CURRENT** |
| `runtime/scripts/gitexec.py` | none | **CURRENT** |
| `runtime/scripts/guard_text.py` | none | **CURRENT** |
| `runtime/scripts/hint_provenance.py` | none | **CURRENT** |
| `runtime/scripts/hitl-loop.template.sh` | none | **CURRENT** |
| `runtime/scripts/hitl_ask.py` | `orchestration ask` (zero-diff) | **CURRENT** |
| `runtime/scripts/inventory.py` | none | **CURRENT** |
| `runtime/scripts/merge_queue.py` | none (git) | **CURRENT** |
| `runtime/scripts/orca_cli.py` | CLI resolution; pin fallback literal `v1.4.229` | **CURRENT** (literal equals the held pin; moves with the bump — B7) |
| `runtime/scripts/pin_review.py` | pack pins (none moved) | **CURRENT** |
| `runtime/scripts/pm.py` | none | **CURRENT** |
| `runtime/scripts/preflight.py` | `orca` on PATH | **CURRENT** |
| `runtime/scripts/proof_status.py` | none | **CURRENT** |
| `runtime/scripts/quarantine_check.py` | none | **CURRENT** |
| `runtime/scripts/run_report.py` | none | **CURRENT** |
| `runtime/scripts/sandbox_doctor.py` | `vm recipe doctor` verdict (`handlers/vm.ts`: a constant renamed, 16,000-char cap unchanged) | **CURRENT** |
| `runtime/scripts/search_sessions.py` | `specs/search.ts`, `handlers/search.ts` (zero-diff) | **CURRENT** |
| `runtime/scripts/send_msg.py` | `send` (zero-diff); sender identity | **CURRENT** (D238-7 noted) |
| `runtime/scripts/spawn_worker.sh` | `worker-start`, `dispatch --inject`, YOLO map, roster, `vm recipe doctor`, refusal codes | **PATCHED** (D238-1, D238-10; roster CURRENT) |
| `runtime/scripts/task_ops.py` | `task-create`/`task-update` (zero-diff) | **CURRENT** |
| `runtime/scripts/terminal_ops.py` | `terminal create/read/list/show` | **PATCHED** (D238-5) |
| `runtime/scripts/upstream_probe.py` | GitHub tags API; capture surfaces | **PATCHED** (`review-date`, #508) |
| `runtime/scripts/verify-gate.sh` | none | **CURRENT** |
| `runtime/scripts/verify.py` | none | **CURRENT** |
| `runtime/scripts/watchdog.py` | `worker-list`, terminal reads | **CURRENT** (D238-8 noted) |
| `runtime/scripts/worker_ops.py` | `orchestration-worker-specs.ts` (zero-diff) | **CURRENT** |
| `runtime/scripts/worktree_ops.py` | `worktree list/show`, `selectors.ts` (zero-diff) | **CURRENT** |
| `runtime/scripts/wtree.sh` | none (git) | **CURRENT** |

Counts: CURRENT 41 · PATCHED 3.

## Upstream anchors whose file moved in the range

Every `file.ts:line` a runtime doc or script cites was resolved at both tags. Anchors in files
that did not change are CURRENT by zero-diff. Version-tagged history ("at v1.4.203", the dated
`orca-pin.md` corrections) is history, not a claim about the pin. The rest:

| Citation | At v1.4.229 (pin) | At v1.4.238 | Disposition |
|---|---|---|---|
| `spawn_worker.sh:29` `runtime-terminal-contracts.ts:221-225` (prompt stages) | wrong file — the type is `runtime-terminal-send-contract.ts:12` | same | **PATCHED** |
| `spawn_worker.sh:104` `tui-agent-permissions.ts:6-33` | map at 6-39 | 12-45 | **PATCHED** |
| `threat-model.md:35` `terminal-host/containment/` | no such path | no such path | **PATCHED** |
| `dispatch-lifecycle.md:36` `runtime-terminal-contracts.ts:221-225` | wrong file | wrong file | DEFERRED E2 |
| `dispatch-lifecycle.md:32` `cli/specs/agent-launch.ts:6-33` | spec 6-33 | 6-35 | DEFERRED E1 |
| `dispatch-lifecycle.md:65` `core.ts:119,124,135` | as cited | 122,127,138 | DEFERRED E3 |
| `orca-dag-semantics.md:26` `dispatch-depth.ts:41-51` | names `recordedCreatorIdentity`; rule at 60-70 | rule at 63-73 | DEFERRED E7 |
| `sandbox-policy.md:13,20` `tui-agent-launch-defaults.ts:17` | export at 18-19 | 18-19 | DEFERRED E5 |
| `sandbox-policy.md:23` `tui-agent-permissions.ts:7-33` | map 6-39 | 12-45 | DEFERRED E5 |
| `sandbox-policy.md:35` `tui-agent-permissions.ts:21` (cursor) | line 24 | line 30 | DEFERRED E5 |
| `sandbox-policy.md:38` `tui-agent-launch-defaults.ts:12-15` | 13-16 | 13-16 | DEFERRED E5 |
| `attention-budget.md:58` `account.ts:300-310` | as cited | 297-307 (still inside 300-310) | CURRENT; optional E8 |
| `mission-scheduling.md:47,76` `automations.ts:74-103`, `:114-130` | tagged "at v1.4.229" | runs spec 121-137 | CURRENT as tagged history |
| `dispatch-lifecycle.md:20,28,122`; `spawn_worker.sh:21,1175` | as cited | same lines (import-only edits) | CURRENT |

## Deferred until after #606 runs — exact edits

These files are in the #606-registered activation payloads of ship-it, clean-sweep, review-it or
root-cause (`scripts/ablation.py`'s `transitive_load`); any byte change makes the registration
stale. Apply after the ablation has run, re-run `python3 scripts/ablation.py prereg` only if a
re-registration is wanted, and keep each mission inside `scripts/mission-load-budgets.json`.

- **E1** `runtime/dispatch-lifecycle.md:32` — replace
  ``[--effort <lvl>] [--prompt <t>] [--retry-launch <id>]`, `cli/specs/agent-launch.ts:6-33`)``
  with ``[--effort <lvl>] [--surface chat|terminal] [--prompt <t>] [--retry-launch <id>]`, `cli/specs/agent-launch.ts:6-35` at v1.4.238)``.
- **E2** `runtime/dispatch-lifecycle.md:36` — replace ``(`src/shared/runtime-terminal-contracts.ts:221-225`)``
  with ``(`src/shared/runtime-terminal-send-contract.ts:12`)``.
- **E3** `runtime/dispatch-lifecycle.md:65` — replace `` `core.ts:119,124,135` `` with `` `core.ts:122,127,138` ``.
- **E4** `runtime/dispatch-lifecycle.md:154,156` — only with the bump (B3): ``The live PIN is v1.4.229 (`docs/runs/2026-10-17-pin-it-229.md` — delta re-witness across 27 upstream commits; schema v43 unchanged). Before it: 1.4.224``
  → ``The live PIN is v1.4.238 (`docs/runs/2026-10-24-pin-it-238.md` — source-delta re-witness across the 1040-commit tag range; schema v43 unchanged). Before it: 1.4.229 `docs/runs/2026-10-17-pin-it-229.md`, 1.4.224``;
  and `Still PARKED per the v1.4.229 register:` → `Still PARKED per the v1.4.238 register:`.
- **E5** `runtime/sandbox-policy.md` — after ``a host whose owner chose manual mode carries `''` instead.`` insert
  ``From v1.4.238 a third global setting, Auto (`AUTO_TUI_AGENT_ARGS`, `tui-agent-permissions.ts:6-10`, #30677), carries claude `--permission-mode auto` / codex `--approve-for-me` — not a PROFILE flag, so `spawn_worker.sh` exits 5 (LAUNCHED_UNUSABLE) on an Auto host as on a manual one.``;
  and re-anchor `tui-agent-launch-defaults.ts:17` → `:18-19` (lines 13 and 20),
  `tui-agent-permissions.ts:7-33` → `:12-45` (line 23), `tui-agent-permissions.ts:21` → `:30` (line 35),
  `tui-agent-launch-defaults.ts:12-15` → `:13-16` (line 38).
- **E6** `runtime/mission-scheduling.md:42-44` — replace
  ``pass the id from `orca environment list`, never the environment's name.``
  with ``pass the id from `orca environment list` (from v1.4.238 `--host` also takes the bare host name `orca host list` prints and refuses one two hosts share; the id is never ambiguous).``
  Optional **E6b** (line 46): `` `automations run <id>` fires one now`` → `` `automations run <full-uuid>` fires one now (v1.4.238 refuses a shortened prefix; a queued run may have no workspace yet — follow it with `automations runs --id`)``.
- **E7** `runtime/orca-dag-semantics.md:26` — replace `` `dispatch-depth.ts:41-51` `` with `` `dispatch-depth.ts:63-73` ``.
- **E8** (optional tidy) `runtime/attention-budget.md:58` — `` `account.ts:300-310` `` → `` `account.ts:297-307` ``.

### The pin bump package (apply with E4, after E5 and E6)

The pin may not move while E5/E6 stand unpatched: a PINNED verdict at v1.4.238 would assert that
doctrine equals the binary with two known-stale claims in place.

- **B1** `runtime/pins.json` `orca`: `commit` → `e6f7fba58e8e47b45e4343f99101b3ca9e05a5da`,
  `version` → `v1.4.238`, `witnessed` → the bump date, `witness` stays `source`, `live_receipts`
  unchanged (v1.4.224, 2026-10-13), `witness_binary` → "tag v1.4.238 source delta vs v1.4.229 +
  carried live receipts (…1.4.224…)", `onpath_at_witness` → what `orca --version` then prints,
  `next_review` → the next quarterly date.
- **B2** `runtime/orca-pin.md` Current-pin table (Installed version, Build commit, Witnessed,
  Upstream HEAD then, Run record, Prior pin = v1.4.229 `a0cd1644`, Verdict) and the Next trigger
  line — in the same commit as B1 (`tests/test_pins.py`, `TheCommittedReviewDate`).
- **B3** E4 above (`tests/test_release_status_docs.py` `DispatchLifecycleNamesTheCurrentPin`
  requires the live-PIN sentence to name the pin and this record, whose title advances to v1.4.238).
- **B4** `tests/test_spawn_worker.py` pin literals (`v1.4.229` in the drift-note tests, and the
  `orca 1.4.230` "newer patch" stub, which would then lag the pin): changed assertion lines, so a
  **one-way human waiver** `floor-waiver:assertion-removed:tests/test_spawn_worker.py` must land on
  main first (taste waivers no longer grant, `floor_guard.py`; 2026-09-21/23 precedents).
- **B5** `README.md:43,156,158` and `docs/distribution.md` floor lines → v1.4.238.
- **B6** `runtime/providers/certification.json` `providers.orca.upstream` + `certified_against`
  → the new commit/version, `record_version` 4, limitation text "the current pin v1.4.238 carries
  these receipts…"; then `python3 runtime/scripts/certification.py markdown` into
  `docs/certification.md`. `certification.py check --pins <candidate>` already names the one
  STALE provider it voids (orca).
- **B7** `runtime/scripts/orca_cli.py:153,155` and `runtime/providers/base.py:866` fallback literals → `v1.4.238`.
- **B8** `assets/diagrams/generator/wire_docs.py` captions naming v1.4.229 (regenerate only if the diagrams are re-rendered).
- **B9** `docs/runs/README.md`: a row for the bump commit if it lands as its own run note.

## Verdict

**RE-WITNESSED at v1.4.238; PIN HELD at v1.4.229.** Policies: CURRENT 10 · PATCHED 2 ·
DEFERRED-#606 4. Scripts: CURRENT 41 · PATCHED 3. Two stale claims (D238-1 in
`sandbox-policy.md`, D238-2 in `mission-scheduling.md`) and the stale citations of E1–E3, E5 and E7 sit in
#606-registered docs and wait for the ablation; everything else is CURRENT or patched here.
