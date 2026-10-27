# W6 — CI, release pipeline and release bookkeeping

RUN: run_secaudit_20261027 · AUDITOR: w6 (red team) · BASE: review/2026-10-27-security-audit @
15e03dfedbf5 · SCOPE-OWNER: B6 (CI and release pipeline) · SOURCE: `threat-model.md` (B6, B3,
STRIDE Elevation + supply chain) · MODE: static/read-only, scratch PoCs in a `mktemp -d`

Scope read in full: all 13 files in `.github/workflows/`, `.github/CONTRIBUTING.md`,
`.github/CODEOWNERS`, `.github/ci-tools.lock`, `scripts/release_check.py`, `scripts/gen-badges.py`,
`scripts/changelog.py`, `scripts/run_index.py`, `scripts/verdict_check.py`,
`scripts/shard-tests.py`, `scripts/bundle.py`, `docs/release-1.0-checklist.md`,
`docs/ops.md#merge-gate`, `docs/ops.md#release-cut`, `docs/ops.md#publishing-releases`,
`docs/releases.json`, `evals/demo/target-app/compose.yaml`. `.github/actions/` does not exist;
`runtime/scripts/publish-dist*` does not exist (`publish-dist` is a workflow only).

Hunt order followed as briefed: `pull_request_target` → expression injection → `permissions:` →
third-party pins → fork secrets / `workflow_run` artifact trust → release path → bookkeeping
scripts. Headline: **this pipeline is the strongest surface in the tree — no
`pull_request_target` at all, zero inline `${{ }}` in a `run:`, all 46 actions on full SHAs, no
secret reachable from a fork PR.** What survives is the reflexivity problem: the gate that
protects `main` is *built by the thing it gates*, and three bookkeeping/release controls can be
turned off by the file they read.

Severity: P0 secret exfil or write to `main`/a release from a fork PR · P1 needs a maintainer
action or a crafted merge · P2 hardening · P3 cosmetic.

## Findings

