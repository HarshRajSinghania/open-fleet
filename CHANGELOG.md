# Changelog

All notable changes to open-fleet are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the version source of
truth is `.claude-plugin/plugin.json`.

## [Unreleased]

- **VF-Bench replays in one command, at a pinned revision, in a clean environment** (#601).
  `bench/vf-bench/replay.py run --rev <commit>` exports the commit into a fresh repository by a
  local fetch, runs every case N times under a built environment (only `git` and `python` on
  `PATH`, empty `HOME`, no system git config), one process per case with a timeout, and writes a
  JSON report and a text summary: the exact versions (corpus digest beside `gate.py`'s pin, the
  blob ids of `gate.py`, `verify.py` and `vfbench.py`, `VERSION`), skipped, unsupported, timed-out
  and unscored cases by name, and per configuration the false acceptance, false rejection, wrong
  reasons, coverage of the README's verifier-check inventory, wall time and run-to-run spread with
  every case whose verdict moved. The naive self-scorer is labelled the synthetic baseline, never
  a product score. `compare` fails on any difference outside host facts, raw refusal text and wall
  time; `reproduce` replays what a published report pins; `drill` requires a deleted or edited
  corpus case or pinned fixture to fail the replay. `replay-reference.json` publishes a three-run
  macOS replay of the #600 corpus at `27b5ed613949` (verify.py 0/53 and 0/19 in every run), and
  the new `vfbench_replay` job, which `gates` needs, reproduces it on the GitHub runner and uploads
  its report. External verifiers plug in through a documented stdin/stdout adapter contract
  (`verify.py` itself behind it is the reference adapter; malformed, timed-out and crashing
  adapters are listed, never scored); none has been measured, and reports say so with a null
  score. `heldout-protocol.json` predeclares the development and held-out splits, their digests,
  planned release dates, leakage checks and an unfilled holder role, and `heldout.py check`
  verifies no committed blob is a held-out case. Not done: a real external verifier, an actual
  holder and held-out set, and the CI reproduction's first run on a pull request.

- **VF-Bench samples the verifier invariants it used to name as unsampled** (#600). Twenty-eight
  isolated traps join the corpus — signed-dispatch tamper on a profile-signed record, class
  substitution and replay; hidden criteria in a table and in JSON; unaddressed and dropped
  criteria; a swapped manifest digest; a stale reviewed SHA; illegal and swapped lighting; an
  empty intent packet; an illegal reviewer mode; incomplete Art-12/50 provenance; a surviving
  pinned mutant and a zero-kill tally; a revert, a production change and a swapped mutant under
  the oracle-scope exception; three `pr.number` shapes; the author's own approval, a non-member's,
  and a dismissed one; a negative-control artifact symlinked out of the clone, an unpinned one,
  and a named run log that does not exist — each beside a named valid neighbour on the same
  fixture (eleven new controls) and each declaring the refusal it exists to earn.
  `tests/test_vfbench_guards.py` deletes each trap's one guard from a copy of `verify.py` and
  requires the trap to pass and its neighbour to stay green. The bench now scores false
  REJECTION beside false acceptance, a fixture control going RED is scored instead of raised, and
  the CI gate also fails on a trap refused for the wrong reason or a corpus case neither scored
  nor skipped by name. Result: false-done 0/53, false-reject 0/19 (corpus digest
  `277f594ca6e1…`; `VERSION` unchanged). The README carries a guard-by-guard inventory of every
  verifier check — trap, justified unsupported, or deferred with its unit-test pin — and states
  that the provenance, intent, reviewer-mode and lighting legs verify presence, not truth. No
  verifier hole was found: every new trap was refused for its declared reason as `verify.py`
  stood.
- **`decisions.py --pin-ref REF`.** `check`, `active` and `append` can take the human-grant
  key from a trusted git ref instead of the working tree, and refuse a tree whose pin differs:
  a change that swapped `.orca/human-grant-pubkey` for its own key otherwise verified grants it
  signed itself. floor_guard.py already read the pin at its base ref; this gives the CLI the same
  anchor. Without the flag, behaviour is unchanged.

## [0.8.0] - 2026-10-23

- **The project is renamed orca-fleet → open-fleet.** The repository is `ravidsrk/open-fleet`
  (old `ravidsrk/orca-fleet` URLs redirect), and the Claude Code plugin and its marketplace are
  `open-fleet`: an existing plugin install reinstalls as `open-fleet@open-fleet`. A2A card ids
  are `open-fleet:<mission>`. The `ORCA_FLEET_*` environment variables are now `OPEN_FLEET_*`
  (`OPEN_FLEET_ROOT`, `OPEN_FLEET_RUNTIME`, `OPEN_FLEET_STATE_DB`, `OPEN_FLEET_STATE_DIR`):
  every reader still accepts the old name when the new one is unset, and `preflight.py` refuses
  when `OPEN_FLEET_ROOT` and `ORCA_FLEET_ROOT` name different catalogs; snippets, docs, the
  bundle and the `posix` spawn environment emit only the new names. Example key paths moved
  from `~/.orca-fleet/` to `~/.open-fleet/` (no script defaults to either — keep passing the
  path your key lives at), and the bundle ownership marker is `.open-fleet-bundle.json`. Orca
  itself — the runtime, the `orca` CLI and its `ORCA_*` variables — is unchanged. Archival run
  reports, reviews, research, completion evidence and the decisions ledger keep the old name:
  they are hash-bound, dated evidence.
- **The 2026-10-23 end-to-end review's findings are closed** (#629; children #612–#628). The
  review found a bypass in each mechanism the thesis stands on; each now fails where it passed:
  - Verifier: a stillborn mutant is refused even when the runner prints `N failed` (pytest,
    Jest, Vitest); `--execute-nc` runs no source-repo git hooks and the seal re-checks the index
    it commits; profile-signed dispatch records verify through one canonicalization; the
    oracle bind reads the runner's own test discovery; `pr.number` must be an integer.
  - Deny-hook: one peeler for launch wrappers (`timeout`, `exec`, `setsid`, `env -i`, `nice -n`,
    grouping, `!`, `xargs`, …) feeds every tier; `$'…'` is decoded; the self-guard covers
    `chmod`, `sort -o`, `ed`, `rsync` and inline interpreter writes; the Never list and rule 5
    cover history-discarding git, destructive `gh` verbs and every remote-code shape found;
    matching fails closed when `grep` errors.
  - CI: `gates` runs `if: always()` and fails unless every need succeeded; release publishers
    refuse any actor but the owner and a tag off `main`; `v*` tags are restricted by a ruleset;
    no `${{ }}` reaches a `run:` body; PR commits carrying attribution trailers fail.
  - Floor guard and ledger: every diff is `--text` with pinned prefixes; waivers are read from
    the base ref and grant only as one-way human decisions; removed or re-keyed CONSTRAINTS rows,
    moved test files and imperative skips are caught; a pinned key requires a signature on every
    one-way line, signed over `ts` and class; routine post-merge teardown is not the deletion door.
  - Validator: one frontmatter reader (block scalars, full-length caps); one composition set for
    quarantine across validate, preflight and the CLI; misspelt clause tokens, hidden mission
    dirs and one-point paraphrases fail; each mission has its own activation-load budget under
    the 34,000 cap; `bundle.py --out` never deletes what it did not write.
  - Suite and scripts: tmux workers carry the spawner's `PATH`, and the lifecycle test fails
    closed on any real agent; the suite runs green on macOS; watchdog fails loud on missing
    timestamps and skips pending CI; diff_scope counts both sides of a rename; chain_check
    folds case and spelling.
  - Doctrine: migrate-it parks each phase for a recorded deploy grant; offload-it lands its
    recipe through a PR; every FREEZE is a one-way `decide-and-freeze` gate; the contradictions
    the review listed are reconciled, and `tests/test_doctrine_consistency.py` checks them.
  - The 16 MB showreel moved to the v0.7.1 Release assets; `pinned-demo` is a required check.

- **External CI monitor runs without a logged-in CLI** (#528). `scripts/external-ci-monitor.py`
  gains `--transport rest`, which reads the public Actions API with no `gh` login (a
  `GITHUB_TOKEN` is sent when set), so a scheduled cloud session can run it. The default `gh`
  path and the Codex heartbeat are unchanged. `--quiet-when-current` keeps a green run on
  `main`'s current head healthy past 24 hours: a quiet week no longer pages, and a head that CI
  never finished still goes `stale`. [docs/ops.md](docs/ops.md#incident-2-am) names the hosted
  daily check that runs it.

- **Pack pins re-witnessed** (2026-10-14). gstack `v1.84.1.0` → `v1.91.101.0` (`47d639ab`),
  addyosmani/agent-skills `0.6.9` → `0.6.13` (`aeac41d4`), mattpocock/skills `v1.2.3+9` →
  `v1.3.1` (`24fe0ef7`), each read from a full-history clone and landed with its rug-pull review
  under `docs/research/pin-reviews/`. All three are `changes-noted`; none widens a permission
  past what the fleet already gates. Doctrine follows the upstream moves: matt dropped
  `resolving-merge-conflicts` and renamed `CONTEXT.md` to `GLOSSARY.md`; a pack's "stop your
  turn for approval" is a worker `ask` (`gate-classification`); a gstack `/ship` worker turns off
  its early Greptile draft PR (`release`); `/cso` v3 needs its compiled launcher (harden-it);
  `triage-findings` keeps the confidence gate and exclusions cso v3 dropped; review-it's addy
  worker reports a mutation suspicion instead of running it. `pin_review.py` now puts hook
  executables named by a `hook` token, setup/install scripts, and SKILL.md frontmatter
  `hooks:`/`allowed-tools:` changes on the permission surface, and `.md.tmpl` sources in
  instruction. Before this, those landed in `code` or `instruction` only.

- **Trusted merge gate.** `verdict-gate.yml` runs on `workflow_run`, so GitHub loads it from
  `main`; it runs `main`'s `scripts/verdict_check.py --post-status` and posts the GO verdict as
  the `verdict-gate` commit status on the PR's current head. A `pull_request_review` run loads
  its workflow from the PR, so the old `verdict` job could be rewritten by the PR it gated (PR
  #571 review). Statuses are latest-wins, so a later GO clears a failure without a re-run.
  Runs for one PR share a lock and post in order. The status can be posted by a dedicated
  GitHub App whose key lives in a `verdict-gate` environment limited to `main`, so neither a
  fork's job named `verdict-gate` nor a branch workflow can stand in for it; the setup and
  branch-protection switch are in [docs/ops.md](docs/ops.md#merge-gate).

- **review-it reads `external-run`** (2026-10-14). The 2026-10-13 Linux witness (#527) —
  a NO-GO verdict on stablyai/orca PR #28206 at `6dcd957a`, four read-only workers, every
  artifact retained in its run directory — was filed at `doctrine-only` as substrate evidence;
  it binds unchanged at `external-run`, so the `RUN:` header's tier was amended and the tier
  claimed. Run report: `docs/runs/2026-10-13-review-it-linux.md`, envelope:
  `docs/reports/review-it-external-run/`. run by Ravindra Kumar (@ravidsrk).

Five pull requests merged after the `v0.7.1` tag (first-parent `v0.7.1..878e2245`).

- **Component quarantine switch** (#565, #558). `runtime/quarantine.json` is a human-only
  deny-list of `mission:`, `playbook:` or `pack:` components. `scripts/validate.py` fails the
  catalog if a mission routes through a quarantined component, `preflight.py --mission` refuses
  to start a run on one, and `runtime/scripts/quarantine_check.py` checks ad hoc. A malformed
  file fails every gate closed; an entry whose `by` names no human is refused. Ships empty.
- **Agent Baseline adopted as a yardstick** (#564). A frozen-catalog assessment
  (`docs/research/2026-10-14-agent-baseline-assessment.md`) and a new runtime policy,
  `runtime/threat-model.md`: trust assumptions, four security boundaries each graded with its
  residue, and a graded response ladder whose quarantine rung is the switch above. `attest-it`
  rides it.
- **Lean plugin install witnessed at the tag** (#554, public-beta draft gate 3). Install and
  uninstall transcripts retained; the installed copy fingerprint-matches a bundle rebuilt from
  the tagged commit.
- **Release rehearsal skips already-tagged versions** (#556, closes the #555 window).
- **0.7.1 provenance recorded** (#553) in `docs/releases.json`.

<!-- coordinator: entries for the 2026-10-14 doc-review fixes go below this line -->

Fixes from the 2026-10-14 whole-repo review:

- **Verifier (`verify.py`).** The executed negative control seals the mutant as a throwaway
  commit and runs clean → control → clean, each in its own repository whose refs that named
  the head name that phase's commit — an annotated tag stays an annotated tag of it, and
  its signature is dropped in the clean phases too, including a signature appended after
  the message, and a tag of a tag stays a chain — so `git verify-tag` cannot pass on only
  one of them — under a fresh HOME and TMPDIR, so a test can no longer tell which phase it
  is in (git status, marker files, branch refs, tag type). The alternates path uses the
  filesystem encoding, so
  a non-ASCII checkout still runs. Git runs with
  `GIT_NO_REPLACE_OBJECTS=1` and no graft file. An approval counts only from a non-author
  OWNER/MEMBER/COLLABORATOR. The transcript hashes the manifest bytes actually judged. A
  missing `origin/<base>` is fatal on sound lanes. `--no-gh`, `--lane` and `--execute-nc` are
  bound by the signed dispatch record. Malformed `criteria`/`criterion_ids` get named fatals.
- **`verify-gate.sh`** reads the dispatch pubkey from the target repo (where `verify.py` reads
  it), and resolves git and python3 once to absolute paths.
- **`deny-hook.sh`** reads abbreviated long options the way git does (`--del` is `--delete`)
  and hard-denies `git push --mirror` and `--prune`.
- **Runtime scripts.** `floor_guard.py` parses diffs by hunk count (new `diffparse.py`);
  read-side tools and `diff_scope.py` run one absolute git under a hardened env (new
  `gitexec.py`); `upstream_probe.py` keeps `GITHUB_TOKEN` on the API origin; `spawn_worker.sh`
  checks dependencies for `ready` tasks; `hitl-loop` refuses answers with line breaks;
  `print-settings-snippet.sh` emits JSON with an encoder; `egress.py` validates `--ts`;
  `watchdog.py` uses the nudge time it parses; `ed25519.py` rejects x = 0 with the sign bit
  set; one shared `orca_cli.run_json` replaces eight copies of the envelope reader.
- **Install.** `install.sh` refuses a shallow clone with the `git fetch --unshallow` remedy
  (and `run_report.py`/`validate.py` name it), works through symlinked paths (`pwd -P`), and
  refuses to repoint another clone's links without `--force`.
- **CI.** `verdict-check` runs the checker from the base commit, so a PR cannot rewrite it;
  an author self-GO still binds the SHA and is documented as not review. Every job has a
  `timeout-minutes`; `bind-check` passes `base_ref` through env; ruff adds F401, F841, B023,
  B905 and PLE.
- **Identity gate.** Point similarity is containment, so padding cannot dilute it; negation
  is a divergence, not a stopword; points are capped at 20 content words; a tokenizer failure
  is loud. The engine moved to `scripts/_identity.py`.
- **Tests.** The layer probes run on a temp copy instead of planting files in the repo;
  shard weights re-measured.

## [0.7.1] - 2026-10-13

- **The plugin install is now the lean generated tree.** `scripts/bundle.py` emits the
  plugin manifest, hooks, and gate runtime at the bundle root, so the published `dist`
  tree is itself the installable plugin; the marketplace now sources the plugin from
  the `dist` branch instead of the whole repository. A plugin install copies about
  24 MB (build-time `du`) instead of the 66 MiB whole tree measured at v0.7.0. The
  receipt archives stay in the source tree, untouched — this is the "separately
  generated distribution" the #518 packaging decision named. Copy installers see no
  change. (Public-beta draft gate 3.)

- **ship-it earns the catalog's first `external-run`** (#515). A maintainer-frozen
  spec became [ravidsrk/mdtoc](https://github.com/ravidsrk/mdtoc) BUILT @ `046d1f8d`
  on the Linux witness VM: six slices, three review-forced fix rounds, an integrated
  FAIL closed by a seam-fix slice, re-review PASS. Run report:
  `docs/runs/2026-10-13-ship-it-mdtoc.md` (binds via `run_report.py`), envelope:
  `docs/reports/ship-it-external-run/`. run by Ravindra Kumar (@ravidsrk).

- **pstack 0.15.20 read, not vendored.** Two habits folded in as playbooks:
  `explain-the-number` (a budget number is `unmeasured` until the limiter, the limit
  arithmetic, the error count, and proof the timed work happened are in the run) and
  `encode-lesson` (a correction seen twice becomes architecture, types, a lint, or a
  test, proved RED on a past specimen). No new mission. The router, the swarm, and
  "land even if CI flakes" stayed out. Witness:
  `docs/research/2026-10-12-pstack-adoption-audit.md`.

Four pull requests merged after the `v0.7.0` tag (first-parent `v0.7.0..a3fba89`). None
changes a mission, a playbook or the verifier; each is listed with what it does not prove.

- **0.7.0 provenance recorded** (#538). `docs/releases.json` moves 0.7.0 out of `preparing`
  into `releases`, bound to tag `v0.7.0` and cut commit `8a5211b`.
- **Plugin install witnessed** (#539, H-08). A clean-container plugin install and its uninstall
  control are retained at `docs/completion/evidence/CF-02b-plugin-install.txt` and
  `CF-02b-plugin-uninstall.txt`: 22 missions registered, zero after uninstall.
  `docs/completion/PLUGIN-INSTALL-WITNESS.md`, `docs/install.md` and `docs/distribution.md`
  state the limits. It witnesses install and uninstall, not an authenticated model turn or an
  Orca run.
- **External CI health reader** (#540, #528). `scripts/external-ci-monitor.py` reads `main`'s
  latest `validate` conclusion from outside Actions, with contract tests and a retained outage
  drill (`docs/completion/evidence/T-13-external-monitor-drill.txt`). The poller is in the tree;
  the scheduled watch that runs it is configured but paused (H-09, pending activation).
- **Critical-path peer ownership prepared** (#541, #530). `.github/CODEOWNERS` adds
  `agentsalpha` on `runtime/`, `scripts/`, `.github/` and `docs/ops.md`; the merge was
  authorized as a one-way decision in `docs/DECISIONS.md`. The write invitation is not yet
  accepted and no peer `APPROVED` review exists (H-10), so the bus factor is still one.

## [0.7.0] - 2026-09-28

The 2026-09-16 self-test campaign ran all 21 missions against orca-fleet itself
(scoreboard: `docs/reports/selftest-campaign-2026-09-16/rollup.md`; per-mission transcripts
under `docs/runs/campaign-2026-09-16-<mission>/`). No tier advanced on the campaign's own
runs: the rollup's Amendments record that its map-it cell was wrong (#451 is ship-it's
fixture merge, not a promotion) and that `clean-sweep` and `prove-it` hold `self-run` on
their own promotion reports. Five runs produced fixes (ruff 0.16.7 bump, F1 flake fix,
H1 hot-path fix, PF-3 coverage net, documentation page); the ruff bump, F1 fix, and docs
page among them have since merged to `main`.

The deep-review branches. The 2026-09-10 review (archived at `docs/reviews/2026-09-10-review.md`)
and the upstream deep audit under `docs/research/` opened issues #255–#276; the 2026-09-11 review
(`REVIEW.md`) opened #279–#307.

**Both review backlogs are now closed, and the release audit after them has landed.** The
2026-09-11 backlog (#279–#306) and a second independent review's #309–#318 merged together in
#308 — 38 issues, one commit each. #307 stayed open until its nine release tags were published;
they now exist and the gate that demanded them passes. The release audit of 2026-09-12 landed as
#321–#338 against `deny-hook.sh`, `verify.py`, `egress.py`, `bundle.py`, `spawn_worker.sh` and the
mission contracts, with its evidence under `docs/reports/release-20260912/`.

What the #308 round changed about the verifier is worth naming, because each was a way a unit
could be graded against a proof it chose: `check_redaction` now scans `commands[].artifact`, the
captured stdout where a leaked credential actually lands (#309); an unsigned `report-only` or
`planning` class is measured against what `base_sha..head_sha` really changes, so one
worker-controlled env var can no longer shed the negative control, intent packet, lighting and
reviewer_mode (#310); the signed dispatch record covers the control's own inputs — `nc_paths`,
`nc_command`, `nc_artifact_sha256` — so signing the class and contract no longer leaves the worker
picking its own oracle (#311); a standing `CHANGES_REQUESTED` at the reviewed head is no longer
overridden by a second approval (#317); and a floor-guard waiver is a DECISIONS record the ledger
can retire, not a line that happens to contain a rule id and a path (#313).

Landed on 2026-09-10 and previously unlisted here, which the entry below promised and did not do:
missions `migrate-it`, `oncall-it`, `absorb-it`, `document-it`; scripts `bundle.py`, `deny-hook.sh`,
`egress.py`, `floor_guard.py`, `guard_text.py`, `decisions.py`, `evidence-run.py`, `inventory.py`.
A changelog that says "each is listed below as it lands" and then lists none is worse than one that
promises nothing (#293).

**The 2026-09-14 holistic review** (`docs/reviews/2026-09-14-holistic-review.md`, filed as
#349–#386) landed on the `review/2026-09-14-holistic-fixes` line. Its P0 was the macOS-red suite:
`run_report.py` resolved the interpreter root but compared the token lexically, so a symlinked-prefix
interpreter inside a graded tree passed as the system one (#349). Two blast-radius holes closed:
`bundle.py --out .` no longer removes the source catalog (#350), and `deny-hook.sh` bounds `sudo
tee` through sudo's own options, stacked `sudo`, `nice` and `--` (#351). The verifier requires the
commands ledger to show the coordinator-named proof command green on head's tree rather than any
exit-0 record, and an empty or unparseable `--nc-command` is RED, never a silent skip (#352, #382).
`evidence-run.py` locks the manifest itself, so parallel wrapped runs neither lose a record nor
leave a lockfile beside it (#382, #388). A mutating run's report carries `waves=<n>` and one
measured WIP-curve row per wave; `run_report.py` refuses a missing, partial or doubled row (#365,
#389). Every mission's behavioral eval has a fixture-backed case graded on the workspace the agent
leaves, through `workspace_state` checks that read files with no model in between; the
narration-only cases are labeled and their set frozen (#364). Mission guides and their diagrams
are held to parity by a test (#385). CI's action pins moved to checkout v7.0.1 and setup-python
v7.0.0 before the Node 20 actions left the runners (#367). The round's later PRs (#397–#404):
`evidence-run.py` joins a sidecar lock that already exists before taking the inode lock and
rejoins one that appears mid-append (#393); `run_report.py` reads WIP-curve rows only inside the
report's `## WIP-curve protocol row` section, never from a fenced example or a deviations table; a
workspace-state `glob` never reads dependency directories and fails closed over an empty match
set; and the image wiring script checks every anchor on every run. The whole line was promoted
to `main` in #387.

### Changed

- README no longer claims "verified, not asserted"; it states the claim the mechanism supports
  — scope frozen against a coordinator digest, commits real on the base, review looked up on
  GitHub and tree-bound, the negative control executed by `verify.py --execute-nc` for revert
  and hand controls — and names the clean-env re-run and the ≥10% sample as coordinator
  doctrine (#258).
- Four false or unsupported claims corrected (#258): `attention-budget.md` is the exemplar of
  the Evidence-level rule, not "the measured exemplar" (its own level is ASSERTED); the symlink
  install is the verified path (`CF-02-r2` evidence) and the plugin path preserves references by
  construction only; the unlocated Osmani quotation is gone, replaced by the source's own
  L3/L4/L5 definitions; the gstack / addyosmani characterization names what those packs now
  ship (a content-hash evidence ledger, cross-model review, a fail-open Stop gate, a floor-guard
  reference — inside the producing run, no executed negative control).
- Autonomy re-derived from the source (#264): every mission is `autonomy: L4` (a coordinator
  plus parallel isolated workers); the human-owned verdict or plan in review-it, map-it,
  root-cause, and attest-it is a gate class, not a lower level; scheduled unattended runs are
  the L5 shape. The derivation is `docs/concepts.md` § Autonomy; every guide's Autonomy line
  carries the per-mission reason.
- The mission-identity test gains a sixth point, the oracle (#265): two workflows that differ
  only in oracle are one mission with an `oracle=` source, and differ as missions only when the
  oracle changes the proof's shape or the parking classes. `ARCHITECTURE.md` re-argues
  access-it, field-test-it (the oracle-tiered "prove it on the target" mission: DEVICE /
  EMULATOR / BROWSER / DESKTOP / CLEAN-ENV), and pin-it under it; no mission is deleted.
- `runtime/pins.json` pins Orca and the three upstream packs by commit and witness date, and
  `tests/test_pins.py` requires an entry for every pack a `compatibility:` field names (#271).
- `docs/releases.json` — every CHANGELOG version bound to its cut commit, with
  `test_every_changelog_release_has_a_cut_commit` holding the two together, plus the release-cut
  checklist in `docs/ops.md`. Annotated tags `v0.1.0` … `v0.6.1` were reconstructed at those
  commits; a tag is a repository ref rather than branch content, so the committed file is what a
  fresh clone can check and the one-line publish command lives in `docs/ops.md` (#274).
- `TODOS.md` is a pointer to `docs/completion/GAPS.md`, the run-archive field-proof plan, and
  the review issues (#275). `docs/research/REJECTED.md` ledgers every rejected mission candidate
  with source, shape, reason, and date.
- `docs/getting-started.md` states that the completion-gate hook is wired only under the plugin
  install and links the symlink-path snippet; `docs/distribution.md` drops the "verified, not
  asserted" framing.
- The GitHub **About** blurb has a canonical, checked-in source: `docs/about.md`. The box is a
  repository setting, so no workflow can write it and nothing in CI can read the live value —
  which is why it is the one description surface that had gone stale twice on a hardcoded
  catalog count while `plugin.json`, `marketplace.json` and the README badge had all stopped
  stating a number. The canonical text drops the count too, `check_doc_counts` now lints
  `docs/about.md` so it cannot creep back, and a contract test binds the text to the
  marketplace description, the 350-character limit GitHub truncates at, and the lint wiring
  itself. Applying it stays a maintainer action.

### Added

- Release-readiness review of 2026-09-28 at `ad1a0ed`
  (`docs/reviews/2026-09-28-release-readiness-review.md`): every frozen gate re-run locally and
  against CI, upstream Orca read at the v1.4.215 pin and at HEAD, the 1.0 checklist walked
  against live state, findings ranked P0–P2, and the tiered path to 0.7.0, a public beta, and 1.0.
- The review's findings, filed as #510–#525 and landed together (#509):
  - `runtime/scripts/orca_cli.py`, the one place the fleet resolves the Orca CLI's name
    (`ORCA_CLI_COMMAND`, then `orca-dev` when `ORCA_DEV_REPO_ROOT` is set, then `orca-ide` on
    Linux, else `orca`), with `--path` for the resolved executable; every operator tool and
    `spawn_worker.sh` call through it, and a test greps the scripts for a literal `orca` (#510).
  - `release.yml`: a GitHub Release from the tag's own CHANGELOG section on every `v*` tag
    (idempotent, so the nine historical tags can be backfilled from the `docs/ops.md` block) (#511).
  - `validate.py` lints pin-version claims: any line in the README, install, getting-started or
    distribution docs that pins or floors an Orca version must name the version in
    `runtime/pins.json`; the README's proof-status sentence is generated by `gen-badges.py` from
    `metadata.proof` and checked by `--check` (#512).
  - A `floor` lane in `validate.yml` runs the sharded suite on Python 3.11 and 3.12 beside the
    3.13 lane, so the installer's floor is a proven one (#514).
  - The README catalog carries a **Proof** column, bound to each `SKILL.md` by
    `tests/test_docs_navigation.py` (#515).
  - `runtime/scripts/upstream_probe.py` and `upstream-drift.yml`: a weekly probe of upstream's
    tags that files or refreshes an `upstream-drift` issue when a new minor lands or the pin falls
    ten patches behind; the README states the support window it implies (#516).
  - "Before you run a mission" in the README: what a fleet does to the machine it runs on, in one
    place above the catalog instead of in a FAQ (#517).
  - `publish-dist.yml`: the bundled `dist/` tree (`bundle.py`) pushed to the `dist` branch as one
    orphan commit per `v*` tag, with provenance; `docs/install.md` names the branch (#518).
  - `scripts/release_check.py`: the 1.0 checklist as a runnable check with one verdict per row,
    and the checklist rewritten so every row is a check the script performs (#519).
  - `main-health.yml`: a daily dead man's switch that reads the latest completed `validate`
    run on `main` and files or refreshes a `ci-failure` issue when it is red or stale, so a
    runner outage or a failed alert step is no longer silent; `docs/ops.md` names the no-runner
    incident shape (#520).
  - `THIRD_PARTY_NOTICES.md`, `CODE_OF_CONDUCT.md`, `.github/CODEOWNERS`, a pull-request
    template and issue templates, and a README affiliation line (#521).
  - "What a run costs" in `docs/getting-started.md`: hours, sessions and money for a first
    mission, with the measured activation load stated as a share of a 200k context in every
    mission guide's callout and a section in `docs/concepts.md` (#523, #525).
- Upstream CLI adoption: eight fail-closed operator tools (`task_ops.py`,
  `check_reply.py`, `hitl_ask.py`, `worker_ops.py`, `terminal_ops.py`,
  `worktree_ops.py`, `send_msg.py`, `search_sessions.py`) plus `spawn_worker.sh`
  extensions (inline `--spec` creation, `--retry-of`/`--retry-request` linkage
  with `request-show` triage, `--timeout-ms`, explicit `--run`/`--from` binding,
  routing passthrough) — every behavior change with failing-first hermetic tests.
- `offload-it` mission (22nd): stand up a per-workspace environment recipe end to
  end, proven by a clear recipe doctor plus an enacted provision loop; with the
  `computer-drive`, `clean-env-drive`, and `publish-evidence` playbooks and the
  review-it/access-it/field-test-it/document-it/attest-it touchpoints that ride them.
- Runtime doctrine re-witnessed against the pin and HEAD: three false claims
  corrected (`terminal stop` is hidden/deprecated, not removed; no `unanswered`
  gate state; schema v42), stale anchors refreshed, and seventeen upstream guard
  notes folded into the policies.
- External-run intake (#415): `docs/run-submission-guide.md` (the envelope +
  bindable-core bundle format, binding in one paragraph + one verify command,
  runner-credit convention), `docs/call-for-runs.md` (every doctrine-only
  mission by name, machine-checked against the catalog so promotions keep it
  current), and the `bind-check` CI job (`scripts/bind_check.py`) routing every
  run report a PR adds or modifies to `run_report.py`.
- Runtime policy layer modernized to the current Orca orchestration model (#251): worker-start
  supervised spawn path with typed refusals, Run-scoped fleets, batched Delivery + ack inbox,
  worker-release/retain lifecycle, --retry-request idempotency, ask --resume same-id, spawn_worker.sh
  v4 (ro never takes worker-start — it would launch Orca's YOLO default), and the
  `reviewed_wtree` content-fingerprint equivalence class (a content-identical rebase no longer
  voids a review), verified end-to-end in verify.py + merge-serialization.
- Audit quick wins (#250): diagnose.md "Redact first", round-by-round grilling in
  decide-and-freeze, api-contract + simplification review lenses, security lens rate-limit +
  destructive-path target validation, speed-it keep-or-revert + attempt ledger, map-it
  Prototype/Task ticket types, compound-learn environment-improvement categories, release.md
  doc-sync unit, sandbox-policy Never-row target validation.

- `pin-it` mission: re-witness and re-pin runtime-mechanics doctrine against the installed Orca
  binary — per-claim receipts, archived refutations for removed claims, substrate-block
  classification; terminals `PINNED` / `PINNED-WITH-PARKED` (from the 2026-09-09 upstream
  adoption audit).
- `floor-it` mission: install a written, numbered, tool-enforced quality bar — frozen
  CONSTRAINTS table, one tool per dimension, prove-fires negative control per gate, GUARD
  diff-watch against bar-lowering; terminals `FLOORED` / `FLOORED-WITH-PARKED`.
- `reshape-it` mission: churn-weighted shallowness inventory → human-confirmed surface →
  mutation-audited characterization net pinned BEFORE any restructure → one module-deepening
  per unit with build-blind review; terminals `RESHAPED` / `RESHAPED-WITH-PARKED`.
- `field-test-it` mission: on-device verification via the Orca emulator skills or a paired
  physical device — baseline, reproduce, fix, re-verify at `head_sha` with a revert negative
  control; terminals `FIELD-PROVEN` / `FIELD-PROVEN-WITH-PARKED`.

**The images are now generated from a committed prompt source, and they answer developer
questions instead of restating the mermaid.** Every banner and diagram under `assets/` is
re-rendered with Nano Banana Pro from the prompts in `assets/diagrams/generator/`, so a stale
picture is a prompt edit and a rerun rather than a redraw. The 21 mission diagrams became
developer-contract cards: what you give it, what it interrupts you for, what you get back, and
where it stops, at 60 words or fewer so the captions survive the guide's embed width; the
pipeline stays in each guide's mermaid block. Nine visuals were added where a question had no
picture: the you-say table that opens the README, the negative-control head-to-head, the install
stack with its three paths and their gate status, the gates as they reach your terminal, the
artifacts a run leaves behind, the mission handoff graph, the proof ladder, the verify-gate
trust boundary, and the mission-identity test. Every diagram ships a light variant behind a
`<picture>` element. ARCHITECTURE.md deliberately carries no image: it counts toward every
mission's activation load, and the validator said so.

**The 2026-09-14 tracker run's supervision lessons are now policy.** One field
run produced a hung reviewer, a wedged verdict worker, and two fenced
coordinator terminals; the recoveries are preserved as `runtime/worker-supervision.md`
(per-dispatch budgets, the stuck-but-alive ladder, transcribe-at-delivery,
fenced-coordinator re-bind). Beside it: `playbooks/mutation-hunt.md`, the
reviewer-side method the run's three review rounds converged on (killer mutants
in scratch clones, forced schedules, vacuity guards, forced residual demos),
and `playbooks/conductor-close.md`, the post-merge evidence closure generalized
from the run's own taskspec. All three compose from clean-sweep's deferred
reads, keeping them out of activation load; the one ARCHITECTURE bullet the
new policy required cost clean-sweep ~100 tokens of headroom (33,800→33,900).

**The supervision ladder's first responses are mechanized (#418).**
`runtime/scripts/watchdog.py` polls worker heartbeats, classifies
OK/SLOW/HUNG/WEDGED, auto-nudges HUNG once, and emits stop-redispatch
RECOMMENDATIONS with JSONL evidence on still-HUNG or WEDGED — the stop and
re-dispatch stay coordinator decisions. Thresholds and rate limits live in
`runtime/watchdog.json` (tunable without code edits); `--dry-run`
classifies with zero side effects. A recorded 2026-09-14 heartbeat trace
ships as the replay fixture.

### Fixed

- Runtime scripts no longer spell the Orca CLI as `orca`: on Linux that name is the GNOME screen
  reader (`orca-ide` is the CLI, per upstream's own resolution stub), so every dispatch from a
  Linux host either hung on the wrong program or failed at `command -v` (#510).
- Five stale hand-typed claims re-stated against live state: the Orca floor (v1.4.215) in the
  README, install, getting-started and distribution pages; the proof-tier sentence; the opening
  of `docs/call-for-runs.md` (every listed mission stands at `doctrine-only`); the 1.0 checklist's
  Gate 1, which grepped for a check that no longer exists (#512).
- The v1.4.215 pin record now carries what the re-pin missed: the schema line moved v41 → v42
  (`orca-dag-semantics.md`), and two post-pin upstream commits — the `dispatch:` → `run:` mail
  redirect with its `recipient_run_bound_redirect` warning, and the `dsh` agent — are logged in
  `orca-pin.md` for the 2026-12-28 re-pin (#508) to witness (#513).
- The Python floor is what the suite proves, not an installer policy: `install.sh` asks for
  ≥ 3.11 (the code needs 3.10; two 3.10-only failures are test-side) instead of 3.13, and the
  docs say so in one sentence (#514).
- The negative-control demo's transcript check no longer depends on stdout/stderr interleaving
  or on the uid: `run.sh` runs the verifier unbuffered, the workflow strips the host-dependent
  custody NOTE lines before diffing, and the recorded transcript and its inventory hash were
  regenerated (#522).
- The tests badge counts what it says — "test functions", which is what `unittest` discovers —
  instead of "test definitions" (#524).

## [0.6.1] - 2026-09-09

plugin.json, marketplace.json, and this heading now agree on 0.6.1 (issue #237).
The alert-on-failure workflow, the completion-run items, and the ops rollback
step.

### Added

- `alert-on-failure` workflow (#213): a failed `validate` run on `main` opens or
  updates an issue labeled `ci-failure`; a `workflow_dispatch` drill files and
  closes a `[drill]` issue so the alert path can be proven without redding
  `main`. `validate` publishes the proof rollup and routing score to its run
  summary; `docs/ops.md` incident step 1 names the issue as the alert. The
  drill on `main` filed and closed #229 on 2026-09-02.
- `docs/runs/TEMPLATE.md` and a per-mission field-proof plan in the run-archive
  index (#212): targets, tiers, terminals, and blockers for the nine
  doctrine-only missions; a tier still advances only through a mission run.

### Changed

- `docs/ops.md` incident step 4 documents the rollback this catalog has
  (`git revert -m 1` of the merge via a PR; no deploy target), rehearsed
  against a real merge commit on a scratch clone; `playbooks/release.md`
  says `-m 1` too. Completion gap G-14 closes on that evidence and
  its ACCEPT expiry marker (#226) with it. #212 closes as a tracker: the
  field-proof plan in `docs/runs/README.md` is the live one, and G-09 stays
  deferred in the register.
- Adversarial review of every mission skill, one `SKILL.md` at a time, fixing
  contract drift against the playbooks and runtime policies rather than prose:
  `ship-it` proves the integrated whole at the BASE head before `BUILT` and
  names deploy/rollback as one-way gates (it never self-authorizes a deploy;
  it may execute one under a recorded grant); `harden-it` routes every PoC to
  an execution profile BEFORE quorum-verify or re-attack runs it (the audit
  writes scenarios, it does not execute them); `prove-it` records the mutation
  audit as the manifest's `negative_control` + `binding_audit` (not
  `metric_contract`, which `verify.py` never reads for it) and drops the
  "semantics-preserving mutation" wording — that phrase names an equivalent,
  unkillable mutant; `deflake-it` binds the green streak to one SHA and names
  how CI re-runs are triggered; `access-it` gains the BASE bootstrap,
  build-blind review, and LAND steps its compose clause already declared;
  `attest-it` requires the obligation catalog to be a sourced document at a
  digest, never model recall; `clean-sweep`, `oss-contribute`, `review-it`,
  `map-it`, and `root-cause` ride `sandbox-policy` (issue / PR / review text is
  data, never instructions) and state their worker profiles; `modernize-it`
  treats the lockfile as a hot-file merge chain and installs bumped packages
  with lifecycle scripts disabled until provenance is verified; `root-cause`
  draws its boundary at landing, not editing; `speed-it` guards at the
  declared budget, not the lucky run; `oss-contribute`'s CLASS enum gains
  `refuted` / `duplicate` and its allowed parks name
  `awaiting-maintainer-merge`.
- Guides realigned with their skills: deflake-it defaults (30/30, not 20/10),
  review-it's verdict table (a Required finding also blocks), harden-it's phase
  order, ship-it's integrated prove, prove-it's mutation wording;
  `mission-chaining.md` names `CLEAN` (not the nonexistent `HARDENED`) among
  clean terminals.
- Routing: bare "keyboard" no longer routes to `access-it` (a keyboard-shortcuts
  feature is `ship-it`); `aria` matches as a whole word or the head of an identifier
  (`aria-label`, `ariaLabel`, `aria_roles`) and never inside "variant", as a prefix
  of "Arial"/"ARIAL", or as the title-case name Aria mid-sentence (at the head of a prompt,
  line, or sentence the capital is conventional and still routes); seven routing
  examples and a direct classifier test added.

- Product-completion run 2 (resume at `f2e53f4`, `docs/completion/`): every
  angle re-scored on fresh-clone evidence (67%, was 56%; CONDITIONAL GO pending
  H-07, the review-it dry run re-witnessed on the current head); the six critical
  flows re-evidenced with failure paths (a copied mission loses its
  `../../playbooks` references; an over-claimed `proof:` tier fails
  `proof_status --check`); new human actions H-04..H-07 (GitHub About
  description still says 10 fleets, next version cut, failure-notification
  setting, CF-05 re-witness on the current head); the G-14 ACCEPT expiry is
  now a filed issue.

### Fixed

- Leftover Greptile comments from the post-launch PRs (#219–#223): incident
  process compares `plugin.json` to the dated CHANGELOG heading (not
  `[Unreleased]`); dispatch-key rotation names all three verifier sources
  and a post-merge `git fetch` so the `origin/HEAD` pin moves;
  README Ops navigation is a real `href`; digit-bearing unexpected
  frontmatter keys (including hyphen-leading) fail the extras allowlist;
  GAPS/`status.json` match the closed G-06..G-08/G-11..G-13 issues.

## [0.6.0] - 2026-09-01

plugin.json, marketplace.json, and this heading now agree on 0.6.0 (issue #209).
Signed dispatch, the #163–#184 sweep leftovers, SECURITY.md, the Python 3.13
pin, product-completion close-out, and the post-launch G-08/G-11/G-12/G-13/G-07
agent slice.

### Added

- Signed dispatch records make a worker's substitution of `{manifest-id, contract-digest, unit-class,
  lighting}` **detectable off-worker** (issue #135, follow-up to #112). The coordinator signs the tuple
  off-worker (`runtime/scripts/dispatch-sign.py`, vendored Ed25519 in `runtime/scripts/ed25519.py`);
  `verify.py` verifies the signature against a supplied public key, binds it to the unit, and rejects a
  substituted or unsigned field. This is a soundness boundary **when the verifying key is trusted —
  i.e. off-worker** (CI/MCP/SDK, or an auditor with the coordinator's real key); the native in-session
  hook stays advisory (no in-session anchor is worker-untamperable, the #112 result). Opt-in; default
  behaviour unchanged. See [docs/verify-gate.md](docs/verify-gate.md#signed-dispatch--making-the-native-path-sound-135).
- `SECURITY.md` disclosure path; `.env.example` lists every `ORCA_*` gate input.
- [docs/ops.md](docs/ops.md): account inventory (GitHub, plugin marketplace,
  greptile, agentskills) and a 3-step incident process (issue #215).
- Index check of public marketplace aggregators (issue #210): GitHub self-host
  and buildwithclaude auto-index are live; official directory, skills.sh, and
  claudemarketplace.net still need [H-02](docs/completion/HUMAN_ACTIONS.md).

### Changed

- CI Python pin `3.x` → `3.13` (catalog gates).
- CI runs ruff 0.16.5 on `E9`/`F63`/`F7`/`F82` (syntax / undefined names)
  only (issue #214). Full rule set is still a policy change.
- Validator and the orphan-protocol test share `explicit_protocol_refs` (issue #216).
  A Related-section backtick no longer keeps a protocol alive; `ship-it` rides
  `mission-chaining` and `review-it` rides `mission-scheduling`.
- Validator allowlists only three extras beyond the agentskills.io spec
  (`proof`, `autonomy`, `proof_evidence`). A fourth top-level field fails
  the catalog (issue #211). skills-ref still reports those extras; that is
  expected, not a migrate-to-metadata prompt.

### Fixed

- Leftover review comments from the #163–#184 sweep PRs: pin discovery cannot
  cheat via local `HEAD`; env pubkey precedes the repo pin; nested schema keys
  are matched as keys not substrings; the trust-boundary assertion is bounded
  to that H2; `ORCA_EXECUTE_NC` is documented as fail-closed; vf-bench ancestry
  is hermetic; the review-leg GREEN half still skips on a shallow clone (the
  fail-closed fetch pin does not — `verify()` keeps aggregating); mutation e2e
  tests spy the review and NC lanes; temp fixtures are cleaned up.
- Validator: a non-UTF-8 or unreadable `SKILL.md` (and the same class of error
  in playbooks/runtime) is a one-item per-file failure instead of aborting the
  catalog (issue #71).

## [0.5.0] - 2026-08-26

Release hygiene: the previous Unreleased block was already on main (issue #42).
plugin.json, marketplace.json, and this heading now agree on 0.5.0.

### Fixed — live docs after E1–E6

- Mission guides' Composes sections now name every protocol their SKILL declares
  (ledger-contract, evidence-manifest, acceptance-review, and the rest that had drifted).
- Human-facing schema (README, concepts, getting-started, ARCHITECTURE) documents the
  intent packet, lighting, and `accountable:` on promotion.
- README proof status includes the 2026-07-17 clean-sweep tracker self-run.
- Research archive index marks snapshots as historical; E1–E6 landed in PR #68.

### Added — Addy August delta (E1–E6)

- Lighting: per-unit `lit` / `dark-eligible` (`gate-classification.md`, ledger row,
  evidence manifest). Default lit; dark-eligible only Lane A + unfakeable oracle.
- Intent packet on the evidence manifest (`goal` · `ruled_out` · `why`); verifier
  checks presence. Distinct from `claim`.
- Autonomy contract on TASK specs (`decompose-dag`, `remediate-finding`).
- `compound-learn` + `attention-budget` composed by the remaining mutating missions.
- Promotion PR names `accountable: <human>` (`release.md`).
- Next self-run must emit the WIP-curve row (`docs/runs/README.md`).

### Added — orchestration-tax adoption (Addy gap analysis)

- `runtime/attention-budget.md`: producer-side WIP caps (default ≤3 builders),
  sort isolated vs judgment-heavy work, scale fleet to verification capacity.
- `playbooks/compound-learn.md`: post-mission REFLECTION.md proposals; human must
  approve every AGENTS.md/GOTCHAS line (never auto-write).
- `liveness-resume.md`: reflection-before-retry + identical-error kill on doctor
  respawns.
- `build-change.md` + `gate-classification.md`: pre-build plan gate for
  irreversibility stop-list units.
- Wired into `ship-it`, `clean-sweep`, `harden-it`; docs in concepts, getting-
  started, ARCHITECTURE, README; research archive under `docs/research/`.

## [0.4.0] - 2026-07-16

Adds an eleventh mission, `oss-contribute`: landing contributions on a repo you
do NOT control. It is `clean-sweep` forked for upstream work, and it is a distinct
mission by the five-part test — the convergence proof is a PR open and internally
reviewed (not a merged SHA), the state machine adds upstream-PR overlap discovery
and an assist/alternative/stand-down decision while dropping the merge step and the
merge-serialization conductor, and `awaiting-maintainer-merge` / `externally-covered`
are normal terminals. Ships with the `upstream-contribution` playbook (fork topology,
overlap check, contribution decision, DCO/CONTRIBUTING etiquette) and enters at
`external-run` proof — a real run against `dodopayments/chimely` (5 PRs, 4 quoted
review-assist comments) is in `docs/runs/`. `validate.py` now holds `oss-contribute`
to the mutating-mission evidence-manifest standard.

`oss-contribute` also gained a post-open PR follow-up loop: a PR is not
fire-and-forget, so the unit stays live (watch, triage each review thread against
the current head, fix valid ones as fix rounds on the same branch, answer every
thread) until merged, closed, or quiet. Adds the `FOLLOWED_UP` ledger flag.

Made the catalog messaging count-agnostic so adding a mission no longer means
rewriting counts across the docs. The README badges now read dynamically (version
from `plugin.json`, mission and test counts from generated `assets/badges/*.json`
via `scripts/gen-badges.py`); the manifest descriptions dropped the count and the
mission enumeration; and `validate.py` gained three guards — a count-lint that
fails on any hardcoded catalog count in the doc surfaces, a keyword check that
every mission is in `plugin.json` keywords, and a badge-freshness check.

## [0.3.0] - 2026-07-13

Syncs the runtime policies with the current Orca `orchestration` and `orca-cli`
skills (an audit against both found drift, including one bug in 0.2.1), and adds
two capabilities the audit surfaced: the full agent roster and scheduled runs.

### Added — agent roster (flags from Orca source, autonomy-correct)

- `spawn_worker.sh` now covers the Orca roster, and the write tiers use each
  agent's fully-autonomous flag — the exact flag Orca appends by default
  (`src/shared/tui-agent-permissions.ts`, cloned and read directly):
  claude `--dangerously-skip-permissions`, codex
  `--dangerously-bypass-approvals-and-sandbox`, gemini `--yolo`, grok
  `--permission-mode bypassPermissions`. This fixes a latent blocking bug: the
  prior `rw` flags (acceptEdits / workspace-write / auto_edit, and a wrong grok
  `--always-approve` from a web source) are the SANDBOXED modes that still
  prompt on shell + network, so a build worker running tests or `npm install`
  would block and defeat the run — the exact failure this project exists to
  avoid. `ro` stays read-only (non-blocking because it cannot mutate); `danger`
  shares `rw`'s flag and adds the ephemeral-sandbox requirement. opencode/droid/
  omp/pi have no Orca autonomous launch flag → `WORKER_CMD`. The old
  claude|codex-only refusal is gone; `WORKER_CMD` generalizes the override to
  any agent; `sandbox-policy.md` carries the full matrix.
- Because `rw` launches a permission-bypass worker, it is fail-closed behind a
  new explicit opt-in `ORCA_COORD_ALLOW_AUTONOMOUS_WRITE=1` (mirroring the danger
  gate) so a bare/accidental spawn never starts a bypass worker silently. The
  safety envelope is the isolated worktree + build-blind review + PR gate +
  testnet/staging rails; `danger` additionally mandates an ephemeral sandbox.

### Added — scheduled runs

- `runtime/mission-scheduling.md`: Orca `automations` run a mission on a cadence
  (nightly clean-sweep, weekday review-it PR sweep). Each is a full unattended
  run — headless autonomy, one-way gates parked not faked, cross-run
  anti-inflation, stops at BASE/report. Wired to review-it and clean-sweep (the
  cleanly-schedulable missions).

### Fixed

- Subtree lineage (0.2.1 bug): a supervised unit's worktree is created with
  `--parent-worktree active`, not by merely omitting `--no-parent` — the latter
  relies on Orca inferring the parent, which only works "when it can"
  (`runtime/dispatch-lifecycle.md`).
- Inbox mechanics: `check --peek` inspects unread WITHOUT consuming (the correct
  tool when an off-type heartbeat is buried); the old note misdescribed `--all`
  and omitted `--peek`.

### Added

- Provenance rule: lifecycle authority is the payload `taskId`+`dispatchId`
  verified against the dispatched pane, never a handle comparison; a
  `worker_done`/`heartbeat` from a different pane is ignored, and
  `terminal_handle_stale` means re-resolve and never dual-send
  (`runtime/liveness-resume.md`).
- Orca-native progress surface: workers update the worktree comment +
  `--workspace-status` at checkpoints, complementing the file ledger.
- `--setup run` on the builder worktree for repos needing setup hooks;
  `task-list --brief` for coordinator DAG sweeps; the composite worktree-id
  form `<repoId>::<worktreePath>`; the Linux `orca`-is-the-screen-reader gotcha
  (use `orca-ide`); `worker_done` auto-completes the task (no manual
  `task-update`); expanded group roster (`@grok`, `@cursor`).

## [0.2.1] - 2026-07-13

Closes the gaps a coverage audit found between the catalog and the original
Orca coordinator prompt library (the two monolithic prompts this repo
decomposed from).

### Changed

- Worktree lineage is now a subtree per unit: a supervised worker's worktree is
  a CHILD of the coordinator (omit `--no-parent`), and its dependent workers
  (reviewer, fix rounds, integrator, bot reconcile) run as fresh terminals
  inside that worktree — so one `WT_CLEAN` tears the whole subtree down at merge
  (`runtime/dispatch-lifecycle.md`).
- The bot-reconcile policy is generalized from Cursor BugBot to ANY PR review
  bot (Greptile, CodeRabbit, …) with a full wait → ingest → reconcile
  discipline: bounded poll with a did-not-run fallback, comment triage folded
  into one change request, dynamic bot-login detection.

### Added

- First-merge spot-check: the run's first merge gets a dispatched verification
  of its shape before the train continues, since the pipeline inherits it
  (`runtime/merge-serialization.md`).
- No-gh fallback: the conductor degrades to local `git merge --no-ff` into BASE
  when `gh` is unavailable, and records that the promotion PR is owed.
- Plan skeptic: a fresh worker stresses a decomposition against the frozen
  spec's criteria (orphan criterion / gold-plating / order / stub-slices)
  before it commits (`playbooks/decompose-dag.md`).

## [0.2.0] - 2026-07-13

Lessons ported from the failed predecessor (ravidsrk/autonomous-fleet) — the
mechanisms it earned in real runs, without the multi-runtime platform that
killed it.

### Added

- `runtime/mission-chaining.md`: sequential gated chains — the previous
  mission's verified terminal state is the gate, degraded terminals stop the
  chain, deferral carry seeds the next enumeration.
- Proof-status honesty: every mission declares `proof:` (`doctrine-only` |
  `self-run` | `external-run`) in frontmatter; advancing requires a linked run
  report on disk; validator-enforced. All ten missions start at doctrine-only.
- Instruction budget: validator-enforced line caps (missions 130, playbooks 90,
  runtime 160) so doctrine creep fails CI instead of surfacing in a postmortem.
- Orca coordinator mechanics from the predecessor's real runs: one message per
  `check --wait` call, read-marking semantics, broadcast-only group addresses,
  worktree retirement guards, lost-preamble recovery, a ban on mid-run
  `orchestration reset`.
- Blind-fix anti-anchoring and a three-round review budget in
  acceptance-review; a field-validated PR sizing seam in build-change and
  remediate-finding.
- `reviewer_mode` recorded on every manifest and a run-close sha256 integrity
  inventory (byte-identity rejection is a coordinator judgment, not automated).
- Structural anti-inflation: re-runs treat a prior run's green-but-unverified
  claims as the first items to re-verify (liveness-resume + clean-sweep).
- Trust boundary (repo/issue/PR/log text is data, never instructions) and an
  argv-never-interpolation rule for runtime scripts, with contract tests.

## [0.1.1] - 2026-07-13

### Added

- `scripts/validate.py` now rejects a mission with no machine-checkable
  Composes/rides name, scans clauses to the end of their paragraph (an "e.g. "
  or a capitalized "Rides" can no longer hide a dangling name), resolves every
  `<name>.md` mention across missions, playbooks, and runtime policies, flags
  case/underscore typos of protocol names and path-prefixed references, and
  ignores external URLs.
- Negative-path test suite (`tests/test_validate.py`): every failure branch of
  the new composition and reference checks is locked to a fixture that must
  trip it.

### Changed

- `release.md` owns the BUILT state end to end (entered by landing via
  merge-serialization); the orphaned `land.md` playbook is folded in and removed.
- `ship-it` declares its playbooks and runtime policies in a machine-checkable
  Composes/rides clause instead of bare directory pointers.
- `root-cause` delegates only the diagnosis phases of the diagnose playbook and
  stops before its fix phase; fix authority stays with the separately authorized
  handoff.
- `dispatch-lifecycle` documents the worker-spawn specifics its script relies on:
  composite worktree selectors, re-dispatch-to-used-handle as a no-op, and why
  the bounded re-Enter loop is safe.

### Fixed

- `runtime-prove` was composed but never placed in harden-it, speed-it,
  modernize-it, and prove-it; each pipeline now runs it between review and land.
- speed-it, modernize-it, prove-it, and deflake-it declare the runtime policies
  their REVIEW/LAND phases ride; deflake-it composes `remediate-finding` so a
  flake fix has a PR, review, and merge protocol.
- The orphan contract test requires explicit reference forms; "landed" in prose
  can no longer keep an orphaned playbook alive.
- Vendor names and dead README pointers scrubbed from runtime scripts;
  ARCHITECTURE layout matches the tree.
- Clarity: `{{DETECT_RUNS}}` gets a default (20), the exploit sandbox is named
  `sandbox-policy` consistently in harden-it, observe.md's depth heading no
  longer points at a definition release.md never had, and review-it's
  test-adequacy axis is marked as static reasoning for read-only workers.

## [0.1.0] - 2026-07-13

### Added

- Initial catalog: 10 outcome-named missions, callable playbooks, runtime
  policies and scripts, the agentskills.io validator, and architecture contract
  tests.
