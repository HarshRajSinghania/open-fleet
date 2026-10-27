# Threat model — tree-wide code security audit, 2026-10-27

RUN: run_secaudit_20261027 · COORDINATOR: opencode session (Ravindra Kumar) ·
BASE: review/2026-10-27-security-audit · FORK_POINT: 15e03dfedbf5 (origin/main at T0) ·
T0: 2026-10-27 · SOURCE: this page · WIP: auditors=6 verifiers=3

Derived from `runtime/threat-model.md` (the standing four boundaries). That page bounds the
SYSTEM; this page bounds the CODE this run audits. Where they differ, this page is narrower and
names the code path that carries the boundary.

## Trust assumptions (inherited, unchanged)

- A worker, and anything it executes, is **untrusted**.
- Everything a worker or a third party can write is **untrusted input**: branch names, PR bodies
  and titles, commit messages, transcript JSONL, ledger and manifest files, evidence manifests,
  `.git/config` and `.git/info/*`, filenames, env values, `git`/`gh` output, CI event payloads,
  fetched tarballs.
- The coordinator-side checks are a **control plane**: `verify.py`, `verify-gate.sh`,
  `gate-batch.py`, `dispatch-sign.py`, `run_report.py`, `bind_check.py`, `inventory.py`,
  `floor_guard.py`. Their job is to hold when everything above is hostile.
- Missions, playbooks and runtime policies are trusted; they change only by reviewed PR.

## What is in scope

All first-party executable code at BASE: `runtime/scripts/**`, `scripts/**`, `hooks/**`,
`.github/workflows/**`, `install.sh`, the Python vendored dependency tree under
`scripts/vendor/`, and the data parsers those files run over (manifests, ledgers, transcripts,
release JSON, corpus files). Also the docs contract they encode where the code trusts a doc.

## What is out of scope

Model-provider security, GitHub itself, the host kernel, and `daemon/` (Orca — vendored pin).
Third-party binaries (`git`, `gh`, `gitleaks`, `ruff`) except where we invoke them unsafely.

## Boundaries and their code carriers

### B1 — Sandbox: worker code must only touch its worktree

| Carrier | Where | Threat |
|---|---|---|
| `runtime/scripts/deny-hook.sh` | 5,182 lines, PreToolUse | peeler/segment gap, a HIGH-tier shape that gets ALLOW, fail-open on a missing parser |
| `runtime/scripts/spawn_worker.sh` | profile opt-ins | env opt-in bypass, profile downgrade |
| `runtime/scripts/containment.py`, `worktree_ops.py`, `wtree.sh`, `worker_ops.py` | worktree lifecycle | path traversal in unit names, `git worktree` following a planted config |
| `runtime/scripts/gitexec.py`, `scripts/_trajectories.py`, `runtime/scripts/hint_provenance.py` | hardened git env | a repo-declared filter/hook/fsmonitor/textconv that still runs |
| destructive paths (`rm -rf`, `git clean`, teardown) | several | target not validated after symlink resolution; check/use race |

### B2 — Network and egress

| Carrier | Where | Threat |
|---|---|---|
| `runtime/scripts/egress.py` | receipt chain | content leaked into receipts, hash-chain forgery, path escape of the receipt log |
| `scripts/live_broker.py`, `scripts/live_container.py`, `scripts/_trajectory_live.py` | live API calls | key handling, proxy env, response trust |
| `scripts/external-ci-monitor.py` | polling | unbounded/credentialed requests, parsed output trusted |
| `install.sh`, `scripts/install.sh`, `bundle.py`, `publish-dist.yml` | download paths | `curl \| sh` without pinning, unpinned tarball, symlink unpack |

### B3 — Supply chain and integrity

