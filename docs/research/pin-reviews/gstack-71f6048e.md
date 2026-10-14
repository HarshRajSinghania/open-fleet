# Pin review — gstack 71f6048e8ada

Dated snapshot: 2026-10-14. Rug-pull review (RES-05) for the `gstack` pin in
`runtime/pins.json`: baseline inventory at `71f6048e8ada25180e61438abc1d98cb151fe9a7`.
Upstream: https://github.com/garrytan/gstack.git

Verdict: baseline recorded (clean as a starting point — an inventory,
not a line-by-line audit). Future bumps diff against this surface.

## Changed surface by class

### instruction (236)

- 236 files; by top-level directory:
  - `.github/`: 1
  - `AGENTS.md/`: 1
  - `ARCHITECTURE.md/`: 1
  - `BROWSER.md/`: 1
  - `CHANGELOG.md/`: 1
  - `CLAUDE.md/`: 1
  - `CONTRIBUTING.md/`: 1
  - `DESIGN.md/`: 1
  - `ETHOS.md/`: 1
  - `NOTICE.md/`: 1
  - `README.md/`: 1
  - `SKILL.md/`: 1
  - `TODOS.md/`: 1
  - `USING_GBRAIN_WITH_GSTACK.md/`: 1
  - `agents-digest/`: 1
  - `autoplan/`: 6
  - `benchmark/`: 1
  - `benchmark-models/`: 1
  - `browse/`: 3
  - `browser-skills/`: 1
  - `canary/`: 1
  - `careful/`: 1
  - `codex/`: 4
  - `context-restore/`: 1
  - `context-save/`: 1
  - `cso/`: 3
  - `design-consultation/`: 2
  - `design-html/`: 4
  - `design-review/`: 1
  - `design-shotgun/`: 2
  - `devex-review/`: 1
  - `diagram/`: 1
  - `docs/`: 50
  - `document-generate/`: 1
  - `document-release/`: 2
  - `freeze/`: 1
  - `gstack/`: 1
  - `gstack-upgrade/`: 1
  - `guard/`: 1
  - `health/`: 1
  - `investigate/`: 1
  - `ios-clean/`: 1
  - `ios-design-review/`: 1
  - `ios-fix/`: 1
  - `ios-qa/`: 2
  - `ios-sync/`: 1
  - `land-and-deploy/`: 4
  - `landing-report/`: 1
  - `learn/`: 1
  - `lib/`: 2
  - `licenses/`: 1
  - `make-pdf/`: 6
  - `model-overlays/`: 11
  - `office-hours/`: 4
  - `open-gstack-browser/`: 1
  - `openclaw/`: 11
  - `pair-agent/`: 1
  - `plan-ceo-review/`: 2
  - `plan-design-review/`: 2
  - `plan-devex-review/`: 3
  - `plan-eng-review/`: 2
  - `plan-tune/`: 1
  - `qa/`: 5
  - `qa-only/`: 1
  - `retro/`: 2
  - `review/`: 16
  - `scrape/`: 1
  - `setup-browser-cookies/`: 1
  - `setup-deploy/`: 1
  - `setup-gbrain/`: 6
  - `ship/`: 10
  - `skillify/`: 1
  - `spec/`: 2
  - `sync-gbrain/`: 1
  - `test/`: 21
  - `unfreeze/`: 1

### permission-surface (39)

