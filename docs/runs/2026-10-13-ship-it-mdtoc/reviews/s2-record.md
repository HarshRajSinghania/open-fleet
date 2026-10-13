# Review record — S2 (coordinator attestation, no-gh lane)

- reviewed_sha: a960241d781231af4d1bf30ffba27b9887e363d1 (final head after fix round)
- round 1: task_44c348100fae / ctx_f83b49176af2 — PASS with 2 MEDIUM (fenced marker pair chosen as TOC region; duplicated/stray marker pairs silently stale) + LOWs, artifact reviews/s2.md sha256 846486dbbb2281befca69a88078c368d38323ec6df8b3242bb32a151011c4b54
- coordinator disposition: both MEDIUMs fix-now (in-slice defects against AC-1/AC-3 fence discipline, not S3 carry); LOWs fixed: lone-close guard, --stdout prints the full updated document (SPEC AC-4 "prints the result"), --check+--stdout is exit 2, H1-only "# T\n" guard. Fix round task_68f8e06228eb landed a960241; coordinator probes independently re-ran the two MEDIUM repros green.
- round 2 (this verdict): task_74d1c45f852d — PASS, artifact reviews/s2-r2.md sha256 2c5cb38d0a6f1d6228c52035aa64f34cc8a6f0af2062805a399d76d064ff75bd
- builder dispatches: task_a485af881dfc (build, head 5afaf7c), task_68f8e06228eb (fix round)
- reviewers build-blind (not the builders); freshness: reviewed_sha == manifest head_sha.
- deferred LOW (round 2): markers inside inline code spans are matched anywhere on a non-fenced line; fails safe (exit 2) when a real pair also exists. Recorded as a known limit for the integrated prove, post-ship issue candidate — not a third fix round.
- known limits by design (round 1, not re-raised): mixed line endings, non-atomic write, setext H1 anchor, --max-depth 1 empty TOC.
