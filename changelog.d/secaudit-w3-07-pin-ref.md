- **`decisions.py --pin-ref` anchors the human grant key only at a ref the checked change cannot
  move** (2026-10-27 security audit, W3-07). `--pin-ref` now takes only a remote-tracking ref
  (`refs/remotes/origin/main`) or a commit id, resolves it once and reads that commit — a local
  branch, tag or `HEAD` is refused, and the ref can no longer move between the check and the read.
  Without `--pin-ref` a working-tree pin is used with a stderr NOTE, and a caller that sets
  `ORCA_PROVENANCE`/`OPEN_FLEET_PROVENANCE` cannot run at all. The trajectory harness anchors on
  the base commit it recorded instead of its own `main`. Two existing test assertions now name
  `refs/remotes/origin/main` instead of `main` (landed under a one-way floor-guard waiver).
