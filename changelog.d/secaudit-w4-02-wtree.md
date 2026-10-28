- **`wtree.sh` no longer trusts global or system git config**
  ([2026-10-27 security audit](../docs/runs/2026-10-27-security-audit.md), W4-02, W4-07). On a
  one-uid host `~/.gitconfig` is the worker's to write, and a global clean filter both ran in the
  coordinator and chose the fingerprint: it mapped a tampered file back to its committed blob, so
  verify graded a tree no test saw as FRESH. Every staging git call now runs with global and system
  config off; a changed path any declared driver filters (Git LFS included) is exit 3
  (unverifiable), and a global `core.excludesFile` is not read. Inherited
  `GIT_DIR`/`GIT_WORK_TREE`/`GIT_INDEX_FILE`/`GIT_CONFIG`/`GIT_CONFIG_PARAMETERS` no longer steer
  the fingerprint or blind the driver listing, and git is resolved once to an absolute path.
  Staging (`read-tree`, `add -A`, `write-tree`) now runs in git custody: a git dir wtree.sh builds
  over the repository's objects and work tree, whose config defines no driver, so a filter a
  still-running worker adds after the driver listing neither runs nor chooses the fingerprint;
  a partial clone or a non-regular `info/exclude` is exit 1, and the staged objects no longer
  land in the repository's store.
