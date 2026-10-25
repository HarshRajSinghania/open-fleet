# Run report — #604 WIP-curve experiment, version 2, live (12 runs, four WIP settings), 2026-10-25

RUN: mission=wip-curve tier=doctrine-only inventory_at=86065113eae2826138b993c74e9774b7fa45d249 manifest=docs/runs/2026-10-25-wip-curve-604-live/manifest.json verifier=GREEN

This is an experiment run, not a catalog mission run. `mission=wip-curve` names the experiment
(`scripts/wip_curve.py`), and `tier=doctrine-only` because the run advances no mission's proof
tier. The header exists so that `runtime/scripts/run_report.py` binds the evidence below to a
commit. The verifier is GREEN under a dispatch record the coordinator signed for this unit; see
[Evidence binding](#evidence-binding).

| Field | Value |
|---|---|
| Question | #604: how does verified-CLOSED throughput change with the number of concurrent builders and reviewers, before anyone changes the fleet's WIP caps (`runtime/attention-budget.md`)? |
| Registration | [`wip-curve-prereg-v2.json`](../experiments/wip-curve-prereg-v2.json), version 2, sha256 `c30c2c15890d565af64c126dd456de4a09310c757ad33975a310e170412e1aa8`, fixed before any version 2 data. Version 2 superseded version 1 after its second live run met an expired credential ([Version 2](../experiments/wip-curve-prereg.md#version-2), #679). |
| Design | Four conditions: `b1r1` (the serial baseline), `b3r1` (the current cap), `b6r1` (wider parallelism, one reviewer) and `b6r2` (the reviewer-capacity control). Three repetitions each, 12 runs, in the registration's Latin-square order. Six fixed tasks on a synthetic stdlib-only package, with build-blind reviewers, a coordinator-run oracle and the merge queue. |
| Runner | `scripts/wip_curve.py` at `bacb5f8dd8` (#679 merged), inside the container live harness ([`scripts/live_container.py`](../../scripts/live_container.py), #672). |
| Command | Each run: `python3 scripts/live_container.py run --arm wip_curve --results ~/of-live/wip-curve-v2 --timeout 14400 --cap-usd <authorised less spent> --per-call-usd 1.60 -- --prereg /repo/docs/experiments/wip-curve-prereg-v2.json run --results /results/experiment --workdir /results/sandboxes --worker live --agent claude --model claude-sonnet-5-5 --cost-cap-usd 150 --reservation-usd 2.00 --next 1`. Then `report` and `verify`, each in its own launch at the same commit. |
| Worker | `claude-sonnet-5-5` on Claude Code 2.1.304 (every run records the pin and the harness version), in the image `open-fleet-live:claude-2.1.304` (`sha256:59c37b04d715…`), built from the committed Dockerfile. It ran as uid 10001 in a container that held no credential, with a USD 1.60 `--max-budget-usd` on every call. |
| Spend guard | Two caps. The broker's `--cap-usd` is the USD 150 authorised less everything #604's launches had settled before it (USD 149.54 for the first run, USD 143.72 for the last). The arm's own `--cost-cap-usd 150` reserves USD 2.00 per dispatch in a ledger shared by every run, [`experiment/budget.jsonl`](2026-10-25-wip-curve-604-live/experiment/budget.jsonl). |
| Billing | The owner's Claude subscription, through the broker. Every USD figure is therefore NOTIONAL: what Claude Code, or the broker's price list, says the API would have charged, not money spent. |
| Human gate | The owner authorised USD 150 for #604 on 2026-10-24, recorded in the registration's `cost` block ("Authorising you on everything. Go ahead and complete it."), and authorised version 2 on 2026-10-25 (`supersedes.authorised_by`). |

## Result

All 12 scheduled runs completed, and all 12 are protocol-compliant as the registration defines
it: every model each run's usage record observes is the pin. The broker, which sees every request,
recorded one call on another model, in `wip2-b6r2-rep2`; see [One call off the
pin](#one-call-off-the-pin). Every unit of every run reached verified-CLOSED (6 of 6 tasks, 3 of 3
repetitions, in every condition); nothing parked and no merge gate failed. The full report is [`report/report.md`](2026-10-25-wip-curve-604-live/report/report.md),
with its JSON beside it.

| Condition | WIP | Throughput /h, mean [95% CI] | Latency median min, mean [95% CI] | Rework (pooled, 95% Wilson) | Freshness | Conflicts | Cost USD per run, mean |
|---|---|---|---|---|---|---|---|
| `b1r1` | builders=1 reviewers=1 | 119.64 [58.13, 181.14] | 0.24 [0.21, 0.27] | 2/19 = 0.105 [0.029, 0.314] | 0 | 0 | 0.4228 |
| `b3r1` | builders=3 reviewers=1 | 202.71 [116.23, 289.20] | 0.53 [0.45, 0.61] | 4/20 = 0.200 [0.081, 0.416] | 1 | 1 | 0.4413 |
| `b6r1` | builders=6 reviewers=1 | 194.08 [168.86, 219.31] | 1.01 [0.88, 1.14] | 6/21 = 0.286 [0.138, 0.500] | 3 | 3 | 0.4581 |
| `b6r2` | builders=6 reviewers=2 | 247.16 [195.84, 298.48] | 0.66 [0.36, 0.96] | 6/21 = 0.286 [0.138, 0.500] | 3 | 3 | 0.4618 |

**The recommendation is keep.** The registered decision rule raises the cap only when a condition
above it (`b6r1` or `b6r2`) has a throughput interval whose lower bound exceeds `b3r1`'s upper bound
(289.20/h), with rework and freshness within set margins of `b3r1`'s. `b6r2`'s lower bound is
195.84/h and `b6r1`'s is 168.86/h, so neither separates. The rule lowers the cap only when `b1r1`
beats `b3r1`, which it does not. Anything else is keep, including a null or negative result. The
rule yields a recommendation only: a cap change would be its own human-reviewed policy change citing
this report. The recommendation does not depend on `wip2-b6r2-rep2`: without it, `b6r2` over its two
other runs is 258.95/h [219.51, 298.39], still below `b3r1`'s upper bound, and the rule still says
keep. [`runtime/attention-budget.md`](../../runtime/attention-budget.md) now records the caps
as measured once, with this result.

## What this shows, and what it does not

**Throughput rose from one builder to three.** `b1r1` closed 120 units an hour on average, `b3r1`
203. The intervals overlap, so three repetitions cannot rule out a smaller effect, but the
direction matches the cap.

**Six builders with one reviewer did not beat three.** `b6r1`'s mean, 194/h, sits at `b3r1`'s. Its
median latency doubled (1.01 minutes against 0.53) and its review queue grew (median 0.38 minutes
against 0.24): one reviewer became the bottleneck, as the cap's "one reviewer per three builders"
assumes.

**A second reviewer recovered throughput, but not decisively.** `b6r2`, six builders and two
reviewers, had the highest mean, 247/h, with latency back near `b3r1`'s. Its interval still overlaps
`b3r1`'s, so it does not meet the registered bar for raising the cap.

**Coordination costs grew with WIP.** Rework rose from 0.105 at one builder to 0.286 at six, and
conflicts and freshness violations (a review voided because the head moved) from 0 to 3 per
condition. The merge queue caught every one: no gate failed and every unit closed.

**The confounds the registration names were held.** Reviewer effort is flat across conditions
(637 to 685 tokens per review). Task difficulty is even: every task closed in every run, at a median
latency the condition, not the task, sets. One model, one harness version, one machine label and one
set of experiment inputs ran every run, and the cooldown between runs was kept.

**What this run is not.** One synthetic six-task package, stdlib-only Python, on one host, through
the posix provider, with one model and agent reviewers only. Larger tasks, other languages, real
repositories, other providers and human review capacity, the serial bottleneck
`attention-budget.md` actually names, may bend the curve differently. Three runs per condition see
a large effect, not a small one. The units here close in under two minutes, far shorter than a real
unit; the curve's shape, not its absolute rates, is the finding.

## Spend: two ledgers, one notional bill

| Run | Started (UTC) | Broker calls | Broker refused | Broker settled USD | Arm charged USD | Broker cap USD | Receipt |
|---|---|---|---|---|---|---|---|
| `wip2-b1r1-rep1` | 07:28 | 39 | 6 | 0.464935 | 0.405901 | 149.54 | `20261025T072848Z-wip_curve-a542b577` |
| `wip2-b3r1-rep1` | 07:41 | 54 | 8 | 0.607289 | 0.524333 | 149.08 | `20261025T073146Z-wip_curve-c221ea8d` |
| `wip2-b6r2-rep1` | 07:54 | 47 | 7 | 0.531510 | 0.459994 | 148.47 | `20261025T074401Z-wip_curve-07078de6` |
| `wip2-b6r1-rep1` | 08:05 | 47 | 7 | 0.533251 | 0.461573 | 147.94 | `20261025T075525Z-wip_curve-fc57ffd4` |
| `wip2-b3r1-rep2` | 08:17 | 39 | 6 | 0.458048 | 0.399137 | 147.41 | `20261025T080715Z-wip_curve-0d07f54b` |
| `wip2-b6r1-rep2` | 08:28 | 47 | 7 | 0.533097 | 0.461485 | 146.95 | `20261025T081856Z-wip_curve-360ffaaa` |
| `wip2-b1r1-rep2` | 08:40 | 45 | 7 | 0.524903 | 0.456505 | 146.42 | `20261025T083056Z-wip_curve-3a6f8a93` |
| `wip2-b6r2-rep2` | 08:54 | 47 | 7 | 0.651138 | 0.461536 | 145.89 | `20261025T084455Z-wip_curve-7ae9926e` |
| `wip2-b6r1-rep3` | 09:06 | 45 | 7 | 0.519385 | 0.451358 | 145.24 | `20261025T085634Z-wip_curve-c6389de8` |
| `wip2-b6r2-rep3` | 09:18 | 48 | 7 | 0.537299 | 0.463861 | 144.72 | `20261025T090825Z-wip_curve-fee81434` |
| `wip2-b3r1-rep3` | 09:29 | 40 | 6 | 0.461014 | 0.400320 | 144.18 | `20261025T091950Z-wip_curve-b318b0d9` |
| `wip2-b1r1-rep3` | 09:41 | 41 | 6 | 0.468611 | 0.406068 | 143.72 | `20261025T093127Z-wip_curve-c40be662` |
| **Total** | | **539** | **81** | **6.290480** | **5.352070** | | |

- **The broker's ledger** holds every API call the arm's Claude Code made: each one started,
  settled with HTTP 200 at the price the API's own usage gives, and none was left open. The
  `report` and `verify` launches made no call.
- **The arm's ledger** charges each dispatch the `total_cost_usd` its own stream reports. Its total
  equals the runs' observed cost. The broker's is USD 0.94 higher because it prices every API
  request a call made, including the ones Claude Code's own total leaves out.
- **#604's whole bill** is USD 6.290480 for version 2 and USD 0.455626 for version 1, USD 6.75 of
  the USD 150 authorised.

## One call off the pin

The registration requires every model a run's usage record observes to equal the pin, and the
runner reads that record from each dispatch's stream: every stream's result line, in all 12 runs,
reports usage for `claude-sonnet-5-5` alone. The broker's ledgers see more: every API request
Claude Code made, including side requests its own usage record leaves out. Of version 2's 539
calls, 538 ran `claude-sonnet-5-5`. One did not: call 32 of `wip2-b6r2-rep2`'s launch
(`20261025T084455Z-wip_curve-7ae9926e`), at 08:55:25 UTC, ran `claude-sonnet-5` with 158 input,
47,709 cache-write and 7 output tokens, and settled USD 0.119659. No assistant message in any
stream came from it, and no stream's usage reports it, so it was one of Claude Code's own side
requests, not a worker's turn; what it asked is not retained.

As registered, the run is compliant. Because the registration's purpose is one model across the
experiment, the decision was also recomputed without that run, and it is the same: keep. Version
1's ledgers show no call off the pin. A later run should pin Claude Code's side-request model too,
or count the broker's models in compliance.

## Observations and deviations (recorded, not hidden)

- **One call off the pin**, above.
- **81 refused requests.** In every run, 6 to 8 of Claude Code's requests carried a `safeguards`
  field the broker's allow-list cannot price, and the broker refused them before they reached the
  API. Every run completed regardless. The refusals were uniform across conditions and were left
  as they were rather than changing the broker mid-experiment; the same happened in version 1's
  first run.
- **Version 1, superseded, retained.** Version 1's two live runs are in
  [`version-1/`](2026-10-25-wip-curve-604-live/version-1/experiment/runs/) with their receipts.
  `wip1-b1r1-rep1` completed. `wip1-b3r1-rep1` began 24 hours after the subscription token was
  written for the harness, and the API refused all 18 of its calls (HTTP 401). It still read
  `complete`, so the stopping rule's re-run was refused. A third launch was interrupted during its
  cooldown and made no call. Version 2 (#679) halts a run on a refused credential and names the
  host, not the container, as the machine; its runs are never pooled with version 1's.
- **The token.** The owner replaced the expired token before version 2 ran; the first version 2
  launch followed a USD 0.009 smoke check that settled every call with HTTP 200.

## Containment

Every launch ran in two containers on the operator's Docker host: a broker that alone held the
token, as a read-only file mount, and the arm, which held no credential and reached the API only
through the broker. Every receipt records the commit, an image built from the committed Dockerfile,
zero token redactions in the output, and both containers verified destroyed. The report and verify
re-ran the workers' oracles there too, never on the host.

## Retention and secret check

Everything the run wrote is retained here except each run's lock file: the 12 run directories
(records, event logs, streams, the git bundles of what landed, the private state stores, oracle and
review transcripts), the shared spend ledger, the report and its verify, and every launch's receipt,
log and broker ledger. `manifest.json` pins all 697 files by sha256. No retained file holds a
credential shape, gitleaks found nothing, and no file holds the subscription token.

## Evidence binding

Commits on `claude/run-report-604-live`, forked from origin/main `6f02e410da`:

| Commit | What it adds |
|---|---|
| `08151bdea7` | The retained evidence, `contract.json`, `rederive.py`, and `manifest.json` pinning every file by sha256. This is the unit's `head_sha`. |
| `0dcfebac12` | The manifest bound to `head_sha`, with the contract digest, the re-derivation record and `rederive.txt`; the coordinator-signed dispatch record and its public key. |
| `86065113ea` | The GREEN verifier record and `verifier.txt`, pinned in the manifest. This is `inventory_at`. |

An earlier binding on this branch (`9ebdb656dd` to `651e286562`) was superseded after review found the call off the pin: the contract now requires the broker's model reconciliation and the decision with that run excluded, so the evidence was re-bound and re-signed. The run itself ran at `bacb5f8dd8`. `rederive.py` checks that the runner, its call helper,
`events.py`, the registration and the task set are byte-identical there and on this branch.

Re-derivation, recorded through `evidence-run.py` on `08151bdea7`'s tree, exit 0, 66 checks:

`python3 runtime/scripts/evidence-run.py --label rederive --manifest docs/runs/2026-10-25-wip-curve-604-live/manifest.json --artifact docs/runs/2026-10-25-wip-curve-604-live/rederive.txt -- python3 docs/runs/2026-10-25-wip-curve-604-live/rederive.py`

It runs the runner's own `build_report` over the retained runs and reproduces `report.json` field
for field, and `report.md` byte for byte. One substitution bounds what that proves: the report
re-runs each landed task's oracle, which is worker-written code and refuses outside the harness,
so `rederive.py` replaces those 72 re-runs with the bound transcripts' recorded passes. The real
re-runs are the in-harness `verify` launch (`20261025T094506Z-wip_curve-b861c2aa`), which found 0
binding problems. It also re-derives both ledgers, every launch receipt, and version 1's refused
credential.

### Signing: who signed, and with what

- **Signer.** The coordinator, through this agent session acting as its signing hand for this one
  unit.
- **Key.** The coordinator's local dispatch key, the one that signed #605's and #602's units. Its
  public half is committed beside the record as
  [`dispatch-pubkey.hex`](2026-10-25-wip-curve-604-live/dispatch-pubkey.hex), byte-identical to
  theirs.
- **Custody.** The private seed is `~/.open-fleet/coordinator-dispatch.seed`, mode 0600, in a 0700
  directory outside every repository; `dispatch-sign.py` re-asserted that at signing. It was never
  printed, copied or committed.
- **What was signed.** [`dispatch-record.json`](2026-10-25-wip-curve-604-live/dispatch-record.json),
  over `manifest_id=wip-curve-604-live`,
  `contract_digest=sha256:c80c0ae3dbdd81391acbe8df50c171af772f377ce600dfae85c350956cedb14a`
  (`contract.json` at `08151bdea7`) and `unit_class=report-only`.
- **What it is worth.** The key lives on the same machine as the session that used it, so the
  signature records the coordinator's authorisation of the report-only class; it is not an
  off-worker trust anchor. It is not the repository's `.orca/dispatch-pubkey` enforcement pin.

### The verifier run

| Label | Tree | Exit | Outcome |
|---|---|---|---|
| `verifier` | `0dcfebac12` | 0 | **GREEN**: `verify: OK — all required checks passed`. [`verifier.txt`](2026-10-25-wip-curve-604-live/verifier.txt) |

It ran with the stub `claude` first on `PATH`, the system `/usr/bin` ahead of `/opt/homebrew/bin`,
and `SHELL=/bin/sh`:

`python3 runtime/scripts/evidence-run.py --label verifier --manifest docs/runs/2026-10-25-wip-curve-604-live/manifest.json --artifact docs/runs/2026-10-25-wip-curve-604-live/verifier.txt -- python3 runtime/scripts/verify.py --manifest docs/runs/2026-10-25-wip-curve-604-live/manifest.json --contract-source docs/runs/2026-10-25-wip-curve-604-live/contract.json@08151bdea74493ca2dd1c1a946b5f7c249115bf4 --contract-digest sha256:c80c0ae3dbdd81391acbe8df50c171af772f377ce600dfae85c350956cedb14a --unit-class report-only --dispatch-record docs/runs/2026-10-25-wip-curve-604-live/dispatch-record.json@0dcfebac12de5d860c8079737a513a513fb80e8a --dispatch-pubkey docs/runs/2026-10-25-wip-curve-604-live/dispatch-pubkey.hex@0dcfebac12de5d860c8079737a513a513fb80e8a`

It confirms, under the signed report-only class, that the contract's criteria (WC-1 to WC-7) are
complete, every artifact matches its sha256 pin, the credential scan found nothing, and the
dispatch record names this unit and signs the contract digest and class. `verify.py` skips the
content-bound command ledger and the source-binding control for a `report-only` unit, so GREEN does
not vouch for either; `rederive.py`'s recorded exit-0 run stands for them. `--base` was not given,
so the ancestry leg was skipped before merge.

Re-check:

- `python3 docs/runs/2026-10-25-wip-curve-604-live/rederive.py` re-derives every figure above.
- `python3 runtime/scripts/dispatch-sign.py verify --record docs/runs/2026-10-25-wip-curve-604-live/dispatch-record.json --pubkey docs/runs/2026-10-25-wip-curve-604-live/dispatch-pubkey.hex` checks the signature.
- `python3 runtime/scripts/run_report.py docs/runs/2026-10-25-wip-curve-604-live.md --mission wip-curve --tier doctrine-only` binds the report.
- `python3 runtime/scripts/inventory.py check docs/runs/2026-10-25-wip-curve-604-live.md` re-hashes the inventory below.

## Gates

Catalog-side, run on the landing branch: `python3 scripts/validate.py`, ruff, the floor guard,
`check_trailers`, `changelog.py check`, `run_index.py check`, `gen-badges --check-last-release`,
the `run_report.py` binding above, `inventory.py check`, gitleaks, and the run-report, run-index,
docs-navigation and changelog tests. Results are recorded in the landing PR.

## Run-close integrity inventory (sha256)

```
c80c0ae3dbdd81391acbe8df50c171af772f377ce600dfae85c350956cedb14a  docs/runs/2026-10-25-wip-curve-604-live/contract.json
1f4d5db594495b1c4b0a15ec8ccc7008b6be1079b498ad2109da1530b70cdcaa  docs/runs/2026-10-25-wip-curve-604-live/dispatch-pubkey.hex
1e2cfab247540cd7906f76fccb2a420c52080c1e21a3c24f541cbaed303d8114  docs/runs/2026-10-25-wip-curve-604-live/dispatch-record.json
350e4a621103a786eb9eccd2abf5cd2233aa67f7a4078af863f7599af22e6781  docs/runs/2026-10-25-wip-curve-604-live/experiment/budget.jsonl
a6a8123c80dd885e018069dba93948b6412b2bfeb4df6eee516b831510440358  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/calls.json
03f1836c2b8245f196f63cd2d789b9b7aff5ee083772f186ac2bfabc6be7ec15  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/events.jsonl
553ca9c7a33c575dee70c99e8162f529a538a175792de9a55406a513bd002b2c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_016be7f299.json
47400f270fd64fe47a1257d280df2b93e3bc202ed85279804167a949dd1cf0bc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_16aeb12993.json
4f1f2b161b33fce1f7af2fc1040d801bf7a74d225756e9dfbf3dc84880c00767  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_17defc52c5.json
476b2b495c277182a8b0f2a9ddd4bf73585257e8af309c42bf89f8aa07caba7e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_295d7b2c76.json
37e95ff3c747514f8a409ea6bd3eeaf8f2cf8ba582f52501c0349963783ecf64  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_52f0225227.json
27d355d559d0751e62d7334ac09df333a35726f93abb3cb653c2a3598077ae79  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_5d1ddc06f7.json
0390cef75f0334bd7eaf211b208d69148c2bf507cd4247561d901603bbfc8254  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_72699a3f49.json
ce7f4475fe286cd0ffc5f3c0fade6130b84502923fb186a17d75a3486a4e77b9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_c4396f5800.json
191fb4479d1ccfba2b943aaf81f95721d8ef7ff51c5500c70f0a70032abd233d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_c7c68ed3fd.json
3a14a0e92e3193d1c4b5c6c33ae47258c377c0dcb76fe718d9b51731ca493f19  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_d4d8f1b517.json
1242769108fa886d9f78294e3b761c50b48d6bc7657b1ad420fbc6d332fb296a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_df57dea233.json
ad0e3837f3ff9dad406fdb38da18da9ad41bccdd181d55d2f221c3af1a368d90  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/exits/disp_ffe203d023.json
01dbc871298a1486d1bd688f02b3841c0732e2755e85ab626ad7b56d102bbec3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/merge-receipts.json
a13f09de57697fc8ec4d2f40091a8664f634becd67d270d98df6ad55a048b82b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/oracle/t1-a1.json
d34cf013910e393526938535c252830c131f6c3ab6d86176dd62f12e483eb880  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/oracle/t2-a1.json
92189f02c5be5163a3fda2e9ba1271fc0198f36fbc0fea202602192257dcd31f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/oracle/t3-a1.json
70906f5150702bf4b7ecab9590629287edb6feaebe31eca6bd986e025722764a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/oracle/t4-a1.json
ae0a09f0e2f9699613cb5c2a12f89b6a91db00871d4206f43c8a68812d73a09d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/oracle/t5-a1.json
221f71bec263c9e8be66d832aed4b6fc98c9d41baa80513c0a4cfa59635d7f98  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/oracle/t6-a1.json
679d90f0ef19952648170f9e5a5ab63bd6a31fdd868189f91bea63e8da7f02be  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/reviews/disp_016be7f299.txt
5b4ebb5924654c3870689d0692854212ba6032aa1681a33b38dc59296f21672d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/reviews/disp_52f0225227.txt
4e6d39fc979e22d9d44e96fe83b032e6b6365cd5513bd30e8acc4bac2951a869  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/reviews/disp_5d1ddc06f7.txt
1ceb525537076b4a29d5bb7f1d6f93767e80d390e4f1de8f326b0d375b9b68ed  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/reviews/disp_c4396f5800.txt
e56e91097da3c2cc31f6f4bc329ccef8d414825ca65744293636f0853551290c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/reviews/disp_c7c68ed3fd.txt
274860d13ae9f1eaf3e1ace261830b2c5be4352b9dcb4937c78ed5742ac526f8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/reviews/disp_ffe203d023.txt
acf36c92db56438056cb7298bece627e4c95760263d0166d8ec5c6cba59e097a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/run-report.md
a34535a5c19d12c8a000b48a147d5c2afca0f1f3741d4bc8835056e96a260cf7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/run.json
f6c86f8cd1203a51b74f97d474cc862723b850f77e5b7441d61d98c36d464434  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/state.db
9fb5500dc171d231e8a3cdadfbe5a2c7bbbe95e64114878f5942a2555880e165  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_016be7f299.jsonl
96554a1ac58c690d5773ca5d33cc6ee0ffe100207a60a6840b83b248a75dfc09  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_16aeb12993.jsonl
a97c54a5c5c0cfe13ef5e472721bae09ad0d5eadb18abf1a87aba77ba2334ee2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_17defc52c5.jsonl
3ce7e2b5dea30b5526bce7f32dde4aaee943377e49b4045c57ec6c2838df852b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_295d7b2c76.jsonl
2d0aca6dd5516020c78013625acb5086d01454ad55d0be55cad5cf92e9db9ef9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_52f0225227.jsonl
a90ba450cff0cba15cd2b88c471ab17bcc10847d06563806ec2707ed228fcf95  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_5d1ddc06f7.jsonl
fc56e85fe65f2aa6192b43f9f2eb4cd4fd470d8387d4bf82f0c8a1423d69b93a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_72699a3f49.jsonl
f070e8ec7b53483b1d24d2123615d58569e8b08f4702bf4534afc2bca9f154fc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_c4396f5800.jsonl
ee6ab464282b1a7a7703c637a9e338975952bd27226a0fc13969a82092b1e167  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_c7c68ed3fd.jsonl
3ac31c6d545fb2ce3a8a39adaf4c130554098475c6510be914cd99065c75a6a2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_d4d8f1b517.jsonl
254854c317a2eeb41de53021ac85102284e4784eca543edec0fbc0db40a90799  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_df57dea233.jsonl
e6da23bc6361ddbfa0f0e4cd8e0fd05c5e506ef5f83a21f8935d6169f41be0c3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/streams/disp_ffe203d023.jsonl
6f3783c2004832d8794642b5265647b47563c686ed7af7ed04e8af6aa5b224fb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep1/target.bundle
421f06063ac17814af04089044b95c13bc76791c2382103da20ab1465b441be9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/calls.json
ac1f1e8ba606ee0ece042c133eed4d99d42d3639e27f145a442d57a9379c4b15  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/events.jsonl
aa5dad707522e24972814dc138c8cf7a620ccdc99780b9c3b43567801e06eb7d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_0f4fe86993.json
3f49dfb9a22a596589307043117569785e1428ad745e9c89a3f39c845ddd2fdd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_1f01c403fb.json
504d2e3dd64d7cfcc71752c71f003e6427242dbe267b4eaa959a217414bc6b83  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_24924d59a6.json
5c8c072473e97e7faf5b16d3a05ebb1c28952e9c52c8663968993cbc35977ae3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_29bb4d4130.json
9c4fa7204589af1c3bceb1b9246a8fb42a4f9a787a0a043168879c078b90f179  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_380dcba6f2.json
813303e32203ed5d3d8ed1e4a3f2536a2426d759ee4479f41015d5c87adb412e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_42e840384f.json
e09e28a5360cf4217675dc773b5553ca61943404ef2732073a6125f4740c877f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_44d8a4c1dd.json
3a25cf4168c8432b1573f4dd5c57b1cf7b19cddb18bdee035ed1771f81909412  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_501f78abce.json
a0b76563118808f1dcef7cd93a236242e2e6100cb5bee724f17b3d914659833d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_59489a007a.json
24f8b7e9ad2b7dad4b75b93b75e54c18a566e3559cf33f678b46216491528aec  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_701003d3cc.json
5816343a09256d5877e5e390046b62041f884bf29b74dea9e624d86419813f21  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_7c1f40cbfc.json
8d40ee306a216637389c1d0ad92b94f71b3d27b462ac6ad030cefa42a99c65df  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_9c986aedfe.json
2b7b742840411d3e33a10e5be17436346bb8a23f3a05d13ed66338cefa6c585e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_d28ded040d.json
7d518f4436e58d3767a44d322bd7c0991410021e81147e4202113270d11c1ba4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/exits/disp_f03167b619.json
233dff8f94f9877f2fa5fa6ccb0a1f8608fccd55da7c0268da3c0c1e655c30ae  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/merge-receipts.json
c881f84440c12b0c2ea97bc7b5fbb395c0d61577db3da26c4ffdf942c3075aa9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/oracle/t1-a2.json
7d1e87dfd5128956b10889469d7af65bc44da7a920bd84058ce9e1bd31a583b6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/oracle/t2-a1.json
6fef43a0b641c21393f049cbabdaa8340e7ecbec8fbc732850a3415c58e86d15  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/oracle/t3-a1.json
34b84a6c249fca47412500a41bd5b968d81f8443ddbfc35f028d75af6e02aaf2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/oracle/t4-a1.json
d25c8d724d91d1d103af4cef1bc275327af7606745e503b1e89c18a224e6f22f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/oracle/t5-a1.json
36b4fdb8b9f6a3950f212e5b24c9792a5999bee694fc8a336cf2bb8c31d2e165  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/oracle/t6-a1.json
80bee6eafa596429f20ee186b9cee7651e7c1da96f101513fa16161d161949fc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_0f4fe86993.txt
df21246d886d774c589f909fa3e6f015c6af7fca2b340c52104b8c547883adbd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_29bb4d4130.txt
4c8825dc5b578942e7a5ca976d534fddcfb37a2021e9ff94a2ed74b9157a9d60  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_380dcba6f2.txt
87b58d05c1f571d164128a381413a4c7f9d9ddaa1369438239181dca6921d25a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_42e840384f.txt
c6091f2fd57e6e3440b1e0e91365d9809deb9dc9c48e0a48b19f553af4c71c98  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_59489a007a.txt
a129e4e5f9f8cee3dce80eafd502ddcb2aa223fa3f68feae521a783a01e33065  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_9c986aedfe.txt
5cb15adb0ac74d0b9beb1936b78816fb592607835564e3d08528589d9bfb7158  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/reviews/disp_d28ded040d.txt
3065495002432fa1a59ff9159c3bbc1adf1f66c06bb6de8ae81e633fdf99184a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/run-report.md
f66c40f14d4194f08e3afc99c254512529540671d1b50a4f4a2ebf1e95db7941  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/run.json
efdb90609b8dd2be4ba9a21d127158ff324a314f78e261003577f9e89b36f9be  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/state.db
ac8593ed75f04d58bb982fc04c6aa1361bb74d0e308597f4cf6470d789e4eeab  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_0f4fe86993.jsonl
b2faa70397e3d1fcf49c0baca0054c4d3b29394108130b47a1a2d0cd4c9085ce  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_1f01c403fb.jsonl
73a82f02fdebccba5f647793dfa2c7b9a9c843104cd823e9dec5b88c73cd36bd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_24924d59a6.jsonl
fd95e1dbfcaada6d01fa4d3ca783c8f85e08772c5667cba2016700b95668d5ca  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_29bb4d4130.jsonl
e35137d276b55c82659025617146dd84fe68631d72b90d00aded1b37daf9bcc8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_380dcba6f2.jsonl
8205366dfcda7b9ef047b47623dd65cccbb90ba9abd3acb52f038a0399f2a144  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_42e840384f.jsonl
a32b6626923b1535380f0d6f3b78bfc8b7e5b02b74095cb5f37f270c5f0a25ca  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_44d8a4c1dd.jsonl
906a86d0dde7215e56d040432b21a07da089cccd983fa0aa96c90d2d0d52cf55  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_501f78abce.jsonl
59457da2a8f3404f327768f36c6127d906d75edfa2fb70437f06ebb8fd94c0a0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_59489a007a.jsonl
a3f699eb2984a216a80ad47d83e5291df03f7434589758a335bff25dc7fa8a36  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_701003d3cc.jsonl
ea3b7cfe25ee9a840a03f9b19776971974e1382d3f31e0d5d537aa6ec41b5c63  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_7c1f40cbfc.jsonl
ce3bb9c264104de1a16eeefcf6aa1b21b73a911c093f274e0b050c9a927d7a5b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_9c986aedfe.jsonl
842655bcefef7f30f4d6ff3f850d783abc0d02b4f0a06809ad611c2528cee259  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_d28ded040d.jsonl
eece7c5762031e77bba778c3cb6c9b07640e75158adec49dbe821721f6881ffe  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/streams/disp_f03167b619.jsonl
16c8f920775f044bb4127e0cef589efa23024ebb863a335a2d988df658058f4a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep2/target.bundle
288f9a9f1d06aae429a8cd7b4e302f2cc962507147c0294141e6c8fb0a63bb77  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/calls.json
35067b3f6b0a79c1b28d94e03c84843ae3f61aea82190b36374fa2e4f5c250c7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/events.jsonl
64ada0a2a8a3e734d6a88101c910bf57acd052948da0e39e021e68f7d5a0c30e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_008aa24573.json
497a1cf08f19fe5788dbc11c90beb7cad3d7ea5577492c4e63bb2ec5b348a3fa  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_2946669e67.json
0fc1bbb7d356dce5b4f177f706b9deaf6b5f889f37f4b9c03e200ceec871dee9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_3daed64c16.json
812acb8e0e8a482f2cb0e22db03bc32d6c6593e2c65680a730a46aa92b199ca2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_58386f103d.json
21f3deb81ace64e3ed58f4806b7f338473624adca480c77a26835d9dd60a2732  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_59148477e4.json
cfceb0ab66977159dbdf2e55d347638e4993adcc06a90e9ec73b3ae0b858f4bf  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_aff19186d6.json
ae9b05e0cfa5dd1f135a4c6c1707761bd79b3c7a1ffd88c4875c33d6c4c79213  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_b7fe67fb3c.json
71dd19b33694cffaf739597133cb162cb5c6a063540ab3bbaba2466be34e2635  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_cfdfc6ac36.json
2ac3051664f7909dca75f6110fb0d6eccf4c7818ebb8eaf04477cde266993916  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_e59b930d4d.json
8f2bd4cac1438c3fcffa1a787fd8e1763b34c658acfa27e08139872d09f92deb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_ecd625c6fb.json
2e9e689b7837310a8e9c169d0e8e1321082c40ffd19ff40066a92ff7dc40237a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_eef4b2c104.json
f7012495044fbfe1f01e0c8262a02fcbb3954f92fc8f7405952f6159e4830df6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/exits/disp_f699b48c29.json
ad0f4fb4685cd1647798e2ef37a9cf7848e7497b7d4d3cd824017decfbc341cd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/merge-receipts.json
b3ca930c2866b2a2277b0f0c4fce5a3bbf3427177c611fffead22a14789470b8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/oracle/t1-a1.json
f26aa51d3650a2ac0f1e2362e76f4957d9e2ed9fdc5eba65551193dc10083c86  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/oracle/t2-a1.json
ac67d67cc809dfda8815fa35fb9b4b3de38d34389eb0c26314374380f1a1c18c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/oracle/t3-a1.json
6f68b0cf9eee5204f924a6dff876616e4870480c941e309e0ba89371908f4490  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/oracle/t4-a1.json
e2d05eaf00493f745143e311765c55f8bc8d6dfe9cb90ab804397815adfa0a38  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/oracle/t5-a1.json
30de2e9a152c739aa647650b781785b8b0d8f6633fe9798e8c5f3b4560d7e3f6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/oracle/t6-a1.json
6ca0c8bed26eb1a8302e252d8788cb97c264f0ae861aa2e80d21e567046b5924  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/reviews/disp_58386f103d.txt
635a050858eea2a8ab1bb73a1ef30240cc5b698ef6bc169aa0b42cf2c3ac8372  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/reviews/disp_59148477e4.txt
73bba5c2ca51729b66b0a46e88638d0796a73ae838ee26fb94a1bd86776b16fa  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/reviews/disp_b7fe67fb3c.txt
2e3accd778af4bfbcc8de4a0577842f21df270f0533c709247118fdc1c4ec474  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/reviews/disp_e59b930d4d.txt
bbb0a703650e2dd9f8afe8019cf9033391bdb1f006b371ca067aff53cb9f41e3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/reviews/disp_ecd625c6fb.txt
a2b13bfb54b50793a31160227cf0f3fee4d276c8e643ddfb71bf5d04dab1d549  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/reviews/disp_eef4b2c104.txt
8b1a4f4923fce0dc8536f3903c477bff43a0fe5fb6126d3aa2cf12ed3b1b1b04  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/run-report.md
539ff1212b82e2ae638d45313c51db4d8659ba2dda17ab9cb98dadb715193693  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/run.json
024be0cd08b317656734222207491753ef91af2d6c04717806d1717ed62b5545  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/state.db
f7e5d5e047b8bcc74930feaf9db0b754bde6960b88f368088a3327fde6951919  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_008aa24573.jsonl
721af54e86f68006d902e5a6aa897e288ad5037a006904b26d3806560fe1c4d8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_2946669e67.jsonl
c9fe3571e30f843ca6492bc4b005f0481f19ec9217f80f4cba5032f1c64a2f7d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_3daed64c16.jsonl
069f05defccd6ad606c15e334cc45c5a069c9c2ebf38ab8f31524417d307cdd2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_58386f103d.jsonl
1ce03456a60bb016876efe31a6e6fabca3b5e1c713588cf0342c95e8ce601fc7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_59148477e4.jsonl
11813233a8852d790fa921b3c8b6a6879d65c3b674938ad9487e6f720135056c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_aff19186d6.jsonl
c58486d12315ceead5cac271db0dc70d2e9f06cf41207cf1d36d6a24609f6f39  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_b7fe67fb3c.jsonl
ef0e573fd98876622a1456b2f7af474054a15e271bd1f9712cbeda20e85a3f61  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_cfdfc6ac36.jsonl
4d032e232eb80a16963470ca4f88e10674648483c83561e46f57fa153f570886  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_e59b930d4d.jsonl
c0536c839204f99442b0fe75a409df90181ce69863120c7950bae7de19d297a0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_ecd625c6fb.jsonl
829077828a587a100ac7cd5709c0be2e8ee53106bf8b9555778d66c08e989a50  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_eef4b2c104.jsonl
e59a3636e60b2db68623f0a257e4bf5ab8e0dc9850a7b75243becae0b82fbf5c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/streams/disp_f699b48c29.jsonl
e022d1cbc595a2ef5ebab9881fb9708f8b515db2a8d37ab099cc2004291395e2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b1r1-rep3/target.bundle
58b04d09d5ff438936b192b7036b31b9123a4f3cb53baa38ad86dac8d7dd7be9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/calls.json
ba0138611ee86be829598506d7efcfa564980a4a51b27e76fa0b2d7e6d719ea9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/events.jsonl
e8599dbc835980c433eb43ffa7daee6fce72930336427e53a8d49123cbfdff6c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_05187cc94e.json
ef953a08d984b231a14b7710ce33887490939afa303e9a7fd2c5944d105bed27  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_1109550c3b.json
37f96672fbeda67d6f0a101adbcc340924e95acbc7e2a4aa3fe1a675ab621a35  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_1a3c50a42d.json
fa8483a2bdf593aa7f2fd99117a352d83b772652ef20505a6f50dffe601c2c00  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_2aba6539b6.json
8cf93e9e366f34d28eece87fce1ef40361eae70da0c6795beb01ec766ae9e522  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_316662f0e7.json
97da681318ca483b13062cca6be87a4d7a59b1551eaf8c0dbf7d72597331d22f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_5b30f9a03d.json
7627287e1b7a2106f47fb4250716e87d9fcdad68a3884df44b9193562bd01684  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_6097ee8e6f.json
e17400ca2f4fee6b7ab1a77a44a54e89dccb7bc0d488c38a10bad93f8f29d0d4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_94779407b8.json
d3b7602d94f3f0553532818c74ea8df88f4207296c0f826fb0457c3eba461c6a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_ab597c0822.json
05a54aaf1391aaefdcaa1e6668c817ffcbc9d95d62b146de4badef4fcc571ccd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_b5be83de5b.json
437de2b08c726ce30dce8838aeead9d5a1cbcfce77a9b6e12de63a0bf0bff705  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_c44bb2ab83.json
eae156f8552edce18ed8cada737419ceefd2eb544b0582eef65db9cbb762a80e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_c883f41f55.json
cd2454061ec28740995109517476f3e0a6e96474be4af688fe32ae5e539bd0ca  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_cf165cda08.json
f6f23833a5edc18dfb07ba7ad6e72b52b64c69a9fdcfdbb76ddf2495d523eeb3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_e430b03982.json
ac50ef210abfe2e7e4f53c9c0d2a598312c9eec49f4437160d00e0502b26d1a0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_e9d9f312d5.json
0c7bdfb5cbb374daf978bddf81309824bef6717498a365ae4da8d9712eba02a5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/exits/disp_f4d0f3da20.json
536df15beb97c1643a6c8a665f7eb5e789125a79d856376e34f471fbe2acef59  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/merge-receipts.json
abbac6b960efd376fd1e2c9d8923f165941fe0eb8d8329ce45856e632928e41d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t1-a1.json
86678fb7fbe9902f8ad761e9356aabe3c3d355d78c14f7cd3427d8ef9139f0e5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t2-a1.json
dd72a4deac519b2567c3376429d13f8cafe7ae48313bd7f18b56026f41e3b931  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t2-a2.json
dea7c742047f159aa187b4007a1dcfce1d79246c552b8ea63c1021d5c755ad30  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t3-a1.json
8d62ba3da8e3aac3d2abdb25939b3a8865df2ddb61a527f3529d07260286918a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t4-a1.json
61c431a04d4f2f2b7313c417b1e0c49c934961243e77b7126b1690968e0d84e8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t5-a2.json
0cce6d8bc2ea3979b8e219b00a40785ad3e6925c9831427ba642d66bc8bf6692  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/oracle/t6-a1.json
1f1462740bf2411179ae11953b3dbc257b1687409111db7e4cccc52c6392e10a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_1109550c3b.txt
adc2d5fbe36fb47ea3c4455e3a9e0faa72c935829d031a1107e2e85097f31425  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_1a3c50a42d.txt
893294a2b3ec6a2e2be0482174779353c5b2c1de96a9da090a473583d45a1740  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_316662f0e7.txt
e51311d64771210f81394efefef2e1edba9295cfc320e66132d564187c3cc1d4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_5b30f9a03d.txt
457a2c2a8244bf30fe46c165df9d212591f7b4dfa09b17498147acc0ec7c662f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_ab597c0822.txt
eb2e66ec843f336ff69aaad30fecfd014f61131430e40f6e0e8a80b1fee3b2b3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_b5be83de5b.txt
8bfbb97d6438a14fb6fa118edb80717676921532ad00b6b4d7e296142377348a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_c44bb2ab83.txt
ea67e00b3e38dc98bdd078c61d3f887d40340495f0b346f7721e8de9b45bdf58  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/reviews/disp_cf165cda08.txt
4d603d0819fd9f6337180a6c0c6e6030465fc36a5d4f7a806857b602a707f48c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/run-report.md
51604a0391708528013a1dd4b5defaa33138ecefc6a42a8b2d7a356826d1abef  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/run.json
b8832ce2ea6375a4e0e357a25b85d4758603c803dea0a7bcaad904f1fdb27cb3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/state.db
b5911f9cf1dacd4187abee63bf659d9700caa1b4befabf16427276ef18bc8dd7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_05187cc94e.jsonl
7fcd6b1b4d8334b66660d741f6cd9105b0aed9e4d549d29d8ae01c64e107850b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_1109550c3b.jsonl
53fb5a9e8d2fb2227ef2782040e0e3b78c42dd1e2b8a597e0539850845b7f940  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_1a3c50a42d.jsonl
10a57d82d82299324f53290badc9006d7af7b6095e63d77cd8934be289d89541  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_2aba6539b6.jsonl
dff6ce79b608560b15519ad9febc4e2f474f1f6edd86dae63b5fc0b539ccc3e1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_316662f0e7.jsonl
8df367e9eed79bb40c1f66fda0ac6d1524b3b1b6d00b4f6352b497b2c3a357a0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_5b30f9a03d.jsonl
caf72560e7855f1bed21541f59a9ab300c66e16291a5dbefc9eb7bc8231c8f86  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_6097ee8e6f.jsonl
5533da01b2d43759fe4ec89c20d0cdf446db23762c0e3aa47c697965309c7b99  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_94779407b8.jsonl
71bd2af93b30f949606590ca2205c5259f4a2704a6df265f7827fe488d751e7c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_ab597c0822.jsonl
8daa725b7c10ca2be1ff71f2065f611ce7e5b1d7b62dbad59acd3890c7753bd3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_b5be83de5b.jsonl
3fdd8bc19599bcc7aa37e6511ce43aac87a28c3a13425360cc49cf7939318b1f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_c44bb2ab83.jsonl
4153fc8be01861e1584de860b0bb47459d681891145000f6e8196e90c04a0f8c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_c883f41f55.jsonl
4327837b2d9b989b7dc3ec7412ff96b346cac4d21f210382218bba03384d9581  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_cf165cda08.jsonl
a97ab6893ab8b7fd557f9aa089cf0f0a8b5d64cd3ac7312e91fb19d9ae4a6dfc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_e430b03982.jsonl
614b3c568b2b48c1d3edc7955fd067a747edd2ff10bc69b661d35d006037ae8d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_e9d9f312d5.jsonl
70ec80f3bec5eae423a580a6d3846ad89999efc1b2751a64c316a3730b289abc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/streams/disp_f4d0f3da20.jsonl
58c0be2ef4a6b60ccf1d40c152e512defe0b1ac5862c00d8cf36de165b51c1a6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep1/target.bundle
951545b803b8187593e496ec0b7cb12cd757c2e8aa836a49b17dd1105b512665  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/calls.json
d9ac8efb172f795601f519481eb4d8093c881c4a71962da595444750654cb4d4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/events.jsonl
731063efe3d9e67be1149802930211dd3ad65f34e03ca80b37dd47cb17eacf5d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_28948cf137.json
eae8a5e96fbb435f2ef848c47ac0ec6a2561c92c3f6ec785fd6591891b88d672  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_4d9b7966a9.json
4e4cfc300a35ca48198c3bb5b14367e56ad2239f851f0d9eee1b23f181efcd32  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_50cf049b8b.json
069462234d073f0dff47d0371116fcb3624c0946eb685be72d4bcf3123b173bb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_5aa15aa317.json
5eee7706b5576af2090826951563b38fa57b8f938eaa96e4e2173def2bdfa3ce  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_652ba0c38b.json
462a50f92c5ca9c524c1319f6f5594fc33e8ad84f7e4c42b48d3ec32b0303b04  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_823f5aca84.json
1c48ae46f411591e58d17084684c2ed07ca0733d62a9eab880842f4b31351dc4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_a64876c658.json
076bce69e7e806f3f62dbfcfe2712f6601a6e1da250ec595535592d2e20c2405  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_c668cb44b6.json
544b9ff926c549f20f30f0d7447d737285270b515a6d306000c0ed7e99a03f64  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_c76519cbb3.json
5559003ab8f3a72389ff763f0fe4e6483e4b75e2f39637c1e02607677f1c2828  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_c8f65a41c6.json
f2796aedd4993323ebc3a0dc954aa8c8d8db5f31acf07eb783cd5b9accdea01c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_ee0916fdca.json
788ba27275e493e2ea09196ad769161518c7eefef99116523647cd2f0d811775  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/exits/disp_f1d7674327.json
44f841da518992cb26594d7a0f1b327145f18f11ce48990332515c61583f22d7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/merge-receipts.json
1ab5480aad7cbeb8bedc06c232c2904e6acb1b89eca2f99d6a72ab0e130f642e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/oracle/t1-a1.json
98f6b37eb5007b3d082806bb36b299d108047577b09da2cbaafb49d609f865ed  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/oracle/t2-a1.json
89baad1d334e2daa75384c797964136e96b58846806015e6bfc5fbc6c9bf3966  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/oracle/t3-a1.json
d1c0ff8ce671d946ba9084293e1808708d285e6631f53ee4fe32434685442104  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/oracle/t4-a1.json
5ad808187cf5f1ba6528dce054005aac39ecf19e1a76d4fd9d0cbec8a2b82187  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/oracle/t5-a1.json
2aedbbab4a636954c94031e366b007a79da9ec888a292dc9083c740feff9a3c9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/oracle/t6-a1.json
4448223de02287c9ba45a773027079bfff2010e0750a89254b0ef49741a82539  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/reviews/disp_28948cf137.txt
a28a7cedde2ec293f892209d5c86e57937704b6c5bcdebe01a50adfb998d0f1b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/reviews/disp_50cf049b8b.txt
1e8230f0ccb6fefb7cf469379e138a60dd5ef1e857e5a91e3fa6ebb2fa047f8f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/reviews/disp_652ba0c38b.txt
3182849e702875ee43a22971e95fb5c4a27da8da3ed3a4b4a683ee50049203f0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/reviews/disp_823f5aca84.txt
4aa27564fa90eb7bdcbd3248e916eec109523823eb19947044bf408356972e42  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/reviews/disp_ee0916fdca.txt
b830c98c05e1aaafc19a678103da4cdcca4b9c461bf365fd769d28c596ca841c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/reviews/disp_f1d7674327.txt
7b30c34af88af12c6e00ba4a1c1773e7c21ad6c2ebfe4aefb949f393a3c06dc4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/run-report.md
c9c9ce6adea7447c140deab12cc4b4ec8cd18354793c64f1eeefc54598a492a8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/run.json
b0062b5992238676f58d156a79a89b6d4c28760fba56dd7c8526056d573ba461  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/state.db
139a72f2c45e3171a2ca370f988013d4b2fa9c71622db24e19f0864cb8a2d899  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_28948cf137.jsonl
13afd214239f69e519cecde985310dd1e6d18d921a71d9ffe67639aec0390e67  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_4d9b7966a9.jsonl
094eaf387aa421167309e8157964f7ac5adc6c52ebc72cffcca7317d06d4bd61  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_50cf049b8b.jsonl
885b2049e76c1915cbf58842e1b7945aff7034520c1b05682d9d63e7c15e024e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_5aa15aa317.jsonl
d17fe8321cbb8b34b95f10994478bee14c56536fb02bdb251d3a6ceb9bedf858  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_652ba0c38b.jsonl
64c0566e0463ed9ae8c9b8b4d47c8ff7f79bf73e23a842a2a8cf7314057f3f62  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_823f5aca84.jsonl
a6694de50bab89ae99bb5efac56b1351619c9df3c0ad044cff53171c804e7c3b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_a64876c658.jsonl
58b465c8c877380fdb0bf696f5744d652531e0d1dc2504a84224c000409df176  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_c668cb44b6.jsonl
2001f3d4307302c9cb74c842f35215b990a900026859200e69759620f212e17e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_c76519cbb3.jsonl
853c4cc16753aa966a3e8872150f1029bef30c682557882b4f27193a3b2c54ec  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_c8f65a41c6.jsonl
861554586fb895e86634d2ac67a84e329b52a753fa6b2a9980c6fff00ee6c29a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_ee0916fdca.jsonl
3cec04640aeac3cd7dfd86b6f4f7759f5f4cc41c23d0c91fd0a74e3f47fe3888  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/streams/disp_f1d7674327.jsonl
1371b80b309ce9256b27c9bf5a21cbc19ea827e283553ce4ffed7a640c9bbbb3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep2/target.bundle
b85306116b37ae304969b26541fea61945651bdf0f91873b4fce71ca176101ed  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/calls.json
49771bb05712a20dc18acf550305c3c46f5fd38b47c083fc2e55aca720462fbc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/events.jsonl
46505c4834cce32c92ef8737cccca907d45e5ee64cce0501062dae84f7c4d576  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_0e7f78626b.json
b8adc02d4203ba65a2c58b6a533bfbee2c04d3276c67cd5d60cd64b4af4f2205  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_3a2288e455.json
47af6321a6d6dac2f939945f8b8ff112b15e9d49c8898dd3941ceb2b5c8c4b1a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_53b2e87795.json
ac5a0ec3487c0f5bf3290e39d24d3e3e1ac9cb657964a875c8b2de152547707a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_668ef8b203.json
1eacf55350fdf336071721406c3ce14e36f53eba0350be8becb38e0a8b8d79f2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_83fce759b0.json
06b3598d6af5df1a9b00c1f7a57c92de136ab9f527981e00ac6120f80a8b4b4d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_8a82b9c13d.json
a90b65c7afa5a19a52cd2bc6e014a9477734299a8f36d7fe3642ab5f60fe625a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_b06e00c477.json
eba50e449f92e39e721a1884389df1f89b60b7fd5adfc96913b7ab8a885922a1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_b915c4f60d.json
64c0d8ad96a65b47e551bd2e73a2944ad3eb4970a6f1561df2c24676c99ca23e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_bdafba82c0.json
40a66571302bceef47f44ddbbad57c9a0cc2840898d61f31080599e3c61de5b0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_f0672c6272.json
5c2651cb2da3e39741a01c22dc0d4aa119f8d303032898b373c9438eb3209db5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_f328eb889f.json
d7de692a9a53046b0d025f2041f0e888bd4d542288c84fdd442faebca53dd8c6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/exits/disp_fcdafa2dca.json
be7480cdfc7db66efa2b4ec83273225bb41e2b7fe69505adee925b19edb12538  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/merge-receipts.json
6d5d3c501ef5e8a21bc9fe8f31f9617aacbe6aff50ebf8afe42f49dff3bd8ef2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/oracle/t1-a1.json
da9244a8b580f7a9db723d4a44c200a8c17276f8bb3afdf943bfb6917ab2cb64  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/oracle/t2-a1.json
f46bd405133f9c17aa6f54f776ad6d6ad559127e1658e5cead0ab0fe9bda3ef8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/oracle/t3-a1.json
8f5f8d243ddbeb96e0728faac832b470fe663733c9a5a2523bbf3288e33ff2ee  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/oracle/t4-a1.json
d82b356a4ef72ea9048c3b3753f8cb75d5b025b088cb94d80e375fababe7ceb5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/oracle/t5-a1.json
1e4ce9c7296ad767625b04852c904d7c6612cf028f7297768995453203c728c2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/oracle/t6-a1.json
9013d83c92bd50e4dd5fc636ead30570ad4fc7ab57beb3dbb23c8acd15b187e3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/reviews/disp_0e7f78626b.txt
d726286133d01c24f80ac7665d1c8d5df5300029898f6c02d74de2e398d4a7da  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/reviews/disp_668ef8b203.txt
15b3cc804c239c3ea628b975135c1d39a059dfd7f0b5df06830702e372c89205  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/reviews/disp_b06e00c477.txt
2eee6c1d4c4a7ef98a72396d23b28dec64f2778252ae0f9a9c0a6cb9b6ba5d21  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/reviews/disp_bdafba82c0.txt
e174d9b3fd027bb72a80558aabafc101e8de08f773ba06e19a1f8d9b71f727f8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/reviews/disp_f328eb889f.txt
2fd9e7da83ebf6bb6c47de7482df0ad2298ee6a10c0b30354cbfc8aa6ce193e6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/reviews/disp_fcdafa2dca.txt
111858cc5f51faa03b62a6c27b071704ad58eb2461c9dab74915f92fc60607c2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/run-report.md
7c1e9e95c6c08f1e1e39fe5eae1b90c0650fc2271772b67706f69387ffe896db  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/run.json
08787af1ade9f04a5c3c782cb1e4bdb508e5eee02ba222fc02a09934a5033984  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/state.db
5b7646382294695b5541c35447f3ae2b962c07228247497198799648d98a4370  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_0e7f78626b.jsonl
831dea4fb5a882754fa742160d489d350bf03883a9da7356764e00235f935971  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_3a2288e455.jsonl
9a4299cad288dfce76e66f42309bbf63b93d2f1ebf48e8459a028ed3c6ebc8c8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_53b2e87795.jsonl
1375e8b8a5bc3f3d3fd6c2a0cbc8b8459fe7525aacfb4bfcf30648554e75de4f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_668ef8b203.jsonl
1406cafa5ecd915c3239b89964280c07889dd853e98619612ef2dc4de7d2ae45  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_83fce759b0.jsonl
9fbc4c48d9f43f42963e617982b58ce5839b6144593078b9608cf6c1514f8b32  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_8a82b9c13d.jsonl
8032863ef7a85ab34f00fbd4682edfb0273a33e1539b7b14a2986115631f9b3e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_b06e00c477.jsonl
11874cb6f7a7e5f0ccf8cb9b4fd4c89c08bace9a3dc5e647846281604708c686  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_b915c4f60d.jsonl
bef33230db1e9fee6ef1a7d2a350b5d32747d353cf5a4329e8472f7a5e2a11be  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_bdafba82c0.jsonl
084358add03e5898a04d85166931a7b8f8aba21188f597427795613cbdecb4c6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_f0672c6272.jsonl
6c6b99f9a02f2367be99a5a6f224930ed56650d0f53a44b6c823c80d08a522b2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_f328eb889f.jsonl
51b8e5330d9a2a8a5bb97e1aac79060054ad291c9ca34c8f1ed6547c95ac2b77  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/streams/disp_fcdafa2dca.jsonl
f7fa2afbd91a71605466022f36b590a7a29465b8e12bca5659853cd4bb8a009e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b3r1-rep3/target.bundle
ee400d32d29d9ce64d13341f3d9d1e6f3bcf972c01a9cc39bbef3f460892fd44  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/calls.json
9fafc1ffb8e342e192b4ea3255dcb97402403200aa289061a87687da5623c54e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/events.jsonl
aeada479d51aa89e2cdb942c8188b29c3b19f3c1f7669ff5dc0a621be2a1f557  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_187b8a39a8.json
ba2c7f3354895b964406e8e036d3412437ce47b331a7e4a5b46735a5a879cb99  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_302b7e30f9.json
60e0723719e4a5ebeb78f776da8660055d5eb50824e6307523b215c09fb3ca57  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_36800fd2cf.json
b44b555ac4424315af435e6f5149f2fee160bcb13abdc6ea743afddcb5275d36  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_3b93d38fe2.json
ea69046db0d0cbff68caa5b39a733d376f0a33e5a0971a8371dff4745faafaab  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_4053b7332b.json
b0f2f38cdce41705314bb79666644870d7270a5ca2b162ca4629260a09a6720f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_42dc890cbb.json
11c007a04832269859ec5c089b88fb31f3324383eb6d73d27229cfa2b957ddf6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_491a297b25.json
8eee620bad4c2370fdc207ccda3ab7a8a209617ac9066afec1abcb5ef6ac4ddd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_7d5624bad5.json
a9bc14a57ca865ad91ef613331143319b0d1fc739d7660c16318e7d9231ed012  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_951c3e271b.json
58359114b070a73d654e851dacc32e766d9737e83ce9df5d499a0f773e46de90  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_960d3ab1fa.json
00ee513490986c92c0574074cfc496f46bd577a2d23f6fc453f7712ae56d0daf  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_97a4c334df.json
a8a80c02a6a27111cba4f9e688791c8b200330deab9ae3679f438b02903afa5c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_ae88182a9c.json
c98edf34bf7b9a1fdab72bdb45ec52191943db8c88a3bdd75d94d085d2e1f4a1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_d2a704d9a1.json
f22c45e65a9f30b3ae8176018d82e68734e22fdfac1d172be4c666e5d2eb2b96  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/exits/disp_ec80e10037.json
7bf44e311fbbbbf9e024e4328b19a280f2b6f92cbbfc2ca70ce88ecfa4f9ad3e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/merge-receipts.json
1af5fbe006097af72baa8810b4c24759640dc1b1bc6172f248cde08eac90ac33  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t1-a1.json
ba71831b9d20d5c7962c9c67c6918aa4d75ca1b14d11932e645dc98ac3d02372  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t2-a1.json
fabfd11632fde7a6f9fddf666f2afee34ecc3a40f886651cfd7d23e18aae7a9b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t3-a1.json
8933b343b674c7ceb829085cea2b7fd77f3ab8c05a4486193247d5088b2935db  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t4-a1.json
21d337a2c4ae94ffd8a1a6783a8e0e6417523e554075246b30c5a878e09e6a39  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t5-a1.json
f54e113e0bbdb94cb2173cd4e74f0d05b22022ddb3908fb70741e8c93c8f7608  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t5-a2.json
e97eb61ae15637b39b1d5ae71ff9d9ea29ff63b75b31a3f129613f1a28592dc1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/oracle/t6-a1.json
838389c23a2d023077762b2046fefda97b8da81eff530f39d47400e096b505ec  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_302b7e30f9.txt
ca84ce44d6751f444d85573c326e3fbbd6e9edf8832bd8685f66ccb698b7c2bb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_36800fd2cf.txt
b77d422169ca301685f23d7084e9c40d968dfdda2f2faff2701c3dc76161d3e4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_4053b7332b.txt
1e46925c9e7aa8a6e0f23a74dcba2d9838bb48a41bd0cee53ddbd37ac0efec0d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_42dc890cbb.txt
6e10b02dc63a03083df3cb08f7101a4b86cad7e18636407662d8f17e810b1860  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_491a297b25.txt
8bcec2f5b5339e1bf35121f9ea38d796bd9b172634bbf87a977bbe98894b07f5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_7d5624bad5.txt
99f36c097cabaa232a1d73914983fc51a26c3b1123f82f3c247e3f422a71fc34  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/reviews/disp_d2a704d9a1.txt
dd5dd27b5081cfb8dbccbc70e40a0ae8ecfeb3fe34a449d2ce2c0d7aeb3eeec6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/run-report.md
7702e9589880d9aa2e83d6e0030aaefc161c9d79f4f41460149acd32983f8f6e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/run.json
dfbbdec5609196bf0092ba58fb9b647c1fe5ed8b14a034b9aa85aaa8167758a2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/state.db
2a67e8839ff463446f3c6679e523d0b72cc20f8237ed7e0984926a2e83c35282  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_187b8a39a8.jsonl
864286ef74958d80b5b88c5b2cae78b4224d8644ca5ee14cf3640d2533b6ef7f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_302b7e30f9.jsonl
b018650f6fce2cddffe6a3298ff2f8687ddeef1c883356479b1e48aca8fce4f0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_36800fd2cf.jsonl
0b5e2195a7a331d846959f451382183b1af9fe90e2427d152164b9bf39806877  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_3b93d38fe2.jsonl
1276e3e1635167534b498d1a0b54463bdd0431a6b667116d9c4342994f223ed0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_4053b7332b.jsonl
abec1ab55281d90253e9aff40e4bcfe4ec3262b1fcb3783f53ffaaec33b49772  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_42dc890cbb.jsonl
e50a7c9dd37a609936f01ccf5ae672e41df8879e43901017b4fbe66297f6c9d5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_491a297b25.jsonl
91cd17db7c55fb0e9afdc235a015a262420d70b7fc3be31cec67f7fc6f19853b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_7d5624bad5.jsonl
24f9b1859fd25653630761a4c371fc3dfce84a66fd03885f574b23e31b604988  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_951c3e271b.jsonl
8a4159bd5f71c26b5528ea3bbc115095ecca6856eadf4daf61922fd7eccc369c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_960d3ab1fa.jsonl
4ea38e2f94f3893512b065df889649b1a19125658df5af2473736a319927d9b5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_97a4c334df.jsonl
81589618f38b80997527b29e917cea27dd4b65ab1f02f81cf744092530ade2e3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_ae88182a9c.jsonl
af20b519823a9b5b6ebe8f0a3d6d1eb8585b8752b3a6c6a1151f1cd616b960e1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_d2a704d9a1.jsonl
a8e16b4d1d3c7b8ec94bbec20feca9027478e306cf78b8ff4d044ebb3e496a13  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/streams/disp_ec80e10037.jsonl
d4bd03c2ec35b8dabfc46d5b0eacd19013e2b82f57f98b76823d23f99bdb3399  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep1/target.bundle
f874465ce0e406ccb01f675835e5992e816b46b2473dbedf7c9d60d836fc5498  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/calls.json
7dfafa7479850cd5955ed64bc4feadbdaba6fb2912366920e416dc418bf9de8a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/events.jsonl
d017ba92da9eddc0227ae47590224c90e7ad6a5a82aae86ac4a941024170d852  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_03369b3c6f.json
57d704e6eb743637740392524806212e60a623d99356d17df84f443f9d17b512  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_04e450f63d.json
7162d6669eb8711d048858aea2dd57faa10fa809c354afadfd6dcd5330fb0484  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_1159071b95.json
346c122518c70130abbfe30d2ee304c7fbbe97cc4bb8bdb3f17da07c473b2299  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_1412b80222.json
2889fc2ec61be6b5b3c8ab2cf961cb7fd39c7375bd8f0eb5383f62317eb1ec8e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_47fe6688ba.json
78641d874a3e97833efacd8d91fd66a16f86a3ba2f05fac1f21f106f37615072  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_5f5f86949f.json
92536d7a15d18ad00a166edc819a276ab7405c9c975c88b95e629fe2dbe827fb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_6807686fb6.json
2d76b07cd49b1e3320e4e1e8484c83f6d31e1e8ba5d0a8ade09d7c2ca1899d9a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_7576b7bb8e.json
ad5e299b0be3a3b2c805a73cdf7924a0c449ba03402e2b7638a4050036e2a874  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_9680af19de.json
437e8678674ed8c28de5996324f1262f543667c9f4f241043e9b8f9df7362375  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_9852b712e1.json
a56d0f96f9143ccad137cf1887746588ba07b89a7906bfc7abac216aed1fe3a2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_9bdaeb1496.json
2cb06fa926b6ade472030a9016cb2a095999d33d757f8d5c5d1feccd2fcbdd2f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_b5440596e8.json
021280f2a30dc6256e3db2640c75985e1fe970027127f8b30276ce9adfd02dc4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_d256542fba.json
82a134831de527208f9eb7584c1da24f23b34e961115a4e0faee7a0f5a1547b5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/exits/disp_d9db98552e.json
8cf964dc800ddb0ea0b38c75be11d3ef55d319651123228a172a31094f2dca04  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/merge-receipts.json
d590dc22baf7b1e0214673b60b035e17f9d8b5c8274193b5aad81845da97a8b4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t1-a1.json
6185a1c380aa8893d64e6e8abde680ef36a93240b875cfb740365510e3cc7fa4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t2-a1.json
7d2cec84149ddee62cdacbc272f1f6c6fd7cda3f3982c387f95c33d981451e5c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t3-a1.json
2c1dca2c878fd0d2f1d6e65cbb4573ae27170baeb4bc5d65f30af657b0f20348  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t4-a1.json
4f3bb4b5f64bb8d50940fc085daf8eed6781f2c76462d143c2300ab262d25f01  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t5-a1.json
d9879ce177142187705da13b0b66c60f23d55f1ede6e2e7264ccf84db665796e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t5-a2.json
fb0678e4c6ef175d546785a9d804bd1d0abde092f5f248851ab6dee1aeb8b55f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/oracle/t6-a1.json
41c5a14877f5fdec08e2629bbf4f60c3685f55b00ccc6fe9c89266d724e56205  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_04e450f63d.txt
4d3384a33574ce0300ad867b68713cef146f8e07f201e2a162817c222990d103  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_1159071b95.txt
ef35e87df26f8da674255a9d7ade3858e485511220bd03b5196af6ae973cc6fb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_47fe6688ba.txt
1577daf28c4f8bab7c8ac60f07da31d9c476b294ef2bda98fae72dd1ab161ce1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_5f5f86949f.txt
3d8308cf019bbaa6824b901862932ff69e57af74eb29eb7e54f4ae20e6f02eeb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_6807686fb6.txt
a7cb2b61f5fe1050bbf93419993f903b72bd4cb3d71285bc89c40f45f1007547  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_9bdaeb1496.txt
46b435638c987d62f808aa9f243bab10af61b179b0766ddb4aba050f334f15ec  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/reviews/disp_d256542fba.txt
505709c9e91fda53b7e0affe04e34d7761d91a8d69fae8b5f223a42ffa6a77ff  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/run-report.md
7e5fdadfe06b13eaa421dcca41fbc6eff01a76f00dd495636d6e0a6b9f96b1e2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/run.json
c8abedd6f57f8a21f8f2c931db2421bb4cbbdac2de988b732f7de3e9d649f29d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/state.db
8cd229213399fb7d069e2cad047424b579f390132d80cb07ee33ad8c90ed87ac  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_03369b3c6f.jsonl
298054d0803af003a829966ba11d5690073df62ed922767c70944920668fd0c2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_04e450f63d.jsonl
f21324d4ae32b01fa48b5675a276bb0b247efad8f40ddbcbc1ef29c572ad0058  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_1159071b95.jsonl
63ccb6d18ab4b962411d63b2b6a7c66d2e6ff60166ef7491f0920ad3fcf81d54  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_1412b80222.jsonl
1738be45529bcc88b8edeb89495eaa55255e3328232ff91ff851c7c724225676  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_47fe6688ba.jsonl
4abf725dcdd3e89793eb83cb6801381a2a5f4fbfafbe20f8f6984084699ab249  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_5f5f86949f.jsonl
8e4ff9c4028a238092c6210bf1c89414a4b31823c01a6d68e8dcc11006ca43bb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_6807686fb6.jsonl
ff3dd8c2636fd48410d2c00e4e56dae2ca3fc21887a00e23fd1eddcc10b6297a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_7576b7bb8e.jsonl
b0c74832ac616cf149ed5a7487f903f2368ec244e3db127ed19be090cb78112e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_9680af19de.jsonl
2c88a992ca3e6f1e8ecedf82818b72405ce4f85ee76dcf67d603fce1efda4c67  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_9852b712e1.jsonl
f1afbf4fb261aa3ea1ce97a84019d39678122432dd8293a794d57d973f0d3a40  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_9bdaeb1496.jsonl
097aa0e13cb1d8c346f746fdf7f69a189d551d088b7969ffe3c17c7dd31aee32  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_b5440596e8.jsonl
7ac8628272f0061f86e2bf92bcbd1489900cdcfc916e4d6ae3c92886b8ab0c7f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_d256542fba.jsonl
c4b4213c89283be8fbbe7a712bf60b51cb898530707fc6fc64ea4f849a4c2de6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/streams/disp_d9db98552e.jsonl
fae005bb99f96eb055cc5d62d49782c0178b222a06e8d1829894e4cd0a9bae3a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep2/target.bundle
dd05c27654971c624ded0f28000218a4ade49c51eff5430bc6d6244d7541ec2e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/calls.json
767c3ccb2be3f087df14ce4171d35e472588efe19fd131840eae6d7b48362bd5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/events.jsonl
c49d6150e79eb8d332ae8cfbdcffcbba414b245a98edf6a080ad57df8b95f7d8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_096ee07bd5.json
291689703d4396a72b9a5157a9d1ad977d0df1c38927523386065c656f121f0c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_0f1f51d996.json
b3b4214c6c2dc4583fb75f30a3f451578be432c4599d50aad081537ea992bec5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_16be40d48d.json
a4c91e797750f50e9f1a28021ef5accba4743f82ee045c3962a08ad88983387e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_5cf12f7bd6.json
8bf65d437645d1804a14d38dfa77716fbc6c9bc07743a2cb5e0b7a9827491b8f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_6ff0e06634.json
982408ee0de4dbc3ea18e2937f9b07321d9463e8c841d2d1822bce0670c616c4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_7e179c2738.json
11195287f4379ba795b0a1097e57fcc941d1175e8e1bd1bd2bacd00a9dabb425  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_8a9965e584.json
53cd2f8beb269dcf0721a4a1f7a4caa0cd7a22c732721619f6558b3ae3070ce6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_8e47d33179.json
24f8112e24aa3f848cf0c3d366c65b39fdee71db23cc3e855da38404a7fb1a37  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_931a1b76fa.json
28ab646a602ae6b06f9e991aa4c3ba5f4573867d473e298eee23d56dfb6f3ec2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_96fb53726a.json
fdc1af488aec2882fc7c5ebc83265804ed90a3c1a76de2fda9c07a72c29b0192  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_b376112302.json
d4476752740888d9ad2f711729a98479dda84c1213d7ee1305d349a1eee8c018  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_d5b640116b.json
86c53700d2733cc56a38ec949b6d153072cfe44c3d2d92b31958446e37fdd6ee  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_e70786da08.json
5cb8eacd30b8c94b96986df28672b764bcd5c0acd278595adcf60caf0b3ce6d7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/exits/disp_f8818e7dc2.json
bf62193ae1ce6a9a42f1d7422f1d15aa5483f29e962bf86dba28591f3a4e5631  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/merge-receipts.json
fe46fbfa910d9ddf542028f9459243432d3da4b40e6eb4153b54bcc58a821d39  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t1-a1.json
4bad3cb06adee9f2d4f9dec784438ae1b6f1c9806418088df72e8bab77fff59a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t2-a1.json
651221f877ca8c17a68c1b07b7649d8db8b627abfb204172ec2abd2b9c205966  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t3-a1.json
e367e45b2e7bd49c5bb70d27285790e74d5f8bdf7d49ccf25bd51713ea6d95c0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t4-a1.json
7ece88fcd3be052495e217f06a8c938cd9223eab23d684a70d0a8e7c904787a7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t5-a1.json
922c82218c96eda0bbc0633c80520a8b8b504710f22e603fcc649e4e2ec0e89b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t5-a2.json
5416596017fec84488118f9eb9673cb692b89d82d976428f0fa461f30581a274  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/oracle/t6-a1.json
e2997c39c77b3a1bba32b5839d8528c438ce56b3dde43522e22a9f7167d1b661  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_0f1f51d996.txt
6bea4fe787a6162ddc8149bd2429ea668c20990220228ba214f2b9c98635b1ec  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_5cf12f7bd6.txt
11e4fe28132496806bcf11cb7e9c3012feaf2f30fb8abb7464cfdbf0e251c256  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_7e179c2738.txt
c1ea429ec1322ee2686b3a4d0aaccc17ca3f79ce0ef2991490b902f7c408472e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_b376112302.txt
19135d25e908e49fc34dc231c9438c7a116fcfc37c7c32784a2d1abeb58a0577  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_d5b640116b.txt
6cd3a46b6cdf6046c173d87b4fb60a31a231eef1406b83d0d2adef9e8405aba5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_e70786da08.txt
8fb694e0eb4281cb2de7baa9e57a4ae6570356d630e8c2f3bf65af106dd3b5e3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/reviews/disp_f8818e7dc2.txt
5494b771b4ce988d4d349f28585c40eb3f0748924d2adc18953ce013690f04aa  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/run-report.md
bfa2c1a157984d785218970fc9c0b257c0b1fa95b9a17205971473be37196739  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/run.json
6b44d5ab69a03744ea53ba6e1d04d5f98c39e0aa5ad56a4f8fcf31f0b6bf8880  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/state.db
1fa6d4015b8eaea9c1566f615e4e1430ad640dfaa6f5030d564507da39d0c88d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_096ee07bd5.jsonl
30cc63423e05c25fb1943f64dcd9ec7e0773b333d277ed25f0df4fdac42607f3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_0f1f51d996.jsonl
3b68801cca8b88296a197c10ece6b12ca5459ede958353fc0efd723f3446e222  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_16be40d48d.jsonl
6da2793ed2fd29b87cadf73e8ef0e5498efa30ad3d6d2469b76d73d80e3f6dee  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_5cf12f7bd6.jsonl
13eef3f0a81d35f19a8bc199cd2c905e4f276479b2928a22406079abc934f2d2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_6ff0e06634.jsonl
f2cf5b0abe427b781c4a75e34aa44c319e334188a3d98cc07a20deaac1d8fd31  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_7e179c2738.jsonl
ad74912dab04054151b21db775c301131f8005c46206b2d568823b36c5ad3ee3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_8a9965e584.jsonl
e633d134cdb7ead093118c8cc35ac6f50bd07c0a8889cad428322c63c9b852b8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_8e47d33179.jsonl
b7c66e2fb55441a6d150f04956ad4a8df2045b73f54bc2672bf06e00d91c4d7a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_931a1b76fa.jsonl
b2581fbc0891f989bd40560bad9b9fa35a0f83f0d6c379da3a55122ca42f7236  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_96fb53726a.jsonl
d44c9f137cf989734e50f0a670605b4e0011e1852fa0baf971d0bbfa9b11599c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_b376112302.jsonl
4f575b86cdc59db2ebf242408b1ceb289e0e807c5fcc06e0459996a5d12bd372  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_d5b640116b.jsonl
c92a0ac7aabb7e5dbb87e97e0c2b5ae0b103e0e961124d65123fd576fc1fe94b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_e70786da08.jsonl
6d0c3dde39a8216d41f3e8258ab62fb9cf2ff5decab3886ca2feb90462d755e2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/streams/disp_f8818e7dc2.jsonl
7a5c422ae92cd44ba5d36fc9bf15ac516c90f4b1a388710505923f49892ce2c5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r1-rep3/target.bundle
d8da949a7b33ce7b99d0c8bd3deaf7cd2cb491deee4ce8a454909cbd58036448  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/calls.json
d79f1bffded9e9db90a1272bc59f5528da086a89874696fe6516a952819642e8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/events.jsonl
c75fd0bdb2359ff979665b2b72a01e98cbcc9e99edf19458c0a82545814ad85f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_0f74c19feb.json
a288893832cdb7425353a3a97ffa7ac8ad1ea5dd13757224f358d0c19ccbfb99  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_359a7f6926.json
fd8cc8cc07631bcd9471497e33f16ea6014eb5bcdf6fec4004cc771150e1be89  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_4e2e9aa34c.json
b9f8fa1b67ed616f018383939345617eba61ffbe9ce7d494e6b906b88f361d24  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_51a44c6757.json
45a39403a66ea7f46d0a0a7bc3c415d034cdcb8496ecc94a32596ffa3f4e2f27  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_5628c735ab.json
171ba2e0bb6a427900eb992b502855bd2090c549c36503fde8f7828e55e05771  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_73d8dba179.json
82b96b2fc4a55678c9273f8a7ad85c4adc166ac49961f307f69d66d43c612366  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_7e1a6ef355.json
1d57ecac3831a174010d02ab8a760c2d4ea92d42444ce4e8be27b1a0541e9fdf  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_9ef5d0fc20.json
fc11d323b2ba0a72e3740c35581143d2103ccc46d09a3d0481efe9f432e945ea  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_aaf6e49f3c.json
f32b8a22459f15fbec91e63e18b61fba7030997a36fa373b81acd4f25b20e78d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_baa72fa847.json
b7bfc45513ba9a1e1b115c1dcb6fd37591f80a6124f508610766dd345405a118  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_d4e0d3feac.json
13f3fd613a3e4e934c4461635b86f2c3a3666e2de55ad47697efe0bec115b38a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_d8df6341b6.json
16c7a235d44980993c01921612ef79fd0b325d837b7a6464961ca3287564c76e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_f0f60c0c28.json
35eb4338cd692f21a45c2e9a1906331bd00e0c0108cdaf03d557e0f585540aff  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/exits/disp_f570ccf5dc.json
09c50c29271f1f622642b36651b7df40bb92b78d66377802446e0cdfeab33f97  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/merge-receipts.json
c864577258a6d331cd8c80d03ff19077d21e8ed3246a696e0cfd1178afa27ba7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t1-a1.json
ceaa195ef81200de66200d5d14543b17ca0cd15e512748f65918a466a45f1b3c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t2-a1.json
6c7b0b3e010301ad4734d5d3e8c97105cc69f03f2ea5fadb513c147a7ca67b21  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t2-a2.json
6abe0e3afd7912ea29776ca01361511317dd5f14847d61724afc44a6fbf18358  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t3-a1.json
6041f221a96dc464e526e4231ae6ff547ec9e411c6f4b997f71a0b41f32ceac9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t4-a1.json
600941e72937766a23b7202ee73366da44729428a95e180d68baf18d12727628  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t5-a1.json
897a3d43c892e925c94830618701f742e774162a80e19ed7bbb67ce50b2151fd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/oracle/t6-a1.json
783e7ea4f28e8d14e1e3c699f2ba2469d870cc1a8ce1ace30979674d7b892de6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_0f74c19feb.txt
82fb3957c4725ef2c29ec70e9e63dfb8b73d91079242f5978fa42a903ba4ab9b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_4e2e9aa34c.txt
9c7ff8cc6a528888e40241549c6393cb651dbd111d6cc1e14c46b299764b6cc9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_51a44c6757.txt
d41e12a31b03742915051ccd6a08c36f7d65e067769071509fcb71db037171a2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_73d8dba179.txt
3872d649b300256c8f4ab4aea7a55a71cf8edac2fdd6df835f3aa1dc04a3bdd2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_9ef5d0fc20.txt
4ab3a862d6a3a304580f33f9c5be2c58858d426fa695a7dff7031595d154b49f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_d4e0d3feac.txt
489af8b7d6f244c83aad18d620dc93191053301ebaa284d20f0b9f803e485517  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/reviews/disp_f570ccf5dc.txt
32f644a1a4fa6be2849483b94e44305f3c721ee766123f335132ab7c3ca75b20  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/run-report.md
cd92adc793538637fc1738ffa09c9da0b4a289d05d17561a06f2e7dee2b8cd01  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/run.json
1435f2f7747c45109d506f91506c69e8762e102651bd322a226dbf55c3cf5573  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/state.db
b4a3da21bbaf851fc1e83c9f85212856b8de86e944ad971e506565d3f72ae67b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_0f74c19feb.jsonl
f76ffdfbcb33b8349c6f67d7edde69aebb48b9d79a7ac512b58a4fd4a5d5ee7d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_359a7f6926.jsonl
f60fce8888d4f3a761a1f82a9e2fade1478569e45ac4b0e3ffcc7706e41d9c65  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_4e2e9aa34c.jsonl
b9088114cc98ccf41490641316d321c1abefc45847d7761e5b8d981cded453a5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_51a44c6757.jsonl
2ed8cec3f8c0e7ad71753fe52f0762b34570cc603bccdb52a1e4b58359aa4814  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_5628c735ab.jsonl
1cdf3a4503b5ee5af36b84016ac663dc0783704ea75f57c6d4f87f5f0795f69e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_73d8dba179.jsonl
a17933e7e5da9f991eec2758619c5aa867c0b4735f16388f4e98e15220831484  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_7e1a6ef355.jsonl
036225f94d584e37c1bc3192b9eb87e8866fd4b56475e6f696037b61f3a65b56  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_9ef5d0fc20.jsonl
0b86e0dcf39fb2bd25306aeca2ef7c3197fb4e1f6abe3ce651e7ec65f8440e58  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_aaf6e49f3c.jsonl
b6a0c379e5bf9acac2db7fad170ff5698e29be00d7d63a1846f5f4eb98842ea5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_baa72fa847.jsonl
71a09f0087eb68a33714d96af971ca51200412b2b70c692eade35e3f88fd802d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_d4e0d3feac.jsonl
a5744d9a78d91754110a307e87c11fb7e0c789219ec10f9f3024eeabc7b99053  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_d8df6341b6.jsonl
141b3a60034d6986690482bd640da279a8522dee4ede4b148b4b6623bf9e52d7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_f0f60c0c28.jsonl
64343c576362bfa0dc4cc186fd3ec240458ebaa452289ef654dad67d7b03b4fc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/streams/disp_f570ccf5dc.jsonl
952de2affd47ce82cc05269ee278f6c8ca26130d2b6327700790ef9578574b10  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep1/target.bundle
430c13fc6a2139c2ec1fc459f7e330c2da36cb3391aaf3d1238263ac3fa53d57  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/calls.json
d6f4dad67a1bb2188dc446225b54b7e2966074d3e2b99365bae9037fb46c0b56  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/events.jsonl
5a77922d226959ac8a018c63b19f9bcd9657645d44e2ee8df13798227adb91c6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_043ef851a1.json
42e3994148168481c7e26979494c9ce6ec3d7d4137ef5a2f6009c852591b246b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_1765728b17.json
aa25fd5de453e64b349f19520c98a59492c1f00159d0de0c1a6afaf9dae4a1a9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_17fa4aab0e.json
e44124e78f7599bf8183ae8e51fc980392ad92d5e59c32d69ac9c9d999c9e539  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_46e719f85e.json
d6b048fdf23efb46bf4572952312bb214fb0cf7a03a1d5224af0f745a006bdcf  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_57b8186cf1.json
c7ab82bbd3b6854df9bc18ebf85769995ad5f4d52a4c13b575859d2d5ce3ab1b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_594b353098.json
f8d59cd15cf51adea53d7f3a036654bb522df54eec0fc0f5748b28882b764b2c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_92ee0a5995.json
61bb97ed3db9fb1ceba6c1580517536ab4057c8e35f97a83826400cfd0f4feec  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_b8fe728b6c.json
93dddeadc56e070326a188519cbb64f781ee97efc580c48c917c0c8311ea9945  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_be65b23c01.json
436554cc507b5bbe8cb3d0f8e30d487084c28da90f5c1709d9d59922fd369647  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_c93de13a07.json
3dd35712817036ec4747f2cf0f001ce7a833aea74cd261bf238999cf3f799d45  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_d2696ed6bc.json
04c36a7caa7fa10ca56fbf1ba52e6a3d48c8606438bbc36909bac63285732ec1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_ec0691364f.json
f909efa63d63c05aa4ab73097a7c0ec16d2efe23e6975aec5fdc99df1d82db99  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_f2dcc52424.json
e5fc01fe8bf8c168bbae59d370b4dab1ea79d7c0a190da73bb13aec536750f3c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/exits/disp_fd17a9df52.json
f15de63d54501a337ab350dbb2682f78707e181cb623d28311eb53ca01ab2e69  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/merge-receipts.json
c39f5d1843f7d4157344e6f06b235113ebaa3c7a5fab5f436131e5509d36b2e0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t1-a1.json
4564971bc2ba7f91bf986cb822cfa749be894acc4dd7481e1ec8265663a07d68  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t2-a1.json
2755e69289ef403ddca727ce7dc584e6e1ef00a9bca99c7ab92fd3604419a344  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t3-a1.json
1c64b0067afbe1630cdc0f30d44b88dd60de553696e6f6f164a347196c784d8e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t4-a1.json
75de83f22d81c6582374cd60f39488d1b6698d89b1baeba530224831691fe417  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t5-a1.json
562fdd1ecff98c88fb7cc4c374099699e8027f69eebf0faf195cbab0d43cae18  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t5-a2.json
a382c10e5e80ca759dc52272649dd0fb27a8a68315283be651a5fa30f437742f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/oracle/t6-a1.json
56e06d2da6c4e1f10124529c4cbd8df12267500c7fa4c4f88432669a9a117d3c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_1765728b17.txt
5c0535a99c75c7a277a9ebfe1589b4535437f8a79a345611ce122d1378250cee  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_17fa4aab0e.txt
add2f93c8314bc94add87b1b3c761b3f89d6db49a8d38c6c0a27674abc5c4e25  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_46e719f85e.txt
7885a83cecacc5707af0f07f6a3ddd5b66b59165e31bfdc5a120bf2700791bf4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_57b8186cf1.txt
a06b116283755717eca74636226602ad42f3a0760d23651a061c8ffd47f5516e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_594b353098.txt
5275d78609fa325d096aa13a0a5280add12b789908fef77870dabac6017a2f43  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_92ee0a5995.txt
e52683c24dc9a3972afe814e68e8a78d126756b533c609a8421c636073f2e905  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/reviews/disp_fd17a9df52.txt
759c40a5e82bc29507964a82068c888417ac79441a5641268462066a5e3d3eb0  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/run-report.md
028e40587ea65f0536c8c56fd669453fa2f23304f294b5b10dc3603d80c2a8bd  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/run.json
a8cf9db1588bde1337469aae46d660168b2a315c022dcb9cbadc396ef24af64b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/state.db
011a3de0f0ee24e9f4318e2dc5a66b726b24bb9a28d06beb55a5673b491e4538  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_043ef851a1.jsonl
72b07f0a43042a67c78c80568dc066135c51291b5b0e4d6aa6145e93b00f3241  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_1765728b17.jsonl
b1f9fce2279112271589c6fee5273cc32db5b97793570725745199742904cb03  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_17fa4aab0e.jsonl
d0bddb1a297601b11b4b056e8b19692b21c5fc41d5b07b531a95afcb11e119b6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_46e719f85e.jsonl
539f89a9f43020766567198074ac11616f39e38ea86cc157f5a13a8755114d05  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_57b8186cf1.jsonl
700170f58e9021f533311a3381c2524d4e858554db598d4ec8216d9c901d5eb1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_594b353098.jsonl
a1d5b13e92f15d616c13416a7763b0f55537ab9f7fe32f8fcc9273e5f3803eff  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_92ee0a5995.jsonl
c558a4062485b2ab0ab8926156d6df9658a434b59dc4c0c26a1d57d8c20d98fb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_b8fe728b6c.jsonl
d706a1f31adaf43487c12daeca5f1378a541820ba0656f487d17c71c2222a1bb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_be65b23c01.jsonl
0650da471c56465c50b993a75f08cfe7371ec03469d4f73df684231a8985fec3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_c93de13a07.jsonl
e888c9f70bff269e4450a7b843eaa1447ed549400e5650b37dc5f28c7a1cb06e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_d2696ed6bc.jsonl
d4719b5c15fec83291dcb6f1696d190b091a7cf76c2a95f5332769c826214a23  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_ec0691364f.jsonl
10bc5c911c643a972d6e2b1f5a814f45711737ec64c2a20256cd2c0d0065a1a7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_f2dcc52424.jsonl
76e1434c1f59a8fa5627a4d1253c35ac80a517b273ec7d86f029b44e1eab46e1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/streams/disp_fd17a9df52.jsonl
de74eafb72e47fff93e0c05a3ca18c265e29881ffd047d8e388bf2798b27780d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep2/target.bundle
ca32de5f2a80f2af704398ce9de22e368fba9979aec3bea3536e8ad379a2f7e8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/calls.json
1bfc4de2f876f63e71bad5c6107f239263144dd8998741948d3c32184295d002  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/events.jsonl
7beee3dc069c6c9b9458965e2fb13a850467734eb643dbc00a50793a132d71dc  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_0dc89cf95a.json
75843cb8829a86626e078cd182c28553f86e14e73fe1585693a8d0c680467a7e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_14ef4f4e30.json
ab14482308c5e2f89b469251c22288f93e0a2bd2b33ce7fab2123a1f437df3e2  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_2517037ccc.json
9b07bbc55f5261cf03cb50adb8a249a0c3107ff4d5d7c8bedc6c55ec28a1b3bb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_2c760d4522.json
5b63c67349b669744665a5154bd60457d7bdc675fe2bad756c742b430444a8df  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_3441cd45b5.json
2c47b9a3e4f6b7c7eea2521425d24e21c693e58116831bcd091b14a8b039494e  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_4e82452b1a.json
4e63e3899df5ce109fccb9cf3aac3cf10c58bc4ea233628f38c492e5c00d39ad  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_5275c5a3cd.json
f34559853e3c0b625848bc1f4d24e8317957e589bf0fd579d3bc5e90602abae6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_6fb67a7106.json
1758b297e23aa051b032d9a67226dace8c6e84a438225839f6fc4cf9a2ddaf14  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_6fe6f637c2.json
662513cbdfb7929762821ff9ee15b3f0ceccbc4ff5f97db851a97ee9c95d9b37  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_9ecf9ebaec.json
0460bf028b1a4eaee925351408472653d70503965b48ccbd8a3a63b5342981ce  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_c3270727eb.json
8fb304cb92112008730f69f95cca381b6c08777a4ef81bd228141a018af8de14  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_de9a07d227.json
03a28e7042f34354b7efb09f752a371d943ce24aa4f183adf324e07c4ff3fc2f  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_e21abe7241.json
a1d68522c8f41292b7737af667186473db89d62f52e13376afb65f031d21faa6  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/exits/disp_e36c4ce7c7.json
bedf974774fbc382172ba895cf498a4be3d8bbc4ae1f97c7edb32a4c99398d2c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/merge-receipts.json
748ccb2cd7202eedb3754296bd52e54f351cc15f7597b76577e58f883176c397  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t1-a1.json
32119273d9cf1b7c4d49a68aab31d4ce8eb2eafce46a59f160df435c56af94a9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t2-a1.json
c9d0da4172044f42cc98eae73f5affebc34e8f839de608f72af0a0d117df9832  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t2-a2.json
bc35e5aeff3b0313f1a4d20ea3d253640ea17c41b26ec54f3786def4209855c9  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t3-a1.json
34bf28012baeaff36b86f1868f71541c0f5f5b53e5319eac455eb7f7f2c6a992  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t4-a1.json
ad7abf09286b708f4b864545392612b3ea8d50f0241527fa4129244ab2219b2b  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t5-a1.json
c913b1d807a8dc1a7ac252e0b630da7085538a37d66d0f6dea15725dc684105d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/oracle/t6-a1.json
34892d863eae32a5ebfee475aedbae51b7242f19112e0be59a0c75645989c3b7  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_0dc89cf95a.txt
b68779735f1f110e300a6705e51c6b3ff24c93d4f9bd70de333775a286883eca  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_14ef4f4e30.txt
9ff7b858b788181d0f752a79cfb7361167d709b431a1eb71027350cde7b34784  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_2c760d4522.txt
31612fa476549b760573a76c035b4e0a7176eca51937b75569ffeefa4f65803c  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_3441cd45b5.txt
d046b2b0fccbbca6050698a485e647fa01b9488a448f6a7966c000ff7e8dac50  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_5275c5a3cd.txt
7483053620c13e5776bddc0341810e52f2a7af444ac3c19a0f4bfac0b87a0f65  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_de9a07d227.txt
21ce6f95ff93d57899a3bb971c46ed2748a85513d20c5e1d5430fb3ae7e767a5  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/reviews/disp_e36c4ce7c7.txt
392f0b528f35dcbdc51d49e8665712533cbe4d188da5b78dbaf50046bc88a959  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/run-report.md
5dcc77d24098d3bd421c66860c8672d982751ab81bf7eb17f077bac9253c1fe4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/run.json
c217375b3bf4e443b991679a5e56c13ac835e859ac500a0beb09771040278a15  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/state.db
0e38de975688f15432991808caf92338fe0df94043bbee3047e770b6df2c7e81  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_0dc89cf95a.jsonl
9c45317fd7fee6ee815becd7d23e57362314f1ec28c6b3e64809f485889b4656  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_14ef4f4e30.jsonl
1d7e9b2fb0d6b129daa8d8e60005398e6406c573be23188e6b43eeb10a7fa9fb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_2517037ccc.jsonl
81ff5198942c8a64817dacb339ecb6a8c289f97987b4e2a9d8086c5cf686e59d  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_2c760d4522.jsonl
96be000a7a4db9ce4f3d3a04ea0a2cc818f2a8313627dc891826f0909e326d29  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_3441cd45b5.jsonl
400af723fc51d62236e56763216745149e5db17526eeeef3b7815ac7fb730052  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_4e82452b1a.jsonl
f0ed3e3b7d4f2eec4738b11a7d9e908fef30f898eb27c7eed82ee415ce834f7a  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_5275c5a3cd.jsonl
b69c46618d0d38fc6df92dcaf70dc64d67d6da3d94992be97367fc23ef308bb1  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_6fb67a7106.jsonl
60c29cee99bbc4d7dd360a7d8dac14229f3b8271666859048cc4fcf48ec21ccb  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_6fe6f637c2.jsonl
fb27340fcedcae30a464aaef19629466944ecf28b702d539f0f519c3a16bc301  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_9ecf9ebaec.jsonl
079ee60e89a67fff9cb496a8ebb41b36fa5dedc2d0563f8084888caafa6405b3  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_c3270727eb.jsonl
cf2c5f50c0a0126db9b68f1b48d236476d7e23a498a90639b702a79dc1f76fc8  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_de9a07d227.jsonl
b13b70bd43b752845ea029a6618fe3a4ec9ffc6b9dbcf1669078676b1b3d9587  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_e21abe7241.jsonl
a8182c525cc57df4c7756484bbee635d0eb0cd9e1f57e7b8aef6670aed75a952  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/streams/disp_e36c4ce7c7.jsonl
e193a1597731ef52a5b0924a35a01458c66e1e2f9711e68c511d4a262c31e6d4  docs/runs/2026-10-25-wip-curve-604-live/experiment/runs/wip2-b6r2-rep3/target.bundle
0a2e9a8b9656ab0f94ae2104dd07aa7ede81d155795fb9b55b432a178034106b  docs/runs/2026-10-25-wip-curve-604-live/manifest.json
446200e766f9450145219d62d5464eaaa39b06cec5a5270d1694662339a2de01  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T072848Z-wip_curve-a542b577.broker/spend.jsonl
a63b2096b1a9dd715d6a22b888269a2ca83fc4357624660520916c5b9544ea4e  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T072848Z-wip_curve-a542b577.json
7b316f67bd93e496a432e0abae4ad4063c6b1508ff00400039af6421a4c00e95  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T072848Z-wip_curve-a542b577.log
b6a4f062d4fa4325ad3266fd6ad47e55a0481719a54d250ac555c372eb868108  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T073146Z-wip_curve-c221ea8d.broker/spend.jsonl
e3945ccae103b19cd323a973ed51fe5d8351591788744356a34dd53caa459357  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T073146Z-wip_curve-c221ea8d.json
657d0fd269a6dd942ab565e618eb6d050f09f776241e2cea4f80325162c9a337  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T073146Z-wip_curve-c221ea8d.log
c6652b3ea41896cb5fb0b2e2c8811d164056cfaeddcd0abad7e25bd220ea078f  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T074401Z-wip_curve-07078de6.broker/spend.jsonl
5761142350231954c2bd45072de3067c4c369077fe628fd5a48c2db92f95dd5c  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T074401Z-wip_curve-07078de6.json
5084a88269b4c18ef6344880529133c882e5c19e26deb2ecdfcf18ba6cb34355  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T074401Z-wip_curve-07078de6.log
32990c494d0ea4c4762118c5decbb6557c254cf1c257d3727a68a15aeb244367  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T075525Z-wip_curve-fc57ffd4.broker/spend.jsonl
9f02c8d8fc2ccff531a17d25a82b3bcab76310784978ec855d44f8890aba8600  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T075525Z-wip_curve-fc57ffd4.json
c88162ecdb473ad4c4073c5cf4540b9357a3a4c19da0ac05b1f27df25978390f  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T075525Z-wip_curve-fc57ffd4.log
92ace35ea72e0c4522ef6b235c440f14921019af12e0a7439371a07165aa973f  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T080715Z-wip_curve-0d07f54b.broker/spend.jsonl
f362bdde7d6579fbff00e9017d829ce9ce925f1a5dbb97032794aadf32c1a8a9  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T080715Z-wip_curve-0d07f54b.json
0cb3ff1c3b1e6bd7a2fb169aab0cc9fd35b883db126b5fc2dcb72539a78181fd  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T080715Z-wip_curve-0d07f54b.log
131eeee4dd379bf09d4e2d88d81febca726848f8b6ef3ef2100c7f23239e7c00  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T081856Z-wip_curve-360ffaaa.broker/spend.jsonl
a615d37fb34e2bb053c70b6604601a3f7cdee3117d6616ced007eb587a8cddc4  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T081856Z-wip_curve-360ffaaa.json
08e7ed0eacceab18337efa29428b08751494a7bbaec33f5c0479945cb0f02923  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T081856Z-wip_curve-360ffaaa.log
d27992c42db49be0ce0073ecc5c15b68ac2dd15e6981017f6ad9e002f2f924ee  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T083056Z-wip_curve-3a6f8a93.broker/spend.jsonl
364d4cbdbbe0c8e70b4870917844e96231ec370ebb81478544a5ce70c8000a5a  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T083056Z-wip_curve-3a6f8a93.json
03a5ab48a3df778f147809907e4f3c377e0f034552b4bf53171b351b7ff2cdb5  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T083056Z-wip_curve-3a6f8a93.log
c21d1190d81885e41877e3f2790d39ed1332194117064d9d4cacbd8abb7b3e29  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T084455Z-wip_curve-7ae9926e.broker/spend.jsonl
7183f8c73bafb2e573df85ece82b7c6482ee2562a982538151e82f9297ae2009  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T084455Z-wip_curve-7ae9926e.json
d47a15e9f9f36175d766b7d42436900abd27d9d2929ef75adb8c08493b5922b6  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T084455Z-wip_curve-7ae9926e.log
36234ff310be491f99dba3dd8f0928573a2c75f747c0b763485289d19259d028  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T085634Z-wip_curve-c6389de8.broker/spend.jsonl
cb39a90e085a0f39b6d59c9b2bfc696bd492987405a0fa05e0a69108abddcd0a  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T085634Z-wip_curve-c6389de8.json
393be50efa626e5446d36436a9ea87fded8eaee7c26f148b5188aafbcf7bb2af  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T085634Z-wip_curve-c6389de8.log
cde66e9bd091a60e552ed8fd09c36ff0ba2180b1449f67d2d5c2543c76fad331  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T090825Z-wip_curve-fee81434.broker/spend.jsonl
bd1caa2aba3df0b25d91c2ea999a7ca63cab3573196db72b2ad5abc1b08875aa  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T090825Z-wip_curve-fee81434.json
d87aca83222e0eab4ec958c63715be5b27e0a92ec2c3916c4c62444b47efb0e6  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T090825Z-wip_curve-fee81434.log
19e39fb14e4209f901464ced62c3271894035ba495f27361fc40772ce6ad247a  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T091950Z-wip_curve-b318b0d9.broker/spend.jsonl
94e3eedfc94bcf87c18229b9588e8b390c95b1a74bf17845a1aed14ea0e2fffc  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T091950Z-wip_curve-b318b0d9.json
60150bf5b697e07b35d78d125cca28cf1cdccd660c1950b4ca91a7fc67786faf  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T091950Z-wip_curve-b318b0d9.log
066e5ed51d249bd9ce15ad11dbe9a6eaeb4d194dcef35c5a2cb249027ce9f9f8  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T093127Z-wip_curve-c40be662.broker/spend.jsonl
48116cefbe58deb451bba90ee14a983cb35604aae36347a74d74f94283f766ee  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T093127Z-wip_curve-c40be662.json
2939799888f8b31eecb785561ea9c185d3c5d7bea55a1e70042a4c42d9ec794e  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T093127Z-wip_curve-c40be662.log
9b30e165bdc7d41172d505780881a3f3ab0eb2a253adbf5a8c79bfabb6e5d981  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T094424Z-wip_curve-eace71ed.broker/spend.jsonl
f5a86ede73d6027eafc9d5aeed026eb35b24bde037c365610c2e49c35d21e889  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T094424Z-wip_curve-eace71ed.json
82ac6e9de9bdd39d97cf0683f309ff3c28a717a6ab6d6637f536495c3164f2c1  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T094424Z-wip_curve-eace71ed.log
c868a1adc70fc9f40745bc099a347575170c5a4c1b4ce4ad1caa89ec2f399a2c  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T094506Z-wip_curve-b861c2aa.broker/spend.jsonl
a318f6f3845b477a9aacaf850da8c441077d0601427d6295fe3ffa348e8008c6  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T094506Z-wip_curve-b861c2aa.json
be478bfa00eb5bfcc3d396140a7c16aae299a3dd6753f09bc294a653c76acfab  docs/runs/2026-10-25-wip-curve-604-live/receipts/20261025T094506Z-wip_curve-b861c2aa.log
973ba590e9c428b472290ec50cb5d39f2dadf6e6a09c09f67cdae35af5e5ea35  docs/runs/2026-10-25-wip-curve-604-live/receipts/chain.log
27b8b18c31f4e199696cca5f23d905ee0d78214c2bc4effeefaedbc3254201ab  docs/runs/2026-10-25-wip-curve-604-live/rederive.py
b7b1a481b939559f213aac7e5b81c268fa70b3e973f7ef01790fdc487dd4c687  docs/runs/2026-10-25-wip-curve-604-live/rederive.txt
a3321ae7437da210e8f74b34d7b3661f71b1c772a8eef2bbfc52379aa3a27c65  docs/runs/2026-10-25-wip-curve-604-live/report/report.json
83271b1d47be141aa7a402a2074106d75d8a970b6ed18ef2a47727bdc7967e91  docs/runs/2026-10-25-wip-curve-604-live/report/report.md
152623fb941f511ab4b52fb0eeb2c14ba64eb0a45a321e39c5cfe0336e4c444c  docs/runs/2026-10-25-wip-curve-604-live/verifier.txt
858fd2cb3dc33e8bdad9150fce3673d3139c7af518836a052de5b5d75c4854b8  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/budget.jsonl
d015b259fabfff9c109bb2a2ebac9eb03e863e2d736357099a4c692308065a0d  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/calls.json
9112fbc5dbd74184b0ad575822459615d2ca54ab0a23e4f5375ca24b215b13b4  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/events.jsonl
d07609e08a5f1a463f82de40af68e46097ad4b3ebab6de45443ef9a839093d8d  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_0fecdc5c5c.json
5149540232548ba8dfea29ce4512d4576ff99e05489f9f5ce64d9d3f4b8bff32  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_1868e24d9a.json
f6e8c5eb83c9f2fe4f381080fe2f664f16738eadcecae46f9e1ab29abf743baa  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_3ebc265106.json
b072065bcc40de0006e0c0379bf77dc31e5f0d0c351232fd2532cb8aec3c1229  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_45458a13cb.json
85aaa3a88cfc2b0dca90ef3ff01fe56ceea823eb0ec1674e04b664477489f13b  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_52ccadc506.json
593dd226d90c8fe7bc8e7278482a3a447b02119a10071133e8fe484a37779e5f  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_59b96195cc.json
1e5c03e01682129be1ec34dbaa29a137a732dc867913287acc629fe739ab5263  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_63027640fe.json
df7afad639ee125f46946635297d5eda3d985cd0e6810d60fd7b4b4580cb211a  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_88f9b63134.json
dbb04597dd4155fea40306643ceae787a3298625e25264a9cc6e961e3414ad3a  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_9b6e5af1bc.json
e3477611bd7a4f8fe5ae1b421b9d44fd0006a96113bf3d209745e9eca9bc8f9a  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_af32c89184.json
c335c34f3910a1e05376ec36f37bc125b54b8361b890ca8e91a653bee0462f6e  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_bb028041c3.json
775bdc6246af664b5e54bc15f937f9e72ab15840de6d19decebc34a19ed3118d  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/exits/disp_e6ee682b3c.json
987fa3b76101ea0acea694c4190bcf821bcc71ff9d54cf33900a6bda7faa95c9  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/merge-receipts.json
ccf88960f67c19b87993e561179e0a1feed8e83f76e966bd807303f78906a77d  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/oracle/t1-a1.json
0088b528cddd5533f33c1dd6ba0139cb95a9eeb6b01149cef068d4dd95d73019  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/oracle/t2-a1.json
d4634da48da18621273673ac9cf314261ad150df87ef2a472409f7a46ade5a86  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/oracle/t3-a1.json
be144165c9a349907a61ba78447973b603eb1a13c9b4b872a00a4a4a3fccc6ca  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/oracle/t4-a1.json
036e6eb740b1796405f7124661354e8ac68dcf7d3a7b99f1933cce59cf6aa0d0  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/oracle/t5-a1.json
ec38db0ef07f15869ec35f985e48b8223c6d512b898196d76a0769f505558682  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/oracle/t6-a1.json
de38c44e179ca1644b000772cba4b4cf546a834f17c679fafbc7a7aef895591a  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/reviews/disp_1868e24d9a.txt
70e12ef435ef0ab64861681fd9f7bbe3c24bec03861ad2ef358652b97693c40e  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/reviews/disp_3ebc265106.txt
5c3321d82a43f69c16b60c7d9d0b84845b08db8e866fe70017269511494fe108  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/reviews/disp_9b6e5af1bc.txt
019960a4ba38a4c2fc55f5dd263a4634387006da104347035e4636da2d5d1238  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/reviews/disp_af32c89184.txt
551a0adebe397c964d7d13b66cdf426d93134d47842d19c39b6d832d645d893f  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/reviews/disp_bb028041c3.txt
1cde219b63eb9b1f76e0da9bb7bc86abdd19f99759aa0cc18b2c2825ed8b6886  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/reviews/disp_e6ee682b3c.txt
c4769dc24663be24b8faab3ea146a6ccef2bc1631a134c01491c3074b132a4b0  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/run-report.md
6564067362a4474dd4694a52be8c6bc0c30b145b4b0846f1a9253b0e9215500f  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/run.json
3b843e0e9f208ebf518156dfa955319272d99a66384ce5990663d2672aa3c940  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/state.db
51f246b5ba6e628712d7199f4eab69ccd027f81710bf99951943895f1dbc9b2c  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_0fecdc5c5c.jsonl
3f1f38dd82dabcb34884741b5b1eeef039857c67aed27ef23454ffcbcdecb45f  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_1868e24d9a.jsonl
2a2cae95c9e6f012344439ddf9d98aeaf9f54c02ac87dc1097ba4ca7f62a2b82  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_3ebc265106.jsonl
15dd8ad25d6bb6f8e2b1398e98f6d4cdf43c185400a90e51a3d1f10b7e1c17f0  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_45458a13cb.jsonl
a48ab019ab93ce93c2b87a4525453967473681b7a22c1c5b3258bbb0873c5a65  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_52ccadc506.jsonl
d42290b816df74fa1a76d860f0b6053364c87769aa96b2b9c884cf0a59cad986  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_59b96195cc.jsonl
b0e3175413771b59aaa6ce656e84a0d5294f5bf25ceb2dde8f0f18f1ce96bbd0  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_63027640fe.jsonl
5e1dfcd72108eef654732f5dde4fa02a0214f4f7c06d426617244ed39e900472  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_88f9b63134.jsonl
7151055faf6f9d5105530751135e7e6f04237f7b47894b91af47104562ed3746  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_9b6e5af1bc.jsonl
1ad7be11f9ae50b78313fe22b03818e7da01a91f3c129118742ef426ba68aea6  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_af32c89184.jsonl
99d2b410b860ecd649020d12ad37ac3fcd6183a3e3bb19dc02b447b897f2d7f2  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_bb028041c3.jsonl
4c2bdd72a4023092582f254eba8fb857a89a5e750bd0e2ce48dd01699e6add46  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/streams/disp_e6ee682b3c.jsonl
f8d78a1f05f07df4a8c4b889337f3cebd54ba22d5a356d40daa8a669b2351d28  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b1r1-rep1/target.bundle
d3bdbf54019e20aae11df0fcc86a1e931c674ab1f0000dcba4484a9b85b0d4a0  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/calls.json
1c8f0cb03b95a758a8333a001dc638fb0e307433ec62d49a645db1914f99d12d  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/events.jsonl
d111bd9fafea6831d4dee7d9471b350810c9bdc89e6c5fa6e0dbe1a2cdae5bb1  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/merge-receipts.json
c2de0c71133ade441a05dd86293d2575929fe2cfc06b78fe1c49338dd33ee4a5  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/run-report.md
ece2ee1714615118a29797883c00ea283de05a39fe01fb0759058ab50d8a0437  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/run.json
1f190f282d6d98474cfa5688eb4397af0b2f048b2e037aa7eca678679d2a98de  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/state.db
b47c2251c00b09ba95e4153d87977fa4cc41020c9edbe91d0a4de37582d72dca  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_036e45e607.jsonl
967363d766c65409ded658db0c342cc3459d7d43d751b9da5b67ec05a47e23b0  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_2831cc8199.jsonl
392e301e95d4f099b25977dd31b9bede6d14fbdcf88f2537029a7453e696a2bf  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_2e34d04c77.jsonl
ef3cf1730ab0b76c958e1b47ba69c1d2ebf5997dd4cd8fa93c6776dadbad4ff5  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_374b3d8b97.jsonl
2d4940fc223d0f8ef2667db3d3c62785a53d8f9186f13f5b50d521c955f08d19  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_5abf8d452b.jsonl
9f57c008eb92cb89f6315e36b99b3f7ad87425024fe7e8ae0efdc98945278819  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_5e5aee6235.jsonl
62bfa201f5b4c8735fd2213b31d7974e7c5b0d95dbdaba0f2594b12b0e649148  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_70f1c15848.jsonl
52dd4b7c3e99a4da6d7fc5f0e21e90e52a4cfdf7784106df3b887c4dca2917a7  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_8289db0142.jsonl
3344e43fdae8e79fd33da7da2c981a63bf36e12a1b26b401404d21b752f13ceb  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_8dccd777ec.jsonl
85d7e142bb592729658e51179e0f95a4f40029b03e406e70d1184450914c6e20  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_8fffa2255b.jsonl
dee90e2b814e61ecdd21327b544ea7b58d2ee10f9183ba7882baefea302080e9  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_9047a5a576.jsonl
8db5a124d6b47e2cdae84abd35421e9568e0a143dbe11ab1d9b015f00147e593  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_9587c85798.jsonl
569f1933dacdcf8e1490f0463c7ca44c1faa46133e5b9d1cfa23dfeedfe6d034  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_b5c344bf30.jsonl
72f699d96a8b8569f42349bdafbd26d864db90a367aa0d44421470576a94d933  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_be3b75ede9.jsonl
0977f1ae6b2c0ba7679775d46b4e3692f6016dcf28fc0f248de378a06dd32387  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_c172e03395.jsonl
682846392e9e8c3e032a5dc836c9cb7fb0f8bad23c6cfc67859d787373921ca6  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_d0ccbd6c30.jsonl
0936887a3e79e6e31c424808d22e1ab83dccbcf72d44b8ea2c8bf2132124ab8d  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_e2a0384c4c.jsonl
5fb0f307e1f396012b70796230feedb6ab06119982974bce727b288a7c871af1  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/streams/disp_f4f52bee35.jsonl
b102e1bbad7b6fdc10d0d009cc2bc1e35b917dfabff48e4a3fe34879ff7440d9  docs/runs/2026-10-25-wip-curve-604-live/version-1/experiment/runs/wip1-b3r1-rep1/target.bundle
996e4f41725ffee3bf06d5178d0d4ec935fd609e1d01b8c45e817d3181dfdf78  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T053322Z-wip_curve-350fbc0e.broker/spend.jsonl
28ceb0bcd2f5fc3a058a6b97893448d872b9374c6a81dc58750ce826c23272f2  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T053322Z-wip_curve-350fbc0e.json
861e58d16f1f6b61e9ef9dbd3db97891439c52d30470382c3584e9864c9ef39c  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T053322Z-wip_curve-350fbc0e.log
6b8f8f772eff6c32140b0248a39c2de8d8fb94ae4ca5a91737dda1f8ee256725  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T053822Z-wip_curve-456aaa8f.broker/spend.jsonl
1ea990a3ced41f1474438de139a92327d8df4c5525e899f75ad935bcadce8714  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T053822Z-wip_curve-456aaa8f.json
0dae8106c4fd8380ecf14fc0efb5b079ac07e67277e0187f6e79f6dd34dc2a40  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T053822Z-wip_curve-456aaa8f.log
3a0f122e945bfe3f3f118578ba8492051166d98dce0f7fbae589f61eebd84529  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T054651Z-wip_curve-99eecc14.broker/spend.jsonl
c050b6d967b72d30156bb8cd03b371afdfe6d0cea0d4915d40bace5d685ba41c  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T054651Z-wip_curve-99eecc14.json
6411cde4c1781f1da42283f6253e9d492bd0a536bed8cd0f46bf06648d8d1dfb  docs/runs/2026-10-25-wip-curve-604-live/version-1/receipts/20261025T054651Z-wip_curve-99eecc14.log
```
