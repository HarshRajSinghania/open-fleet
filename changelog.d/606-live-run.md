- **#606's live paired ablation ran, and its report binds: keep the current activation** (#606).
  The registered design ran once in the container live harness at origin/main `c220067e9c`: 4
  missions × 9 tasks × 5 repeats in both arms, 360 cells, `claude-sonnet-5-5` on Claude Code
  2.1.304. [docs/runs/2026-10-25-ablation-606-live.md](../docs/runs/2026-10-25-ablation-606-live.md)
  retains the results, both spend ledgers, the receipts and every cell's stream, recording and
  usage, and `run_report.py` binds it at `doctrine-only` with `verify.py` GREEN under a
  coordinator-signed dispatch record. The pre-registered rule returns SUCCESSFUL_REDUCTION for every
  mission, but that verdict cannot be acted on. Task success was 0 of 180 cells in each arm: the
  registered agent command (`--permission-mode acceptEdits`) refused every test run and every commit,
  so no worker could verify or land its work. And every attempt to read the catalog holding the
  reduced arm's deferred documents was refused, so the reduced arm never received them. The run
  shows no scope or approval violation in either arm and 42–62% fewer input tokens in the reduced
  arm, and recommends keeping the current activation; the report gives a follow-up design. A first
  launch that ran `claude-opus-5-5` while recording `claude-sonnet-5-5` was stopped and is kept as
  superseded. Spend was USD 63.19 notional, settled by the broker, of the USD 750 authorised.
