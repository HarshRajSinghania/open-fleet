# Binding contract: #596 live first runs, 2026-10-24

Frozen and committed before the run's artifacts. The unit binds the archive of the live first runs
that the certification record cites. Each criterion is re-derived from the committed files, not
from anyone's narration.

- LR-1: each cited receipt reads `verdict: GO`, `tier: live-unreviewed` and worker `live`. Its
  catalog commit is `b96d47e3354564e1593d34182a817ae04e54545d` with `catalog_dirty: false`, and
  every lifecycle step from `prereqs` to `release` is ok, with `verify.py` returning OK.
- LR-2: the dev-Mac runs (`mac-ro/`, `mac-rw/`) ran Claude Code 2.1.304 through the isolation
  wrapper retained in `isolation/`. Their transcripts name the model and the cost, and their own
  first-run manifest, contract, change and report are retained beside the receipt.
- LR-3: the clean-host runs (`clean-host/`) ran in a fresh `ubuntu:24.04` container from a fresh
  clone, through the scripts retained there. Those scripts pass no credential except
  `CLAUDE_CODE_OAUTH_TOKEN`, by name.
- LR-4: the earlier runs at `456051e3ec` (`first-attempt/`) are retained as the finding they
  were: `ro` GO, and `rw` NO-GO at `result` because the rw assignment never asked for the report
  as the final answer.
- LR-5: the Orca `ro`/`claude` re-witness attempt (`orca-ro-attempt/`) is retained as refused
  before any injection. It certifies nothing.
