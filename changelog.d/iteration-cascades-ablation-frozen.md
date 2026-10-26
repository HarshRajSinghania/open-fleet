- **#606's ablation registration is frozen at its run commit** (#606). The registration's
  `bound_run` block names the commit (`c220067e9c`) and the run's own results, and
  `ablation.py prereg` checks the pins there, with that commit's own check on that commit's own
  tree. An edit to `ARCHITECTURE.md`, a runtime policy or the #602 suite no longer makes the
  registration stale (five `--refresh` commits followed the run in one day), `--refresh` and the
  live tier refuse a bound registration, and any other edit to it fails. The pins are back to the
  ones that ran, and the run's results must be the bytes its report's inventory pins.
  #604's registration needed no change: it pins only its own task set and seed commit.
