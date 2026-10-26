- **The certification tests' "moved pin" no longer hard-codes the next Orca release** (found by
  the #705 survey of tests that pin literal current state). `TestPinRefreshInvalidatesCells` moved
  the pin to the literal `v1.4.240`, the next upstream release, so the re-pin to v1.4.240 would
  have turned those mutations into no-ops and failed the stale-pin test in that PR. Each moved
  `version`, `live_receipts.version` and `certified_against` value is now derived from
  `runtime/pins.json` (its last number bumped), so it always differs from the current pin. No
  assertion line changed.