| id | file:line | sev | class | untrusted input | exploit scenario | gain | why it fails | PoC |
|---|---|---|---|---|---|---|---|---|
| W6-01 | `.github/workflows/validate.yml:272-303`, `guard.yml:19-27`, `negative-control.yml:8-11`; `.github/CODEOWNERS:5-9`; `docs/ops.md:44-51` | P1 | Elevation / repudiation — the graded party supplies the grader | PR-authored workflow YAML | Fork PR `evil:green-my-gate` replaces the `gates` job body with `steps: [{run: echo ok}]`, deletes `needs:`/the needs-check step, empties `guard.yml`'s job the same way, pushes; `gates`, `guard` and `pinned-demo` all conclude success on the head SHA with every real gate (secret scan, vf-bench, coverage floor, floor-guard, trailer rule) skipped. One owner click merges — no review is required | `main` takes code that passed nothing, and the merge-gate numbers are fiction | A `pull_request` run loads its workflow from the **merge ref**, so the PR's own YAML is the gate. Required contexts match by *name* from app 15368; `guard`/`pinned-demo`/`gates` have no pinned identity (only `verdict-gate` got one — ops.md:53-69). `CODEOWNERS` cannot help: ops.md:50-51 says "No approving review is required", so nothing enforces code-owner review either, and every `@agentsalpha` entry is inert | written demonstration; the mitigation is cited as *the* reason `verdict-gate` exists (verdict-check.yml:3-8) and was not extended to the rest |
| W6-02 | `.github/workflows/validate.yml:68-82` (upload `path: .coverage.*`, `include-hidden-files: true`), `validate.yml:318-339` (`download-artifact` `merge-multiple: true` → `coverage combine` → `coverage report`) | P2 | Tampering — the artifact the floor reads is written by the PR | any file matching `.coverage.*` in the checkout root | `tests/test_zz.py` builds a `coverage` data file (`CoverageData.add_lines` for every line of every `scripts/**` and `runtime/scripts/**` file) and saves it as `./.coverage.pad` at import time. The shard's upload glob picks it up, `gates` merges all six artifacts into the checkout root, `combine` unions it, `coverage report` reads 100 % against `.coveragerc`'s `fail_under = 80` | the D9 floor passes while the suite covers far less; the poisoned file also inflates *other* PRs, since one bad data file raises the merged total | none of the six data files is produced anywhere the PR cannot reach: `--parallel-mode` writes into the cwd, which is the PR's own tree, and `download-artifact` trusts the artifact's bytes. `.coveragerc` (the bar) is on the frozen guard surface; the *data* the bar is measured on is not | written demonstration; `coverage` absent from this checkout so the data file could not be generated here |
| W6-03 | `.github/workflows/validate.yml:208-253`; `.gitleaks.toml:31-33`; `runtime/scripts/floor_guard.py:193-198` | P2 | Tampering — a waiver mechanism outside the negative control | `.gitleaks.toml` | PR adds `[[allowlists]]` with `paths = ['''^scripts/.*''']` and commits a live token in `scripts/whatever.py`. `detect --redact` reports nothing; `gates` stays green; no waiver is needed because the negative control plants its canary in `tests/test_decisions.py` only (validate.yml:245-253), which the new allowlist does not cover, so the canary still passes | a real credential lands in the tree that the mandatory secret scan looked at and saw nothing | `GUARD_SURFACE_FILES` lists `.gitleaksignore` but **not** `.gitleaks.toml`, and floor_guard's own comment (line 11-15 of the toml) records that a path allowlist waives a whole file. The control is proven for one file shape (fingerprint ignore), so it cannot see the other one | written demonstration (allowlist semantics documented at `.gitleaks.toml:10-21`, unguarded path confirmed by `grep` of `floor_guard.py:193-198`) |
| W6-04 | `.github/workflows/publish-dist.yml:128-133` (`git init` → `git add -A`); `scripts/bundle.py:432-441` | P2 | Tampering — silent payload loss in the published artifact | a dotfile committed under `skills/<mission>/` | Fork PR adds `skills/ship-it/.gitignore` containing `*.md`. `bundle.py` copies it (the `extra` loop and `copytree` take dotfiles; the shipped inventory `bundle-files.json` still *lists* every file). `bundle.py --check` builds on disk and stays green. The next tag's publish `git add -A` honours it and omits every markdown file of that mission from the `dist` branch | the published installer target ships a mission with no `SKILL.md` prose beyond what survives, and its own inventory claims the missing files exist | the check validates the filesystem, the publish path validates git's index; `--check` cannot see a `.gitignore`. Root `.gitignore` is not copied (`PLUGIN_LISTING`/`runtime_files()` take named files and `.py/.sh/.json` only), so nothing else exercises this | **PoC run**: `mkdir skills/m; printf '*.md\n' > skills/m/.gitignore; git init; git add -A` → `git ls-files` = `skills/m/.gitignore` only; `notes.md`/`SKILL.md` untracked though present on disk |
| W6-05 | `.github/workflows/*.yml` `permissions:` (all 13 are `contents: read` or narrower on PR events); `docs/ops.md:42-51` | P2 | Elevation — an unstated repo setting decides fork authority | GitHub setting "Send write tokens to workflows from pull requests" (not in the tree) | With that setting ON, a fork PR that adds `permissions: contents: write` to `validate.yml` and pushes to `main` from a step gets `main` written on its own PR run. With it OFF (GitHub's default) nothing is writable and W6-01's blast radius shrinks to "green but inert". Nothing in the repo records which mode is in force, and no workflow can detect it | with the setting on, a fork PR writes `main` without a merge — the P0 shape — and the docs never say the gate depends on it | the mode is a repository setting; `ops.md` documents the required contexts by API read-back (line 44) and the tag ruleset by id (line 294) but not this | not determinable from code; **action**: read back `GET /repos/ravidsrk/open-fleet` → `actions`/fork token behaviour and record the answer beside the required-context list |
| W6-06 | `scripts/verdict_check.py:77-81`, `verdict-check.yml:66-71`, `docs/ops.md:48-51` | P2 | Spoofing — the required check cannot distinguish review from self-assertion | `pull_request_review` body from the PR author | Fork PR author posts a COMMENTED review `VERDICT: GO` + `reviewed_sha: <their own head>`. `_author_trusted` accepts the PR author unconditionally; `verdict-gate` posts `verdict-gate=success` as the app; the last required context goes green | the only remaining human-shaped control is the owner's merge click; Codex is the only independent reader, and its GO is not required by anything | `open-fleet` has one human, GitHub forbids self-approval, so self-GO was the deliberate answer — but then `verdict-gate` proves *SHA binding*, not that anyone read the diff, and the two are easy to conflate when reading a green PR | cited design (verdict_check.py:21-26, ops.md:100-108), no defect — filed so the gate's claim is not overstated |
| W6-07 | `guard.yml:33-36`, `bind-check.yml:19-22`, `validate.yml:33-35`, `publish-dist.yml:62-66` | P3 | Information disclosure — token written into a working tree that then runs PR code | `.git/config` of the PR checkout | Checkout keeps `persist-credentials` default (true) on the PR-tree path; later steps run `python3 scripts/validate.py`, `floor_guard.py`, the whole suite. Anything in the PR can read `.git/config`'s `http.https://github.com/.extraheader` (base64 `x-access-token:<token>`) and POST it out | a read-only `contents` token leaves the runner (already public-repo-readable, so the gain is small) | the base-checker checkouts set `persist-credentials: false` (guard.yml:45, bind-check.yml:33); the PR-tree ones do not, and they are the ones whose tree executes | cited; mechanism is `actions/checkout`'s documented default |
| W6-08 | `scripts/gen-badges.py:374-376`; `validate.yml:162-165` (`--check-last-release`) | P3 | Tampering — a JSON flag turns a gate off | `docs/releases.json`'s `preparing` | PR sets `"preparing": {"version":"9.9.9","cut_date":"…"}` plus a matching newest dated `CHANGELOG` heading; `last_release_badge_errors` returns `[]` before reading anything (`if data.get("preparing") … return []`), so `docs/assets/badges/tests.json` may say any number | the "badge is the last release's own" gate is silently off | correct for a real cut, but nothing distinguishes a cut from a PR that merely claims one; the shape test still runs, the *byte-equality* test does not | cited |
| W6-09 | `scripts/gen-badges.py:381` | P3 | Injection (argv, not shell) — unvalidated value in `git show`'s spec | `releases[-1]["commit"]` | PR appends a release row with `"commit": "--output=/tmp/x"` → `git show` receives `--output=/tmp/x:docs/assets/badges/tests.json`, is read as an option, and writes `/tmp/x:docs/...`. Not shell, so no command execution | confusion, plus a stray file; no authority gained | the field is only ever a 40-hex SHA in practice, and nothing validates it is one before it becomes part of an argv *option position* | cited |
| W6-10 | `scripts/release_check.py:565-578` | P3 | Repudiation — "CI runs X" satisfied by text, not execution | any `run:` line in any workflow | PR adds `- run: echo negative-control` to a workflow's step; `gate3/ci-runs-negative-control` and `gate3/ci-runs-vf-bench` both PASS with the real jobs deleted. The code already stripped comments (line 561) and step names, but not quoting/dead steps | release gate 3 records CI coverage that does not exist | `workflow_run_text` is a text scan; it never asks whether the step runs or what it invokes | cited |
| W6-11 | `.github/workflows/release.yml:31`, `56-62`, `84-91` | P3 | Spoofing / release path | dispatch `inputs.tag` | `gh workflow run release.yml -f tag=anything` publishes a Release for a non-`v*` existing tag: `TAG` is never shape-checked here (`publish-dist.yml:76-79` has that `case`, release.yml does not). No newest-tag guard either, and no `--latest=false`, so publishing a *missing historical* tag moves GitHub's "Latest" badge onto it | `Latest` points at a superseded release; the Releases index now carries a non-version entry | the two publishers diverged: publish-dist refuses branch/lightweight/older, release.yml refuses only lightweight+off-main | cited; `--verify-tag`+annotated+on-main are present and correctly ordered |
| W6-12 | `scripts/release_check.py:265-286`; `docs/ops.md:117` | P3 | Denial (of the gate) — the check's own premise contradicts the documented flow | the branch the cut is run from | ops.md says start on a release branch; gate 4 requires a green `install` run on **`main`** whose `headSha` equals local `HEAD`. On a release branch those never match → `gate4/gh-install-run-green-at-head` FAILs at the cut, so `release_check.py` exits 1 and the maintainer must either cut on `main` or take a red gate | the release gate's exit code stops being a verdict on a release branch | the "stale green must not count" rule is right for `main`; the branch assumption was left implicit | cited (code read; not run — needs `gh`) |
| W6-13 | `evals/demo/target-app/compose.yaml:6,19,32,40,53,62,69` | P3 | Supply chain — mutable container refs | seven `image:` tags, no digest | `python:3.13-slim`, `prom/prometheus:v2.53.0`, `grafana/grafana:10.4.3`, `grafana/loki:3.1.0`, `grafana/promtail:3.1.0`, `prom/alertmanager:v0.27.0` — every one a re-pointable tag (and `python:3.13-slim` re-points on every patch release by design). `smoke` runs `docker compose up --build`, and the containers `pip install` from the network | a retagged image runs in the job; nothing verifies it | the workflow header claims "Pins + permissions below are S0's and stay pinned (never mutable tags)", and `EveryWorkflowToolComesFromAHashedLock` only greps `uvx`/`pip install`/`uv tool run` — `docker` is outside its regex entirely | cited |
| W6-14 | `scripts/run_index.py:263-275`, `scripts/changelog.py:250-274` | P3 | Injection — raw HTML reaches a generated Markdown page | a `docs/runs/index/*.json` cell, or a `changelog.d/*.md` line | both writers refuse raw HTML that carries `href`/`src`, so `<script>alert(1)</script>` (no href/src) passes every check and is emitted verbatim into `docs/runs/README.md` / `CHANGELOG.md`. Inside a table cell it stays one line | raw HTML in a published page; on github.com `<script>` is sanitised, so this only bites a non-GitHub renderer of the same Markdown | `html_link()` returns `None` for a tag with no `href`/`src`, and both call sites treat `None` as safe | **PoC run**: `row_errors(<real row>, {"outcome": "<script>alert(1)</script>", …})` → `[]`; `render()` emits the tag verbatim in the row |
| W6-15 | `.github/workflows/*.yml` (46 `uses:` lines) | P3 | Supply chain — a convention with no test | a future PR's `uses:` line | every action is a full 40-hex SHA today (correct), but nothing fails a later `uses: actions/checkout@v4`. `tests/test_pins.py` pins the *pip* lock and `test_repo_hygiene.py:546-574` pins install *commands*; no test reads `uses:` | one review-time slip re-opens the whole action supply chain, silently | the property is enforced by reviewer attention only, in a repo whose stated discipline is "a version string with no hash and no test is a comment" (ci-tools.lock:3-5) | cited (`grep -v '@[0-9a-f]\{40\}'` over `uses:` returns none) |
| W6-16 | `.github/workflows/publish-dist.yml:65`, `71-79` | P3 | Injection (maintainer-typed, not fork) | `inputs.tag` | `ref:` takes `format('refs/tags/{0}', inputs.tag)` raw into the checkout action, and `TAG` reaches the shell from env. `case` only checks `v[0-9]*` *after* the checkout has already resolved the ref, so a value with a space or a refspec (`refs/tags/v1:refs/heads/x`) is fetched before validation | a confusing checkout, then a clear refusal; no authority | maintainer-typed and the guard runs immediately after | cited |
| W6-17 | `.github/workflows/alert-on-failure.yml:14-18`, `main-health.yml:35` | P3 | Repudiation — ops reflexivity keyed to names | workflow `name:` fields | `workflows: [validate, negative-control-demo]` matches by workflow *name*; renaming either workflow (or `validate.yml`'s `name:`) silently blinds the alert path, and `main-health` hardcodes the filename. Nothing asserts the two lists agree | the 2 a.m. alert stops firing with a green CI file | the matching key is a display string that no test holds | cited |

## Cleared areas (checked, no finding)

- **`pull_request_target` — absent.** `grep -rn pull_request_target .github/` returns nothing. The
  classic "base context + PR head checkout + secret" shape is replaced by the
  `pull_request_review` → `workflow_run` split. A PR-authored *new* workflow also cannot run
  pre-merge, so no fork workflow gets base authority.
- **`${{ }}` into a `run:` block — zero occurrences.** All 96 expressions land in `env:`, `if:`,
  `with:`/`ref:`, `name:` or `concurrency.group`, or reach Python via `os.environ`
  (`validate.yml:288-303`). Enumerated every one; the tainted classes
  (`github.event.pull_request.base.sha`, `github.base_ref`, `github.event.workflow_run.head_sha`,
  `.head_branch`, `.name`, `steps.*.outputs.*`, `toJSON(needs)`) are all `env:`-routed and
  shell-quoted. `tests/test_repo_hygiene.py:510-543` is the machine control.
- **`permissions:`** present on all 13. Workflow-level `write` exists only on the two tag
  publishers (`contents: write`) and each is gated on the owner; `issues: write` only on the two
  alert workflows; `statuses: write` scoped to the single `verdict-gate` job under top-level
  `permissions: {}`.
- **`workflow_run` + untrusted artifacts.** Neither `verdict-gate` nor `alert-on-failure` reads
  an artifact of the triggering run: both re-derive from the API and pin the checkout to the
  default branch (`ref: ${{ github.sha }}`, verdict-gate.yml:55/93); `alert-on-failure` also
  requires `event == 'push'` **and** `head_repository.full_name == github.repository`
  (lines 34-36), which kills the "fork branch named `main`" trick its own comment names.
- **Fork PR secrets.** `secrets.*` appears only in `verdict-check.yml` (`GITHUB_TOKEN`,
  read-only) and `verdict-gate.yml` (`GITHUB_TOKEN`, plus `VERDICT_GATE_PRIVATE_KEY` from an
  environment restricted to `main` and consumed by a SHA-pinned `create-github-app-token`). No
  repository secret is reachable from a `pull_request` run.
- **Third-party pins.** All 46 `uses:` are full SHAs; `docker://` absent; `npm i -g` absent; the
  only `curl` (gitleaks, validate.yml:217-219) is sha256-checked *before* extraction;
  `pip install` is `--require-hashes --only-binary :all:` everywhere and test-enforced.
- **Release path, artifact substitution.** Releases carry no assets at all
  (`gh release create` has no glob), so nothing can be substituted between build and publish;
  notes come from the tag's own CHANGELOG after `--verify-tag`, annotated check and
  `merge-base --is-ancestor … origin/main`; the version reaches the section regex through
  `re.escape`; the file section is read with `sys.argv`, never interpolated.
- **Tag mutability.** Annotated-only, must be on `main`, newest-only (publish-dist, re-checked a
  second time against freshly fetched refs *and* against `dist`'s own provenance file before the
  force-push), with the admin-only tag ruleset recorded by id (`ops.md:294-311`). Both publishers
  refuse any actor but the owner, before the checkout.
- **Publish checkout is not the dispatch ref.** `ref:` is the *named tag* on a dispatch, so a
  dispatch from a stray branch cannot publish that branch (`publish-dist.yml:64-66`).
- **Bookkeeping parsers.** `run_index.py` cells: no `|`, no newline, raw links refused,
  every relative link existence-checked, `report` cannot escape `docs/runs` (no `/`), `order`
  typed, unknown keys refused. `changelog.py` fragments: no heading, no blank line, must open
  `- `, relative links must be `../`, carriage returns refused, and `assemble` raises before
  writing when any fragment is wrong. `shard-tests.py`: identifier-only class keys, positive
  numbers, unknown keys refused, weights steer balance only, and the partition's coverage of live
  discovery is proved test-side. `bundle.py`: marker-owned deletions, symlinked-parent refusal,
  `--out` == source catalog refusal, dangling-vendor check.
- **`verdict_check.py` parsing.** Full-40-hex `reviewed_sha` required, case-sensitive marker, any
  other `VERDICT:` line voids the review, DISMISSED/CHANGES_REQUESTED never count, and
  `--resolve-pr` fails closed on zero *or* several open PRs at a head. The gate serialises per PR
  (`concurrency.group`) and `--post-status` refuses a non-SHA.
- **`fixture-target-app.yml`** curls only `127.0.0.1`; job holds no secret; `smoke` tears down
  with `always()`.
- **`install.yml`** runs the PR's installer in a fresh `$HOME` with no credentials — intended and
  correct.
- Not re-audited here (per anti-goals): gitleaks/verify internals (h409), dependency advisories,
  `install.sh` itself.

## Notes on method and confidence

Everything is static plus three scratch PoCs (W6-04, W6-14 run; W6-02 blocked only by an absent
`coverage` module and argued from code). No workflow was executed and no tracked file touched.
W6-01 and W6-05 are the pair worth acting on together: W6-01 says a PR supplies its own grader,
W6-05 says how much that costs — and W6-05 is the only finding that needs a settings read-back
rather than a patch.
