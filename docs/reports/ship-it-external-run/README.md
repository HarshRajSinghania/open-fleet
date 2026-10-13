# ship-it — external run: mdtoc built from a frozen spec to BUILT (2026-10-13)

The catalog's first `external-run`: the `ship-it` mission took a maintainer-approved
frozen spec (`SPEC.md`, AC-1..AC-8) for a Markdown table-of-contents CLI and built it
in a brand-new external repo, [ravidsrk/mdtoc](https://github.com/ravidsrk/mdtoc),
to the mission's **BUILT** terminal — every slice landed, reviewed build-blind, and
proven at one integrated head (`046d1f8d`, 110 tests).

Bindable core: [`docs/runs/2026-10-13-ship-it-mdtoc.md`](../../runs/2026-10-13-ship-it-mdtoc.md)

`RUN: mission=ship-it tier=external-run inventory_at=c8680a68c197ce25c24393db70afe11e93ae756a manifest=docs/runs/2026-10-13-ship-it-mdtoc/manifest-integrated.json verifier=GREEN waves=6`

## The run in one page

- **Substrate:** OrbStack Linux witness VM (Ubuntu 24.04.5 arm64), `orca-ide` 1.4.224
  serve, Claude Code 2.1.296 workers. The VM holds no GitHub credentials, so slices
  landed by local merge into BASE `fleet/ship-mdtoc-20261013` (build-blind local
  reviews + executed negative controls as the oracle); the coordinator pushed BASE
  from the host at close.
- **Shape:** F0 foundation, then slices S1 (scan+slug), S2 (update+modes), S3
  (multi-file+errors). Two hardening slices the reviews forced: S4 (GitHub-faithful
  slugs) and S5 (line-ending/BOM seams). Three slices needed a fix round after
  review; none merged on a worker's say-so — every unit carries a SHA-bound
  evidence manifest that `verify.py --execute-nc` re-checked, mutant included.
- **The integrated gate earned its keep:** the first whole-product acceptance
  review **FAILed** the assembled build (CR-only files weren't idempotent; a UTF-8
  BOM moved mid-file) after every slice had passed. S5 closed those seams; the
  re-review re-ran every repro byte-for-byte and passed all nine criteria.
- **Terminal:** BUILT @ `046d1f8d0ff63b7193bc06e0c373ba60d9e06849`, pushed to
  `origin/fleet/ship-mdtoc-20261013`. No release gate was requested or taken;
  `main` advancement is the maintainer's step.

## Negative control

The integrated hand control disables fence-awareness in `mdtoc/toc.py` at the built
head: the suite goes RED (19 failures + 1 error), and `verify.py --execute-nc`
re-applies it in a throwaway worktree (RED) against a clean re-run (green).
Transcript: [`negctrl.txt`](negctrl.txt) — assembled verbatim from the two
inventory-pinned halves in the run directory, `prove/int-nc-fixed.txt` (the graded
manifest's `negative_control.artifact`) and `prove/int-nc-run-fixed.txt`. Every
slice carries its own executed control the same way (see the core report).

## Runner credit

Runner: Ravindra Kumar (@ravidsrk) · independent.
Bindable core: `docs/runs/2026-10-13-ship-it-mdtoc.md`.
