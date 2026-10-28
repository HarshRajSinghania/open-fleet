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
  opened blocking; a FIFO, symlink or larger file refuses; no user or system attributes file is
  opened) and its
  `core.safecrlf`/`core.checkRoundtripEncoding` as data, so a CRLF (`eol=crlf`) checkout no longer
  reads as modified. Also:
  the `_external.py` runner docstring no longer claims `reset --hard` runs in custody (it is
  refused).
