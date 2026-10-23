# Provider and harness certification

[Documentation](README.md) · [Multi-runtime guide](runtimes.md) · [Runtime scripts](runtime-scripts.md) · [Troubleshooting](troubleshooting.md)

[Multi-runtime guide](runtimes.md) lists 14 orchestrator providers and 14 coding-agent harnesses.
An adapter that exists, and flag construction that a unit test checks, do not show that an
installed upstream ran the route end to end. This page shows how far each advertised route has
actually been proven, and gives a first run you can reproduce on a clean host.

The record is [`runtime/providers/certification.json`](../runtime/providers/certification.json)
(versioned: `record_version`, `recorded`). It has one cell per advertised route:

- **provider cells**: every `(provider, profile, harness)` in
  [`capabilities.json`](../runtime/providers/capabilities.json)'s `supported_profiles` ×
  `supported_harnesses`;
- **harness cells**: every `(harness, profile)` of the shared launch table,
  `build_harness_command` in [`base.py`](../runtime/providers/base.py), for `ro` and `rw`.

Each cell names a tier, the exact upstream version or commit it was certified against, evidence
paths and explicit limitations. An upstream version that nobody recorded stays `unknown`.
[`certification.py`](../runtime/scripts/certification.py) validates the record (`check`), lists
every cell (`matrix [--json]`) and renders the block below (`markdown`).

## How to read a cell

| Tier | What it proves | What it does not |
|---|---|---|
| `live-witnessed` | A real upstream build and a real harness ran the route. The evidence is a `docs/runs/` report whose `RUN:` header records `verifier=GREEN` and that binds under `run_report.py`. | That later upstream builds behave the same: a pin refresh voids the cell. |
| `fixture-tested` | The fleet's own code for the route runs in CI against an in-repo fixture: a scripted upstream transport, or the inert worker of [`first_run.py`](../runtime/scripts/first_run.py). | Anything about the real upstream build or the real harness binary. |
| `source-only` | The launch or flags were written from upstream source or docs. | That anything drives the route. |
| `unsupported` | The fleet refuses the route before any launch, with the typed refusal in `refusal`. A test pins the refusal. | — |
| `unavailable` | The route is advertised, but this repository has no evidence for it, so its state is unknown. | — |
| `stale` (computed) | The provider's pin moved after certification. The cell no longer claims its recorded tier. | — |

## Live-witnessed results

Two cells are live. Both are on the Orca route with Claude Code, and both come from runs that
bind in the [run archive](runs/README.md):

- `orca` `ro`/`claude`: Orca 1.4.224 (`orca-ide`, Ubuntu 24.04.5 arm64) and Claude Code
  2.1.296, 2026-10-13, in the [review-it Linux witness](runs/2026-10-13-review-it-linux.md). The
  run used spawn_worker.sh's custom-argv lane. Turn start could not be observed on that host;
  screen reads and `worker_done` deliveries proved the workers were live.
- `orca` `rw`/`claude`: same build and harness, in the [ship-it mdtoc run](runs/2026-10-13-ship-it-mdtoc.md).
  Only the `WORKER_CMD` override lane was witnessed. On the witness host, the supervised
  `worker-start` lane reported `LAUNCHED_UNUSABLE`.

The Orca pin is now v1.4.229. That pin re-witnessed only the source delta. It carries these
receipts through `pins.json` `live_receipts`, and the record is certified against that
three-part fingerprint. No other provider, and no harness outside the Orca route, has a live
witness.

## Fixture (mocked) results

All other cells that are not refusals use fixtures. They show that the fleet's side of the route
works. They do not show how the upstream build or the harness behaves:

- **posix** (`ro` and `rw`, all 10 harnesses): `first_run.py` drives the whole route through the
  public wrappers. An inert stand-in answers to each harness name, in that harness's own output
  format as read from its source. Every combination runs in CI.
  `danger` uses a scripted fake `docker`. The provider is this repository's own code, so each CI
  run certifies the commit it runs at.
