# First-run contract fr-925ea2

Frozen by first_run.py before dispatch. Reviewed change: `4d4aa92ce453a15073ce8772cdffb27292a2dd52..070ed9dc4aeadb40924cbd932cbb5ce1a279a96c`.

- FR-1: the worker receives this unit's frozen spec (FR-NONCE:b5f9e23aab4908f7) through the posix route.
- FR-2: the worker's report opens with `FIRST-RUN-REPORT FR-NONCE:b5f9e23aab4908f7 070ed9dc4aeadb40924cbd932cbb5ce1a279a96c`.
- FR-3: the report is bound to a commit the coordinator reads from git and verify.py re-derives.
- FR-4: the report quotes the read receipt that ends `.first-run/fr-925ea2/change.diff` and names every changed path.
