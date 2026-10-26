# Comprehensive Visual Review of All 100 Repository Images

**Date:** 2026-10-26  
**Scope:** 100% visual inspection and remediation of all **100 raster assets** (`assets/*.jpg`, `.claude-plugin/icon.png`, `assets/diagrams/*.jpg`, `assets/diagrams/missions/*.jpg`) compared against their canonical generator specifications in [`assets/diagrams/generator/specs.py`](../../assets/diagrams/generator/specs.py), [`assets/diagrams/generator/specs_new.py`](../../assets/diagrams/generator/specs_new.py), [`assets/diagrams/generator/specs_missions.py`](../../assets/diagrams/generator/specs_missions.py), and [`assets/diagrams/generator/specs_light.py`](../../assets/diagrams/generator/specs_light.py).

---

## Executive Summary (Post-Remediation)

| Category | Total Images | Dark / Light Pairs | 100% Clean & Parity-Matched | Minor Template Variations | Open Defects / Parity Drift |
|---|---:|---:|---:|---:|---:|
| **Brand Banners & Plugin Icon** (`assets/*.jpg`, `.claude-plugin/icon.png`) | 4 | 1 pair + 1 social + 1 icon | **4** | **0** | **0** |
| **Architecture & Concept Diagrams** (`assets/diagrams/*.jpg`) | 52 | 26 pairs | **52** (26 pairs) | **0** | **0** |
| **Mission Contract Cards** (`assets/diagrams/missions/*.jpg`) | 44 | 22 pairs | **44** (22 pairs) | **0** | **0** |
| **Total** | **100** | **49 pairs + 2** | **100** | **0** | **0** |

---

## Remediated Findings Across the Full Catalog

### 1. Brand Assets (`hero-dark.jpg`, `hero-light.jpg`, `social-preview.jpg`, `.claude-plugin/icon.png`)
- **[`assets/hero-dark.jpg`](../../assets/hero-dark.jpg) & [`assets/hero-light.jpg`](../../assets/hero-light.jpg) (`2000×848`):**
  - Rendered from a shared precision SVG geometry using `JetBrains Mono` so dark (`#0B1220`) and light (`#F5F8FF`) modes have **100% identical node positions, line breaks, and typography** (`open-fleet` + `Give a mission a goal. Come back to an` / `evidence-verified end state.`), four multi-faceted diamond-hexagonal autonomous-agent vessels with velocity trails, smooth directed DAG convergence curves, and a multi-ring emerald hexagonal verified seal (`⬡` + `✓`). Eliminated the light-mode 12-pointed scalloped rosette and spiky triangle artifacts.
- **[`assets/social-preview.jpg`](../../assets/social-preview.jpg) (`2560×1280`):**
  - Rendered with all **four** autonomous-agent vessels converging along smooth cubic curves into the emerald hexagonal verified seal beneath `open-fleet` and `Autonomous engineering fleets for coding agents — SHA-verified outcomes`, plus the bottom-right 3-node constellation signature mark.
- **[`.claude-plugin/icon.png`](../../.claude-plugin/icon.png) (`1024×1024`):**
  - Rendered natively on a full-bleed `1024×1024` square deep-navy canvas with a double hexagonal frame and four autonomous-agent vessels converging upward into the emerald verified seal, eliminating the vertical letterbox crop seams.

