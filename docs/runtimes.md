# Multi-runtime & harness guide (`open-fleet` RPI)

[Documentation](README.md) · [Runtime scripts](runtime-scripts.md) · [Verify gate](verify-gate.md) · [Architecture](../ARCHITECTURE.md)

`open-fleet` decouples mission outcomes, phase playbooks, and verification gates from any single orchestrator binary through the **Runtime Provider Interface (RPI)**. Every general mission runs unchanged across 14 orchestrator providers and dispatches workers across 10+ coding-agent harnesses under uniform least-privilege sandbox profiles (`ro`, `rw`, `danger`).

---

## Selecting a runtime provider

Set `OPEN_FLEET_RUNTIME` (or the legacy alias `ORCA_FLEET_RUNTIME`) to select the active orchestrator provider:

```bash
export OPEN_FLEET_RUNTIME=posix      # zero-daemon SQLite WAL + git worktree + tmux / cmux / setsid
export OPEN_FLEET_RUNTIME=overstory  # jayminwest/overstory `ov` CLI adapter
export OPEN_FLEET_RUNTIME=t3code     # pingdotgg/t3code MCP thread tools via `t3 acp-mcp-call`
export OPEN_FLEET_RUNTIME=ao         # ComposioHQ/agent-orchestrator loopback HTTP daemon
export OPEN_FLEET_RUNTIME=superset   # superset-sh/superset CLI adapter
export OPEN_FLEET_RUNTIME=orca       # stablyai/orca native binary
```

When `OPEN_FLEET_RUNTIME` is unset the runtime is `orca` (backward compatible, no probe). With `OPEN_FLEET_RUNTIME=auto`, [`runtime/providers/__init__.py`](../runtime/providers/__init__.py) (`active_provider_name`, shared by dispatch and `preflight.py`) selects `orca` when the platform's Orca binary (`orca-ide` on Linux, `orca` elsewhere, `ORCA_CLI_COMMAND` override) is on `PATH`, else `posix`. An explicit non-Orca `OPEN_FLEET_RUNTIME` always wins over an inherited `ORCA_CLI_COMMAND`; an unknown name is refused (exit 2).

The `posix` state store defaults to `~/.open-fleet/state/<repo-id>/runtime.db`, keyed on the git common dir (one store per repository, shared by its linked worktrees); override with `OPEN_FLEET_STATE_DB` or `OPEN_FLEET_STATE_DIR`.

### Neutral environment variables

Every runtime helper honors `OPEN_FLEET_*` primary environment variables while preserving backward compatibility with `ORCA_*`:

| Primary (`open-fleet`) | Legacy fallback (`orca-fleet`) | Purpose |
|---|---|---|
| `OPEN_FLEET_RUNTIME` | `ORCA_FLEET_RUNTIME` | Active RPI orchestrator provider (`orca`, `posix`, `overstory`, `t3code`, `ao`, `superset`, `gastown`, `worktrunk`, `jcode-swarm`, `emdash`, `vibe-kanban`, `paperclip`, `multiclaude`, `openhands`, or `auto`) |
| `OPEN_FLEET_ROOT` | `ORCA_FLEET_ROOT` | Fleet catalog root directory (`preflight.py` refuses when both are set to different paths) |
| `OPEN_FLEET_STATE_DB` | `ORCA_FLEET_STATE_DB` | `posix` state store database path |
| `OPEN_FLEET_STATE_DIR` | `ORCA_FLEET_STATE_DIR` | Directory holding the `posix` state store's `runtime.db` |
| `OPEN_FLEET_SANDBOX_PROFILE` | `ORCA_SANDBOX_PROFILE` | Worker sandbox profile (`ro`, `rw`, `danger`) |
| `OPEN_FLEET_PARENT_PROFILE` | `ORCA_PARENT_PROFILE` | Parent worker's sandbox profile for monotonic narrowing (`ro < rw < danger`) |
| `OPEN_FLEET_UNIT_WORKTREE` | `ORCA_UNIT_WORKTREE` | Active worker worktree boundary enforced by `deny-hook.sh` |
| `OPEN_FLEET_GATE_MANIFEST` / `OPEN_FLEET_MANIFEST` | `ORCA_MANIFEST` | Evidence manifest path verified by `verify-gate.sh` |
| `OPEN_FLEET_UNIT_CLASS` | `ORCA_UNIT_CLASS` | Unit class (`mutation`, `report-only`, `planning`) for `verify-gate.sh` |
| `OPEN_FLEET_EGRESS_LEDGER` | `ORCA_EGRESS_LEDGER` | Hash-chained off-repo egress receipt ledger path (`egress.py`) |
| `OPEN_FLEET_DECISIONS_FILE` | `ORCA_DECISIONS_FILE` | Decisions log path (`decisions.py`) |

