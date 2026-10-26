- **A repository-wide adversarial review closed the bypasses it reproduced and fixed the drift
  it found.** `deny-hook.sh` now expands brace expressions and reads `git -c alias.*`,
  `--config-env` and `GIT_CONFIG_*` inline aliases before matching, so `git push --force{,}` and
  `git -c alias.p=push p --force` are the pushes they are; its `--verify-settings` arming gate runs
  only this hook (byte-identical, under a scrubbed environment) instead of whatever command the
  settings registered, and is told the harness and boundary it arms. `verify.py` binds the
  negative control's `base_sha` to the integration branch (`--base-sha` is now a signed dispatch
  input), names refs in full (`refs/remotes/origin/<base>`), and reads `ORCA_NO_GH` /
  `ORCA_EXECUTE_NC` as switches (`1|true|yes|on`), blocking on any other spelling;
  `verify-gate.sh` stops its verifier at `ORCA_GATE_TIMEOUT_S` (default 2100 s, under the hook
  timeout the shipped hooks now set to 2400 s) because a timed-out Claude Code hook fails OPEN, and
  never reads a worker-writable dispatch key on a sound lane. `spawn_worker.sh` keeps stderr out of
  the receipts it parses and fails closed on an unreadable wait. The posix provider stops the agent
  a `kill -9`'d monitor leaves running (sweep and `stop`, proven by the group's working directory),
  treats a reused monitor pid as a vanished monitor, merges guard configs into the settings already
  at a guard path instead of replacing them, creates the state directory, lanes and transcripts
  user-private, strips the coordinator's custody tokens plus anything in
  `OPEN_FLEET_WORKER_ENV_DENY` from a worker's environment, claims retry requests inside one
  transaction (and reclaims a dead claimer's at once), and stamps the store's schema version.
  `merge_queue.py` bounces `reviewed_sha_unavailable` instead of accepting a payload tree as proof
  of review, and runs `--gate-cmd` in its own `--shared` clone under a scrubbed environment
  (`MQ_GATE_ENV_KEEP` passes names through). `floor_guard.py` guards ruff's ignore/exclude keys and
  `.coveragerc`'s scope, compares constraints rows cell by cell (a reworded criterion, an appended
  lower floor, a full-width digit and a duplicate row are all read), and the guard and bind-check
  workflows run the base branch's own checker against a PR. `run_report.py` refuses a ref name as
  `inventory_at`; `gate-batch.py answer` and `waive` record `--source human:<name>`; `decisions.py
  check --since` lets CI validate the ledger from 2026-09-24 on; `one-way-doors.json` gains the
  `close-without-landing` and `review-verdict` doors the missions already declared; the VF-Bench gate
  names each skip's own cause; and the catalog validator refuses YAML sequence and mapping values
  where strings are required, duplicate frontmatter keys and unreadable top-level lines. Doctrine
  and docs were corrected where they overstated (ruflo, the Orca-free claim, the dark-eligible lane,
  the first-merge authorship check, stale pins, hook paths and flag lists), and the seven missions
  that loaded `ARCHITECTURE.md` at activation no longer do, which keeps every mission under the
  activation budget.
