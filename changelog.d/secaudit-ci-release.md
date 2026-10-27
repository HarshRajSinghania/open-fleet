- **CI and the release pipeline no longer let a pull request grade itself** (2026-10-27
  security audit, W6-01 to W6-17). `verdict-gate`, which runs `main`'s copy of
  `scripts/verdict_check.py`, now fails a PR that changes the CI grader (`.github/workflows/`,
  `.github/actions/`, `.github/ci-tools.lock`) unless the repository owner opened it, and a GO
  counts only from an OWNER, MEMBER or COLLABORATOR review, so neither an outsider's APPROVED
  review nor a fork author's GO on their own PR does; [ops](../docs/ops.md#merge-gate) says what
  a green gate proves and records the fork-token read-back. The coverage floor no longer reads a
  `.coverage.*` file planted in the PR's tree (coverage remains the PR's own measurement of
  itself, an accepted residual); `.gitleaks.toml` is on the floor guard's frozen surface, the
  secret scan ignores the tree's `.gitattributes`, and its canary proves no waiver covers a
  top-level directory wholesale (a narrower allowlist is the floor guard's to stop); no checkout keeps its token; every
  `uses:` and every demo-stack image is pinned by test, and every workflow must stay in the
  block YAML subset those tests and release gate 3 read line by line. The publishers check the tag before
  fetching it, `release.yml` marks only the newest tag Latest, and `publish-dist` stages the
  bundle exactly. `gen-badges.py` checks a claimed cut's badge and the release commit's shape,
  release gate 3 counts only an unconditional step (no `needs:`, matrix, reusable workflow or
  container) of a pull-request workflow whose whole
  `run:` is the script under python3, bash or sh and nothing else, gates 0 and 4 read CI on the branch
  being cut, and both bookkeeping writers refuse raw HTML and a link scheme that runs or reads
  something (javascript, vbscript, data, file), however it is escaped.