---

## Capability matrix and preflight enforcement

[`runtime/providers/capabilities.json`](../runtime/providers/capabilities.json) declares the 8 runtime capabilities, each provider's native and portable fallback capabilities, and each mission's required and optional capabilities:

| Capability ID | Description | Portable fallback |
|---|---|---|
| `cap:core-orchestration` | Worktree lifecycle, run/task state, worker spawn/fence, and two-way mailbox messaging | `runtime/providers/local_state.py` (SQLite WAL + `git worktree` + `tmux` / `cmux` / `setsid`) |
| `cap:sandbox-vm` | Disposable VM or container isolation for untrusted execution and recipe checks | `posix` only: Docker `--on <image>` launch certified by `vm recipe doctor` + [`runtime/scripts/sandbox_doctor.py`](../runtime/scripts/sandbox_doctor.py) (recipes: `docker`, `bwrap`, `gondolin`, `devcontainer`, `hermes-docker`, `apptainer`, `superset-cloud`, `openhands-docker`). Never claimed by an adapter without a real doctor. |
| `cap:session-search` | Cross-session transcript search for prior-art recall | [`runtime/scripts/search_sessions.py`](../runtime/scripts/search_sessions.py) `--local-harnesses` (read-only token scan of 10 harnesses' local stores; no index) |
| `cap:browser` | Headless browser DOM snapshot, console/network capture, and CWV/a11y probing | Playwright CLI / Chrome DevTools MCP |
| `cap:mobile-emulator` | iOS Simulator and Android Emulator lifecycle, screenshot, and UI hierarchy dump | `xcrun simctl` (macOS) and Android `adb` |
| `cap:issue-tracker` | Issue and pull-request enumeration, creation, commenting, and state transitions | GitHub CLI (`gh`) and `runtime/scripts/pm.py` |
| `cap:scheduler` | Recurring cron/interval execution for unattended sweeps | POSIX `crontab` / `systemd-run` / GitHub Actions `schedule` |
| `cap:orca-self-audit` | Live inspection of the proprietary `stablyai/orca` binary and `orca skills get` bundle | None — exclusive to `orca` (required only by [`skills/pin-it/SKILL.md`](../skills/pin-it/SKILL.md)) |

### Running capability preflight

[`runtime/scripts/preflight.py`](../runtime/scripts/preflight.py) checks mission capability requirements against the selected runtime provider and fails closed (exit `2`) when a required capability is unavailable. A fallback only counts when its tools are present (`adb`/`xcrun` for `cap:mobile-emulator`; `docker` for `cap:sandbox-vm` on `posix`, whose sandbox is Docker-only). `capabilities.json` is the single source of truth: each provider's `capabilities()` reads it.

```bash
# General missions pass on posix and all other RPI providers:
python3 runtime/scripts/preflight.py --mission ship-it --runtime posix --mode readonly

# pin-it requires cap:orca-self-audit and fails closed on non-orca runtimes:
python3 runtime/scripts/preflight.py --mission pin-it --runtime posix --mode readonly
# -> exit 2: preflight: ERROR: mission 'pin-it' cannot run on runtime 'posix' — missing_capability: cap:orca-self-audit

# Require native provider capabilities without portable fallbacks:
python3 runtime/scripts/preflight.py --mission offload-it --runtime posix --strict-native-capabilities --mode readonly
```

---

## Supported orchestrator providers (14)

All 14 providers implement [`RuntimeProvider`](../runtime/providers/base.py) and return Orca-compatible JSON envelopes so existing coordinator scripts (`task_ops.py`, `worker_ops.py`, `worktree_ops.py`, `terminal_ops.py`, `send_msg.py`, `check_reply.py`, `hitl_ask.py`, `watchdog.py`) work without modification.

Every adapter delivers the task spec to the worker (`resolve_task_prompt`), refuses unparseable upstream output instead of inventing ids, treats `worker-retain` as non-destructive, preserves the worker's real HEAD (`refs/open-fleet/preserved/<dispatch>`) before any destructive cleanup, and fails closed (`unsupported_operation` / `unsupported_profile`) where upstream has no verified way to honour a profile. Only `cap:core-orchestration` (plus Beads on `gastown`) is native on the external adapters; everything else is a portable fallback.

### Tier 1 — Primary providers

| Provider | Upstream | Transport | Profiles | Native capabilities |
|---|---|---|---|---|
| `orca` | `stablyai/orca` | Native desktop/CLI control plane | ro, rw, danger | All 8 capabilities including `cap:orca-self-audit` |
| `posix` | `open-fleet/posix` | SQLite WAL + `git worktree` + `tmux` / `cmux` / `setsid`; `danger` = Docker (`--cap-drop ALL`, `no-new-privileges`, private git dir synced back on exit) | ro, rw, danger | `cap:core-orchestration` (`cap:sandbox-vm` by fallback when Docker is present) |
| `overstory` | `jayminwest/overstory` | `ov sling` / `ov spec write` / `ov mail`; Overstory's own guard hooks | ro (claude, pi, sapling), rw | `cap:core-orchestration` |
| `t3code` | `pingdotgg/t3code` | MCP `t3_thread_*` tools via `t3 acp-mcp-call` (`T3_ACP_MCP_ENDPOINT`, `T3_ACP_MCP_AUTHORIZATION`, `OPEN_FLEET_T3_PROJECT_ID`) | ro, rw | `cap:core-orchestration` |
| `ao` | `ComposioHQ/agent-orchestrator` | Loopback HTTP daemon `POST /api/v1/sessions` | rw | `cap:core-orchestration` |
| `superset` | `superset-sh/superset` | `superset terminals create` (ro), `agents create --prompt` (rw), `workspaces create --environment` (danger, cloud; not advertised, no recipe doctor certifies it) | ro, rw | `cap:core-orchestration` |

### Tier 2 — Ecosystem adapters

| Provider | Upstream | Transport | Profiles | Native capabilities |
|---|---|---|---|---|
| `gastown` | `gastownhall/gastown` | `gt sling <bead>` + `bd` beads graph (`bd dep add`), `gt mail`, `gt polecat status` | ro, rw | `cap:core-orchestration`, `cap:issue-tracker` |
| `worktrunk` | `max-sixty/worktrunk` | `wt switch --create` + agent detached in `tmux`; `wt remove --reap` after HEAD is preserved | ro, rw | `cap:core-orchestration` |
| `jcode-swarm` | `1jehuang/jcode` | `jcode serve` daemon socket (`comm_spawn` / `comm_read_context` / `comm_stop`) | rw (jcode only) | `cap:core-orchestration` |
| `emdash` | `generalaction/emdash` | workspace-server unix socket (`workspace.sock`, framed wire protocol 12.0.0) | ro (claude), rw | `cap:core-orchestration` |
| `vibe-kanban` | `BloopAI/vibe-kanban` | REST `POST /api/workspaces/start`; `ORCA_RO` executor variant; post-exit auto-commit guard (reject by default) | ro (claude), rw | `cap:core-orchestration` |
| `paperclip` | `paperclipai/paperclip` | REST control plane (port 3100): `adapterConfig` flags read back, atomic checkout, bwrap for danger (not advertised, no recipe doctor certifies it) | ro (claude), rw | `cap:core-orchestration` |
| `multiclaude` | `dlorenc/multiclaude` | Daemon socket `spawn_agent` + tmux; hooks via `.multiclaude/hooks.json`; release needs `orchestration worker-verify` | ro, rw (claude only) | `cap:core-orchestration` |
| `openhands` | `OpenHands/software-agent-sdk` | agent-server REST conversations (port 8000) with request-level deny-hook config; danger only on a docker runtime (not advertised, no recipe doctor certifies it) | ro, rw | `cap:core-orchestration` |

### `posix` launch crash recovery (#597)

A `posix` `worker-start` crosses six boundaries, in this order. A coordinator killed between two of
them (SIGKILL, power loss) leaves state that a restarted coordinator settles by the launch's
**recorded identity**, never by a guess from process exit. Every boundary name is in
`LAUNCH_BOUNDARIES` ([`runtime/providers/posix.py`](../runtime/providers/posix.py)).

| # | Boundary | What is durable after it | What a restarted coordinator does |
|---|---|---|---|
| 1 | `intent_claimed`: ONE transaction writes the launch intent (pre-minted dispatch id, terminal handle, lane dir, planned worktree, owner token, epoch 1), claims the task (`ready → dispatched`) and records the request `pending` with its payload hash | the intent, at phase `claimed` | Hands the claim back (task → `ready`). No dispatch row exists, so no monitor can pass the launch gate. The request → `failed` |
| 2 | `worktree_created`: `git worktree add`, plus the hooks (a side effect, no commit) | as 1 | Same as 1. The worktree is kept, named in the receipt, and its HEAD is pinned |
| 3 | `registered`: terminal and dispatch rows, plus the intent's phase `registered`, in one transaction | dispatch `ready`, pid 0 | Abandons the dispatch if no monitor has claimed the launch gate, and adopts it otherwise (see the gate below) |
| 4 | `monitor_spawned`: the setsid, tmux or cmux monitor starts (a side effect) | as 3 | Adopts the monitor that claimed the gate and publishes its pid. Otherwise it abandons, as in 3 |
| 5 | `published`: pid and backend, plus the phase `published` | the dispatch carries its pid | Adopts it, or tears it down when an operator fenced it during startup |
| 6 | `receipted`: the request → `completed` and the intent's outcome → `completed`, in one transaction | final | Nothing to settle. A retry replays the receipt |

**One monitor per dispatch.** The generated monitor's launch gate is a compare-and-set
(`LocalStateStore.claim_monitor`). It records the monitor's pid only while the dispatch is live
and no other monitor holds it. Reconciliation abandons an unlaunched dispatch with the opposite
compare-and-set (`abandon_unlaunched`), so exactly one of the two wins. A monitor that starts late
(a launcher that outlived its coordinator) is refused at the gate. Neither path ever spawns a
replacement monitor: recovery rolls back or adopts, it never respawns. `worker-stop` and the
liveness sweep use the gate-recorded pid when no pid was published. Before this change, a
coordinator killed after the spawn left `pid 0`, and a stop recorded `stopped` while the agent kept running.

**Ownership and takeover.** While a coordinator launches, it holds an exclusive `flock` on
`<state dir>/intents/<intent>.lock`, and it checks its owner token in the same transaction as
every later commit. The kernel drops the lock when the process dies. A free lock on an open intent
on the same host therefore proves that its owner is gone. `orchestration launch-reconcile [--intent <id> | --request <id>]`
settles such intents. `worker-list`, `worker-show` and a `worker-start` for the same task settle
them automatically, except an `unknown` one, which waits for an explicit `launch-reconcile`.
When the owner is alive, or on another host, the intent is reported `pending` or `unknown` and
left untouched, unless `--takeover` is passed. A takeover swaps the owner token
and bumps the epoch, so the old writer's next commit fails with `launch_fenced`. A fenced writer
releases nothing, deletes nothing and terminates nothing; the new owner decides. One reconciler
settles an intent at a time: every settler, a takeover included, first holds the exclusive
`<state dir>/intents/<intent>.recovery.lock`. Without that lock, a takeover settles while the
fenced owner still holds the launch lease, and once that owner exits, a `worker-list` could
settle the same intent beside it. A second reconciler that finds the lock held reports `pending`
and changes nothing. A lease or lock file is removed only by its holder. Reconciliation
never mints ids, so the run, task, dispatch and terminal ids the worker was launched with are the
ones that the receipt and the dispatch row keep. Launch fencing is per intent, and it is separate
from the mailbox fencing of `run-use --takeover-legacy`.

**Requests.** A `--retry-request` id names one launch attempt. Its state is `pending`, then one
of `completed` (an owned dispatch: live, or already settled by its own monitor), `failed` (an
explicitly failed attempt that launched nothing or was fenced) or `unknown` (an inspectable state
with `nextCommands`; reconcile visits it again). A retry with the same id and payload replays the
outcome. It never starts a second worker: `failed` re-raises the recorded error, and a pending
attempt whose owner is alive answers `outcome_unknown`. A retry with the same id and a different
payload (task, worktree, agent, name, run, profile, parent profile, prompt, effort, sandbox recipe,
`--retry-of`) is refused as `request_mismatch` and never reuses the result. A failed attempt
returns its task to `ready`, so a new attempt takes a NEW request id.

**The recovery receipt** (`launch_intents.receipt_json`, plus `<lane>/recovery.json` when the lane
exists, and the `recovery` field of the request's response) names the previous owner (pid, host,
epoch, whether it was alive) and every process the reconciler found (monitor pid, backend ref,
container), with what it did to each (`adopted`, `terminated`, `none`). It also names the
preserved refs (`refs/open-fleet/preserved/<dispatch>` at the worktree HEAD, and
`refs/open-fleet/sandbox/<dispatch>` when it salvaged a sandbox), the task and dispatch states
before and after, and the cleanup (what was kept, abandoned or removed). Reconciliation never
deletes a worktree or a branch. Its receipt always carries `completionInferred: false`: a dispatch
only becomes `completed` through the worker's own terminal mail
(`ensure_terminal_or_died`). A monitor that vanished gets the synthetic `worker_died`. When that
monitor ran a `danger` sandbox, its private git dir is first synced back (`docker rm -f`, then
`sync_sandbox_git`), so the worker's commits survive.

**What is tested** ([`tests/test_posix_crash_recovery.py`](../tests/test_posix_crash_recovery.py),
[`tests/test_posix_docker_crash.py`](../tests/test_posix_docker_crash.py)):
- **setsid**: a real coordinator subprocess is SIGKILLed at each boundary above, with an inert fake
  agent. The suite also covers takeover of a live owner, a late monitor and an uninterrupted control.
- **Docker `danger`**: crash-tested against a REAL daemon in an opt-in tier. Run it with
  `OPEN_FLEET_DOCKER_CRASH_TEST=1 python3 -m unittest tests.test_posix_docker_crash`. The tier
  SIGKILLs the coordinator at every boundary above. It also crashes the host after publication,
  which leaves the container orphaned; recovery removes the container and syncs its commit back.
  Its uninterrupted control runs one container and syncs its commit. The worker runs in the
  [`tests/fixtures/posix-crash-docker`](../tests/fixtures/posix-crash-docker/Dockerfile) image:
  alpine pinned by digest, plus git and an inert `claude`, built locally as
  `open-fleet-test/posix-crash:<content hash>`. Without the opt-in, a reachable daemon or a
  buildable image, its cases are not loaded and the run prints `real-docker crash tier: NOT RUN`.
  It never counts as a pass. The default suite covers the same `danger` path only against a fake
  `docker` CLI. Last real run: 2026-10-23, Docker 29.8.2 (OrbStack, linux/arm64), 12 of 12 passed.
- **tmux and cmux**: they share the reconciliation code (tmux adoption fills the
  `openfleet-<handle>` session name; a cmux workspace id that was never published stays unknown),
  but neither is crash-tested.
- **Out of scope**: `terminal create` and `dispatch --inject` keep their own row-first ordering
  and have no launch intent.

---

## Supported coding-agent harnesses & sandbox profiles

[`runtime/providers/base.py`](../runtime/providers/base.py) (`build_harness_command`) and [`runtime/sandbox-policy.md`](../runtime/sandbox-policy.md) enforce three least-privilege worker profiles with **monotonic privilege narrowing** (`ro < rw < danger` — a parent running under `ro` can never spawn a `rw` or `danger` child):

- **`ro` (read-only)**: reviewers, research workers, root-cause investigators, and spec auditors. All file mutation and arbitrary shell execution tools are disabled at the CLI flag/config level and guarded by `deny-hook.sh`.
- **`rw` (worktree-scoped read-write)**: slice builders, bug fixers, and test authors. Mutations outside `OPEN_FLEET_UNIT_WORKTREE` / `ORCA_UNIT_WORKTREE` and destructive git/GitHub commands are blocked by `deny-hook.sh`.
- **`danger` (disposable sandbox)**: exploit PoCs and full-container operations inside an isolated VM/container (`cap:sandbox-vm`).

| Harness | Binary | `PROFILE=ro` enforcement | `PROFILE=rw` / `danger` enforcement |
|---|---|---|---|
| Claude Code | `claude` | `claude -p --permission-mode plan --disallowedTools Edit,Write,MultiEdit,NotebookEdit` | `claude -p --dangerously-skip-permissions` + `PreToolUse` `deny-hook.sh` |
| OpenAI Codex | `codex` | `codex exec --json -C <wt> --sandbox read-only -c 'approval_policy="never"'` | `codex exec --json -C <wt> --dangerously-bypass-approvals-and-sandbox` + `deny-hook.sh` |
| OpenCode | `opencode` | `OPENCODE_CONFIG_CONTENT='{"permission":{"*":"allow","edit":"deny","bash":"deny","external_directory":"deny"}}' opencode run --standalone` | `opencode run --auto --standalone --format json --dir <wt>` + plugin bridge |
| Oh My Pi (`omp`) | `omp` | `omp -p --mode json --cwd <wt> --no-session --no-lsp --tools read,grep,glob,find,ast_grep --approval-mode always-ask` | `omp -p --mode json --cwd <wt> --yolo --trusted-extension omp_pi_deny_bridge.ts` |
| Pi (`pi-mono`) | `pi` | `cd <wt> && pi -p --mode json --no-session --no-mcp -ne -na --tools read,grep,find,ls --exclude-tools 'bash,powershell,write,edit,codemode,mcp__*'` | `cd <wt> && pi -p --mode json -e omp_pi_deny_bridge.ts --tools read,bash,edit,write,grep,find,ls` |
| `jcode` | `jcode` | `jcode -C <wt> --no-update -q --tools read,agentgrep,ls,session_search,conversation_search,memory,web_search --disabled-tools bash,write,edit,replace,apply_patch,swarm,selfdev,desktop_selfdev,bg,codemode,mcp run` | `JCODE_HOOK_PRE_TOOL=deny-hook.sh jcode -C <wt> --no-update -q --disabled-tools selfdev,desktop_selfdev run` |
| Goose | `goose` | `GOOSE_MODE=auto goose run --output-format stream-json --no-profile --with-builtin analyze` | `GOOSE_MODE=auto goose run --output-format stream-json --no-profile --with-builtin developer` |
| Hermes Agent | `hermes` | `HERMES_WRITE_SAFE_ROOT=/dev/null hermes --in <wt> --accept-hooks chat --oneshot -Q --toolsets file,web,session_search` | `HERMES_WRITE_SAFE_ROOT=<wt> hermes --in <wt> --yolo --accept-hooks chat --oneshot -Q --toolsets coding` |
| Crush | `crush` | `crush --cwd <wt> --data-dir <wt>/.crush-orca-ro run -q` (`disabled_tools`: bash, write, edit, multiedit, download, lsp_rename, lsp_replace_symbol, agent, agentic_fetch, job_kill, job_output) | `crush --cwd <wt> --data-dir <wt>/.crush --yolo run -q` |
| Gemini CLI | `gemini` | `gemini --approval-mode plan -p <task>` | `gemini --yolo -p <task>` (no deny-hook config is installed for Gemini; the `rw` boundary rests on the worktree/sandbox) |
| Cursor / Antigravity / Grok / Droid | `cursor` / `agy` / `grok` / `droid` | Refused on `PROFILE=ro` (`unsupported_profile`: no verified read-only CLI flag) | Refused whenever a task prompt is given (`unsupported_prompt`: no verified headless prompt flag, so the worker would start without its assignment) |

**Guard installation.** `install_worktree_hooks` points every harness config at the canonical `runtime/scripts/deny-hook.sh` (never a copy inside the worktree), git-excludes the generated configs, and prefixes non-Claude hook commands with `ORCA_HOOK_STRICT_EXIT=1` so an `ask` becomes exit 2 on harnesses that fail open on `ask`. Hermes gets a per-dispatch `HERMES_HOME` outside the worktree whose `config.yaml` adds a `fail_closed` `pre_tool_call` hook; the hook refuses edits to its own configs. Workers inherit `OPEN_FLEET_PARENT_PROFILE=<own profile>`, so a child can never exceed its parent.