- **the 12 external adapters**: they use scripted upstream transports. Nobody recorded which
  upstream revision each adapter was read from, so every one reads `unknown`. The certification
  test drives every non-refused cell to its first upstream call, and every refused cell to its
  typed refusal with no upstream call.
- **harness launch lines**: the flags were read from source. Only the inert stand-in has run
  them.

<!-- BEGIN GENERATED: certification-matrix — runtime/scripts/certification.py markdown -->
Record version 1 (2026-10-23). Counts are cells: one (provider, profile, harness) or (harness, profile) route each.

| Provider | Upstream certified against | live-witnessed | fixture-tested | source-only | unsupported | unavailable | stale |
|---|---|---|---|---|---|---|---|
| `ao` | unknown |  | 11 |  |  |  |  |
| `emdash` | unknown |  | 11 |  | 9 |  |  |
| `gastown` | unknown |  | 10 |  | 4 |  |  |
| `jcode-swarm` | unknown |  | 1 |  |  |  |  |
| `multiclaude` | unknown |  | 2 |  |  |  |  |
| `openhands` | unknown |  | 2 |  |  |  |  |
| `orca` | v1.4.229 (a0cd1644f320) | 2 | 2 | 14 | 24 |  |  |
| `overstory` | unknown |  | 9 |  | 5 |  |  |
| `paperclip` | unknown |  | 3 |  | 1 |  |  |
| `posix` | in-repo |  | 29 |  | 1 |  |  |
| `superset` | unknown |  | 14 |  |  |  |  |
| `t3code` | unknown |  | 4 |  |  |  |  |
| `vibe-kanban` | unknown |  | 7 |  | 5 |  |  |
| `worktrunk` | unknown |  | 20 |  |  |  |  |

| Harness | Upstream version | live-witnessed | fixture-tested | source-only | unsupported | unavailable |
|---|---|---|---|---|---|---|
| `antigravity` | unknown |  |  |  | 2 |  |
| `claude` | unknown |  | 2 |  |  |  |
| `codex` | unknown |  | 2 |  |  |  |
| `crush` | unknown |  | 2 |  |  |  |
| `cursor` | unknown |  |  |  | 2 |  |
| `droid` | unknown |  |  |  | 2 |  |
| `gemini` | unknown |  | 2 |  |  |  |
| `goose` | unknown |  | 2 |  |  |  |
| `grok` | unknown |  |  |  | 2 |  |
| `hermes` | unknown |  | 2 |  |  |  |
| `jcode` | unknown |  | 2 |  |  |  |
| `omp` | unknown |  | 2 |  |  |  |
| `opencode` | unknown |  | 2 |  |  |  |
| `pi` | unknown |  | 2 |  |  |  |

Live-witnessed cells (everything else is fixture, source or refusal evidence):

- `orca` ro/claude: upstream orca-ide 1.4.224, Claude Code 2.1.296, Ubuntu 24.04.5 LTS arm64 (OrbStack VM), 2026-10-13 — [2026-10-13-review-it-linux.md](runs/2026-10-13-review-it-linux.md)
- `orca` rw/claude: upstream orca-ide 1.4.224, Claude Code 2.1.296, Ubuntu 24.04.5 LTS arm64 (OrbStack VM), 2026-10-13 — [2026-10-13-ship-it-mdtoc.md](runs/2026-10-13-ship-it-mdtoc.md)
<!-- END GENERATED: certification-matrix -->

### What the record surfaces

These limitations are recorded in the cells. They are not fixed here:

- **Three Orca read-only rows are weaker than the posix ones.** On Orca, `ro` for `crush`,
  `hermes` and `jcode` uses spawn_worker.sh's pre-#580 rows. `crush run --quiet` auto-approves
  every run. `hermes chat --Continue` keeps writes in its `file` toolset. The jcode row leaves
  `replace` enabled. Treat those cells as unverified read-only.
- **`opencode`, `omp` and `pi` are listed for Orca but refused there.** spawn_worker.sh has rows
  for them only off Orca. Without a `WORKER_CMD` override, the wrapper refuses all six cells.