- `A .github/actionlint.yaml`
- `A .github/actions/fix-bun-temp/action.yml`
- `A .github/actions/register-gstack-skills/action.yml`
- `A .github/actions/restore-deps/action.yml`
- `A .github/actions/seed-claude-config/action.yml`
- `A .github/dependabot.yml`
- `A .github/workflows/actionlint.yml`
- `A .github/workflows/ci-image.yml`
- `A .github/workflows/dependency-review.yml`
- `A .github/workflows/evals-periodic.yml`
- `A .github/workflows/evals.yml`
- `A .github/workflows/free-tests.yml`
- `A .github/workflows/make-pdf-gate.yml`
- `A .github/workflows/osv-scanner.yml`
- `A .github/workflows/pr-title-sync.yml`
- `A .github/workflows/quality-gate.yml`
- `A .github/workflows/skill-docs.yml`
- `A .github/workflows/version-gate.yml`
- `A .github/workflows/windows-free-tests.yml`
- `A .github/workflows/windows-setup-e2e.yml`
- `A careful/bin/hook-extract.sh`
- `A hosts/claude/hooks/auq-error-fallback-hook`
- `A hosts/claude/hooks/auq-error-fallback-hook.ts`
- `A hosts/claude/hooks/memorable-user-prompt-hook`
- `A hosts/claude/hooks/memorable-user-prompt-hook.ts`
- `A hosts/claude/hooks/question-log-hook`
- `A hosts/claude/hooks/question-log-hook.ts`
- `A hosts/claude/hooks/question-preference-hook`
- `A hosts/claude/hooks/question-preference-hook.ts`
- `A hosts/claude/hooks/spawn-bin.ts`
- `A hosts/claude/hooks/spawned-directive.ts`
- `A hosts/claude/hooks/timeline-stop-hook`
- `A hosts/claude/hooks/timeline-stop-hook.ts`
- `A lib/diagram-render/package.json`
- `A package.json`
- `A test/fixtures/arm-benchmark/bugfix-decoys/package.json`
- `A test/fixtures/arm-benchmark/crud-endpoint/package.json`
- `A test/hook-scripts.test.ts`
- `A test/hooks-windows-paths.test.ts`

### code (1326)

- 1326 files; by top-level directory:
  - `.env.example/`: 1
  - `.gitattributes/`: 1
  - `.github/`: 2
  - `.gitignore/`: 1
  - `.gitlab-ci.yml/`: 1
  - `.osv-scanner.toml/`: 1
  - `LICENSE/`: 1
  - `SKILL.md.tmpl/`: 1
  - `VERSION/`: 1
  - `agents/`: 1
  - `autoplan/`: 7
  - `benchmark/`: 1
  - `benchmark-models/`: 1
  - `bin/`: 86
  - `browse/`: 242
  - `browser-skills/`: 4
  - `bun.lock/`: 1
  - `bunfig.toml/`: 1
  - `canary/`: 1
  - `careful/`: 2
  - `claude/`: 1
  - `codex/`: 5
  - `conductor.json/`: 1
  - `connect-chrome/`: 1
  - `context-restore/`: 1
  - `context-save/`: 1
  - `contrib/`: 1
  - `cso/`: 3
  - `design/`: 34
  - `design-consultation/`: 3
  - `design-html/`: 6
  - `design-review/`: 1
  - `design-shotgun/`: 3
  - `devex-review/`: 1
  - `diagram/`: 1
  - `docs/`: 7
  - `document-generate/`: 1
  - `document-release/`: 3
  - `extension/`: 16
  - `freeze/`: 2
  - `gstack-upgrade/`: 14
  - `guard/`: 1
  - `health/`: 1
  - `hosts/`: 12
  - `investigate/`: 1
  - `ios-clean/`: 1
  - `ios-design-review/`: 1
  - `ios-fix/`: 1
  - `ios-qa/`: 36
  - `ios-sync/`: 1
  - `land-and-deploy/`: 5
  - `landing-report/`: 1
  - `learn/`: 1
  - `lib/`: 47
  - `make-pdf/`: 35
  - `office-hours/`: 5
  - `open-gstack-browser/`: 1
  - `pair-agent/`: 1
  - `patches/`: 1
  - `plan-ceo-review/`: 3
  - `plan-design-review/`: 3
  - `plan-devex-review/`: 3
  - `plan-eng-review/`: 3
  - `plan-tune/`: 1
  - `qa/`: 4
  - `qa-only/`: 1
  - `retro/`: 3
  - `review/`: 5
  - `scrape/`: 1
  - `scripts/`: 85
  - `setup/`: 1
  - `setup-browser-cookies/`: 1
  - `setup-deploy/`: 1
  - `setup-gbrain/`: 6
  - `ship/`: 11
  - `skillify/`: 1
  - `slop-scan.config.json/`: 1
  - `spec/`: 3
  - `supabase/`: 9
  - `sync-gbrain/`: 1
  - `test/`: 562
  - `test-setup.ts/`: 1
  - `unfreeze/`: 1

## Reviewer notes

Instruction changes read: baseline inventory — 236 files (skill
directories per capability plus root SKILL.md/ETHOS/CLAUDE docs)
recorded for future bumps to diff against.
Permission-surface changes read: baseline inventory — 39 files: the
pack's own GitHub workflows (inert here), 11 executable hooks under
hosts/claude/hooks/ (the part a bump must diff line-by-line: these run
inside a worker that mounts the pack), one hook-extract script, and
package manifests.

