# Ledger — ship-it mdtoc external run (#515)

RUN: run_4e3ed8344520 · COORDINATOR: term_de3f1b7c-4e1f-4b8f-93e0-6f63e5044871 · BASE: fleet/ship-mdtoc-20261013 · FORK_POINT: 0b9f660d93e64cf57e8245b0f1eb6eb0010ae158 · T0: 2026-10-13 · SOURCE: ravidsrk/mdtoc SPEC.md @0b9f660d (maintainer-approved freeze; human gate #1) · WIP: builders=2 reviewers=2
PHASE: BUILT (046d1f8d0ff63b7193bc06e0c373ba60d9e06849 pushed to origin/fleet/ship-mdtoc-20261013)

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
| task_bfa7e23e0f20 | S3 multi-file+errors (AC-7,9) | t | n/a | n/a | t | t | t | lit | | head 04a9e8f; review PASS (reviews/s3.md, LOW-only: duplicate-FILE + style carried as known limits); verify OK executed-NC (manifest-s3.json, contract amended @27cc97e for denominator extractor); merged c574a547 ancestry-verified |
| task_204bc820b2ec | S4 slug hardening (AC-2) | t | n/a | n/a | t | t | t | lit | | head 4aa7755 after fix round task_479d83732bdf; reviews s4.md PASS+1 MEDIUM (autolinks eaten as tags, dispositioned fix-now) → s4-r2.md PASS no findings (reviews/s4-record.md); verify OK executed-NC (manifest-s4.json); merged c9a6f683 ancestry-verified |
| task_de5d11f52acc | S5 EOL+BOM seams (AC-1,6) | t | n/a | n/a | t | t | t | lit | | head 47ef84f; origin integrated FAIL F1-F4; review PASS (reviews/s5.md, LOW test-gaps folded into integrated battery); verify OK executed-NC (manifest-s5.json); merged 046d1f8d ancestry-verified |
| task_1dbe4c4cb564 | Integrated acceptance @c9a6f683 | f | n/a | n/a | t | f | t | lit | | FAIL (reviews/integrated.md): CR-only idempotence + BOM placement; closed by S5 |
| task_fe34045197bf | Integrated acceptance @046d1f8d | t | n/a | n/a | t | t | t | lit | | PASS (reviews/integrated-r2.md, reviews/integrated-record.md); verify OK executed-NC (manifest-integrated.json); BASE pushed 046d1f8d — terminal BUILT |
