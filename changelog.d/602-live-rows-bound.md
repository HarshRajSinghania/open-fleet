- **#602's live rows carry the bound live run** (#602). The six `live_cases` rows in
  `evals/adversarial-trajectories.json` leave UNRUN for the run #685 bound
  ([report](../docs/runs/2026-10-25-trajectories-602-adapters.md)): each attack case 5/5 PASS on
  `claude-sonnet-5-5` with Claude Code 2.1.304, 5 repeats, in the container live harness, under the
  arm's USD 45 cap. `tests/test_trajectory_evals.py` now pins that bound state, and still checks
  that a row left UNRUN publishes as UNRUN; the one-way waiver this needed (#691) retires here. The
  published table in `docs/adversarial-evals.md` is regenerated, and #606's registration pins are
  refreshed for the fixture's new bytes.