- **A posix `ro` worker cannot report `worker_done`.** It has no tool to send mail, so posix
  records its clean exit as `worker_died (exit=0)`. The coordinator reads the report from the
  transcript. That is how `first_run.py --profile ro` works.

## A refreshed pin voids cells

A provider bound to a pin carries `upstream.pin` (`<file>#<key>`) and `certified_against`, which
holds the pin's `commit`, `version` and `live_receipts.version`. Today `orca` is the only
provider bound this way. If any of the three values moves, **every cell of that provider reads
`stale`** and `certification.py check` fails with `STALE provider …`. The check stays failed
until a maintainer rechecks the cells, updates them, bumps `record_version` and re-records
`certified_against`.

To preview which cells a re-pin voids before landing it:

```bash
python3 runtime/scripts/certification.py check --pins /path/to/candidate-pins.json
python3 runtime/scripts/certification.py matrix --pins /path/to/candidate-pins.json | grep stale
```

Harnesses have no pins. A harness upgrade cannot void a cell automatically, so each harness cell
says which binary, if any, ever ran.

## First run on a clean host

This is the reproducible path for a fresh clone. The default worker is inert, so the run calls
no model and spends nothing. It drives one review unit through the same wrappers an operator
types: `preflight.py`, `task_ops.py`, `spawn_worker.sh` (on `OPEN_FLEET_RUNTIME=posix`, `setsid`
backend), `worker_ops.py`, `check_reply.py` and `verify.py`. The run ends with a SHA-bound
verdict.

### Prerequisites

| Need | Check | Why |
|---|---|---|
| Python 3.11–3.13 | `python3 --version` | Every runtime script; stdlib only |
| Git | `git --version` | Worktrees, the evidence commits, the verifier checkout |
| bash and POSIX `sh` | `bash --version` | `spawn_worker.sh`, `deny-hook.sh` |
| A full clone | `git rev-parse --is-shallow-repository` prints `false` | `certification.py check` binds live cells with `run_report.py`, which needs history |
| For the live run only: the harness, signed in | `claude --version` | The real worker; this run spends |

The fixture does not need Orca, tmux, Docker or a network connection.

### 1. Inert first run (no agent, no spend)

```bash
git clone https://github.com/ravidsrk/open-fleet.git
cd open-fleet
python3 runtime/scripts/certification.py check
python3 runtime/scripts/first_run.py
```

Expected output, with your own SHAs and paths:

```text
FIRST_RUN=GO
ROUTE=posix/setsid PROFILE=ro HARNESS=claude WORKER=inert TIER=fixture-tested
REVIEWED=<base 40-hex>..<head 40-hex>
EVIDENCE=<contract commit>..<report commit> VERIFY=OK
DISPATCH=disp_<id> TASK=task_<id>
ELAPSED_S=<seconds>
RECEIPT=/tmp/open-fleet-first-run-<x>/receipt.json
```

`REVIEWED` is the reviewed range. `EVIDENCE` is the commit range that `verify.py` re-derived. It
contains only the report, with the frozen contract as its base. Add `--profile rw` to have the
worker commit the report and send `worker_done`; the coordinator re-reads the worker's HEAD from
git and refuses a committed report that does not open with the required line. Add
`--agent <harness>` to run another posix harness name, `--keep` to keep the sandbox, and
`--target <repo> --base <rev> --head <rev>` to review your own range. The target is cloned and
never modified. On a 2026 macOS arm64 development host, one inert run took about 2 seconds. That
is a fixture timing, not a clean-host record.

`receipt.json` records each step with its exit, elapsed seconds and, on failure, a recovery
hint. It also records every command's argv and exit, the host (platform, Python, Git, bash), the
catalog commit, and whether the catalog tree was dirty. After a GO, the sandbox is pruned down to
`receipt.json`. After a NO-GO, the whole sandbox is kept for inspection.

### 2. Negative probes

```bash
python3 runtime/scripts/first_run.py probes
```

Each probe must refuse before any launch. The stand-in never runs and no dispatch is recorded:

