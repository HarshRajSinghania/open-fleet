- **The tests badge is the last release's own, checked in CI, and HTML links are refused in
  run-index rows and changelog fragments** (PR #670 review). #670 relabelled the badge "test
  functions at last release" but kept 4714 while v0.8.0 had 3270; it is restored from the cut
  commit, and `gen-badges.py --check-last-release` (CI's `checks` job) fails unless the badge is
  byte for byte the one at the cut `docs/releases.json` names. A run-index cell or a fragment
  now refuses an HTML `href`/`src`, which no link check resolved and the cut never rewrote,
  including a tag split across lines. AGENTS.md points at the new bookkeeping rules.
