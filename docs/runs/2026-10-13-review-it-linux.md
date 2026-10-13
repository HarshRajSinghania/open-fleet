# Run report — review-it external-run (Linux witness, #527), 2026-10-13

RUN: mission=review-it tier=doctrine-only inventory_at=314d63feafff694ffc51df10c21e15da288fed83 manifest=docs/runs/2026-10-13-review-it-linux/manifest.json verifier=GREEN waves=1

| Field | Value |
|---|---|
| Mission | `review-it` — mission source revision `288ae5b5` (catalog main), installed location `~/orca-fleet/skills/review-it` in the witness VM |
| Tier claimed | `doctrine-only` (no promotion attempted — #527 is substrate evidence; run kind: `external-run`, target is not this catalog) |
| Target | stablyai/orca PR #28206 by @Hotragn (session-external author), originating issue stablyai/orca#28164 |
| Fixed point | reviewed head `6dcd957a65daf77fe49f15afbb998b262427224c` · merge-base `cbeb53714640288d172e9d59c53c0e0bff85f6ba` · frozen contract `contract.md@d9259acc10b30cd177f67d294a656d12802cedab` sha256:d70a985e…aae4 · spec source `spec-source.md` (originating issue, first hit) |
| Coordinator / workers | coordinator session driving `orca-ide` in the VM · 4 workers `PROFILE=ro` (Claude Code 2.1.296, plan mode) · TASK packs: matt (3 acceptance axes), addy (security lens) — one pack per worker |
| Orca | `orca-ide status --json` → `"state": "ready"`, `appVersion 1.4.224`, runtime reachable (retained: `status-linux.json`). Host: Ubuntu 24.04.5 LTS arm64 (OrbStack `orca-linux-witness`); resolved CLI name: `orca-ide` |
| Human gates | VM Claude auth — maintainer via OAuth consent 2026-10-13 (long-lived token minted by `claude setup-token` in the VM; token file mode 0600 in VM home, never in any repo). Verdict posting: NOT requested — retained only (one-way gate untouched) |

## Terminal state

**NO-GO** — 0 Critical, 2 Required (security lens; submodule Force Delete copy/ordering
hides superproject data loss). Aggregate: `verdict.md`.

| task_id | unit | BUILD_DONE | PR_OPEN | BOT | REVIEWED | MERGED | WT_CLEAN | lighting | park | evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| task_6d5f6019b040 | axis-standards | worker_done succeeded (ctx_77d9eff998c8) | n/a (report-only) | n/a | n/a | n/a | target clean | lit | — | `axis-standards.md` |
| task_ce92854900ce | axis-spec | worker_done succeeded (ctx_548b632d7b61) | n/a | n/a | n/a | n/a | target clean | lit | — | `axis-spec.md` |
| task_f1a76ab16913 | axis-test-adequacy | worker_done succeeded (ctx_7fe08135a93e) | n/a | n/a | n/a | n/a | target clean | lit | — | `axis-test-adequacy.md` |
| task_850a46a339a1 | lens-security | worker_done succeeded (ctx_ac7f4cbc0e7a) | n/a | n/a | n/a | n/a | target clean | lit | — | `lens-security.md` |

## Convergence proof

- RC-1 fixed point: pinned pre-dispatch from two routes (GitHub API + VM clone);
  re-checked at verdict — PR OPEN at `6dcd957a` unchanged.
- RC-2 axes isolated: four fresh worker terminals, one task each, blind-fix
  expectation is section 1 of every worker report; aggregation in `verdict.md`
  presents axes side by side, worst-per-axis, no rerank.
- RC-3 lens gating: `diff-scope.json` (FRONTEND/BACKEND/TESTS/AUTH, strict,
  exit 0); security ran (NEVER_GATE on a destructive-path surface); perf/a11y/
  data-migration/api-contract/privacy/simplification gate-offs recorded in
  `verdict.md` with reasons.
- RC-4 source-binding: coordinator re-read all 14 distinct quoted lines at the
  reviewed head — 14/14 verbatim (`quote-check.txt`), plus the empirical-git
  precedence proof for the Required pair (dirty superproject + initialized
  submodule → only the submodule refusal, exit 128).
- RC-5 verdict bound: NO-GO per the mission rule (any Required), `head_sha` =
  `pr.reviewed_sha` = `6dcd957a` in `manifest.json`.
- RC-6 boundary: target checkout `git status --porcelain` empty at close;
  workers read-only; nothing posted to stablyai/orca#28206.
- RC-7 substrate: host line + `status-linux.json` above; every phase below ran
  via `orca-ide` inside the VM (driver retained: `coordinator-driver.py`).

## Pipeline evidence (per phase)

| Phase | Command / action | Result | Evidence |
|---|---|---|---|
| PIN | `gh pr view 28206` + VM clone `git rev-parse pr-28206` | both `6dcd957a…`; diff 6 files +91/-1 both routes | `pr.json`, `spec-source.md` |
| PREFLIGHT | `preflight.py --mode readonly --offline --default main` (in VM, target repo) | exit 0 | `preflight.txt` |
| SCOPE | `diff_scope.py --base cbeb5371… --json --strict` | exit 0, AUTH+FRONTEND+BACKEND+TESTS | `diff-scope.json` |
| DISPATCH | `spawn_worker.sh` PROFILE=ro ×4 via Run `run_18440e737a97` | input_accepted (turn observation unsupported on this substrate; workers verified live by screen reads) | `task-list-final.json` |
| ACCEPTANCE + RISK | 3 axes + security lens, isolated workers | 4 reports written; 4× `worker_done succeeded` in one delivery | `axis-*.md`, `lens-security.md`, `worker-done-delivery.json` |
| AGGREGATE | coordinator quote re-read + empirical git precedence test | 14/14 quotes verbatim; precedence confirmed | `quote-check.txt`, `verdict.md` |
| VERIFY | `verify.py` via `evidence-run.py` (below) | `verify: OK`, exit 0, recorded in manifest ledger | `verifier.txt`, `manifest.json` |

## Verifier outcome (recorded exactly)

`python3 runtime/scripts/evidence-run.py --label verifier-rerecord2 --manifest docs/runs/2026-10-13-review-it-linux/manifest.json --artifact docs/runs/2026-10-13-review-it-linux/verifier-rerecord2.txt -- python3 runtime/scripts/verify.py --manifest docs/runs/2026-10-13-review-it-linux/manifest.json --contract-source docs/runs/2026-10-13-review-it-linux/contract.md@d9259acc10b30cd177f67d294a656d12802cedab --contract-digest sha256:d70a985efe136f3499ad1297f395f010cb6d8db2a95621b03c1dfea6c574aae4 --unit-class report-only --dispatch-record docs/runs/2026-10-13-review-it-linux/dispatch-record.json --dispatch-pubkey docs/runs/2026-10-13-review-it-linux/dispatch-pubkey.hex --repo stablyai/orca`

(Three records are retained: the first used an absolute VM path, which the
binder does not count as this repo's verifier; the repo-relative re-record's
`wtree` named an uncommitted working tree, which a fresh checkout cannot
resolve (PR review catch); the binding record is `verifier-rerecord2`,
recorded in the VM on a clean tree so its `wtree` is the committed tree
`3757a27b` in reachable history. A host-side attempt between them failed
closed — Homebrew git is worker-writable on a soundness lane — and was
discarded, never recorded.)

Output (verbatim, also in `verifier-rerecord2.txt`): `NOTE: --base not given — ancestry
check skipped (pre-merge/offline)` · `NOTE: dispatch record signature verified
against the supplied key (#135) — a soundness boundary only if that key is
trusted (off-worker: CI/MCP/SDK or an auditor)` · `verify: OK — all required
checks passed` · exit 0. The dispatch record was coordinator-signed before
dispatch (`dispatch-record.json`, seed custody: VM `~/.dispatch-sign/seed`
0600, outside any work tree; pubkey retained in this directory). Target-repo
objects for base/head were fetched from GitHub into the catalog worktree so
the immutable-commit legs resolve locally; the diff re-derives as 6 files
there too.

## WIP-curve protocol row (mutating self-runs)

Inapplicable: report-only external run. One dispatch wave (`waves=1`):
4 read-only reviewers in parallel, no builders, no rework loop (report-only
missions have no fix authority).

## Deviations and lessons (recorded, not hidden)

- First standards dispatch hit Claude's first-run onboarding screens (theme /
  security notes / folder-trust) and never started a turn. Recovery per
  doctrine: `worker-abandon` (ctx_d1c4f61fe418), host-level onboarding completed
  once in a plain terminal, task reset to `ready`, fresh dispatch. No preamble
  was ever resent.
