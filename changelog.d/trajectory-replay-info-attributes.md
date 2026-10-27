- **The trajectory replay's git calls now ignore a filter selected from `.git/info/attributes`.**
  `scripts/_trajectories.py` read attributes from the empty tree (`GIT_ATTR_SOURCE`), but a
  `$GIT_DIR/info/attributes` line outranks that, so a filter declared in the replay repo's
  `.git/config` and selected there ran on the replay's `add -A`. A recording cannot write the git
  dir today (the replay refuses it), so this closes the second layer: every replay git call after
  `init` now blanks the drivers the repo's config declares, as the verifier gates do. A test plants
  both files behind the write guard and carries a mutation control.
