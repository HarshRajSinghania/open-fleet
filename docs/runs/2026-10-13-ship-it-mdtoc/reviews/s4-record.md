# Review record — S4 (coordinator attestation, no-gh lane)

- reviewed_sha: 4aa77558d1be809ed98acb5ea2847386ef3e9a5d (final head after fix round)
- round 1: task_0b0d754f0f19 — PASS with 1 MEDIUM (autolinks `<http://x>` eaten as HTML tags, heading vanishes from TOC), artifact reviews/s4.md (sha256 pinned in manifest-s4.json)
- coordinator disposition: MEDIUM fix-now (introduced by this slice's own tag regex); the two unguarded-but-correct behaviors (precomposed-accent slug, duplicate suffixes counting depth-filtered headings) gained guards. Fix round task_479d83732bdf landed 4aa7755; coordinator probes re-ran the MEDIUM repro + S4 regression battery green.
- round 2 (this verdict): task_0f6a01c06b41 — PASS, no findings of any severity, artifact reviews/s4-r2.md (sha256 pinned in manifest-s4.json)
- builder dispatches: task_204bc820b2ec (build, head ec5b1f5), task_479d83732bdf (fix round)
- reviewers build-blind (not the builders); freshness: reviewed_sha == manifest head_sha.
- known limits by design (recorded, deferred): sentinel codepoint collision in code-span stashing, quoted `>` inside tag attributes, balanced parens in link destinations, reference-style links unresolved.