| Carrier | Where | Threat |
|---|---|---|
| `runtime/scripts/verify.py`, `verify-gate.sh`, `gate-batch.py`, `_verify_sig.py`, `ed25519.py`, `dispatch-sign.py` | verification authority | fail-open, signature bypass, replayed or stale envelope, TOCTOU between check and use |
| `runtime/scripts/run_report.py`, `inventory.py`, `bind_check.py`, `scripts/bind_check.py` | evidence binding | hash re-derivation skipped, retention receipt trusted from the graded party |
| `runtime/scripts/pin_review.py`, `validate.py`, `quarantine_check.py` | pin and quarantine | regex/parser bypass, path outside the pin list |
| `scripts/vendor/**`, `runtime/pins.json` | vendored code | drifted copy, import shadowing |

### B4 — Identity and gate authority

| Carrier | Where | Threat |
|---|---|---|
| `runtime/scripts/decisions.py`, `gate-batch.py` | gate answers | answer substituted/downgraded, one-way door defaulted on timeout |
| `runtime/scripts/*_sign*`, `_verify_sig.py` | signing | key path from an env var a worker sets, unverified key material |
| `runtime/scripts/search_sessions.py`, `scripts/hint_replay.py`, `_trajectories.py` | transcript ingestion | a transcript record steering a replay/write, path escape from a recorded path |

### B5 — Untrusted text into the model

| Carrier | Where | Threat |
|---|---|---|
| `runtime/scripts/guard_text.py` | the fence | fence break-out, marker collision, size/truncation trick |
| `scripts/eval.py`, `evals/injection-drills.json`, `scripts/deny_hook_corpus.py` | drill suite | a drill that asserts the wrong polarity |
| issue/PR/log readers (`task_ops.py`, `pm.py`, `events.py`, `merge_queue.py`) | ambient text | text rendered into a TASK or a verdict without a fence |

### B6 — CI and release pipeline

| Carrier | Where | Threat |
|---|---|---|
| `.github/workflows/*.yml` | all 13 | `pull_request_target` + checkout of PR head, `${{ }}` expression injection, over-broad `permissions`, secrets on a fork-triggered job, unpinned third-party action |
| `scripts/release_check.py`, `gen-badges.py`, `changelog.py`, `run_index.py` | release bookkeeping | generated file trusted back as input, version/tag confusion |
| `publish-dist.yml`, `release.yml`, `install.yml` | publication | artifact substitution, mutable tag |

## STRIDE axes carried into the audit waves

- **S**poofing — identity of a caller, a repo, a SHA, a signature, a key path (B3, B4).
- **T**ampering — evidence/manifests/transcripts/secrets rewritten between check and use (B3, B4).
- **R**epudiation — a gate/verdict/receipt with no binding to the SHA it claims (B2, B3).
- **I**nformation disclosure — secrets in logs/receipts/artifacts, over-broad checkout permissions (B2, B6).
- **D**enial of service — unbounded parsing, regex backtracking, a hook that hangs (B1, B5).
- **E**levation — shell injection through a path/branch/title, hook bypass, sandbox escape (B1, B5, B6).
- **LLM-specific** — injected instructions in scanned text reaching a TASK or a coordinator decision (B5).
- **Supply-chain** — unpinned action/tarball/vendor drift, filter or hook execution (B3).

## Acceptance bar

A finding is reportable with: the file:line, the untrusted input, a concrete step-by-step exploit
scenario, the resulting authority (what the attacker gains), and a severity (P0–P3). P0/P1 need a
PoC that can be executed, or a written demonstration when execution is impossible here.

Execution routing (before any run): static/read-only → `ro`; scratch-repo exploit → `rw` in
`/tmp/opencode`; networked or destructive → argued from code and PARKED with its blocker, never
run on the host.

## Anti-goals

- Not a re-audit of the h409 surface (verify/sign/gitleaks, CLEAN on 2026-09-21) unless a new
  channel into it appeared since; cite h409 and move on.
- Not a dependency-advisory sweep (that is `modernize-it`).
- Not a docs review; only where a doc is a trust input to code.