### 2. Multi-Runtime & Updated Architecture Diagrams (`verify-gate`, `install-stack`, `runtime-providers`, `tracker-enumeration`)
- **[`assets/diagrams/verify-gate.jpg`](../../assets/diagrams/verify-gate.jpg) & [`assets/diagrams/verify-gate-light.jpg`](../../assets/diagrams/verify-gate-light.jpg):**
  - Eliminated the right-border text overflow on `OPEN_FLEET_EXECUTE_NC is set` inside `verify.py re-derives`, placed Box 1's caption (`OPEN_FLEET_MANIFEST · contract source + digest · unit class`) inside Box 1 so all three top pipeline stages share equal height and aligned horizontal arrows, and unified the two bottom trust-boundary cards (`native hook, inside the worker's own session` and `CI · MCP-Task · SDK subprocess`).
- **[`assets/diagrams/install-stack.jpg`](../../assets/diagrams/install-stack.jpg) & [`assets/diagrams/install-stack-light.jpg`](../../assets/diagrams/install-stack-light.jpg):**
  - Centered all five left-hand stack headings and captions, updated Layer 2 (`runtime provider interface (14 runtimes)`) to `orca (default) · posix (standalone SQLite + worktrees) · auto · overstory · t3code · ao · +9 more` to match [`README.md`](../../README.md), and positioned the top-right pill badges (`wire the gate`, `gate on`, `use dist`) cleanly above the card titles in `THREE INSTALL PATHS`.
- **[`assets/diagrams/runtime-providers.jpg`](../../assets/diagrams/runtime-providers.jpg) & [`assets/diagrams/runtime-providers-light.jpg`](../../assets/diagrams/runtime-providers-light.jpg):**
  - Replaced the muddy brown dark-mode fill in `uniform permission mapping` with crisp `#121B2D` navy fill + `#FFB84C` amber border, added clear container borders for `14 RUNTIME PROVIDERS (OPEN_FLEET_RUNTIME)` and `11 CODING-AGENT HARNESSES (OPEN_FLEET_HARNESS)`, and marked `orca` as `(default)`.
- **[`assets/diagrams/tracker-enumeration.jpg`](../../assets/diagrams/tracker-enumeration.jpg) & [`assets/diagrams/tracker-enumeration-light.jpg`](../../assets/diagrams/tracker-enumeration-light.jpg):**
  - Vertically centered the 4-stage pipeline on the `1600×900` canvas and gave all three left-hand tracker source boxes (`GITHUB`, `LINEAR`, `JIRA`) uniform blue outlines flowing into `T0 TWIN-QUERY` (blue) → `TRUST FENCE` (amber) → `VERIFIED CLOSURE` (green).

### 3. All 44 Mission Contract Cards (`assets/diagrams/missions/*.jpg` & `*-light.jpg`)
- Deterministically rendered all **22 dark/light mission contract card pairs (`44` files)** directly from [`assets/diagrams/generator/specs_missions.py`](../../assets/diagrams/generator/specs_missions.py):
  - Single-line top-left `<id> — <outcome>` header (`<id>` in bold primary type, ` — <outcome>` in muted slate-blue) with decorative constellations placed in the top-right and bottom-left corners so no line ever touches the title.
  - Symmetric 2×2 grid of four equal rounded panels (`YOU GIVE IT`, `IT INTERRUPTS YOU FOR`, `YOU GET BACK`, `IT STOPS AT`).
  - Clean single-outline terminal-state hexagons (`green`, `amber`, `red`, `grey`) in `YOU GET BACK` with zero inner hexagon icons, followed by muted grey-blue artifact lines separated by `·`.
  - Centered muted phase strip (`PHASE → PHASE → ...`) along the bottom and the 3-node geometric constellation signature mark in the bottom-right corner.

### 4. Legacy Orca Killer-Whale Corner Mark Removed Across All 86 Legacy Diagram Files
- Replaced the legacy bottom-right jumping killer-whale silhouette in all 22 existing concept diagram pairs (`44` files) and all 22 mission contract card pairs (`44` files) with the 3-node geometric constellation signature mark.

---

## Detailed Image-by-Image Catalog (All 100 Assets)

### Part 1: Brand Banners & Plugin Icon (4 Images)

