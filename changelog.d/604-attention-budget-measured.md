- **The attention budget's mutation-wave WIP caps are MEASURED, and kept** (#604).
  `runtime/attention-budget.md` now records #604's live result: 12 protocol runs at four
  mutation-wave settings ([report](../docs/runs/2026-10-25-wip-curve-604-live.md)) measured
  verified-CLOSED throughput and kept the caps. The report-only and planning caps, which no run
  measured, stay ASSERTED. The policy grows by 11 bytes, within every mission's activation-load
  budget. #606's registration pins are refreshed to match (`ablation.py prereg --refresh`) after
  #606's run was bound, and the registration names the version that ran at `c220067e9c`; the
  bound run re-derives from its own commit, so the refresh changes nothing it checks.
  `docs/adversarial-evals.md` now says why the trajectory suite's `live_cases` rows still read
  UNRUN, beside the two bound live reports.
