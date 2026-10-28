- **`decisions.py --pin-ref` anchors the human grant key only at a ref the checked change cannot
  move** (2026-10-27 security audit, W3-07). `--pin-ref` now takes only a remote-tracking ref
  (`refs/remotes/origin/main`) or a commit id, resolves it once and reads that commit — a local
  branch, tag or `HEAD` is refused, and the ref can no longer move between the check and the read.
  Without `--pin-ref` the working-tree pin is used with a stderr NOTE whether it is present,
  swapped or absent (an absent pin checks one-way grants unsigned), and a caller that sets
  `ORCA_PROVENANCE`/`OPEN_FLEET_PROVENANCE` cannot run at all. The trajectory harness anchors on
  the base commit it recorded instead of its own `main`. Two existing test assertions now name
  `refs/remotes/origin/main` instead of `main` (landed under a one-way floor-guard waiver).
- **Every trust anchor named as a remote-tracking ref resolves by its exact name** (W3-07 class,
  review of the fix above). The anchor sites followed `symbolic-ref`, checked that the target was
  SPELLED `refs/remotes/…`, then let `rev-parse` or `cat-file` resolve it — and git expands a ref
  name (`refs/<name>`, `refs/tags/<name>`, `refs/heads/<name>`, …): with `refs/remotes/worker/key`
  absent, a local branch `refs/heads/refs/remotes/worker/key` answered for it, a revision suffix
  (`refs/remotes/origin/main~1`, `^`, `@{1}`) read an older commit's retired key, and 64 hex digits
  in a SHA-1 clone expanded to a branch of that spelling. `gitexec.remote_tracking_commit` is now
  the one rule: a commit id must name that commit object; a ref must be a full `refs/remotes/…`
  name that `check-ref-format` accepts and that exists under exactly that name, every symbolic hop
  remote-tracking too, looked up in one `for-each-ref` listing and peeled to a commit once.
  `decisions.py --pin-ref`, `gate-batch.py --pin-ref`, `run_report.py`'s trusted base, `verify.py`'s
  trust keys and `release_check.py`'s gate-1 anchor call it; `verify-gate.sh` mirrors it in sh.
  Each planted exploit — the absent-remote local branch, the suffixes, the hex-named branch — had
  verified a worker's key, bound a report the PR's own policy judged, or passed gate 1.
- **The base verify.py, floor_guard.py and diff_scope.py read against is resolved by exact name,
  once** (W3-07 class, second review). `verify.py`'s ancestry, base-binding and `--symbol` checks
  probed `refs/remotes/origin/<base>` and then handed the NAME to `merge-base` and `git grep`: with
  the ref absent, a local `refs/heads/refs/remotes/origin/main` holding a worker's poison commit
  passed both the ancestry proof and the base binding on a sound lane, and a symbol the worker
  committed read as on base. `floor_guard.py` and `diff_scope.py` resolved `--base` (and
  origin/HEAD's target, cut to the short `origin/<x>`) with `rev-parse`, which tries tags and
  local branches first: a tag or local branch spelled `origin/main`, an origin/HEAD pointed at a
  local branch, a suffix such as `origin/main~1`, or the absent-remote local spelling made
  `floor_guard` read a planted waiver (`clean (1 waived)`) and `diff_scope` diff against the
  change's own tip (the AUTH lens off). All three now resolve once through
  `gitexec.remote_tracking_commit` (`gitexec.base_commit` for the two diff tools, where a bare
  local branch name such as `main` stays usable by its exact name with an advisory NOTE), and
  every later diff, waiver, pin, merge-base and grep read names the resolved commit.
