- **The posix provider no longer runs a command a worker plants in git config**
  ([2026-10-27 security audit](../docs/runs/2026-10-27-security-audit.md), W4-01). It ran a bare
  `git` with the coordinator's whole environment on `worktree add`, `worktree remove` and the
  `danger` sandbox sync, so a `core.hooksPath`/`post-checkout`, a `core.fsmonitor` or a
  `filter.<d>.smudge` written into the shared `.git/config` (or the same-uid `~/.gitconfig`) ran as
  the coordinator. Every provider git now runs through `runtime/scripts/gitexec.py`'s floor with
  each declared driver blanked; a new worktree is checked out in a second step inside it, so a Git
  LFS repository's worker gets pointer files and no `post-checkout` hook runs. Also:
  `gitexec.py` and `diff_scope.py` drop an inherited `GIT_CONFIG`/`GIT_CONFIG_PARAMETERS`, which
  blinded the driver listing or outranked the floor (W4-07), `worktree rm` decides from the
  repository's own worktree list (W4-08), `diff_scope.py` fails closed when git is absent at
  import (W4-14), a `-`-leading `terminal send` text reaches tmux/cmux, `--key=value` and `--` are
  understood, a non-identifier launch env key is refused (W2-01, W2-02), and nine git call sites
  refuse an option-shaped revision (W2-04).
