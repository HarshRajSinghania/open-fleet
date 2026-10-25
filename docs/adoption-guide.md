# Adopting open-fleet: Greenfield vs. Brownfield Rollout Guide

[Documentation Hub](README.md) · [Getting Started](getting-started.md) · [Mission Catalog](missions/README.md) · [Prompt Recipes](recipes.md) · [Ecosystem Comparison](comparison.md)

<!-- Note: Human operator rollout guide. Not a discoverable skill; stays out of agent activation context. -->

Rolling out autonomous engineering fleets across a team or codebase looks different depending on whether you are starting from a clean slate (**Greenfield**) or introducing multi-worker automation into an existing production repository (**Brownfield**). This guide gives you a structured, low-risk rollout path for both.

---

## Greenfield vs. Brownfield at a glance

| Signal | Greenfield codebase | Brownfield (existing / legacy) codebase |
|---|---|---|
| **Baseline test suite** | Small, fast, deterministic from Day 0 | Large, uneven coverage, often contains intermittent flakes |
| **Architecture & boundaries** | Unsettled; decisions still cheap to change | Established conventions, coupled modules, implicit invariants |
| **CI quality bar** | Needs to be wired up front (`floor-it`) | Partially wired; tightening gates immediately would break active PRs |
| **Negative-control reliability** | High — reverting a new change reliably turns its test `RED` | Fragile until flakes and untestable seams are isolated |
| **Blast-radius tolerance** | High on an integration branch | Low — requires read-only trust building before autonomous write waves |
| **Recommended entry point** | [`map-it`](missions/map-it.md) → [`ship-it`](missions/ship-it.md) → [`floor-it`](missions/floor-it.md) | [`review-it`](missions/review-it.md) → [`deflake-it`](missions/deflake-it.md) → [`prove-it`](missions/prove-it.md) → [`clean-sweep`](missions/clean-sweep.md) |

---

## Path A: Greenfield rollout (new services & products)

On a greenfield repository, your goal is to establish a **verifiable oracle** and a **frozen quality floor** early so every subsequent feature run has deterministic back pressure.

### Day 0 setup

1. **Shape the architecture before writing code (`map-it`):** If the domain boundaries, storage engine, or external contracts are still fluid, run [`map-it`](missions/map-it.md) first. It interviews you one decision at a time, records architectural forks in `docs/DECISIONS.md`, and produces a frozen execution map and task DAG.
2. **Ship the walking skeleton (`ship-it`):** Hand the frozen spec or first vertical slice to [`ship-it`](missions/ship-it.md) with `"Stop at the promotion PR"`. Verify that your baseline test command runs cleanly at Phase 0 and that the first slice lands with a working negative control.
3. **Lock the CI quality bar (`floor-it`):** Before the codebase grows past its first few modules, run [`floor-it`](missions/floor-it.md) to wire one deterministic tool per quality dimension (lint, typecheck, secret scan, test runner) and prove each gate turns `RED` on an injected violation.

### Greenfield growth triggers

Bring in specialized missions as your service crosses real operational thresholds rather than all at once:

| When this trigger occurs… | Bring in… | Why now |
|---|---|---|
| First authentication, billing, or untrusted-input surface lands | **[`harden-it`](missions/harden-it.md)** | Closes the threat model (`audit → exploit → fix → re-attack`) while the attack surface is still small |
| First persistent schema change after initial production deploy | **[`migrate-it`](missions/migrate-it.md)** | Enforces `EXPAND → DUAL-WRITE → BACKFILL → SWITCH READS → ZERO READERS → RETIRE-WRITES → ZERO-WRITERS → CONTRACT` |
| Service prepares for external traffic or on-call rotation | **[`oncall-it`](missions/oncall-it.md)** | Verifies telemetry and runbooks with a source-blind failure diagnosis oracle |
| Public UI flows stabilize | **[`access-it`](missions/access-it.md)** & **[`speed-it`](missions/speed-it.md)** | Locks WCAG 2.2 AA conformance and Core Web Vitals / latency budgets |
| Public SDK, CLI, or HTTP API is exposed to external callers | **[`document-it`](missions/document-it.md)** | Binds every reference and guide claim to a `file:symbol` with rename-to-`RED` controls |
| Enterprise customer or regulator requests compliance evidence | **[`attest-it`](missions/attest-it.md)** | Re-derives SOC 2, NIST SSDF, or EU AI Act conformance from SHA-bound artifacts |

