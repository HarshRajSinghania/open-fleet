# Troubleshooting

[Documentation Hub](README.md) · [Install](install.md) · [Verify Gate](verify-gate.md) · [Local Development](development.md)

Use this diagnostic guide to resolve setup, runtime, completion-gate, and pull-request issues. Run catalog maintenance scripts from your **`open-fleet` clone** and run project test suites from your **target repository**.

---

## Quick diagnostic table

| Symptom | Likely cause | Jump to fix |
|---|---|---|
| `install.sh` succeeded, but a mission refuses to start | Runtime prerequisites (`orca`, `gh`, or `OPEN_FLEET_RUNTIME=posix`) are not ready | [Mission cannot start](#the-catalog-installs-but-a-mission-cannot-start) |
| Agent does not list outcome skills (`ship-it`, `review-it`) | Symlinks missing in `~/.claude/skills/` or plugin inactive | [Mission missing from agent](#the-mission-is-missing-from-the-agent) |
| Mission errors on missing `playbooks/` or `../../ARCHITECTURE.md` | Skill directory was copied (`cp`) instead of symlinked (`ln -s`) | [Playbooks not found](#playbooks-or-architecture-links-cannot-be-found) |
| `install.sh` refuses an existing mission directory | Destination in `~/.claude/skills/<name>` is a real folder, not a symlink | [Existing directory refusal](#installation-refuses-an-existing-mission-directory) |
| `print-settings-snippet.sh --check` says `ok`, but unverified units pass | Snippet was not merged into `~/.claude/settings.json` | [Completion gate not firing](#the-settings-snippet-says-ok-but-completion-is-not-checked) |
| `verify-gate.sh` blocks a turn or task (`exit 2`) | Missing manifest, missing `ORCA_CONTRACT_*`, or failed check | [Gate blocks a turn or task](#the-gate-blocks-a-turn-or-task) |
| `spawn_worker.sh` exits `2` with `SPAWN=REFUSED` | Missing `rw`/`danger` consent env vars, `danger` on `orca`, or unmet task deps | [Worker spawn refused](#worker-spawn-is-refused-spawnrefused) |
| `preflight.py` refuses `BASE` (`"BASE is the default branch"`) | Mutation mission pointed at `main`/`master` instead of an integration branch | [Preflight refuses BASE](#preflight-refuses-base) |
| Preflight stops on a failing baseline test suite | Target repository has pre-existing failing or flaky tests | [Baseline suite failing](#the-baseline-suite-is-already-failing) |
| Worker terminal appears idle or coordinator session closed | Worker stalled past heartbeat or coordinator restarted | [Idle worker or coordinator restart](#a-worker-appears-idle-or-the-coordinator-restarts) |
| Local tests pass, but conductor refuses to merge PR | `reviewed_sha != head_sha` (post-review rebase/push) or GitHub checks pending | [PR still blocked](#tests-passed-but-a-pr-is-still-blocked) |
| Missions appear twice, or `verify-gate.sh` runs twice per turn | Stacked both symlink install (`~/.claude/skills/*`) and Claude Code plugin | [Duplicate skills or double gate](#duplicate-skills-or-verify-gatesh-runs-twice-stacked-install) |
| Long coordinator session auto-compacts and forgets phase state | Host context window compacted mid-run | [Context compaction mid-mission](#context-auto-compaction-mid-mission) |
| Model refuses PoC exploit step during `harden-it` | Upstream model cyber-safeguard triggered on exploit phrasing | [Cyber-safeguard refusal in harden-it](#upstream-model-cyber-safeguard-refusals-during-harden-it) |
| Plugin update keeps old version, or Windows symlinks/hooks fail | Cached marketplace index, or Windows clone without WSL2 / `core.symlinks=true` | [Plugin cache or Windows symlinks](#plugin-update-keeps-an-old-version-or-windows-symlinks-fail) |

---

## The catalog installs, but a mission cannot start

- **Cause:** `scripts/install.sh` requires only `git` and Python ≥ 3.11 to link skills, and prints soft warnings when runtime tools are offline. Running a mission requires a live runtime (`orca` or `OPEN_FLEET_RUNTIME=posix`) and authenticated `gh`.
- **Fix:** Check your runtime environment from a terminal:
  ```bash
  python3 --version
  git --version
  gh auth status
  orca status --json   # Or use `orca-ide` on Linux outside Orca terminals
  ```
  - If using **Orca** and `runtime.state` is `not_running`, run `orca open` and wait for `ready` (at or above the catalog pin in [`runtime/pins.json`](../runtime/pins.json); see [pinned prerequisites](distribution.md#prerequisites-pinned)).
  - If running **without the Orca desktop app**, export `OPEN_FLEET_RUNTIME=posix` ([Multi-runtime guide](runtimes.md)).

---

## The mission is missing from the agent

- **Cause:** Symlinks in `~/.claude/skills/` are missing or broken, or the Claude Code plugin is not enabled.
- **Fix (whole-catalog symlink):** Run `sh scripts/install.sh --check` from your `open-fleet` clone.
- **Fix (selective symlink subset):** Check the individual symlink target:
  ```bash
  python3 - <<'PY'
  from pathlib import Path
  mission = Path.home() / '.claude/skills/review-it'
  print('symlink:', mission.is_symlink())
  print('target:', mission.resolve())
  print('skill exists:', (mission / 'SKILL.md').is_file())
  PY
  ```
- **Fix (plugin install):** Run `claude plugin details open-fleet@open-fleet` or check `/plugin` inside Claude Code ([plugin setup](install.md#claude-code-plugin)).

---

## Playbooks or architecture links cannot be found

- **Cause:** A `skills/<mission>/` directory was copied out of the source repository without `playbooks/`, `runtime/`, and `ARCHITECTURE.md`.
- **Fix:** Reinstall using the [symlink or plugin path](install.md#choose-an-install-path). If you must use a copy-based installer, build or pull the self-contained `dist/` bundle generated by `python3 scripts/bundle.py` ([bundle details](install.md#copy-installers-and-bundles)).

---

## Installation refuses an existing mission directory

- **Cause:** `scripts/install.sh` never overwrites a real (non-symlink) directory in `~/.claude/skills/<name>` to protect local files.
- **Fix:** Inspect `~/.claude/skills/<name>`, back up or remove the directory if it was an old manual copy, and re-run `sh scripts/install.sh`. Alternatively, install into a custom directory with `--skills-dir=/absolute/path`.

---

## The settings snippet says “ok”, but completion is not checked

- **Cause:** `sh hooks/print-settings-snippet.sh --check` only verifies that the hook template and `verify-gate.sh` exist in your clone; it does not inspect `~/.claude/settings.json`.
- **Fix:** Merge the `Stop` and `TaskCompleted` hook entries from `sh hooks/print-settings-snippet.sh` into `~/.claude/settings.json` and run the fail-closed test in [Verify the completion gate](install.md#verify-the-completion-gate).

---

## The gate blocks a turn or task

- **Cause:** `verify-gate.sh` is fail-closed (`exit 2`). A block occurs when `ORCA_MANIFEST` is missing on `TaskCompleted`, when `ORCA_CONTRACT_SOURCE` / `ORCA_CONTRACT_DIGEST` are unset, or when `verify.py` finds an unaddressed criterion, missing git ancestry, stale review, or failed negative control.
- **Fix:** Inspect the stderr diagnostics printed by `verify-gate.sh`. See **[Verify gate — Environment variables](verify-gate.md#native-path--plugin-hooks-set-claude_plugin_root)** for required inputs and **[Trust boundary](verify-gate.md#trust-boundary)** for advisory vs. off-worker execution.

---

## Worker spawn is refused (`SPAWN=REFUSED`)

- **Cause:** [`runtime/scripts/spawn_worker.sh`](../runtime/scripts/spawn_worker.sh) validates sandbox profiles, coordinator consent flags, and DAG dependencies before creating or mutating any task, exiting `2` with `SPAWN=REFUSED task=<id> <reason>` on violation.
- **Fix:** Match the refusal message on stderr:
  - **`PROFILE=rw launches an autonomous permission-bypass worker — set ORCA_COORD_ALLOW_AUTONOMOUS_WRITE=1`:** Export `OPEN_FLEET_COORD_ALLOW_AUTONOMOUS_WRITE=1` (or `ORCA_COORD_ALLOW_AUTONOMOUS_WRITE=1`) in the coordinator environment when dispatching write workers.
  - **`PROFILE=danger requires ORCA_COORD_ALLOW_DANGER=1` or `has no supported authoritative placement binding`:** `PROFILE=danger` is unconditionally refused on the `orca` runtime because `orca` does not bind prelaunch disposable-sandbox placement. To run a `danger` lane, use a placement-bound runtime such as `OPEN_FLEET_RUNTIME=posix` with Docker (`--on <recipe>`), `OPEN_FLEET_COORD_ALLOW_DANGER=1`, and `OPEN_FLEET_SANDBOX_RECIPE=<recipe>` ([Multi-runtime guide](runtimes.md)).
  - **`deny-hook arming UNVERIFIED … ORCA_DENY_HOOK_SETTINGS is unset`:** every profile, `ro` included, refuses when no guard registration is named (W4-06). Wire the hook (`deny-hook.sh --settings <worktree>`, plus `--readonly` for `ro`) into the harness settings and name that file in `OPEN_FLEET_DENY_HOOK_SETTINGS`. Off Orca the provider installs the guard inside `worker-start`, after the gate: set the named opt-out `OPEN_FLEET_ALLOW_UNVERIFIED_DENY_HOOK=1` and verify the installed registration with `deny-hook.sh --verify-settings <worktree>/.claude/settings.local.json`, as `first_run.py` does. Under `OPEN_FLEET_REQUIRE_DENY_HOOK=1` the opt-out is ignored.
  - **`unmet_deps=<N>` or `status=pending`:** Complete upstream tasks in the DAG first, or pass `--mark-ready` only after all dependencies have reached `completed`.

---

## Preflight refuses BASE

- **Cause:** Code-mutating missions refuse to use your repository's default branch (`main` or `master`) as the integration `BASE` branch.
- **Fix:** Allow the coordinator to create a dedicated integration branch (e.g., `ship-it/integration`) forked from your default branch. Non-promoting missions (`review-it`, `map-it`, `root-cause`, `attest-it`, `oss-contribute`) run preflight with `--mode readonly` and do not require an integration branch.

---

## The baseline suite is already failing

- **Cause:** Feature and refactoring missions require a green baseline test suite at Phase 0 so pre-existing failures are never confused with fleet regressions.
- **Fix:**
  - If the failures are **intermittent flakes**, run **[`deflake-it`](missions/deflake-it.md)** first.
  - If the failures are **deterministic bugs**, run **[`clean-sweep`](missions/clean-sweep.md)** to drain them first.
  - If you are running **`open-fleet`'s own test suite** inside an Orca terminal and see a sender-identity fixture error, run with `env -u ORCA_TERMINAL_HANDLE` ([Local development](development.md#everyday-checks)).

---

## A worker appears idle or the coordinator restarts

- **Cause:** A worker process hung past its heartbeat window or the coordinator terminal was closed.
- **Fix:** Do not manually edit worker worktrees. Check the run ledger first:
  - Under [`runtime/worker-supervision.md`](../runtime/worker-supervision.md) and [`runtime/liveness-resume.md`](../runtime/liveness-resume.md), the watchdog classifies a stalled worker, nudges it once, and recommends a stop and re-dispatch; the coordinator performs the stop and the fresh re-dispatch, with a counted retry.
  - A restarted coordinator reads the ledger header (`RUN`, `BASE`, `FORK_POINT`, `T0`), cross-verifies completed rows against git ancestry, and resumes from the last unverified unit.

---

## Tests passed, but a PR is still blocked

- **Cause:** Local test execution is only one leg of verification. The conductor also requires an `APPROVED` review where `reviewed_sha == head_sha` and green required checks.
- **Fix:** Inspect the PR state via `gh`:
  ```bash
  gh pr view 123 --repo owner/repo --json headRefOid,baseRefName,mergeStateStatus,reviews
  gh pr checks 123 --repo owner/repo --required
  ```
  If a rebase, bot autofix, or late commit changed the branch tip after review, dispatch a fresh build-blind review of the new `head_sha` ([`runtime/reviewed-sha-freshness.md`](../runtime/reviewed-sha-freshness.md)).

---

## Duplicate skills or `verify-gate.sh` runs twice (stacked install)

- **Cause:** Both the symlink install (`~/.claude/skills/<mission>` + `~/.claude/settings.json` hook snippet) and the Claude Code plugin (`open-fleet@open-fleet`) are active on the same machine.
- **Fix:** Pick **one** install path per host ([Install — Do not stack](install.md#pick-one-install-path-per-host-do-not-stack)). To keep the plugin and remove the manual symlinks, run from your `open-fleet` clone root:
  ```bash
  find ~/.claude/skills -maxdepth 1 -type l \( -lname "$(pwd -P)/skills/*" -o -lname "$(pwd)/skills/*" \) -delete
  ```
  Then remove the manual `verify-gate.sh` entries from `~/.claude/settings.json` so only the plugin's [`hooks/hooks.json`](../hooks/hooks.json) fires.

---

## Context auto-compaction mid-mission

- **Cause:** Multi-hour coordinator runs (`ship-it`, `clean-sweep`, `harden-it`) can hit the host's context auto-compaction threshold, causing the coordinator session to summarize away active phase rules.
- **Fix:** Because `open-fleet` stores authoritative state in **git** and the **on-disk run ledger** (never in chat scrollback), you do not lose progress when a session compacts:
  1. Start a fresh coordinator session (or run `/clear`).
  2. Invoke the mission and point it at the existing ledger path (`Resume <mission> from ledger <path>`).
  3. Per [`runtime/liveness-resume.md`](../runtime/liveness-resume.md), the coordinator reads the `T0` header, re-verifies completed rows against `origin/<BASE>` git ancestry, and resumes from the first unverified unit.

---

## Upstream model cyber-safeguard refusals during `harden-it`

- **Cause:** [`harden-it`](missions/harden-it.md)'s [`playbooks/triage-findings.md`](../playbooks/triage-findings.md) phase requires proving P0/P1 findings with a non-destructive proof-of-concept before patching. Frontier models with strict automated cyber safeguards can misclassify exploit-verification prompts against your own repository as offensive activity and refuse the turn.
- **Fix:**
  1. Ensure the prompt and Frozen Contract explicitly state that the target is **your own local repository test fixture** and that the proof is a **non-destructive regression test demonstrating the bug pre-fix (`RED`) and passing post-fix (`GREEN`)**.
  2. If a finding requires a host-unsafe or safeguard-blocked exploit payload, park the live PoC step under `harden-it`'s documented parking rules (`HARDENED-WITH-OPEN-ITEMS` with the precondition named) or use an authorized evaluation account.

---

## Plugin update keeps an old version or Windows symlinks fail

- **Cause (stale plugin version):** Running `claude plugin update open-fleet@open-fleet` without refreshing the marketplace cache reads the previously cached `dist` ref.
- **Fix (plugin update):** Refresh the marketplace first:
  ```bash
  claude plugin marketplace update open-fleet
  claude plugin update open-fleet@open-fleet
  ```
- **Cause (Windows symlinks / `.sh` hooks):** Cloning on native Windows without `core.symlinks=true` turns symlinks into plain-text files, and native Windows `cmd.exe` cannot execute POSIX `.sh` hooks directly.
- **Fix (Windows):** Run `open-fleet` inside **WSL2** (recommended), or re-clone with Developer Mode enabled and `git clone -c core.symlinks=true https://github.com/ravidsrk/open-fleet.git` ([Windows & WSL2 support note](install.md#windows--wsl2-support-note)).

---

## Report a problem with enough context to reproduce it

When filing an issue, include:
1. Catalog commit SHA (`git rev-parse HEAD`), OS, Python version, and install path (`symlink` vs. `plugin`).
2. Runtime provider (`OPEN_FLEET_RUNTIME`), harness binary/version, and mission name.
3. Exact prompt or command executed, ledger row / dispatch ID, and full error output (with secrets redacted).

Use the [bug report template](../.github/ISSUE_TEMPLATE/bug_report.md) for runtime defects, the [doc-claim template](../.github/ISSUE_TEMPLATE/doc_claim.md) for documentation drift, and [SECURITY.md](../.github/SECURITY.md) for private vulnerability disclosures.