| # | Asset | Resolution | Status | Detailed Visual Notes |
|---:|---|---:|---|---|
| 1 | [`assets/hero-dark.jpg`](../../assets/hero-dark.jpg) | `2000×848` | **PASS** | Deep navy `#0B1220`, 4 faceted diamond-hexagonal autonomous-agent vessels converging left-to-right along smooth directed DAG trajectories into an emerald hexagonal verified seal (`⬡` + `✓`); `open-fleet` + `Give a mission a goal. Come back to an evidence-verified end state.`. |
| 2 | [`assets/hero-light.jpg`](../../assets/hero-light.jpg) | `2000×848` | **PASS** | Near-white `#F5F8FF` background, white/pale-blue faceted vessels with `#2F6FEB` outlines and `#1F9D55` emerald hexagonal verified seal. 100% geometric and line-break parity with `hero-dark.jpg`. |
| 3 | [`assets/social-preview.jpg`](../../assets/social-preview.jpg) | `2560×1280` | **PASS** | 2:1 OpenGraph card with centered `open-fleet` wordmark, `Autonomous engineering fleets for coding agents — SHA-verified outcomes`, 4 converging vessels, emerald hexagonal verified seal, and bottom-right 3-node constellation mark. |
| 4 | [`.claude-plugin/icon.png`](../../.claude-plugin/icon.png) | `1024×1024` | **PASS** | Seamless full-bleed `1024×1024` square icon with double hexagonal frame and 4 autonomous-agent vessels converging upward into the emerald hexagonal verified seal. |

---

### Part 2: Architecture & Concept Diagrams (52 Images / 26 Pairs)

All 52 diagrams are `1600×900` (16:9) and carry the 3-node geometric constellation signature mark in the bottom-right corner.

