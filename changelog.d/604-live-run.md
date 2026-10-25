- **#604's WIP curve is measured, and its report binds** (#604). Version 2 of the pre-registered
  experiment ran all 12 scheduled runs in the container live harness, with `claude-sonnet-5-5` on
  Claude Code 2.1.304. All 12 were complete and protocol-compliant. Throughput rose from one
  builder to three; six builders with one reviewer did no better than three; and rework and
  conflicts rose with WIP. The decision rule recommends **keep**: no setting above the cap
  separated in throughput. [`runtime/attention-budget.md`](../runtime/attention-budget.md)
  records the caps as measured once, and the report is
  [docs/runs/2026-10-25-wip-curve-604-live.md](../docs/runs/2026-10-25-wip-curve-604-live.md).