---

## Path B: Brownfield 4-phase rollout (existing & legacy codebases)

> [!IMPORTANT]
> **Do not start a brownfield rollout by unleashing `ship-it` or `clean-sweep` on a repository with a broken or flaky test suite.** Every code-mutating mission in `open-fleet` relies on the baseline test suite and negative-control replay (`--execute-nc`) as its completion oracle. If your suite fails randomly, workers will stall at Phase 0 or fail negative-control verification.

Adopt `open-fleet` on an existing repository in four incremental phases:

```text
PHASE 1 (Week 1)          PHASE 2 (Weeks 2–3)        PHASE 3 (Weeks 3–6)         PHASE 4 (Ongoing)
Zero Production Changes ──▶ Stabilize the Oracle   ──▶ Bounded Debt & Security ──▶ Full Autonomous Delivery
review-it / map-it (ro)   deflake-it / prove-it /    clean-sweep / harden-it /   ship-it / reshape-it /
root-cause (throwaway rw) floor-it                   modernize-it / absorb-it    migrate-it / chains
```

### Phase 1 (Week 1): Diagnostic & non-landing missions (zero production changes)

Start with missions that never land changes on `BASE` or `main`, while understanding each mission's worker permission profile:

- **[`review-it`](missions/review-it.md) on live pull requests (`PROFILE=ro`):** Run `review-it` alongside human code review on 3–5 open PRs. All reviewer workers run strictly read-only (`PROFILE=ro`). Observe how the coordinator freezes acceptance criteria, dispatches parallel reviewers, filters out unquoted speculation, and binds the `GO` / `NO-GO` verdict to `reviewed_sha`.
- **[`map-it`](missions/map-it.md) on an upcoming epic (`PROFILE=ro`):** Use `map-it`'s read-only exploration workers (`PROFILE=ro`) to chart a cross-cutting refactor or feature against the existing codebase without modifying production files.
- **[`root-cause`](missions/root-cause.md) on a hard production bug (`PROFILE=rw` in throwaway worktrees):** Point `root-cause` at an intermittent incident. Note that `root-cause` investigation workers run with **`PROFILE=rw` inside isolated throwaway worktrees** so they can write reproduction scripts, add temporary diagnostic probes, and execute tests to falsify rival hypotheses — but `root-cause` has no fix or merge authority, so no code changes ever land on `BASE` or `main`.

**Exit criterion for Phase 1:** Your team is comfortable reading the run ledger, answering one-way gates, and inspecting SHA-bound manifests.

### Phase 2 (Weeks 2–3): Stabilize the test oracle

Before running multi-worker mutation waves, make your repository's test oracle trustworthy:

1. **Kill intermittent flakes (`deflake-it`):** If CI fails intermittently, run [`deflake-it`](missions/deflake-it.md) on the offending test directory to reach a verified consecutive-green streak (`STABLE` or `STABLE-WITH-QUARANTINE`).
2. **Cover the highest-risk untested paths (`prove-it`):** Pick 1–2 critical modules (e.g., auth, billing, permissions) that lack strong assertions and run [`prove-it`](missions/prove-it.md). Every new test is audited against injected code mutations so weak "happy-path-only" assertions are rejected.
3. **Establish a non-regressing CI floor (`floor-it`):** Run [`floor-it`](missions/floor-it.md) to lock in the checks that now pass and guard them against future bar-lowering diffs.

**Exit criterion for Phase 2:** The baseline test suite runs green reliably at Phase 0, and reverting a behavior change in your target module reliably turns a test `RED`.