| Probe | What it tries | Refusal |
|---|---|---|
| `unsupported-profile` | `PROFILE=ro` for `cursor`, which has no verified read-only launch | `spawn_worker.sh` exit 2 |
| `privilege-escalation` | an `rw` child under `OPEN_FLEET_PARENT_PROFILE=ro` | exit 2, monotonic narrowing |
| `unarmed-deny-hook` | `OPEN_FLEET_DENY_HOOK_SETTINGS` naming a registration that never denies | exit 2, `deny-hook not armed` |
| `malformed-upstream-response` | a runtime CLI that answers with non-JSON | exit 1, `SPAWN=FAILED` before `worker-start` |
| `missing-capability` | `pin-it` on posix, which lacks `cap:orca-self-audit` | `preflight.py` exit 2 |

Expected output: one `PROBE=<name> REFUSED` line per probe, then `PROBES=GO`.

### 3. Live first run (one command; not yet witnessed)

```bash
python3 runtime/scripts/first_run.py --worker live --agent claude --keep
```

This command runs the same lifecycle with your real `claude`. **It spends**, because a real model
reviews the change. The receipt is labelled `live-unreviewed`. It becomes certification evidence
only after a maintainer records the run as a `docs/runs/` report that binds. The record's
`posix` `ro`/`claude` cell can then move to `live-witnessed`, and the clean-host record below
gets its numbers. No such run is recorded yet.

### The Orca path

The Orca path is the one already witnessed: a `review-it` run through `orca-ide`. The
[review-it Linux witness](runs/2026-10-13-review-it-linux.md) records its prerequisites, the
exact `spawn_worker.sh` lane, the `verify.py` invocation and its GREEN outcome. To repeat it,
follow [Getting started](getting-started.md#your-first-mission-a-review-it-dry-run) with Orca
installed.

### Troubleshooting

| Symptom | Likely cause | Next step |
|---|---|---|
| `step=prereqs`, `` `claude` is not on PATH `` | `--worker live` without the harness installed | Install and sign in to the harness, or drop `--worker live` |
| `step=preflight` | Not run from a git repository with Python 3.11+ | Read the `preflight:` line; see [troubleshooting](troubleshooting.md) |
| `step=dispatch`, a `SPAWN=REFUSED` line | An inherited `OPEN_FLEET_*`/`ORCA_*` variable or a profile refusal | The sandbox clears the known ones; read the `SPAWN=` line in the receipt's failure |
| `step=result`, `worker still ready` | The worker did not finish within `--timeout` | `python3 runtime/scripts/worker_ops.py read --dispatch <d> --source transcript` with the sandbox's `OPEN_FLEET_STATE_DB`; raise `--timeout` |
| `step=result`, `report does not open with` | The worker ignored the spec's first-line contract | Read its transcript. A live model must start its answer with the exact `FIRST-RUN-REPORT` line |
| `step=verify` | `verify.py` refused the bound manifest | The receipt's `recovery` field has the exact command and checkout to re-run |
| `certification.py check` fails with `STALE` | The pin moved after certification | Recheck the provider's cells, then re-record `certified_against` (see above) |
| `certification.py check` says a live cell has no binding report | A shallow clone | `git fetch --unshallow`, then re-run |

## Recording a clean-host first run

A clean-host record counts only when it comes from a host that has not run open-fleet before.
Record:

1. The host: OS, architecture, and how it was provisioned (fresh VM or container image and its
   digest).
2. Prerequisites as found, and anything installed to meet them, with versions.
3. Elapsed time for setup (clone, installs) and for the run. The receipt already carries
   per-step `elapsed_s` and the total.
4. Every failure, verbatim, with the recovery that cleared it.
5. The receipt itself, for the inert run, the probes and, if authorized, the live run, filed
   with a `RUN:` report under `docs/runs/`.

## Not certified yet

- A live POSIX first run with a real agent (`first_run.py --worker live`) on a fresh clone.
- A clean-host first-run record with measured setup and run times.
- Live witnesses for every other provider, for Orca on macOS, and for any harness other than
  Claude Code. Their upstream versions stay `unknown` until a run records them.
