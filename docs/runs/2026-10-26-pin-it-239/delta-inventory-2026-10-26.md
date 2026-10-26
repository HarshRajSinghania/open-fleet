# Delta inventory — Orca v1.4.238 → v1.4.239 (pin-it, 2026-10-26)

Source range: tag `v1.4.238` (`e6f7fba5`) to tag `v1.4.239` (`47f77cf7`), 8,964 files changed, read
from a local clone (`receipts/oracle-2026-10-26.txt`). Live: the installed Orca.app and CLI
1.4.239 (`receipts-live-2026-10-26/`, captured by `upstream_probe.py capture`), and the #680
ro/claude worker witness ([run report](../2026-10-26-review-it-orca-ro-680.md)).

## Findings (D239)

| ID | What moved | Doctrine | Action |
|---|---|---|---|
| D239-1 | A terminal launch's permission is a stored choice per agent: `own`, `ask`, `accept-edits`, `auto` or `full-access` (`tui-agent-permission-choice.ts:17-23`). Its flag goes before the user's `agentDefaultArgs` text (`tui-agent-launch-defaults.ts:165-179`). `full-access` is the YOLO map, and an older host with no stored choice keeps the migrated YOLO default (`:37-38`). | `sandbox-policy.md` named three host modes (YOLO, manual `''`, Auto). | PATCHED: `sandbox-policy.md` names the stored choice. `spawn_worker.sh`'s comment follows. The wrapper's exit 5 on anything but the rw flag is unchanged and test-pinned. |
| D239-2 | `dispatch --inject` cannot see a native Claude Code install: the process is named for its version, and an idle Claude sets no title. `agent-process-recognition.ts`, `claude.json` and `runtime-terminal-agent-presence.ts` are unchanged since v1.4.238. | The ro lane refused every native-install host. | PATCHED in #700: the guarded no-inject fallback, live-witnessed. |
| D239-3 | Helper workers: with nesting on, a worker's SUB-DISPATCH section starts helpers in its own Run (`preamble.ts:244-262`). The nesting default is unchanged (`NESTED_WORKER_MAX_DEPTH_DEFAULT = 1`), and the witness preamble carried no SUB-DISPATCH section. | `dispatch-lifecycle.md`: workers do not dispatch sub-workers at the default depth. | CURRENT. The change is additive and off by default. |
| D239-4 | `ask --timeout-ms` accepts 1 to 1800000 ms (default 600000); the spec note and the worker-contract guide say so. | `hitl_ask.py` already enforces 1..1800000. | CURRENT |
| D239-5 | `connector start\|send\|prompt\|answer\|cancel\|watch` (6 new paths; 287 → 293 by spec source); `terminal split --retry-split`, `skills install\|update --force`, `serve --supervise`. | No fleet script uses them. | Noted (additive) |
| D239-6 | An upstream comment audit rewrote comments in place (e.g. `message-check-handler.ts`, `check-keepalive.ts`). The code and its line numbers are unchanged. | Cited lines still show the cited code. | CURRENT |

Unchanged at v1.4.239 (`receipts/key-files-v1.4.238-v1.4.239.txt`):
- schema v43 (`contract-constants.ts:23`);
- `dispatch-methods.ts`, `runtime-terminal-send-contract.ts`, `tui-agent-config.ts`, `tui-agent-permissions.ts` (the YOLO and Auto maps), `dispatch-depth.ts` and `worker-launch-preferences.ts`, whose launch receipt's `effective` still carries agent, model and effort only.

The CLI command specs gained only the paths and flags in D239-5. Eight of the twelve bundled guides are byte-identical to the v1.4.238 archive; four gained the D239-3 and D239-4 text (`receipts/guides-v1.4.238-vs-installed-1.4.239.txt`).

## Citations (`receipts/citations-v1.4.238-v1.4.239.json`)

101 upstream citations in `runtime/`, `playbooks/` and `skills/`, compared at both tags. 66 cite the same text at the same lines. Each of the other 35:

