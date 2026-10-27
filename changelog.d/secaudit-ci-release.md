- **CI and the release pipeline no longer let a pull request grade itself** (2026-10-27
  security audit, W6-01 to W6-17). `verdict-gate`, which runs `main`'s copy of
  `scripts/verdict_check.py`, now fails a PR that changes the CI grader (`.github/workflows/`,
  `.github/actions/`, `.github/ci-tools.lock`) unless the repository owner opened it, and a fork
  author's GO on their own PR no longer counts; [ops](../docs/ops.md#merge-gate) says what a
  green gate proves and records the fork-token read-back. The coverage floor combines exactly
  the six shard data files from outside the PR's tree; `.gitleaks.toml` is on the floor guard's
  frozen surface and the secret-scan canary reaches every top-level directory; no checkout
  keeps its token; every `uses:` and every demo-stack image is pinned by test. The publishers
  check the tag before fetching it, `release.yml` marks only the newest tag Latest, and
  `publish-dist` stages the bundle exactly. `gen-badges.py` checks a claimed cut's badge and the
  release commit's shape, release gate 3 needs a job step that runs the script, gates 0 and 4
  read CI on the branch being cut, and both bookkeeping writers refuse raw HTML.
