- **The living docs were audited claim by claim against the code and brought back in line.**
  Each fix rests on the code line it cites; historical records are untouched. The entry points no
  longer name an `OPEN_FLEET_HARNESS` variable (a worker's harness is the `[agent]` argument of
  `spawn_worker.sh`, its profile `PROFILE=ro|rw|danger`), the README's sample transcript prints
  what `preflight.py` and `verify.py` really print, and the FAQ says which missions still use Orca
  off it. Nine mission contract cards were re-rendered to their SKILL.md gates and phases, and the
  `offload-it`, `field-test-it`, `pin-it` and `map-it` compatibility fields corrected. One real
  bug: `reshape-it` ranked churn with `git log --since=90d`, which git silently ignores, so it
  counted all history; it now uses `--since=90.days.ago`. The runtime policies, the runtime
  scripts reference, the verify gate, runtimes, certification, concepts, evals, bench and
  governance docs had their flags, exit codes, env aliases, source ranges, counts and pins
  corrected. Comments and help text in ten runtime scripts now say what the code does, as do two
  printed messages (`floor_guard.py`'s base-ref error names all five refs it tries, and
  `verify.py`'s class-downgrade NOTE no longer says tests are exempt); no behavior changed.
