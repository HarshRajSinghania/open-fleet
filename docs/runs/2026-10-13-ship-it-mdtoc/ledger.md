# Ledger — ship-it mdtoc external run (#515)

RUN: run_4e3ed8344520 · COORDINATOR: term_de3f1b7c-4e1f-4b8f-93e0-6f63e5044871 · BASE: fleet/ship-mdtoc-20261013 · FORK_POINT: 0b9f660d93e64cf57e8245b0f1eb6eb0010ae158 · T0: 2026-10-13 · SOURCE: ravidsrk/mdtoc SPEC.md @0b9f660d (maintainer-approved freeze; human gate #1) · WIP: builders=2 reviewers=2
PHASE: BUILDING

Substrate: Linux witness VM (Ubuntu 24.04.5 arm64, orca-ide 1.4.224 serve,
Claude Code 2.1.296 workers). Lane: offline (no gh in VM) — local merges to
BASE, PR_OPEN=n/a per slice, `no-gh: local-merge`; BASE pushed from the host
at close. Target repo at /Users/ravindra/projects/mdtoc (shared mount).

Spawn lane deviations (recorded at F0): the supervised worker-start lane is
unusable on this host twice over — Claude's bypass-permissions first-acceptance
timed out agent readiness (accepted host-wide once), then READY spawns read
LAUNCHED_UNUSABLE because the host's agentDefaultArgs lack
`--dangerously-skip-permissions`. Builders therefore run the custom-argv lane
with WORKER_CMD='claude --dangerously-skip-permissions' (verbatim spawn_worker's
verified claude:rw flag) into coordinator-created worktrees; folder trust was
pre-seeded in the VM's ~/.claude.json for the worktree paths. Failed attempts
ctx_4684039b34d8 (readiness) and ctx_5c107c24e37a (LAUNCHED_UNUSABLE, stopped)
are settled; the first worker-start worktree is orphaned in the VM and cleaned
at teardown.

| task_id | unit | BUILD_DONE | PR_OPEN | BOT | REVIEWED | MERGED | WT_CLEAN | lighting | park | evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| task_11560fce010c | F0 foundation | f | n/a | n/a | f | f | f | lit | | |
| pending | S1 scan+slug (AC-2,3) | f | n/a | n/a | f | f | f | lit | | |
| pending | S2 update+modes (AC-1,4,5,6p) | f | n/a | n/a | f | f | f | lit | | |
| pending | S3 multi-file+errors (AC-6e,7) | f | n/a | n/a | f | f | f | lit | | |
