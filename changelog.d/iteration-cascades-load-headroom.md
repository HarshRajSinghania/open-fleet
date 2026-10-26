- **Every mission's activation-load budget carries 2.5% declared headroom, and the cap moves to
  35,000** ([budgets](../scripts/mission-load-budgets.json)). Budgets were the measured load
  rounded up to 500 under a 34,000 cap, so `ship-it` sat 7 tokens under its budget and
  `oss-contribute` 8: one sentence added to any doc either loads failed `validate.py` in an
  unrelated PR. A budget is now the load plus `headroom` (0.025), rounded up to a step of 100,
  which gives every mission 2.5 to 2.9%; growth past it still fails, and a shrink of more than
  `max_slack` (now 500) beyond that line must be banked. The cap is the heaviest load plus the
  same headroom; ARCHITECTURE.md's "never raised" sentence is replaced with the reason it was.