| # | Diagram Pair (`dark` / `light`) | Status | Detailed Visual Audit (Dark & Light) |
|---:|---|---|---|
| 5–6 | [`artifacts-map.jpg`](../../assets/diagrams/artifacts-map.jpg) / [`-light.jpg`](../../assets/diagrams/artifacts-map-light.jpg) | **PASS** | File tree on left (`ledger.md` and `docs/runs/<date>-<mission>/`) and 3 GitHub boxes on right (`one PR per unit` → `merged into BASE` → `the promotion PR, BASE → default`) with matching amber promotion arrow and constellation corner mark. |
| 7–8 | [`attention-budget.jpg`](../../assets/diagrams/attention-budget.jpg) / [`-light.jpg`](../../assets/diagrams/attention-budget-light.jpg) | **PASS** | Contrast between sprawl (`spawning is cheap`) and bounded `WIP ≤ 3 builders` (`one human — the serial bottleneck`) with matching dual blue+amber border and constellation corner mark. |
| 9–10 | [`decision-gates.jpg`](../../assets/diagrams/decision-gates.jpg) / [`-light.jpg`](../../assets/diagrams/decision-gates-light.jpg) | **PASS** | Three lanes (`MECHANICAL`, `TASTE`, `ONE-WAY DOOR`) with green `PROCEED` badges and amber `PAUSE — WAIT FOR YOU` badge, dashed override arrow, and 3 autonomy pills at bottom. |
| 11–12 | [`evidence-protocol.jpg`](../../assets/diagrams/evidence-protocol.jpg) / [`-light.jpg`](../../assets/diagrams/evidence-protocol-light.jpg) | **PASS** | Left-to-right flow (`WORKER` → `EVIDENCE MANIFEST` → `INDEPENDENT VERIFIER`) with all 6 verification checks and green `VERIFIED` / red `VOID` badges. |
| 13–14 | [`first-run.jpg`](../../assets/diagrams/first-run.jpg) / [`-light.jpg`](../../assets/diagrams/first-run-light.jpg) | **PASS** | Three-stage flow (`> ship this: add /healthz` → `THE FLEET – coordinator + workers, each in its own worktree` → `evidence manifest – SHA-bound`) with unobstructed `[VERIFIED]` stamp. |
| 15–16 | [`fleet-topology.jpg`](../../assets/diagrams/fleet-topology.jpg) / [`-light.jpg`](../../assets/diagrams/fleet-topology-light.jpg) | **PASS** | `COORDINATOR` with `ledger` and `verifier` dispatching `builder`, `reviewer`, and `conductor` (`fresh worktree + terminal each`) with `gates only` human link. |
| 17–18 | [`gates-terminal.jpg`](../../assets/diagrams/gates-terminal.jpg) / [`-light.jpg`](../../assets/diagrams/gates-terminal-light.jpg) | **PASS** | `ONE-WAY` freeze grill prompt on left + `TASTE` and `PROMOTION` cards on right, clean typography and constellation corner mark. |
| 19–20 | [`install-stack.jpg`](../../assets/diagrams/install-stack.jpg) / [`-light.jpg`](../../assets/diagrams/install-stack-light.jpg) | **PASS** | Five centered architecture layers on left (`upstream worker packs` down to `coding-agent harnesses`, with `orca (default) · posix ...` on Layer 2) and `THREE INSTALL PATHS` on right with non-overlapping pill badges (`wire the gate`, `gate on`, `use dist`). |
| 21–22 | [`liveness-resume.jpg`](../../assets/diagrams/liveness-resume.jpg) / [`-light.jpg`](../../assets/diagrams/liveness-resume-light.jpg) | **PASS** | `WATCH` band (`worker – no heartbeat / past the window` → `respawn in a FRESH terminal`) and `RESUME` band (`dead coordinator` + `ledger` → `new coordinator` → `reconnect, scoped to its own run`). |
| 23–24 | [`merge-train.jpg`](../../assets/diagrams/merge-train.jpg) / [`-light.jpg`](../../assets/diagrams/merge-train-light.jpg) | **PASS** | Three worktree branches entering `SERIAL MERGE QUEUE (1 → 2 → 3)` with `rebase onto BASE · run suite · fast-forward` into `BASE`, plus amber `HUMAN GATE — promotion PR` to `DEFAULT`. |
| 25–26 | [`mission-chaining.jpg`](../../assets/diagrams/mission-chaining.jpg) / [`-light.jpg`](../../assets/diagrams/mission-chaining-light.jpg) | **PASS** | `map-it` → `ship-it` → `harden-it` chain with green `MAPPED` / `BUILT` handoffs, downward amber `*-WITH-PARKED` arrows into red `CHAIN STOPS`, and green `DEPLOYED_AND_VERIFIED` terminal. |
| 27–28 | [`mission-handoffs.jpg`](../../assets/diagrams/mission-handoffs.jpg) / [`-light.jpg`](../../assets/diagrams/mission-handoffs-light.jpg) | **PASS** | Three-column handoff layout (`ship-it`, `clean-sweep`, `migrate-it`) plus `oncall-it → root-cause` and `harden-it → prove-it → ship-it` chain bracket. |
| 29–30 | [`mission-identity.jpg`](../../assets/diagrams/mission-identity.jpg) / [`-light.jpg`](../../assets/diagrams/mission-identity-light.jpg) | **PASS** | Six-point mission-identity checklist on left and two worked examples (`clean-sweep` vs `speed-it`) on right. |
| 31–32 | [`mission-map.jpg`](../../assets/diagrams/mission-map.jpg) / [`-light.jpg`](../../assets/diagrams/mission-map-light.jpg) | **PASS** | 22-mission decision tree (`WHICH MISSION DO I WANT?`) with 100% accurate spelling across dark and light modes. |
| 33–34 | [`negative-control.jpg`](../../assets/diagrams/negative-control.jpg) / [`-light.jpg`](../../assets/diagrams/negative-control-light.jpg) | **PASS** | Head-to-head comparison of `A SELF-SCORING GATE` (`GREEN — exit 0`) vs `OPEN-FLEET'S VERIFIER` (`RED — exit 2`) on the same gamed manifest. |
| 35–36 | [`one-router-per-worker.jpg`](../../assets/diagrams/one-router-per-worker.jpg) / [`-light.jpg`](../../assets/diagrams/one-router-per-worker-light.jpg) | **PASS** | Left panel (`ALLOWED — CROSS-PACK AT MISSION LEVEL` with green `CLEAN`) vs right panel (`FORBIDDEN — TWO ROUTERS IN ONE WORKER` with red `CONFLICT`). |
| 37–38 | [`proof-ladder.jpg`](../../assets/diagrams/proof-ladder.jpg) / [`-light.jpg`](../../assets/diagrams/proof-ladder-light.jpg) | **PASS** | Three-rung ladder (`doctrine-only` → `self-run` → `external-run`) + right archive callout with amber border in both modes. |
| 39–40 | [`reviewed-sha-freshness.jpg`](../../assets/diagrams/reviewed-sha-freshness.jpg) / [`-light.jpg`](../../assets/diagrams/reviewed-sha-freshness-light.jpg) | **PASS** | Top lane (`CASE A — NO POST-REVIEW COMMITS` → green `FRESH — MERGE ALLOWED`) vs bottom lane (`CASE B — REBASE OR AMEND AFTER REVIEW` → `git diff-tree reviewed_sha head_sha`). |
| 41–42 | [`run-timeline.jpg`](../../assets/diagrams/run-timeline.jpg) / [`-light.jpg`](../../assets/diagrams/run-timeline-light.jpg) | **PASS** | End-to-end run timeline from intent and freeze through parallel dispatch, verification, merge train, and promotion PR. |
| 43–44 | [`runtime-providers.jpg`](../../assets/diagrams/runtime-providers.jpg) / [`-light.jpg`](../../assets/diagrams/runtime-providers-light.jpg) | **PASS** | Top neutral entrypoints band feeding `14 RUNTIME PROVIDERS (OPEN_FLEET_RUNTIME)` (`posix`, `orca (default)`, `12 external orchestrators`) and `11 CODING-AGENT HARNESSES (OPEN_FLEET_HARNESS)` (`claude · codex · ...` + amber `uniform permission mapping`), converging into `INDEPENDENT SHA-BOUND VERIFIER`. |
| 45–46 | [`sandbox-profiles.jpg`](../../assets/diagrams/sandbox-profiles.jpg) / [`-light.jpg`](../../assets/diagrams/sandbox-profiles-light.jpg) | **PASS** | Three profile vessels (`ro`, `rw`, `danger`) with complete captions (`bypass approvals – opt-in flag required – / exploit PoCs, destructive tests.`) over `disposable per-workspace sandbox – never your machine.`. |
| 47–48 | [`threat-boundaries.jpg`](../../assets/diagrams/threat-boundaries.jpg) / [`-light.jpg`](../../assets/diagrams/threat-boundaries-light.jpg) | **PASS** | Left 2×2 grid (`1 · SANDBOX`, `2 · NETWORK`, `3 · SUPPLY CHAIN`, `4 · IDENTITY & ACCESS`) and right 5-rung response ladder (`1 STEER` → `2 REDUCE` → `3 STOP` → `4 REVOKE` → `5 QUARANTINE`). |
| 49–50 | [`three-layers.jpg`](../../assets/diagrams/three-layers.jpg) / [`-light.jpg`](../../assets/diagrams/three-layers-light.jpg) | **PASS** | Top-to-bottom architecture stack (`MISSIONS · skills/` → `PLAYBOOKS · playbooks/` → `RUNTIME · runtime/`) with `only skills/ may hold a SKILL.md`. |
| 51–52 | [`tracker-enumeration.jpg`](../../assets/diagrams/tracker-enumeration.jpg) / [`-light.jpg`](../../assets/diagrams/tracker-enumeration-light.jpg) | **PASS** | Vertically centered left-to-right pipeline: three blue-outlined tracker sources (`GITHUB`, `LINEAR`, `JIRA`) merging into `T0 TWIN-QUERY` (blue) → `TRUST FENCE` (amber) → `VERIFIED CLOSURE` (green). |
| 53–54 | [`verify-gate.jpg`](../../assets/diagrams/verify-gate.jpg) / [`-light.jpg`](../../assets/diagrams/verify-gate-light.jpg) | **PASS** | Equal-height top pipeline (`the coordinator sets the gate env` → `Stop / TaskCompleted hook fires verify-gate.sh` → `verify.py re-derives` → `exit 0 — allow` / `exit 2 — BLOCK, with feedback`) with zero text overflow, plus `WHERE THE VERDICT IS SOUND` cards below. |
| 55–56 | [`you-say.jpg`](../../assets/diagrams/you-say.jpg) / [`-light.jpg`](../../assets/diagrams/you-say-light.jpg) | **PASS** | Three-column table (`YOU SAY` · `THE FLEET RUNS` · `YOU GET`) across `ship this`, `close every issue`, `harden this`, and `why is this flaky`. |

