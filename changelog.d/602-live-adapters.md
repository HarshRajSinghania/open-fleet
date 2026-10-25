- **#602's live arm can deliver every arrival the fleet does** (#602). With `--live-adapters`,
  `eval.py run --suite trajectories --tier live` runs all ten design cases. It points the task at
  the repository document, prints the CI log from a `ci-log` command on the agent's PATH, carries
  the hint `search_sessions.py --episodic-hint` builds, or carries the retry packet
  `watchdog.py --handover` builds from the case's pinned first attempt. The grader replays a
  composed recording, so each arrival is checked on the case's own surface. Without the flag a
  run reproduces the 2026-10-25 design exactly. HO-01, BN-02 and BN-03 now grant Read, since a
  live worker cannot edit a file it may not read. See
  [the live arm](../docs/adversarial-evals.md#running-the-live-arm).