| Where | Citation | Verdict at v1.4.239 |
|---|---|---|
| `attention-budget.md:58` | `account.ts:297-307` | MOVED → `:273-283`, claim holds; re-anchored |
| `dispatch-lifecycle.md:17` | `local-worker-start.ts:263` | versioned (v1.4.199/v1.4.200 history); unchanged |
| `dispatch-lifecycle.md:65` | `core.ts:108,127` | CURRENT (`specs/core.ts`, same lines) |
| `dispatch-lifecycle.md:122` | `message-methods.ts:113` | MOVED → `:138` (the reply path); re-anchored |
| `dispatch-lifecycle.md:123,126`; `pm.py:10,106` | `message-check-handler.ts:98-107`, `check-keepalive.ts:18-26` | CURRENT (D239-6) |
| `gate-classification.md:45` | `types.ts:39` | UNRESOLVED, and already so at v1.4.238: no orchestration `types.ts` holds the gate states at line 39. Flagged for an anchor audit; `create-graph-tables-sql.ts:190` beside it is CURRENT |
| `liveness-resume.md:47` | `orchestration.ts:115`, `:267-272` | `specs/orchestration.ts` identical at both tags, but the lines do not show the cited behaviour (already so at v1.4.238). Flagged |
| `liveness-resume.md:62` | `terminal-send.ts:19-20` | CURRENT (`specs/terminal-send.ts`) |
| `mission-scheduling.md:24,47,76,82` | `automations.ts:…` | versioned (v1.4.203, v1.4.229, `ee1c5220`); unchanged |
| `orca-dag-semantics.md:56` | `message-inbox.ts:81` | MOVED → `:82`; `:81` kept, because `tests/test_orphan_wiring.py` pins it, with `:82 at v1.4.239` beside it |
| `orca-pin.md:124,125,131` | `core.ts:240-246`, `handlers/terminal.ts:137-142` | dated history (2026-09-26/28, v1.4.215); unchanged. `terminal stop` is still a hidden spec (`core.ts:206`) with its handler (`handlers/terminal.ts:142`) at v1.4.239 |
| `sandbox-policy.md:12` | `tui-agent-launch-defaults.ts:18-19` | rewritten for D239-1 (`:37-38`, `:165-179`) |
| `sandbox-policy.md:39` | `tui-agent-launch-defaults.ts:13-16` | MOVED → `:23-26`; re-anchored |
| `spawn_worker.sh:10,14` | `local-worker-start.ts:243-263` | versioned (v1.4.199); unchanged |
| `spawn_worker.sh:30` | `runtime-terminal-contracts.ts:221-225` | named as a stale anchor (history); unchanged |
| `spawn_worker.sh:40` | `terminal.ts:125-129` | versioned (v1.4.203); unchanged |
| `spawn_worker.sh:44` | `tui-agent-launch-defaults.ts:10` | stale before v1.4.238 (an import line); rewritten for D239-1 (`:37-38`, `:165-179`) |
| `spawn_worker.sh:52,393` | `tui-agent-launch-defaults.ts:10`, `:5-8` | versioned (v1.4.203); unchanged |
| `spawn_worker.sh:133` | `tui-agent-launch-defaults.ts:5-8` | stale before v1.4.238; re-anchored → `:23-26` |
| `spawn_worker.sh:642` | `vm.ts:6-9` | CURRENT (`specs/vm.ts`) |
| `spawn_worker.sh:1114,1116` | `dispatch-capability.ts:18`, `cli-error.ts:117` | a table verified at v1.4.203; unchanged |

## Drift tables

**Policies (16/16):**
- CURRENT 11: `conductor-close.md`, `evidence-manifest.md`, `gate-classification.md`, `ledger-contract.md`, `liveness-resume.md`, `merge-serialization.md`, `mission-chaining.md`, `mission-scheduling.md`, `reviewed-sha-freshness.md`, `threat-model.md`, `worker-supervision.md`.
- PATCHED 5:
  - `attention-budget.md`: anchor;
  - `dispatch-lifecycle.md`: anchor and the live-PIN line;
  - `orca-dag-semantics.md`: anchor and the schema line;
  - `orca-pin.md`: the pin record;
  - `sandbox-policy.md`: D239-1 and anchors.

**Scripts (45/45):**
- CURRENT 43: no command a script calls was removed or narrowed.
- PATCHED 2:
  - `spawn_worker.sh`: D239-1 comment and anchors, plus D239-2 (#700);
  - `orca_cli.py`: its fallback pin version.
