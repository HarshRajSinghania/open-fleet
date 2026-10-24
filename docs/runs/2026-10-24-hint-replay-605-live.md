# Run report — #605 live hint replay (hints off / unchecked / checked), 2026-10-24

RUN: mission=hint-replay tier=doctrine-only inventory_at=0faf0e5cfd2c588c9a0c1ca4f4f128cd0776d8f5 manifest=docs/runs/2026-10-24-hint-replay-605-live/manifest.json verifier=RED

This is an experiment run, not a catalog mission run. `mission=hint-replay` names the runner
(`scripts/hint_replay.py`), and `tier=doctrine-only` because the run advances no mission's proof
tier. The header exists so that `runtime/scripts/run_report.py` binds the evidence below to a
commit. The verifier outcome is recorded as it came out: RED, for the reason given under
[Evidence binding](#evidence-binding).

| Field | Value |
|---|---|
| Question | #605's live arm: do episodic hints change REPEATED task failures? Three arms: hints off, unchecked (historical mode, no provenance checks), and checked (provenance checks against the live checkout). |
| Runner | `scripts/hint_replay.py --live` at origin/main `85daf6d0cf` (#657 merged). The coordinator exported it as a frozen checkout and ran it with [`bin/run-605.sh`](2026-10-24-hint-replay-605-live/bin/run-605.sh) (sha256 `8e59ecac088918b37ffb682e57ccc48a3d270ee018606f17e9600e795589c146`). |
| Command | `hint_replay.py --live --tier live --model claude-opus-5-5 --agent-cmd "claude -p --model claude-opus-5-5 --output-format json --permission-mode acceptEdits '--allowedTools=Read,Edit,Write,MultiEdit,Glob,Grep,Bash(python3 -m unittest:*)'" --budget-usd 40 --per-call-usd 2 --agent-limit-flag=--max-budget-usd --max-runs 18 --attempts 3` |
| Design | 2 `live_task` scenarios (`pitfall-rounding`, `stale-advice-trap`) × 3 arms × 3 attempts = 18 calls. Each call ran in a fresh fixture repository, followed by the scenario's oracle. The corpus is `tests/fixtures/hint-replay.json` (sha256 `962fb3281f466177340e38ec870d275ce34c57c697ade412dcc36c9ee6a4ecb3`), unchanged here. |
| Worker | `claude-opus-5-5` (every call's `modelUsage` names it), run through a pinned Claude Code 2.1.304 behind the isolation wrapper [`bin/claude`](2026-10-24-hint-replay-605-live/bin/claude) (sha256 `e2c35ae7b1fef3a58ff3595233c048d6cef65305496ef68de4783a368ea07302`). The wrapper gives the worker an empty HOME and `CLAUDE_CONFIG_DIR` and an allow-listed environment. It adds `--setting-sources project,local`, `--strict-mcp-config`, `--disable-slash-commands` and `--no-session-persistence`, and sets `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, so no credential is visible to the agent's shell. |
| Spend guard | The owner-authorised USD 40 cap and a USD 2 reservation per call. Every call is handed `--max-budget-usd 1.60`. Ledger: [`results.spend.jsonl`](2026-10-24-hint-replay-605-live/results.spend.jsonl). |
| Billing | The owner's subscription token. Every `total_cost_usd` is therefore NOTIONAL (what the API would have charged), not money spent. |
| Human gate | The owner authorised the USD 40 cap for #605's live arm, as relayed in the coordinator's brief of 2026-10-24. |

## Result

| arm | runs | passed | repeated failures | cost USD (sum) | cost USD (mean) | turns | mean s | mean output tokens |
|---|---|---|---|---|---|---|---|---|
| off | 6 | 6 | 0 | 0.486662 | 0.081110 | 5, 5, 4, 4, 4, 4 | 10.0 | 694 |
| unchecked | 6 | 6 | 0 | 0.372020 | 0.062003 | 5, 5, 4, 4, 4, 4 | 10.0 | 728 |
| checked | 6 | 6 | 0 | 0.365500 | 0.060917 | 5, 5, 4, 4, 4, 4 | 9.2 | 701 |

- All 18 calls were measured and settled. Spend was USD 1.224182 of the USD 40 cap.
- `complete` is true and `stopped` is null ([`results.json`](2026-10-24-hint-replay-605-live/results.json), [`run.log`](2026-10-24-hint-replay-605-live/run.log)).
- Every figure in this report re-derives from the retained bytes with [`rederive.py`](2026-10-24-hint-replay-605-live/rederive.py): 102 checks, 0 failures ([`rederive.txt`](2026-10-24-hint-replay-605-live/rederive.txt)). It also rejects a tampered copy: an invented repeated failure or a stale note marked shown each fail it.

## What this shows, and what it does not

**A ceiling, null result.** Every arm passed every run, so the workers never produced the
repeated failure the arms are meant to separate. On this corpus, hints neither helped nor hurt.
With no failure in any arm, the comparison has no power to tell the arms apart. The run is not
evidence that hints help, nor that hints are harmless in general.

What each scenario shows:

- **`pitfall-rounding`.** The useful note says float `round()` is half-even and to use `Decimal`
  with `ROUND_HALF_UP`. The unchecked and checked packets carried it (UNKNOWN and CURRENT); the
  off packet carried nothing. The off workers avoided the pitfall unaided: all three converted
  through `Decimal(str(amount))` with `ROUND_HALF_UP` and explained why. The hint had nothing to
  fix.
- **`stale-advice-trap`.** The stale note points at `legacy_parse` in `src/legacy.py`. The
  unchecked packets showed it (UNKNOWN: no live source); the checked packets suppressed it
  (STALE, nothing shown). All three unchecked workers read the note and dismissed it themselves,
  because `src/legacy.py` no longer exists in the live checkout. The note's own claim made it easy
  to check, so this scenario cannot distinguish freshness labelling from a worker's own
  verification.

**What this run does not show.** It does not show whether freshness labels are correct, or
whether poisoned notes are withheld. Those are pinned by the deterministic replay,
`python3 scripts/hint_replay.py --check`, not by this run. That replay covers 27 scenarios: the
checked arm labels every hint correctly (accuracy 1.0), shows 0 stale notes and propagates 0
poisoned ones, while the unchecked arm leaks 20 of 20 stale notes and 2 of 2 poisoned ones. This
run measured one thing, the end-to-end effect on a worker's repeated failures, and found no
failure to measure.

**Cost and turns.** Turns are identical across the arms: 5, 5, 4 on `pitfall-rounding` and
4, 4, 4 on `stale-advice-trap`, in every arm. The off arm's higher cost comes from one call. The
run's very first call, `pitfall-rounding.off.a1` (USD 0.202602), created the prompt cache: 22,026
cache-creation tokens, against 3,837 to 4,660 for every other call. Excluding it, off averages
USD 0.056812 per call, unchecked 0.062003 and checked 0.060917; the hint lines themselves add
about half a cent per call. None of these differences is a measured effect at six runs per arm.

#605's fifth acceptance criterion asks the replay corpus to measure the effect of hints on and
off on repeated task failures. This run is that measurement, and its value is null at a ceiling.
It does not support expanding memory volume on the strength of an effect.

## What a stronger follow-up would need

- **Real repeated failures.** Scenarios where workers fail repeatedly without hints: a pitfall a
  capable model does not avoid unaided, with its base rate established on the off arm first.
- **Stale advice that isn't obviously stale.** Advice whose staleness the checkout does not
  reveal, for example an advised symbol that still exists but is now wrong in a way only the
  tests expose.
- **Power.** Enough attempts per arm to separate the arms at that base rate, and a decision rule
  registered before the run.

No issue was filed for this, per the coordinator's instruction.

## Observations and deviations (recorded, not hidden)

- **Permission mode forced to default.** Every call's stderr is the single line
  `⚠ Permission mode forced to default — CLAUDE_CODE_SUBPROCESS_ENV_SCRUB is set
  (allowed_non_write_users hardening). Declare allowedTools explicitly, or set
  CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0 to opt out.` The isolation setting overrode
  `--permission-mode acceptEdits`, and the explicit `--allowedTools` list then carried the run.
  Every call reports 0 permission denials, and every worker edited its file and ran the tests.
- **Notional cost.** The USD figures are Claude Code's `total_cost_usd`: what the API would have
  charged, not money spent. The guard enforced against them exactly as it would against real
  charges.
- **The contract is not a pre-registration.**
  [`contract.json`](2026-10-24-hint-replay-605-live/contract.json) was written at binding time
  from the coordinator's brief. The design it checks the run against, the live command and the
  spend guard, was fixed before the run in `docs/runtime-scripts.md` at `85daf6d0cf`.
- **Absolute paths kept.** `results.json` and `run.log` carry the owner's local paths
  (`/Users/ravindra/of-live/…` and the frozen checkout's scratch path). They are kept verbatim.

## Retention and secret check

Retained under [`2026-10-24-hint-replay-605-live/`](2026-10-24-hint-replay-605-live/),
byte-identical to `~/of-live/runs/605-live/`:

- `results.json` and the spend ledger `results.spend.jsonl`;
- for each of the 18 calls, under `results.calls/20261024T070734-5839-f8f2c0d1/`, its
  `packet.md`, `agent.stdout`, `agent.stderr` and `oracle.txt`;
- `run.log`;
- the run script and the wrapper under `bin/`, retained as plain, non-executable files.

Before copying, every file was searched for `sk-ant`, `oauth`, `ghp_`, `github_pat_`, AWS access
keys, private-key blocks, Slack tokens, `password=`, `secret=`, `bearer`, `api_key`/`api-key`,
`CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY`. The run outputs and the run script had no
hit. The wrapper had three hits, all naming the token's file (`~/of-live/oauth-token`) or the
variable it fills (`CLAUDE_CODE_OAUTH_TOKEN`). The token value is read at run time and appears
nowhere. `verify.py`'s redaction leg (built-in patterns plus gitleaks) found nothing in the
manifest or any artifact. **Nothing was redacted.**

## Evidence binding

Commits on `claude/r12-live-605-report`, forked from origin/main `85daf6d0cf`:

| Commit | What it adds |
|---|---|
| `9b814e7eee` | The retained evidence (77 files), `contract.json`, `rederive.py`, and `manifest.json` pinning 79 files by sha256. This is the unit's `head_sha`. |
| `6240133480` | The manifest bound to `head_sha`, with the contract digest, the re-derivation record and `rederive.txt`. |
| `0faf0e5cfd` | The verifier record and `verifier.txt`. This is `inventory_at`. |

Re-derivation, recorded through `evidence-run.py` on `9b814e7eee`'s tree (`b57f03eb12ce…`), exit 0:

`python3 runtime/scripts/evidence-run.py --label rederive --manifest docs/runs/2026-10-24-hint-replay-605-live/manifest.json --artifact docs/runs/2026-10-24-hint-replay-605-live/rederive.txt -- python3 docs/runs/2026-10-24-hint-replay-605-live/rederive.py`

Verifier, recorded through `evidence-run.py` on `6240133480`'s tree (`ef145e282079…`), exit 2
(RED), output in [`verifier.txt`](2026-10-24-hint-replay-605-live/verifier.txt):

`python3 runtime/scripts/evidence-run.py --label verifier --manifest docs/runs/2026-10-24-hint-replay-605-live/manifest.json --artifact docs/runs/2026-10-24-hint-replay-605-live/verifier.txt -- python3 runtime/scripts/verify.py --manifest docs/runs/2026-10-24-hint-replay-605-live/manifest.json --contract-source docs/runs/2026-10-24-hint-replay-605-live/contract.json@9b814e7eee035fffcac0b969c7eb08012847722e --contract-digest sha256:18c981a462540e089ba0d5eaf3ac66f575401a1bf65965db1d0d884e222533eb --unit-class report-only`

Exactly one invariant failed: `report-only unit changed code [...] and carries no signed dispatch
record`. A report-only unit is unsupervised unless a coordinator signs its class. This range adds
non-prose files: the JSON evidence, the wrapper, the run script and the re-derivation script. With
no signed dispatch record, the verifier will not accept the downgrade from `mutation`. Every other
leg passed:

- the contract's criteria (LV-1 to LV-6) are complete;
- the content-bound command ledger holds the exit-0 re-derivation on `head_sha`'s tree;
- every artifact matches its sha256 pin;
- the source-binding negative control holds;
- the credential scan found nothing.

A GREEN needs the coordinator to sign a dispatch record for this unit (`unit_class=report-only`)
and `verify.py` to be re-run with `--dispatch-record`/`--dispatch-pubkey`. That was not done here.
`run_report.py` binds a recorded RED, and the RED stays as recorded. `--base` was not given, so
the ancestry leg was skipped before merge, as its note says.

Re-check:

- `python3 docs/runs/2026-10-24-hint-replay-605-live/rederive.py` re-derives every figure (0 failures).
- `python3 runtime/scripts/run_report.py docs/runs/2026-10-24-hint-replay-605-live.md --mission hint-replay --tier doctrine-only` binds the report.
- `python3 runtime/scripts/inventory.py check docs/runs/2026-10-24-hint-replay-605-live.md` re-hashes the inventory below.

## Gates

Catalog-side, run on the landing branch: `python3 scripts/validate.py`, ruff, the floor guard,
`check_trailers`, `gen-badges --check`, `python3 scripts/hint_replay.py --check`, the
`run_report.py` binding above, `inventory.py check`, and `tests.test_docs_navigation`. Results
are recorded in the landing PR.

## Run-close integrity inventory (sha256)

```
e2c35ae7b1fef3a58ff3595233c048d6cef65305496ef68de4783a368ea07302  docs/runs/2026-10-24-hint-replay-605-live/bin/claude
8e59ecac088918b37ffb682e57ccc48a3d270ee018606f17e9600e795589c146  docs/runs/2026-10-24-hint-replay-605-live/bin/run-605.sh
18c981a462540e089ba0d5eaf3ac66f575401a1bf65965db1d0d884e222533eb  docs/runs/2026-10-24-hint-replay-605-live/contract.json
222aa2c3aa2c8912ec1624c153b8a978704a5b958178e0323dc5378fb204d85d  docs/runs/2026-10-24-hint-replay-605-live/manifest.json
845c01a4c21e4d2c7c9ac399c471f652ed2fcf0a4acd1c9a544bf4b2c586a98f  docs/runs/2026-10-24-hint-replay-605-live/rederive.py
7b243f682b962d262157975df0ad5036f2a3808de29c50bbc343b89e316c55ef  docs/runs/2026-10-24-hint-replay-605-live/rederive.txt
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a1/agent.stderr
8335686ea6058a055ef8627ab845e23329c8fd2ee68413c499bf70c91e7560d0  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a1/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a1/oracle.txt
3ef5ce41702db2fe5a0819b8059f38336edb717ceaba6a43bbe6f1e68b5eac89  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a1/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a2/agent.stderr
75b41249307f9e566a68c344c91da039a27cd6fc49de82e6b5e70fe512d71df4  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a2/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a2/oracle.txt
3ef5ce41702db2fe5a0819b8059f38336edb717ceaba6a43bbe6f1e68b5eac89  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a2/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a3/agent.stderr
0ef295d3d9380205ef9e4cd62ba3efb33eca7c7428f0844e67d5fa6cade2aa84  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a3/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a3/oracle.txt
3ef5ce41702db2fe5a0819b8059f38336edb717ceaba6a43bbe6f1e68b5eac89  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.checked.a3/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a1/agent.stderr
59109319e522c57a949f80451af1e03f3012356d8e4d90dbe4a1721dc823c617  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a1/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a1/oracle.txt
e3abe201d5eabb9cd544701326b79fdebd6ff3c65558b44f79b15cf564743a97  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a1/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a2/agent.stderr
be37c788496feab690318b7a4c1424997571e2b1aeb115c0f4a186db54d19ac4  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a2/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a2/oracle.txt
e3abe201d5eabb9cd544701326b79fdebd6ff3c65558b44f79b15cf564743a97  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a2/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a3/agent.stderr
e878530442bb4103d071312c3943a42234d58b4b79da341d9f93b0627521d391  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a3/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a3/oracle.txt
e3abe201d5eabb9cd544701326b79fdebd6ff3c65558b44f79b15cf564743a97  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.off.a3/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a1/agent.stderr
d1e56d60a6fba78d71b73d5011c912e1854787e3d155fe3721690336ca4e0e94  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a1/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a1/oracle.txt
173892b91d43435fc0c30bc1dbc20f6d5e559ab2511c1e8a2bd6322b478ca3cb  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a1/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a2/agent.stderr
257fc15dcb030b83c952ddf52007a8246a8ea831f9cd6e5aa241b80b845384d3  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a2/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a2/oracle.txt
173892b91d43435fc0c30bc1dbc20f6d5e559ab2511c1e8a2bd6322b478ca3cb  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a2/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a3/agent.stderr
8a0c8fc13280c4d5ef93a7c206235d1c41287b22d283522e635c2eacbf9b32ca  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a3/agent.stdout
2a50b4749107e50e3993c9a59df48e8d8cebd81e26a286e83bb83d7fe81b2d90  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a3/oracle.txt
173892b91d43435fc0c30bc1dbc20f6d5e559ab2511c1e8a2bd6322b478ca3cb  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/pitfall-rounding.unchecked.a3/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a1/agent.stderr
aff872057415d1327c733b273943eef1d3d6e1c07db08624a792738edd62e4e7  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a1/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a1/oracle.txt
24bb2dbc5d969f18f0fe6c596ed98dbf0a34a605c786aa8d42de8c4f4562c785  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a1/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a2/agent.stderr
9055fad6e1ab720bac66458192ab929627ba765f4ac8051c0a890377d8779d4f  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a2/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a2/oracle.txt
24bb2dbc5d969f18f0fe6c596ed98dbf0a34a605c786aa8d42de8c4f4562c785  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a2/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a3/agent.stderr
34fb5b30601e1da715d398ebddd8d65aa6f210339c6d5ea00e6ee5f9f4709268  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a3/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a3/oracle.txt
24bb2dbc5d969f18f0fe6c596ed98dbf0a34a605c786aa8d42de8c4f4562c785  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.checked.a3/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a1/agent.stderr
e78e05a6fff1f1f8918b6c0e5e2e81666cc812239a89fb2ddd3ec2eced939208  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a1/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a1/oracle.txt
966fe086407cb11867910c29555109525ade61b8673302015995c43ec29fb0fc  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a1/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a2/agent.stderr
dd44fd1be97eecafb20b6ad83b3fa6493a8f5d04d1f403d468c9332df2fa8da9  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a2/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a2/oracle.txt
966fe086407cb11867910c29555109525ade61b8673302015995c43ec29fb0fc  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a2/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a3/agent.stderr
7b0b464fcea1896e9578c8e7a5315e057f881e85047412eece0a243419d2ba5d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a3/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a3/oracle.txt
966fe086407cb11867910c29555109525ade61b8673302015995c43ec29fb0fc  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.off.a3/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a1/agent.stderr
a2fc07c1aeb6ccc41e928eb797e03a5d549ae119d8bab551a30c7585ee781d04  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a1/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a1/oracle.txt
c250e1f86a8f277d56c2cccd1154aff3b3614e49ec79ac5a98f01d41c0800df8  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a1/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a2/agent.stderr
f68b3829f41a37ccbb3b75dd6a5e58241fabc2cfc67ce847a408d0e175e1fdc7  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a2/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a2/oracle.txt
c250e1f86a8f277d56c2cccd1154aff3b3614e49ec79ac5a98f01d41c0800df8  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a2/packet.md
de8f61180dfd6b00ad02c9688d8fbe00b27cad193f4531c9e2017688bbeca57d  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a3/agent.stderr
58a9c030878cde66f15ff14dc0d8b41b4dcc7322d35ad0995b7b793d18c9a4c9  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a3/agent.stdout
445221b98f22d14309aaea4fee1a9f41c9659ced4c922d71fbc0dcbbde571045  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a3/oracle.txt
c250e1f86a8f277d56c2cccd1154aff3b3614e49ec79ac5a98f01d41c0800df8  docs/runs/2026-10-24-hint-replay-605-live/results.calls/20261024T070734-5839-f8f2c0d1/stale-advice-trap.unchecked.a3/packet.md
8681cc2a98e7ed7b74396fefb388ad21df4becc466bae9fa9df49b7d72efe834  docs/runs/2026-10-24-hint-replay-605-live/results.json
796f4b06723a0a04acdd61fff7037f04869fb3063032edeac568a834ce081ce1  docs/runs/2026-10-24-hint-replay-605-live/results.spend.jsonl
449d390f02a7743f8c9a6012567bc73f0af023f7e053c8ca5f039cf1a17fdbab  docs/runs/2026-10-24-hint-replay-605-live/run.log
ef2d781c74b73def57183f216e0082d4e8990974a052f4b8b315f302bf986a94  docs/runs/2026-10-24-hint-replay-605-live/verifier.txt
```
