- **CI runs in about half the wall time, and independent PRs no longer conflict on bookkeeping
  files.** A new `checks` job runs every gate that reads no shard output (trailers, validate,
  routing, proof honesty and binding, bundle, skills-ref, the secret scan, ruff) from t=0 beside
  the shards; `gates` stays the one required context, needs `checks`, and keeps only the needs
  verification and the D9 coverage combine. `scripts/shard-tests.py` now splits a module whose
  weight file records class weights into one unit per TestCase class (`test_wip_curve` was a
  640-745 s shard on its own), and every lane runs six shards instead of four. Four shared
  files stop taking a line per PR: changelog entries are `changelog.d/<slug>.md` fragments the
  release cut folds in (`scripts/changelog.py`, and CI refuses a new `[Unreleased]` entry); the
  tests badge is regenerated only by the release cut and reads "at the last release" in the
  README (`gen-badges.py --release`); the run index's rows are one `docs/runs/index/<run>.json`
  per run, and the table and its "N read yes" summary are generated from them at the cut
  (`scripts/run_index.py`); shard weights are one `tests/shard-weights/<module>.json` per module.
  `release_check.py` gains a bookkeeping check, and `docs/ops.md`'s release blocks run all three
  generators.
