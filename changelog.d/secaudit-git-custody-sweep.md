- **floor_guard, diff_scope, hint_provenance and verify's executed negative control no longer run
  a git driver a worker adds while they read** ([2026-10-27 security
  audit](../docs/runs/2026-10-27-security-audit.md), W4-01/W4-02 class). These tools listed the
  filter, textconv and merge drivers the repository's config declared, blanked them, and then ran
  a git that read that config again, so a driver a still-running worker added between the two
  (selected through `.gitattributes` or the shared `info/attributes`) ran on the coordinator.
  The git custody PR #720 built for the providers now lives in `runtime/scripts/gitexec.py`
  (`custody`, `custody_git_dir`, `custody_env`) and the posix provider uses it from there. Every
  content-reading git at these sites runs against a git dir the coordinator builds over the
  repository's objects (and index), whose config defines no driver at all: floor_guard's tracked
  and untracked diffs, diff_scope's working-tree diff and `--predict-merge`, hint_provenance's
  `diff` and `log`, and the control's checkout, revert, apply and seal, whose scratch worktree is
  no longer a linked worktree of the graded repository. The driver listing stays as a belt and
  keeps its fail-closed refusal. Every other git these tools run drops inherited repository
  selectors (`GIT_DIR`, `GIT_INDEX_FILE`, `GIT_EXEC_PATH`, ...) and carries the custody floor
  (`GIT_NO_LAZY_FETCH=1`, `GIT_ALLOW_PROTOCOL=file`, no signature-verifying child),
  so a planted promisor remote cannot run a payload through a lazy fetch. A repository the custody
  cannot honour (a partial clone) or read safely (a symlinked `info/exclude`) is refused: exit 2
  from floor_guard, `diff_failed` from diff_scope, a `ProvenanceError`, a blocked control. A
  work-tree diff no longer starts a child git inside a checked-out submodule to ask whether it is
  dirty (`--ignore-submodules=dirty`): that child ran under the submodule's own config, so a filter
  planted there ran too. A moved submodule commit is still reported; uncommitted changes inside a
  submodule no longer are. The custody also carries the repository's `info/attributes`, the
  content of its own `core.attributesFile` (read only as a regular file of at most 1 MiB, never
  opened blocking; a FIFO, symlink or larger file refuses; no user attributes or ignore file is
  opened, and no system attributes file except by verify.py's negative control, whose pinned git
  environment does not set `GIT_ATTR_NOSYSTEM`), the content of its own `core.excludesFile` (read
  the same way) and its
  `core.safecrlf`/`core.checkRoundtripEncoding` as data, so a CRLF (`eol=crlf`) checkout no longer
  reads as modified. No repository-named command runs at these sites; a file git would BLOCK on
  is handled best-effort. Before any git runs, floor_guard, diff_scope and hint_provenance refuse a
  repository in which they positively find a config, config include, `commondir` or `shallow`
  that is a FIFO or other non-regular file, checking every spelling of each name a git might
  read (whitespace trimmed or not, either git's config whitespace), without running git and
  without ever refusing on doubt. Any promisor remote is refused as a partial clone (git 2.43
  never writes `extensions.partialClone`). A blocking file that check misses (one it cannot
  parse, a FIFO swapped in after it, one at a work tree `.gitignore` or `.gitattributes`) blocks
  the git call until its timeout (60 s; up to 120 s in the verifier), and the call is then
  refused. predict-merge reports a custody
  refusal or a timeout as such, hint_provenance any git timeout (custody setup included) as a
  `ProvenanceError`, and verify.py's control a timed-out custody query as its could-not-create
  refusal. Also:
  the `_external.py` runner docstring no longer claims `reset --hard` runs in custody (it is
  refused).
