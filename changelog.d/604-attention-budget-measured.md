- **The attention budget's WIP caps are MEASURED, and kept** (#604). `runtime/attention-budget.md`
  now records #604's live result: 12 protocol runs at four WIP settings
  ([report](../docs/runs/2026-10-25-wip-curve-604-live.md)) measured verified-CLOSED throughput and
  kept the current caps. The edit shrinks the policy, so no mission's activation load grows.
  #606's registration pins are refreshed to match (`ablation.py prereg --refresh`), after #606's run
  was bound; the bound run reads its own commit's registration, so the refresh changes nothing it
  checks. `docs/adversarial-evals.md` now says why the trajectory suite's `live_cases` rows still
  read UNRUN, beside the two bound live reports.
