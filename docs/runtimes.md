# Multi-Runtime & Harness Guide (`open-fleet` RPI)

[Documentation Hub](README.md) · [Certification Matrix](certification.md) · [Runtime Scripts](runtime-scripts.md) · [Verify Gate](verify-gate.md)

`open-fleet` decouples mission outcomes, phase playbooks, and verification gates from any single orchestrator binary through the **Runtime Provider Interface (RPI)**. Every general mission runs across **14 orchestrator providers** and dispatches workers across **10 CLI coding-agent harnesses** (plus the `openhands` SDK agent) under uniform least-privilege sandbox profiles (`ro`, `rw`, `danger`).

> [!IMPORTANT]
> **Advertised vs. Certified:** Every provider, profile, and harness listed below has an explicit certification status in **[Provider & harness certification](certification.md)** (`live-witnessed`, `fixture-tested`, `source-only`, `refused`, or `unknown`). Today, Claude Code is live-witnessed on both the `orca` route (`ro`, `rw`) and the standalone `posix` route (`ro`, `rw`, bound [2026-10-24](runs/2026-10-24-review-it-first-run.md)).

---

## Selecting a runtime provider

Set `OPEN_FLEET_RUNTIME` (or the legacy alias `ORCA_FLEET_RUNTIME`) to choose how fleets manage worktrees, worker processes, and task state:

```bash
export OPEN_FLEET_RUNTIME=orca       # Default: stablyai/orca native desktop/CLI control plane
export OPEN_FLEET_RUNTIME=posix      # Standalone: SQLite WAL + git worktree + tmux / cmux / setsid (no Orca app needed)
export OPEN_FLEET_RUNTIME=auto       # Uses 'orca' if the binary is on PATH, otherwise falls back to 'posix'
export OPEN_FLEET_RUNTIME=overstory  # jayminwest/overstory `ov` CLI adapter
export OPEN_FLEET_RUNTIME=t3code     # pingdotgg/t3code MCP thread tools via `t3 acp-mcp-call`
export OPEN_FLEET_RUNTIME=ao         # ComposioHQ/agent-orchestrator loopback HTTP daemon
export OPEN_FLEET_RUNTIME=superset   # superset-sh/superset CLI adapter
```

### How standalone `posix` mode works

