- **The posix provider and the external adapters no longer run a command a worker plants in git
  config** ([2026-10-27 security audit](../docs/runs/2026-10-27-security-audit.md), W4-01). The
  posix provider ran a bare `git` with the coordinator's whole environment on `worktree add`,
  `worktree remove` and the `danger` sandbox sync, and the adapters did the same for their dirty
  check, HEAD pin, t3code's worktree cut and worktrunk's merge prediction, so a
  `core.hooksPath`/`post-checkout`, a `core.fsmonitor`, a `filter.<d>.smudge` or a merge driver
  written into the shared `.git/config` (or the same-uid `~/.gitconfig`) ran as the coordinator.
  Every such git now runs through one custody (`run_git` in `runtime/providers/posix.py`):
  `runtime/scripts/gitexec.py`'s floor plus fixed keys for `fetch`'s alternate-refs command, every
  transport but the local one, submodule recursion and signature verification. A git that could
  apply a filter, diff or merge driver (the clean check, the merge prediction, a new worktree's
  checkout) runs against a git dir the coordinator builds, whose config declares no driver, so a
  worker cannot add one between a check and its use; any other such git is refused. A worktree
  the coordinator creates therefore holds the committed bytes (LFS pointer files, git-crypt
  ciphertext) and runs no `post-checkout` hook, and the adapters' dirty check counts a checked-out
  submodule as uncommitted work. Also: git output is decoded byte-for-byte, so a `\r` or non-UTF-8
  byte in a worktree path no longer hides a registered worktree from `worktree rm` (W4-08),
  `gitexec.py` and `diff_scope.py` drop an inherited `GIT_CONFIG`/`GIT_CONFIG_PARAMETERS`, which
  blinded the driver listing or outranked the floor (W4-07), `worktree rm` decides from the
  repository's own worktree list and refuses when that list cannot be read (W4-08),
  `diff_scope.py` fails closed when git is absent at import (W4-14), `wtree.sh predict-merge` runs
  `python3 -I`, a `-`-leading `terminal send` text reaches tmux/cmux, `--key=value` and `--` are
  understood and only the dispatcher's own `--json` option is consumed, a non-identifier launch
  env key is refused (W2-01, W2-02), and nine git call sites refuse an option-shaped revision
  (W2-04).
