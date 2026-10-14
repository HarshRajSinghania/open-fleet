# Pin review — mattpocock 3cca18b368ae

Dated snapshot: 2026-10-14. Rug-pull review (RES-05) for the `mattpocock` pin in
`runtime/pins.json`: baseline inventory at `3cca18b368ae95cdbdebbff572ccafa662551015`.
Upstream: https://github.com/mattpocock/skills.git

Verdict: baseline recorded (clean as a starting point — an inventory,
not a line-by-line audit). Future bumps diff against this surface.

## Changed surface by class

### instruction (153)

- 153 files; by top-level directory:
  - `.agents/`: 5
  - `.changeset/`: 10
  - `.out-of-scope/`: 3
  - `AGENTS.md/`: 1
  - `CHANGELOG.md/`: 1
  - `CLAUDE.md/`: 1
  - `CONTEXT.md/`: 1
  - `README.md/`: 1
  - `docs/`: 25
  - `skills/`: 105

### permission-surface (4)

- `A .claude-plugin/marketplace.json`
- `A .claude-plugin/plugin.json`
- `A .github/workflows/release.yml`
- `A package.json`

### code (7)

- `A .changeset/config.json`
- `A .gitignore`
- `A LICENSE`
- `A package-lock.json`
- `A scripts/link-skills.sh`
- `A scripts/list-skills.sh`
- `A scripts/sync-plugin-version.mjs`

## Reviewer notes

Instruction surface inventoried: 153 files.
Permission surface read: 4 files — plugin/marketplace manifests and one
release workflow; no hooks, no settings asks at this pin.