---

### Part 3: Mission Contract Cards (44 Images / 22 Pairs)

All 44 mission contract cards (`1600×900`, 16:9) are deterministically rendered from [`assets/diagrams/generator/specs_missions.py`](../../assets/diagrams/generator/specs_missions.py) with 100% uniform layout, single-line `<id> — <outcome>` titles, symmetric 2×2 panels, single-outline terminal hexagons, muted artifact descriptions, centered phase strips, and the 3-node constellation signature mark.

| # | Mission Card Pair (`dark` / `light`) | Status | Terminal Hexagons & Contract Verification |
|---:|---|---|---|
| 57–58 | [`absorb-it.jpg`](../../assets/diagrams/missions/absorb-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/absorb-it-light.jpg) | **PASS** | `ABSORBED` (green), `ABSORBED-WITH-PARKED` (amber) · `ENUMERATE → CLASSIFY → ABSORB → RECEIPT → REVIEW → LAND → CLOSE` |
| 59–60 | [`access-it.jpg`](../../assets/diagrams/missions/access-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/access-it-light.jpg) | **PASS** | `CONFORMANT` (green), `CONFORMANT-WITH-MANUAL-PARKED` (amber) · `AUDIT → TRIAGE → FIX → VERIFY → LAND → RE-AUDIT` |
| 61–62 | [`attest-it.jpg`](../../assets/diagrams/missions/attest-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/attest-it-light.jpg) | **PASS** | `CONFORMANT` (green), `CONFORMANT-WITH-GAPS` (amber) · `INGEST → COLLECT → WITNESS → CROSS-EXAMINE → REMEDIATE → ATTEST` |
| 63–64 | [`clean-sweep.jpg`](../../assets/diagrams/missions/clean-sweep.jpg) / [`-light.jpg`](../../assets/diagrams/missions/clean-sweep-light.jpg) | **PASS** | `DRY` (green), `DRY-WITH-PARKED` (amber) · `ENUMERATE → TRIAGE → FIX → REVIEW → LAND → CLOSE → RE-ENUMERATE` |
| 65–66 | [`deflake-it.jpg`](../../assets/diagrams/missions/deflake-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/deflake-it-light.jpg) | **PASS** | `STABLE` (green), `STABLE-WITH-QUARANTINE` (amber) · `DETECT → CLASSIFY → FIX → SOAK → LAND → RE-BURN` |
| 67–68 | [`document-it.jpg`](../../assets/diagrams/missions/document-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/document-it-light.jpg) | **PASS** | `DOCUMENTED` (green), `DOCUMENTED-WITH-PARKED` (amber) · `INVENTORY → EXTRACT → DRAFT → EXECUTE-CHECK → REVIEW → LAND` |
| 69–70 | [`field-test-it.jpg`](../../assets/diagrams/missions/field-test-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/field-test-it-light.jpg) | **PASS** | `FIELD-PROVEN` (green), `FIELD-PROVEN-WITH-PARKED` (amber) · `PROVISION → EXERCISE → CAPTURE → TRIAGE → FIX → RE-RUN` |
| 71–72 | [`floor-it.jpg`](../../assets/diagrams/missions/floor-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/floor-it-light.jpg) | **PASS** | `FLOORED` (green), `FLOORED-WITH-PARKED` (amber) · `SURVEY → PROPOSE → PROVE-FLOOR → WIRE-CI → LAND → RATCHET` |
| 73–74 | [`harden-it.jpg`](../../assets/diagrams/missions/harden-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/harden-it-light.jpg) | **PASS** | `CLEAN` (green), `HARDENED-WITH-OPEN-ITEMS` (amber) · `RECON → AUDIT → EXPLOIT-PROVE → FIX → REVIEW → LAND → RE-AUDIT` |
| 75–76 | [`map-it.jpg`](../../assets/diagrams/missions/map-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/map-it-light.jpg) | **PASS** | `MAPPED` (green), `MAPPED-WITH-BLOCKED` (amber) · `NAME → CHART → CLEAR THE FRONTIER → FREEZE → PREPARE THE DAG` |
| 77–78 | [`migrate-it.jpg`](../../assets/diagrams/missions/migrate-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/migrate-it-light.jpg) | **PASS** | `MIGRATED` (green), `MIGRATED-WITH-PARKED` (amber), `ABANDONED` (grey) · `EXPAND → DUAL-WRITE → BACKFILL → SWITCH-READS → RETIRE-WRITES → CONTRACT` |
| 79–80 | [`modernize-it.jpg`](../../assets/diagrams/missions/modernize-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/modernize-it-light.jpg) | **PASS** | `CURRENT` (green), `CURRENT-WITH-PINNED` (amber) · `INVENTORY → ORDER → CHARACTERIZE → UPGRADE → REVIEW → LAND` |
| 81–82 | [`offload-it.jpg`](../../assets/diagrams/missions/offload-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/offload-it-light.jpg) | **PASS** | `OFFLOADED` (green), `OFFLOADED-WITH-PARKED` (amber) · `SURVEY → SYNTHESIZE → PROVISION → PARITY-PROVE → TEARDOWN-PROVE → LAND` |
| 83–84 | [`oncall-it.jpg`](../../assets/diagrams/missions/oncall-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/oncall-it-light.jpg) | **PASS** | `OPERABLE` (green), `OPERABLE-WITH-PARKED` (amber) · `FREEZE → INSTRUMENT → ALERT → RUNBOOK → TEST-FIRE → INDUCE` |
| 85–86 | [`oss-contribute.jpg`](../../assets/diagrams/missions/oss-contribute.jpg) / [`-light.jpg`](../../assets/diagrams/missions/oss-contribute-light.jpg) | **PASS** | `CONTRIBUTED` (green), `CONTRIBUTED-WITH-PARKED` (amber) · `RECON → SELECT → BUILD → SELF-REVIEW → SUBMIT → FOLLOW-THROUGH` |
| 87–88 | [`pin-it.jpg`](../../assets/diagrams/missions/pin-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/pin-it-light.jpg) | **PASS** | `PINNED` (green), `PINNED-WITH-PARKED` (amber) · `FREEZE → RE-WITNESS → CLASSIFY → PATCH → LAND` |
| 89–90 | [`prove-it.jpg`](../../assets/diagrams/missions/prove-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/prove-it-light.jpg) | **PASS** | `COVERED` (green), `COVERED-WITH-PARKED` (amber) · `MAP → CONFIRM → CHARACTERIZE → MUTATION-AUDIT → REVIEW → LAND → RE-MAP` |
| 91–92 | [`reshape-it.jpg`](../../assets/diagrams/missions/reshape-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/reshape-it-light.jpg) | **PASS** | `RESHAPED` (green), `RESHAPED-WITH-PARKED` (amber) · `CHARACTERIZE → PLAN-STEPS → STEP → PROVE-STEP → LAND` |
| 93–94 | [`review-it.jpg`](../../assets/diagrams/missions/review-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/review-it-light.jpg) | **PASS** | `GO` (green), `NO-GO` (red) · `PIN → STANDARDS · SPEC · TEST-ADEQUACY · RISK → AGGREGATE` |
| 95–96 | [`root-cause.jpg`](../../assets/diagrams/missions/root-cause.jpg) / [`-light.jpg`](../../assets/diagrams/missions/root-cause-light.jpg) | **PASS** | `DIAGNOSED` (green), `DIAGNOSED-WITH-HANDOFF` (green), `INCONCLUSIVE` (amber) · `STOP-THE-LINE → RED LOOP → LOCALIZE → HYPOTHESES → FALSIFY → DEMONSTRATE` |
| 97–98 | [`ship-it.jpg`](../../assets/diagrams/missions/ship-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/ship-it-light.jpg) | **PASS** | `BUILT` (green), `PROMOTION_READY` (green), `RELEASED` (grey), `DEPLOYED_AND_VERIFIED` (grey) · `FREEZE → DECOMPOSE → BUILD → REVIEW → PROVE → LAND → RELEASE` |
| 99–100 | [`speed-it.jpg`](../../assets/diagrams/missions/speed-it.jpg) / [`-light.jpg`](../../assets/diagrams/missions/speed-it-light.jpg) | **PASS** | `WITHIN-BUDGET` (green), `OPTIMIZED-WITH-PARKED` (amber) · `BASELINE → PROFILE → OPTIMIZE → PROVE-DELTA → LAND → RE-BASELINE` |
