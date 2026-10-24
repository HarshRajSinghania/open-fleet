# First-run contract fr-2420f5

Frozen by first_run.py before dispatch. Reviewed change: `f83ada1d56098ff7875f988efd6fe2cbdc9a5227..223b6eeef8b1a9343f49e16b1a18de71bc20f42b`.

- FR-1: the worker receives this unit's frozen spec (FR-NONCE:4709eae151992bcc) through the posix route.
- FR-2: the worker's report opens with `FIRST-RUN-REPORT FR-NONCE:4709eae151992bcc 223b6eeef8b1a9343f49e16b1a18de71bc20f42b`.
- FR-3: the report is bound to a commit the coordinator reads from git and verify.py re-derives.
- FR-4: the report quotes the read receipt that ends `.first-run/fr-2420f5/change.diff` and names every changed path.
