# Pin review — addyosmani be4e44a9fbc5

Dated snapshot: 2026-10-14. Rug-pull review (RES-05) for the `addyosmani` pin in
`runtime/pins.json`: baseline inventory at `be4e44a9fbc5e8df0beaefadbb28bd22ee61cc39`.
Upstream: https://github.com/addyosmani/agent-skills.git

Verdict: baseline recorded (clean as a starting point — an inventory,
not a line-by-line audit). Future bumps diff against this surface.

## Changed surface by class

### instruction (95)

- 95 files; by top-level directory:
  - `.claude/`: 10
  - `.opencode/`: 1
  - `AGENTS.md/`: 1
  - `CLAUDE.md/`: 1
  - `CONTRIBUTING.md/`: 1
  - `README.md/`: 1
  - `agents/`: 4
  - `docs/`: 16
  - `evals/`: 23
  - `references/`: 7
  - `skills/`: 30

### permission-surface (18)

- `A .agents/plugins/marketplace.json`
- `A .claude-plugin/marketplace.json`
- `A .claude-plugin/plugin.json`
- `A .codex-plugin/plugin.json`
- `A .github/ISSUE_TEMPLATE/skill-gap.yml`
- `A .github/workflows/test-plugin-install.yml`
- `A evals/fixtures/ci-cd-and-automation/package.json`
- `A evals/fixtures/test-driven-development/package.json`
- `A hooks/SDD-CACHE.md`
- `A hooks/SIMPLIFY-IGNORE.md`
- `A hooks/hooks.json`
- `A hooks/sdd-cache-post.sh`
- `A hooks/sdd-cache-pre.sh`
- `A hooks/session-start-test.sh`
- `A hooks/session-start.sh`
- `A hooks/simplify-ignore-test.sh`
- `A hooks/simplify-ignore.sh`
- `A plugin.json`

### code (84)

- 84 files; by top-level directory:
  - `.gemini/`: 9
  - `.gitattributes/`: 1
  - `.gitignore/`: 1
  - `LICENSE/`: 1
  - `commands/`: 9
  - `evals/`: 50
  - `scripts/`: 13

## Reviewer notes

Instruction surface inventoried: 95 files.
Permission surface read: 18 files — plugin/marketplace manifests;
no hook scripts at this pin.