### Phase 3 (Weeks 3–6): Two-speed adoption & bounded backlog drains

Introduce code-mutating fleets on **bounded, well-scoped targets** while keeping human promotion gates (`BASE` → default branch) in place:

- **Drain a scoped audit or issue label (`clean-sweep`):** Instead of pointing [`clean-sweep`](missions/clean-sweep.md) at a 500-issue tracker, scope your first run to a specific label, directory, or audit document (5–15 items). Every fix lands as an isolated PR against `BASE` with a pre-fix `RED` / post-fix `GREEN` test receipt.
- **Upgrade dependencies safely (`modernize-it`):** Run [`modernize-it`](missions/modernize-it.md) to clear reachable security advisories and stale lockfile entries while keeping CI green at every step.
- **Close a subsystem threat model (`harden-it`):** Run [`harden-it`](missions/harden-it.md) on a critical service boundary (`src/auth/`, `src/webhooks/`).
- **Drain community or renovate PRs (`absorb-it`):** Use [`absorb-it`](missions/absorb-it.md) to triage, test, and merge or park an inbound PR queue.

### Phase 4 (Ongoing): Full autonomous delivery, refactoring & mission chains

Once the oracle is stable and your team trusts the `BASE` → promotion PR workflow:

- **Deepen legacy god modules (`reshape-it`):** Run [`reshape-it`](missions/reshape-it.md) on high-churn modules; it pins a characterization test and mutation baseline *before* extracting narrower interfaces.
- **Ship end-to-end features (`ship-it`):** Run [`ship-it`](missions/ship-it.md) from spec freeze through multi-slice implementation, build-blind review, negative-control verification, and promotion PR.
- **Run sequential mission chains:** Combine outcomes for major releases (for example, `harden-it` → `prove-it` → `ship-it` per [`runtime/mission-chaining.md`](../runtime/mission-chaining.md)).

---

## Lifecycle convergence: Greenfield vs. Brownfield

| Engineering need | Greenfield approach | Brownfield approach |
|---|---|---|
| **Architecture & planning** | `map-it` shapes greenfield domain boundaries from scratch | `map-it` maps existing coupling, blast radius, and seam boundaries before change |
| **Test verification** | `ship-it` writes TDD tests per vertical slice from Day 0 | `deflake-it` + `prove-it` stabilize and mutation-audit legacy paths first |
| **Code review** | `review-it` checks spec fidelity and repo standards on every PR | `review-it` provides immediate read-only value on Day 1 with zero repo setup |
| **Refactoring** | Handled inline within small `ship-it` slices | Dedicated `reshape-it` run pins a characterization net before restructuring god files |
| **Schema changes** | Simple migrations before initial launch; `migrate-it` post-launch | `migrate-it` multi-deploy expand/backfill/switch/retire-writes/contract with row-parity probes |

---

## Common adoption anti-patterns to avoid

| Anti-pattern | What goes wrong | Do this instead |
|---|---|---|
| **Stacking plugin + symlink + settings snippet** | Duplicate skill listings and `verify-gate.sh` firing twice per turn | Pick **one** install path per host ([Install — Do not stack](install.md#pick-one-install-path-per-host-do-not-stack)) |
| **Pointing `clean-sweep` at an unbounded 200-issue backlog on Day 1** | Long runtime, high token spend, and noisy triage on stale tickets | Start with a 5–10 item label or a single audit file; expand after reviewing the first promotion PR |
| **Running mutating missions on top of a red baseline** | Phase 0 preflight halts immediately (by design) | Run `deflake-it` or a scoped `clean-sweep` on the broken baseline tests first |
| **Installing via `cp -r` or `npx skills add` from `main`** | Relative links to `../../playbooks/` and `../../runtime/` break | Use `sh scripts/install.sh` (symlinks), the Claude Code plugin, or the published `dist` branch |
| **Starting a mission mid-conversation in a cluttered session** | Coordinator instructions compete with prior chat history and hit early compaction | Always start a mission in a **fresh coding-agent session** |
