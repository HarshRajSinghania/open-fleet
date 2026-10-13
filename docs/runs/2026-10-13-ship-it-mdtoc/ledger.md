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
| task_11560fce010c | F0 foundation | t | n/a | n/a | t | t | t | lit | | head 02f1258; review PASS task_7d2ad49a1f14 (reviews/f0.md); verify OK executed-NC (manifest-f0.json); merged 03e13d38 ancestry-verified |
| task_2e1867b1d215 | S1 scan+slug (AC-2,3) | t | n/a | n/a | t | t | t | lit | | head af83a56 after fix round task_70d29afa81a2; reviews s1.md FAIL → s1-r2.md PASS (reviews/s1-record.md); verify OK executed-NC (manifest-s1.json); merged 4e1ad707 ancestry-verified |
| task_a485af881dfc | S2 update+modes (AC-1,4,5,6) | t | n/a | n/a | t | t | t | lit | | head a960241 after fix round task_68f8e06228eb; reviews s2.md PASS+2 MEDIUM (fenced + duplicated markers, dispositioned fix-now) → s2-r2.md PASS (reviews/s2-record.md; inline-code-span marker LOW deferred, fails safe); verify OK executed-NC (manifest-s2.json); merged fedebc75 ancestry-verified |
| pending | S3 multi-file+errors (AC-7,9) | f | n/a | n/a | f | f | f | lit | | |
