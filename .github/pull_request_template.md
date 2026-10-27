## Problem

<!-- What is wrong or missing, with the file:line or run that shows it. -->

## Solution

<!-- What this change does about it, and why this way over the alternatives. If a mission's
contract changed, show its convergence proof before and after. -->

## Checks

- [ ] `python3 scripts/validate.py` ends with "three-layer separation holds; evals valid."
- [ ] `python3 -m unittest discover -s tests` is green (about an hour serially; it builds real git repos)
- [ ] Docs that state a number now read it from a generator or a test binds it (CONTRIBUTING.md)
- [ ] No `Co-authored-by` or tool-attribution trailers in the commits (CONTRIBUTING.md)
- [ ] Bookkeeping is one file per change: a `changelog.d/<slug>.md` entry, a weight file per new
      test module, a `docs/runs/index/` row per new run; no edit to `CHANGELOG.md`, the tests
      badge or the run-index table (CONTRIBUTING.md)