- Plan-mode (`PROFILE=ro`) workers write their report into their plan and stop
  at a plan-approval prompt. The coordinator read each plan in-pane, verified
  its scope was exactly "write report + check + worker_done", and approved it
  in-pane (plus one outside-working-dir read allowance for the retained spec
  source). Target cleanliness was re-verified at close ( RC-6 ) because
  approval exits plan mode.
- `turn_started` observation is `unsupported` for these terminals at Orca
  1.4.224, so every spawn read UNPROVEN; workers were proven live by screen
  reads and by their `worker_done` delivery instead. Candidate pin-it note.
- Lens tallies could not be appended to the target repo's DECISIONS log
  (read-only external target); tally recorded in `verdict.md` instead.
- Worker release returned `retained` for all four dispatches (custom-argv
  lane); panes were closed by the coordinator at teardown.

## Run-close integrity inventory (sha256)

| Artifact | sha256 | producer |
|---|---|---|
| `docs/runs/2026-10-13-review-it-linux/manifest.json` | `0f0c32bfc820eeadcac1999132fb76ea360b74016bcef0ebe7adf1ab191b3ad3` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/contract.md` | `d70a985efe136f3499ad1297f395f010cb6d8db2a95621b03c1dfea6c574aae4` | coordinator (frozen @d9259acc) 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/spec-source.md` | `9d2ce4f29f540d0df72b6ab549bc11c7b1e4c36808d670dc61a9977e3835f4aa` | gh API capture 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/pr.json` | `e3af9b77cfbf1444c609f61b4fc0d5ef2afcda54d1f16ea9f48b7b0cd690aab7` | gh API capture 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/status-linux.json` | `4097d520df90edc6e9b9206ac07d11ae31eb26e0bea81551471db1f720e97cc4` | orca-ide 1.4.224 status 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/preflight.txt` | `93ecaa481e589bb9b515f1c57969305f02d6c8551c358648abe595c5173e764d` | preflight.py readonly 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/diff-scope.json` | `a62f7cd3becc69234eda84aef11ed29f87722cf82add307dd02f93133aa18a15` | diff_scope.py --strict 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/coordinator-driver.py` | `2b6ec30381d7169773bd2c283eaf1f36c046cbc0dca30fe909f183f87d3a0057` | coordinator 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/dispatch-record.json` | `ed0c05196c313ec50be15e57058ee07621d31cca4ce5137b957ec91eb226c1a8` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/dispatch-pubkey.hex` | `4063344914de0fd53c0bc2e8d756419d828f1b54a29340c2c19e10184cdeaf31` | dispatch-sign.py gen-key 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/axis-standards.md` | `67c61823632e039c2df5343466da54a50deb3a5959d8125774d19a36eb193198` | claude worker (task_6d5f6019b040) 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/axis-spec.md` | `c0ff6c9ac3c8d9f8cde134e90291cbd65f05886514fb5852a73530c8f0f1f428` | claude worker (task_ce92854900ce) 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/axis-test-adequacy.md` | `86658e8fc7a0945f544901d8b83fea6f7ebf364282deeb8c0ff0670e549bd9c5` | claude worker (task_f1a76ab16913) 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/lens-security.md` | `e209565ea235f6da3ed155e17f21f7b6cc43bd12b99ed224bf58e576d9eab84e` | claude worker (task_850a46a339a1) 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/worker-done-delivery.json` | `bafc798bcaae1ac5106b40b20fb2bebe193ef6f4d11e4c4ff01863ddd7e7b4c3` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/task-list-final.json` | `cef579b6371ce4ffd0d241127d1b9bbba4d184ff06ca336e12aa2ac9cf85fe0f` | orca-ide orchestration task-list 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/quote-check.txt` | `8d69be5335156e147dbde971e04e5805389c07ea8327484aa54b9764b06a66f0` | coordinator re-read + empirical git 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/verdict.md` | `e01333b6f792a293be32e4ef89560f1aaee3ac858b502941922387bb389f4e03` | coordinator aggregate 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/verifier.txt` | `9fa574c6572cc376b2eaa9e1bf49d1305fba36b893b7df8f3fd0e8797226b618` | evidence-run.py verify.py 2026-10-13 (absolute-path record) |
| `docs/runs/2026-10-13-review-it-linux/verifier-rerecord.txt` | `9fa574c6572cc376b2eaa9e1bf49d1305fba36b893b7df8f3fd0e8797226b618` | evidence-run.py verify.py re-record (dangling-wtree record) 2026-10-13 |
| `docs/runs/2026-10-13-review-it-linux/verifier-rerecord2.txt` | `9fa574c6572cc376b2eaa9e1bf49d1305fba36b893b7df8f3fd0e8797226b618` | evidence-run.py verify.py re-record on committed tree (binding record) 2026-10-13 |

## Gates

Catalog-side (this repo at landing): `python3 scripts/validate.py`,
`python3 scripts/bind_check.py --base origin/main`, and the sharded test suite
run on the landing branch; results recorded in the landing PR. Target-side:
none — report-only, target untouched. Evidence binding: artifacts retained in
this run's own directory at `inventory_at` above; `inventory.py check --at`
and a direct `run_report.check_report` call were run by the coordinator
before landing (results in the landing PR).
