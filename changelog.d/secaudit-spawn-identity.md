- **The spawn path's identity inputs are bounded: the parent-profile cap reaches Orca workers,
  CLI commands and installer operands are validated, and printed receipt fields are inert**
  ([2026-10-27 security audit](../docs/runs/2026-10-27-security-audit.md): W4-04, W4-10, W4-11,
  W4-12, W4-15/W2-03, W2-05/W5-22, W5-19, W5-20; W4-13 is parked, since running the resolver
  under `python3 -I` changes a pinned assertion that needs a one-way human waiver first).
  `spawn_worker.sh`'s custom-argv launch
  from its own rows (every Orca `ro` worker) now carries the worker's own profile as
  `OPEN_FLEET_SANDBOX_PROFILE`/`OPEN_FLEET_PARENT_PROFILE` (and their `ORCA_` aliases), so a `ro`
  worker's `PROFILE=rw spawn_worker.sh` is refused on Orca too, and a session carrying fleet
  worker identity with no parent profile is capped at `ro` rather than uncapped. Both are the
  worker's own environment: a guard on the spawn path, not a sandbox. The title label is bounded
  before it names a file. `OPEN_FLEET_CLI_COMMAND` /
  `ORCA_CLI_COMMAND` must name one executable, one policy in `orca_cli.py` and
  `upstream_probe.py`. `sandbox_doctor.py` reads the recipe from recipe fields only and refuses a
  transcript whose placement claims contradict themselves. `worker_ops.py`, `terminal_ops.py`,
  `send_msg.py` and `orca_cli.run_json` print every receipt field escaped and on one line.
  `send_msg.py` now says its sender check catches accidental mismatches only. `first_run.py`
  hands its on-host sandbox an allowlisted environment, so no operator credential reaches the
  worker. `scripts/install.sh` refuses an empty or option-shaped `--skills-dir`, ends `mkdir`/`ln`
  options with `--`, validates mission names and names an unset `HOME`.
