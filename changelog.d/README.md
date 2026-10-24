# Unreleased changes, one file per change

Each change that belongs in the [CHANGELOG](../CHANGELOG.md) adds one file here,
`changelog.d/<slug>.md`, instead of editing `CHANGELOG.md`. Only your own PR touches your
fragment, so two open PRs never conflict over the changelog. The release cut
([docs/ops.md](../docs/ops.md#release-cut)) folds every fragment into the new dated section,
newest first, and deletes the fragments.

Write the entry exactly as it will read in the release notes:

```markdown
- **What changed, in one bold sentence** (#123). Why it matters, and what a reader of the
  release notes needs to know to act on it. Continuation lines are indented two spaces.
```

The rules `python3 scripts/changelog.py check` enforces (CI runs it in `validate.py`):

- the name is a lowercase slug ending `.md`: letters, digits, `.`, `_` or `-`. Use the branch
  or issue, for example `629-floor-guard.md`;
- every entry opens with `- ` at column 0, and every other line is indented two spaces;
- no blank lines and no headings, since either would split the release list;
- a relative link is written from this directory, `[ops](../docs/ops.md)`, so the repository's
  link check reads it where it sits; the cut drops the `../` when it moves the entry into
  `CHANGELOG.md` at the root;
- UTF-8, LF line endings, a final newline.

On a pull request CI also runs `python3 scripts/changelog.py check --base <base>`, which fails if
`CHANGELOG.md`'s `## [Unreleased]` section gained an entry. The entries already there predate
fragments; the cut folds them in after the fragments. `python3 scripts/changelog.py preview`
prints what the next release section will hold.
