# Frozen contract — review-it Linux witness run (#527)

Mission: review-it (report-only). Target: stablyai/orca PR #28206
"fix(worktrees): offer Force Delete when Git refuses a checkout with submodules"
by @Hotragn — a session-external author. Originating issue: stablyai/orca#28164.

Fixed point: reviewed head `6dcd957a65daf77fe49f15afbb998b262427224c`;
merge-base `cbeb53714640288d172e9d59c53c0e0bff85f6ba`; diff = 6 files, +91/-1.
Spec source (search order first hit): the originating issue, retained in
`spec-source.md` in this run directory; the PR description is the claim against it.

Substrate: the whole run executes on an Ubuntu host driven by `orca-ide`
(OrbStack machine `orca-linux-witness`, Ubuntu 24.04.5 LTS arm64, Orca 1.4.224),
workers are Claude Code agents in Orca terminals on that host, PROFILE=ro.

Criteria:

- RC-1: The fixed point above is pinned before dispatch and re-checked at
  verdict time; a moved head re-pins or voids the run.
- RC-2: All three acceptance axes (standards, spec, test-adequacy) report from
  isolated fresh workers, each recording a blind-fix expectation BEFORE opening
  the diff; no cross-axis rerank at aggregation.
- RC-3: Risk lenses are gated by `diff_scope.py --json --strict` output retained
  in this directory; every triggered lens runs or is a recorded gate-off.
  Security/privacy/data-migration are NEVER_GATE when signalled.
- RC-4: Every finding carries severity (Critical/Required/Nit/Optional/FYI),
  `path:line`, and its verbatim motivating line as it exists at the reviewed
  head; a finding whose quote does not re-read at that SHA is demoted to an
  appendix by the coordinator (source-binding negative control).
- RC-5: The verdict is GO iff zero Critical and zero Required findings survive
  the anti-false-positive gate; otherwise NO-GO. It binds to the reviewed SHA
  in the evidence manifest.
- RC-6: The run modifies no code anywhere: the target checkout is clean at
  close, workers run read-only, and the verdict is retained in this record
  only — nothing is posted to the upstream PR.
- RC-7: The record names the host distribution, the Orca version, and the
  resolved CLI name, with the `status --json` reachability line retained, so
  the Linux claim is checkable from the artifacts alone.
