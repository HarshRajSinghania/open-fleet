# Ecosystem Comparison & Upstream Pack Composition

[Documentation Hub](README.md) · [Concepts](concepts.md) · [Adoption Guide](adoption-guide.md) · [Architecture](../ARCHITECTURE.md) · [Multi-Runtime Guide](runtimes.md)

<!-- Note: Human architectural comparison guide. Not a discoverable skill; stays out of agent activation context. -->

Developers evaluating `open-fleet` often ask how it relates to single-session skill packs and workflow plugins such as **[mattpocock/skills](https://github.com/mattpocock/skills)**, **[garrytan/gstack](https://github.com/garrytan/gstack)**, **[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)**, **[obra/superpowers](https://github.com/obra/superpowers)**, and **[EveryInc/compound-engineering-plugin](https://github.com/EveryInc/compound-engineering-plugin)**.

**The short answer:** `open-fleet` is not a competing collection of leaf coding prompts. It is the **multi-worker autonomous fleet and independent verification layer above them** — composing proven worker techniques from `mattpocock/skills`, `garrytan/gstack`, and `addyosmani/agent-skills` while enforcing worktree isolation, one-pack-per-worker routing, one-way-door governance, and an off-worker SHA-bound completion verifier (`runtime/scripts/verify.py`).

---

## Side-by-side comparison

| Dimension | `open-fleet` | `mattpocock/skills` | `garrytan/gstack` | `addyosmani/agent-skills` | `obra/superpowers` & `EveryInc/ce-plugin` |
|---|---|---|---|---|---|
| **Primary unit** | **Outcome-named missions** (`ship-it`, `clean-sweep`, `harden-it`, `review-it`, …) | **Engineering disciplines** (`/grill-me`, `/tdd`, `/triage`, `/improve-codebase-architecture`) | **Sprint role skills & browser/QA binaries** (`/office-hours`, `/review`, `/qa`, `/ship`) | **Lifecycle slash commands & checklists** (`/spec`, `/plan`, `/build`, `/test`, `/review`, `/ship`) | **Iterative session workflows** (`brainstorming` → `writing-plans` → `subagent-driven-development`; `/ce-plan` → `/ce-work` → `/ce-compound`) |
| **Execution topology** | **Coordinator + disposable workers** in isolated git worktrees (via Orca, standalone `posix`, or 12 other RPI orchestrators) | Single-session interactive pair programming or subagent delegation | Single-session sprint stages with specialist review/QA passes | Single-session lifecycle commands with specialist personas | Single-session loop with subagent tasks and compounding repo memory |
| **Definition of done** | **Independent, SHA-bound evidence manifest** (`verify.py` checks frozen scope digest, `git merge-base --is-ancestor`, `reviewed_sha == head_sha`, and throwaway-worktree negative-control replay) | Passing test seam in the active TDD loop | Review readiness dashboard, QA pass, and ship policy receipts | Per-skill verification checklists and review gates | Subagent review loop + test execution |
| **Cross-pack compatibility** | **Composes upstream packs safely** by mounting **at most one upstream pack router per worker task** | Standalone pack | Standalone pack + custom browser/CLI binaries | Standalone pack | Standalone pack |
| **Branch & merge safety** | Enforces non-default integration `BASE` branch, single conductor merge train, and human promotion PR | Operates on current checkout / branch | Operates on current branch / PR via `/ship` and `land-and-deploy` | Operates on current branch / PR | Uses git worktrees or feature branches |
| **Upstream pinning** | Exact commit + witness date pinned in [`runtime/pins.json`](../runtime/pins.json) and audited by `pin_review.py` | Upstream source | Upstream source | Upstream source | Upstream source |

---

## Why `open-fleet` composes upstream packs instead of replacing them

Single-agent skills solve **how one worker performs one technique** (how to run a tight red-green-refactor loop, how to interview a user until a spec has no ambiguity, how to audit an endpoint for OWASP flaws).

However, two failure modes appear as soon as you try to scale single-session skills to large, unattended engineering outcomes:

1. **Router and philosophy collisions when co-mounted in one session:**
   - `mattpocock/skills`, `garrytan/gstack`, and `addyosmani/agent-skills` each ship their own top-level meta-skill/router, overlapping command names (`/review`, `/ship`, `/plan`, `/tdd`), and incompatible TDD rules (for example, Addy folds refactoring into the inner TDD loop, whereas Matt defers structural refactoring to post-implementation review).
   - Loading all three into one agent's global context causes competing routing instructions and degraded adherence.
   - **How `open-fleet` solves this:** The coordinator dispatches isolated workers, and each worker's `TASK` mounts **at most one upstream pack** ([`AGENTS.md`](../AGENTS.md#one-worker-playbook-router-per-worker-hard-rule) · [Concepts — One router per worker](concepts.md#one-router-per-worker)). Cross-pack composition happens across separate workers in the mission pipeline, never inside a single worker's context window.
2. **Self-scoring completion bias:**
   - When the same session that wrote the code also grades whether all acceptance criteria were met, it can rationalize skipped requirements or pass a tautological test that never fails when the fix is reverted.
   - **How `open-fleet` solves this:** Workers only emit claims (`worker_done` + an evidence manifest). An independent verifier (`runtime/scripts/verify.py`) re-derives the criterion set from the coordinator's frozen `T0` contract digest, verifies git ancestry on `BASE`, checks that a build-blind reviewer approved the exact `head_sha`, and replays the negative control in a throwaway worktree.

---

## How upstream packs map into `open-fleet` playbooks

Every upstream pack referenced by a mission is pinned by commit SHA and witness date in [`runtime/pins.json`](../runtime/pins.json) and audited for instruction-injection or permission widening via `runtime/scripts/pin_review.py`:

| Upstream pack | Pinned version (`runtime/pins.json`) | Strengths composed by `open-fleet` worker phases | Example playbooks & missions that route to it |
|---|---|---|---|
| **[mattpocock/skills](https://github.com/mattpocock/skills)** | `v1.3.1+35` (`49dd158d`) | Ambiguity-draining specification interviews (`grilling` + `to-spec`), vertical tracer-bullet slicing (`to-tickets`), boundary-first TDD (`tdd`), two-axis isolated code review (`code-review`), Ousterhout deep-module design (`codebase-design`), skeptic issue triage (`triage`), and feedback-loop bug diagnosis (`diagnosing-bugs`) | [`decide-and-freeze.md`](../playbooks/decide-and-freeze.md), [`decompose-dag.md`](../playbooks/decompose-dag.md), [`build-change.md`](../playbooks/build-change.md), [`acceptance-review.md`](../playbooks/acceptance-review.md), [`remediate-finding.md`](../playbooks/remediate-finding.md), [`design-twice.md`](../playbooks/design-twice.md), [`diagnose.md`](../playbooks/diagnose.md) (`map-it`, `ship-it`, `clean-sweep`, `reshape-it`, `root-cause`) |
| **[garrytan/gstack](https://github.com/garrytan/gstack)** | `v1.91.121.0` (`d258bcff`) | Scope-challenging plan review (`plan-ceo-review` / `plan-design-review` / `plan-devex-review`), security false-positive filtering & active verification (`cso`), browser QA automation (`qa`), release state machine & canary monitoring (`ship`, `land-and-deploy`, `canary`), and doc coverage auditing (`document-release`) | [`plan-review.md`](../playbooks/plan-review.md), [`triage-findings.md`](../playbooks/triage-findings.md), [`browser-drive.md`](../playbooks/browser-drive.md), [`completion-audit.md`](../playbooks/completion-audit.md), [`release.md`](../playbooks/release.md), [`observe.md`](../playbooks/observe.md), [`doc-coverage.md`](../playbooks/doc-coverage.md) (`ship-it`, `harden-it`, `field-test-it`, `document-it`) |
| **[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)** | `0.6.13` (`aeac41d4`) | Scope-gated specialist risk lenses (`security-and-hardening`, `performance-optimization`, `accessibility-and-inclusive-design`, `deprecation-and-migration`), adversarial runtime proof (`doubt-driven-development`), expand/contract schema migration, question-first instrumentation (`observability-and-instrumentation`), and ADR recording (`documentation-and-adrs`) | [`risk-review.md`](../playbooks/risk-review.md), [`runtime-prove.md`](../playbooks/runtime-prove.md), [`data-migration.md`](../playbooks/data-migration.md), [`instrument.md`](../playbooks/instrument.md), [`record-decision.md`](../playbooks/record-decision.md) (`review-it`, `harden-it`, `speed-it`, `access-it`, `migrate-it`, `oncall-it`) |

---

## When to use a single-session skill vs. an `open-fleet` mission

| Scenario | Use a single-session skill directly | Run an `open-fleet` mission |
|---|---|---|
| Pairing interactively on a single function or small bug fix in one file | Yes — low overhead, immediate conversational loop | Overkill — no multi-worker coordination or integration branch needed |
| Turning a multi-part feature spec into reviewed, negative-controlled PR slices on an integration branch | High risk of context drift and unverified criteria | **[`ship-it`](missions/ship-it.md)** — freezes the spec, dispatches isolated builders (`≤ 3` WIP), runs build-blind review, and verifies every slice |
| Draining 10–30 audit findings or GitHub/Linear/Jira issues to zero | Single session compacts and loses track of the denominator | **[`clean-sweep`](missions/clean-sweep.md)** — freezes the `T0` denominator, lands one PR per finding with a pre-fix `RED` test, and re-enumerates until `DRY` |
| Getting an independent, quote-backed `GO` / `NO-GO` review on a pull request | Single reviewer prompt mixes acceptance and speculative style nits | **[`review-it`](missions/review-it.md)** — dispatches parallel `PROFILE=ro` workers across acceptance + triggered risk lenses and binds the verdict to `reviewed_sha` |
| Auditing, exploiting, fixing, and re-attacking security vulnerabilities | Single agent rarely re-attacks its own patch in a clean session | **[`harden-it`](missions/harden-it.md)** — separates builder and re-attacker sessions and requires a clean re-audit |
| Executing a multi-deploy zero-downtime database migration | Unsafe without phase gates and parity probes | **[`migrate-it`](missions/migrate-it.md)** — enforces `EXPAND → DUAL-WRITE → BACKFILL → SWITCH-READS → ZERO-READERS → RETIRE-WRITES → ZERO-WRITERS → CONTRACT` with human deploy grants |
