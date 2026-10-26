- **The Orca ro lane starts a native Claude Code install, and the ro/claude cell is witnessed**
  (#680). Orca proves an agent present by its pane title or its foreground process name, but a
  native install runs as `versions/<version>` and an idle Claude sets no title, so
  `dispatch --inject` answered `no_agent_detected` for a live claude pane (Orca 1.4.229 to
  1.4.240): the ro lane could not start a worker at all on such a host. For the ro claude row only,
  `spawn_worker.sh` now confirms the pane first: Orca's spawn record names it `claude`, and its
  screen shows Claude's prompt in plan mode. It then delivers the preamble of a dispatch without
  `--inject` by `terminal send`, Orca's own nextStep, and proves the turn start from that receipt.
  Any other screen still refuses with exit 2 and nothing is sent. The
  [2026-10-26 witness](../docs/runs/2026-10-26-review-it-orca-ro-680.md) ran the current row this
  way on Orca 1.4.239 with Claude Code 2.1.304: the plan was approved in the pane, and Write and
  Edit stayed out of the toolset.
