- **#606's live paired runner hands `--model` to the agent and the grader, and checks the model
  each cell ran** (#606). `ablation.py run --tier live` recorded `--model` in its results but never
  passed it on, so Claude Code ran its own default. On 2026-10-25 a launch recorded
  `claude-sonnet-5-5` while the spend broker billed all 38 calls as `claude-opus-5-5`. Now
  `--model` is appended to `--harness-cmd` and the grader command unless they already name it, and
  a command naming another model is refused before anything runs. The recorded `agent_cmd` and
  `grader_cmd` show it. Each cell records the model its agent's `system/init` line names. In the
  live tier, a completed run naming none, or another, is a failed cell, and the run stops there
  (`MODEL_MISMATCH`), so nothing more is paid for on a model the results may not name. The
  results add `models_observed`, as #602's live runner does.