- **Zero-daemon SQLite state store:** Defaults to `~/.open-fleet/state/<repo-id>/runtime.db` (keyed by the repository's git common dir so linked worktrees share one store; override via `OPEN_FLEET_STATE_DB` or `OPEN_FLEET_STATE_DIR`). Concurrent openers safely contend for WAL initialization and run schema migrations inside `BEGIN IMMEDIATE` transactions.
- **Completion signaling for `ro` vs. `rw` workers:** `rw` workers report completion via `send_msg.py --type worker_done`. Because `PROFILE=ro` workers have shell and write access stripped, `worker_start` appends a completion marker instruction (`OPEN_FLEET_WORKER_DONE <dispatch-id> <succeeded|failed>`) on monitored backends (`setsid`, `tmux`, `cmux`). When the `ro` worker exits `0` with that exact marker as the final line of its final answer (parsed by [`runtime/providers/transcript.py`](../runtime/providers/transcript.py)), the exit monitor relays it as `worker_done`.

### Neutral environment variables

Runtime scripts accept `OPEN_FLEET_*` variables alongside legacy `ORCA_*` aliases. Shared provider helpers prefer a non-empty `OPEN_FLEET_*` value; conflict rejection is helper-specific, not a blanket guarantee:

| Primary (`open-fleet`) | Legacy alias | Purpose |
|---|---|---|
| `OPEN_FLEET_RUNTIME` | `ORCA_FLEET_RUNTIME` | Active RPI provider (`orca`, `posix`, `overstory`, `t3code`, `ao`, `superset`, `gastown`, `worktrunk`, `jcode-swarm`, `emdash`, `vibe-kanban`, `paperclip`, `multiclaude`, `openhands`, or `auto`) |
| `OPEN_FLEET_ROOT` | `ORCA_FLEET_ROOT` | Catalog root directory |
| `OPEN_FLEET_STATE_DB` / `OPEN_FLEET_STATE_DIR` | `ORCA_FLEET_STATE_DB` / `ORCA_FLEET_STATE_DIR` | `posix` SQLite state store path or directory |
| `OPEN_FLEET_SANDBOX_PROFILE` | `ORCA_SANDBOX_PROFILE` | Worker sandbox profile (`ro`, `rw`, `danger`) |
| `OPEN_FLEET_PARENT_PROFILE` | `ORCA_PARENT_PROFILE` | Parent worker profile enforcing monotonic narrowing (`ro < rw < danger`) |
| `OPEN_FLEET_COORD_ALLOW_AUTONOMOUS_WRITE` | `ORCA_COORD_ALLOW_AUTONOMOUS_WRITE` | Explicit coordinator opt-in (`=1`) required before `spawn_worker.sh` launches a `PROFILE=rw` worker |
| `OPEN_FLEET_COORD_ALLOW_DANGER` | `ORCA_COORD_ALLOW_DANGER` | Explicit coordinator opt-in (`=1`) required alongside a placement-bound recipe before launching `PROFILE=danger` |
| `OPEN_FLEET_SANDBOX_RECIPE` | `ORCA_SANDBOX_RECIPE` | Certified disposable sandbox recipe ID for `PROFILE=danger` (`sandbox_doctor.py --require-placement`) |
| `OPEN_FLEET_UNIT_WORKTREE` | `ORCA_UNIT_WORKTREE` | Active worker worktree boundary enforced by `deny-hook.sh` |
| `OPEN_FLEET_GATE_MANIFEST` / `OPEN_FLEET_MANIFEST` | `ORCA_MANIFEST` | Evidence manifest path read by `verify-gate.sh` |
| `OPEN_FLEET_UNIT_CLASS` | `ORCA_UNIT_CLASS` | Unit class (`mutation`, `report-only`, `planning`) |
| `OPEN_FLEET_EGRESS_LEDGER` | `ORCA_EGRESS_LEDGER` | Hash-chained egress receipt ledger path (`egress.py`) |
| `OPEN_FLEET_DECISIONS_FILE` | `ORCA_DECISIONS_FILE` | Decisions audit log path (`decisions.py`) |

---

## Capability matrix and preflight enforcement

[`runtime/providers/capabilities.json`](../runtime/providers/capabilities.json) defines 8 runtime capabilities, each provider's native vs. portable fallback support, and each mission's required capabilities:

| Capability ID | Description | Portable fallback |
|---|---|---|
| `cap:core-orchestration` | Worktree lifecycle, run/task DAG state, worker spawn/fence, and mailbox messaging | `runtime/providers/local_state.py` (SQLite WAL + `git worktree` + `tmux` / `cmux` / `setsid`) |
| `cap:sandbox-vm` | Disposable VM or container isolation for untrusted execution and recipe checks | `posix` Docker `--on <image>` launch certified by [`runtime/scripts/sandbox_doctor.py`](../runtime/scripts/sandbox_doctor.py) (`docker`, `bwrap`, `gondolin`, `devcontainer`, `hermes-docker`, `apptainer`, `superset-cloud`, `openhands-docker`) |
| `cap:session-search` | Cross-session transcript search for prior-art recall | [`runtime/scripts/search_sessions.py`](../runtime/scripts/search_sessions.py) `--local-harnesses` |
| `cap:browser` | Headless browser DOM snapshot, console/network capture, and CWV/a11y probing | Playwright CLI / Chrome DevTools MCP |
| `cap:mobile-emulator` | iOS Simulator and Android Emulator lifecycle, screenshot, and UI hierarchy dump | `xcrun simctl` (macOS) and Android `adb` |
| `cap:issue-tracker` | Issue and PR enumeration, creation, commenting, and state transitions | GitHub CLI (`gh`) and `runtime/scripts/pm.py` |
| `cap:scheduler` | Recurring cron/interval execution for unattended sweeps | POSIX `crontab` / `systemd-run` / GitHub Actions `schedule` |
| `cap:orca-self-audit` | Live inspection of the `stablyai/orca` binary and `orca skills get` bundle | **None** — exclusive to `orca` (required only by [`pin-it`](../skills/pin-it/SKILL.md)) |

### Running capability preflight

[`runtime/scripts/preflight.py`](../runtime/scripts/preflight.py) verifies mission capability requirements against the active runtime provider and fails closed (exit `2`) when a required capability is missing:

```bash
# General missions pass on posix and all other RPI providers:
python3 runtime/scripts/preflight.py --mission ship-it --runtime posix --mode readonly

# pin-it requires cap:orca-self-audit and fails closed on non-orca runtimes:
python3 runtime/scripts/preflight.py --mission pin-it --runtime posix --mode readonly

# Require native provider capabilities without portable fallbacks:
python3 runtime/scripts/preflight.py --mission offload-it --runtime posix --strict-native-capabilities --mode readonly
```

---

## Supported orchestrator providers (14)

All 14 providers implement [`RuntimeProvider`](../runtime/providers/base.py) and return Orca-compatible JSON envelopes so coordinator scripts (`task_ops.py`, `worker_ops.py`, `worktree_ops.py`, `terminal_ops.py`, `send_msg.py`, `check_reply.py`, `hitl_ask.py`, `watchdog.py`) run unchanged. Every adapter preserves worker commits under `refs/open-fleet/preserved/<dispatch>` before cleanup and fails closed on unsupported profiles or unverified harnesses.

### Tier 1 — Primary providers

| Provider | Upstream | Transport | Profiles | Native capabilities |
|---|---|---|---|---|
| `orca` | `stablyai/orca` | Native desktop/CLI control plane | `ro`, `rw` (`danger` refused; requires off-`orca` placement binding) | All 8 capabilities including `cap:orca-self-audit` |
| `posix` | `open-fleet/posix` | SQLite WAL + `git worktree` + `tmux` / `cmux` / `setsid`; `danger` = Docker (`--cap-drop ALL`, `no-new-privileges`, private git dir synced on exit) | `ro`, `rw`, `danger` | `cap:core-orchestration` (`cap:sandbox-vm` when Docker is available) |
| `overstory` | `jayminwest/overstory` | `ov sling` / `ov spec write` / `ov mail` | `ro` (`claude`, `pi`, `sapling`), `rw` | `cap:core-orchestration` |
| `t3code` | `pingdotgg/t3code` | MCP `t3_thread_*` tools via `t3 acp-mcp-call` | `ro`, `rw` | `cap:core-orchestration` |
| `ao` | `ComposioHQ/agent-orchestrator` | Loopback HTTP daemon `POST /api/v1/sessions` | `rw` | `cap:core-orchestration` |
| `superset` | `superset-sh/superset` | `superset terminals create` (`ro`), `agents create --prompt` (`rw`) | `ro`, `rw` | `cap:core-orchestration` |

### Tier 2 — Ecosystem adapters

| Provider | Upstream | Transport | Profiles | Native capabilities |
|---|---|---|---|---|
| `gastown` | `gastownhall/gastown` | `gt sling <bead>` + `bd` beads graph, `gt mail`, `gt polecat status` | `ro`, `rw` | `cap:core-orchestration`, `cap:issue-tracker` |
| `worktrunk` | `max-sixty/worktrunk` | `wt switch --create` + detached `tmux`; `wt remove --reap` after HEAD preservation | `ro`, `rw` | `cap:core-orchestration` |
| `jcode-swarm` | `1jehuang/jcode` | `jcode serve` daemon socket (`comm_spawn` / `comm_read_context` / `comm_stop`) | `rw` (`jcode` only) | `cap:core-orchestration` |
| `emdash` | `generalaction/emdash` | `workspace.sock` framed wire protocol | `ro` (`claude`), `rw` | `cap:core-orchestration` |
| `vibe-kanban` | `BloopAI/vibe-kanban` | REST `POST /api/workspaces/start` + post-exit auto-commit guard | `ro` (`claude`), `rw` | `cap:core-orchestration` |
| `paperclip` | `paperclipai/paperclip` | REST control plane (port 3100) with atomic checkout | `ro` (`claude`), `rw` | `cap:core-orchestration` |
| `multiclaude` | `dlorenc/multiclaude` | Daemon socket `spawn_agent` + `tmux` + `.multiclaude/hooks.json` | `ro`, `rw` (`claude` only) | `cap:core-orchestration` |
| `openhands` | `OpenHands/software-agent-sdk` | Agent-server REST conversations (port 8000) with `openhands` SDK agent | `ro`, `rw` | `cap:core-orchestration` |

### `posix` launch crash recovery

A `posix` `worker-start` crosses six atomic boundaries (`LAUNCH_BOUNDARIES` in [`runtime/providers/posix.py`](../runtime/providers/posix.py)) so a coordinator killed mid-launch (e.g., `SIGKILL` or power loss) reconciles deterministically via `orchestration launch-reconcile` without guessing from process exit codes:

| # | Boundary | Durable state after step | Recovery action on coordinator restart |
|---|---|---|---|
| 1 | `intent_claimed` | Launch intent recorded (`claimed`), task `ready → dispatched`, request `pending` | Releases task claim back to `ready`; marks request `failed` |
| 2 | `worktree_created` | `git worktree add` on `fleet/<name>` + worktree hooks installed | Releases task claim to `ready`; preserves worktree and pins HEAD |
| 3 | `registered` | Terminal and dispatch rows written (`ready`, `pid 0`), phase `registered` | Adopts monitor if it claimed the CAS launch gate (`claim_monitor`); otherwise abandons (`abandon_unlaunched`) |
| 4 | `monitor_spawned` | `setsid`, `tmux`, or `cmux` monitor process started | Adopts monitor if gate claimed and publishes its PID; otherwise abandons |
| 5 | `published` | Monitor PID and backend recorded, phase `published` | Adopts running dispatch or tears down if fenced during startup |
| 6 | `receipted` | Request and intent marked `completed` | Complete; idempotent `--retry-request` replays the stored receipt |

Key recovery invariants (tested across `setsid` and real Docker `danger` containers in [`tests/test_posix_crash_recovery.py`](../tests/test_posix_crash_recovery.py) and [`tests/test_posix_docker_crash.py`](../tests/test_posix_docker_crash.py)):
- **Single monitor CAS gate:** `LocalStateStore.claim_monitor` and `abandon_unlaunched` use mutually exclusive compare-and-set transitions so a late monitor can never start an abandoned dispatch.
- **Lock-fenced ownership:** Active launches hold `<state_dir>/intents/<intent>.lock` (`flock`), and recovery holds `<intent>.recovery.lock`. Passing `--takeover` bumps the epoch so any stale writer fails with `launch_fenced`.
- **Zero data loss on `danger` containers:** Before declaring a crashed Docker `danger` worker dead, reconciliation stops the container and syncs its private git directory back to `refs/open-fleet/sandbox/<dispatch>`.

---

## Supported coding-agent harnesses & sandbox profiles

[`runtime/providers/base.py`](../runtime/providers/base.py) (`build_harness_command`) and [`runtime/sandbox-policy.md`](../runtime/sandbox-policy.md) enforce three least-privilege profiles with monotonic privilege narrowing (`ro < rw < danger`):

| Harness | Binary | `PROFILE=ro` enforcement | `PROFILE=rw` / `danger` enforcement |
|---|---|---|---|
| **Claude Code** | `claude` | `claude -p --permission-mode plan --disallowedTools Edit,Write,MultiEdit,NotebookEdit` | `claude -p --dangerously-skip-permissions` + `PreToolUse` `deny-hook.sh` |
| **OpenAI Codex** | `codex` | `codex exec --json -C <wt> --sandbox read-only -c 'approval_policy="never"'` | `codex exec --json -C <wt> --dangerously-bypass-approvals-and-sandbox` + `deny-hook.sh` |
| **OpenCode** | `opencode` | `OPENCODE_CONFIG_CONTENT='{"permission":{"*":"allow","edit":"deny","bash":"deny","external_directory":"deny"}}' opencode run --standalone` | `opencode run --auto --standalone --format json --dir <wt>` + plugin bridge |
| **Oh My Pi (`omp`)** | `omp` | `omp -p --mode json --cwd <wt> --no-session --no-lsp --tools read,grep,glob,find,ast_grep --approval-mode always-ask` | `omp -p --mode json --cwd <wt> --yolo --trusted-extension omp_pi_deny_bridge.ts` |
| **Pi (`pi-mono`)** | `pi` | `cd <wt> && pi -p --mode json --no-session --no-mcp -ne -na --tools read,grep,find,ls --exclude-tools 'bash,powershell,write,edit,codemode,mcp__*'` | `cd <wt> && pi -p --mode json -e omp_pi_deny_bridge.ts --tools read,bash,edit,write,grep,find,ls` |
| **`jcode`** | `jcode` | `jcode -C <wt> --no-update -q --tools read,agentgrep,ls,session_search,conversation_search,memory,web_search --disabled-tools bash,write,edit,replace,apply_patch,swarm,selfdev,desktop_selfdev,bg,codemode,mcp run` | `JCODE_HOOK_PRE_TOOL=deny-hook.sh jcode -C <wt> --no-update -q --disabled-tools selfdev,desktop_selfdev run` |
| **Goose** | `goose` | `GOOSE_MODE=auto goose run --output-format stream-json --no-profile --with-builtin analyze` | `GOOSE_MODE=auto goose run --output-format stream-json --no-profile --with-builtin developer` |
| **Hermes Agent** | `hermes` | `HERMES_WRITE_SAFE_ROOT=/dev/null hermes --in <wt> --accept-hooks chat --oneshot -Q --toolsets file,web,session_search` | `HERMES_WRITE_SAFE_ROOT=<wt> hermes --in <wt> --yolo --accept-hooks chat --oneshot -Q --toolsets coding` |
| **Crush** | `crush` | `crush --cwd <wt> --data-dir <wt>/.crush-orca-ro run -q` (write/exec tools disabled) | `crush --cwd <wt> --data-dir <wt>/.crush --yolo run -q` |
| **Gemini CLI** | `gemini` | `gemini --approval-mode plan -p <task>` | `gemini --yolo -p <task>` (worktree/sandbox boundary) |
| **Cursor / Antigravity / Grok / Droid** | `cursor` / `agy` / `grok` / `droid` | Refused on `PROFILE=ro` (`unsupported_profile`: no verified read-only CLI flag) | Refused when a headless task prompt is supplied (`unsupported_prompt`) |

---

## Reproducing a first run on `posix`

You can validate the `posix` orchestration pipeline without spending API tokens using the inert harness, or inside the disposable container harness for live agent runs ([Provider & harness certification](certification.md#first-run-on-a-clean-host)):

```bash
# Inert verification (no live agent or API spend; runs in CI across all posix harnesses):
python3 runtime/scripts/certification.py check
python3 runtime/scripts/first_run.py --profile ro
python3 runtime/scripts/first_run.py --profile rw
python3 runtime/scripts/first_run.py probes
```

For live container-isolated runs (`--worker live`), follow the **[Live harness guide](guides/live-harness.md)** and **[Recording a live first run](certification.md#recording-a-live-first-run)**.
