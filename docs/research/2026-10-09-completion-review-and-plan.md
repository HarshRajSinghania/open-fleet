# Product review, research, and completion plan — 2026-10-09

> **Dated snapshot.** Live facts were re-derived on 2026-10-09 against `main` at
> `a3fba8908a8921e56533c816902c872ffef62661` (13 commits after `v0.7.0`). This is not a new
> `complete-it` freeze and does not rewrite `docs/completion/DEFINITION.md`. Destination:
> **public-beta announcement, then 1.0.0**, matching epic
> [#526](https://github.com/ravidsrk/orca-fleet/issues/526).

**Date:** 2026-10-09
**HEAD:** `a3fba890` · version `0.7.0` · branch `main` · 0 open PRs
**Method:** catalog + completion ledger + 2026-09-28 review, then live GitHub / CI / pin /
Orca releases. External competitor claims are **not** re-scored here; the 2026-08-28
positioning snapshot remains the comparison, not today's market.

---

## 1. Verdict

Three bars, three answers:

| Bar | Live answer | Why |
|---|---|---|
| Catalog-complete (frozen 2026-09-01) | **GO, stale** | Run 3 closed GO on 2026-09-09. The definition is a 13-mission catalog + verifier, not a public product. Do not re-litigate it; do not use it as the public-beta gate. |
| 0.7.0 cut | **DONE** | Tag `v0.7.0`, GitHub Release, historical Releases backfilled, `dist` branch populated. |
| Public beta announcement | **NOT READY** | Three witnessed acts still unpaid: Linux Orca run (#527), receipt-tree shrink (draft gate 3), external-monitor **activation** (H-09 / #528). Several draft boxes are unpaid *paper* even where evidence already exists. |
| 1.0.0 | **Checklist green, stranger-belief remaining** | `scripts/release_check.py --fast --skip-github` is 22 PASS / 1 FAIL / 10 SKIP. The FAIL is an untracked `.claude/` in this worktree, not the product. What 1.0 still lacks is two bound external runs, a live second reviewer, marketplace copy, and a pin witnessed this quarter. |

The single most important fact: **the product is already an unusually honest MIT catalog.**
What blocks "complete" is not missing missions or a red suite. It is unpaid *witnessed
acts* the repo itself listed, plus a substrate that has moved eight patches since the pin.

---

## 2. What the product is (review)

orca-fleet is a **catalog + independent verifier**, not a hosted app. A stranger is supposed
to install it, trust its honesty claims, reproduce the moat demo, and — with Orca running —
start a documented first mission. Twenty-two outcome-named missions sit on three layers
(missions / playbooks / runtime) and ride Orca orchestration.

**What is genuinely good** (still true at `a3fba890`, corroborating the 2026-09-28 review §9):

- The verifier is real: vf-bench 0/20 false-done, negative-control demo PASS (self-score
  GREEN, `verify.py` RED), CI byte-diffs the demo.
- Proof honesty is machine-checked: 19 `doctrine-only` / 3 `self-run` (`clean-sweep`,
  `harden-it`, `prove-it`) / 0 `external-run`. The three self-run reports bind.
- Doctrine matches the 0.7.0 pin: Linux CLI name resolved (`orca_cli.py`, #510); Python
  floor is 3.11 and CI proves 3.11/3.12/3.13 (#514); README carries a Proof column (#515
  first half).
- Safety envelope is stated *before* the catalog (README "Before you run a mission").
- Community/legal surface exists: `CODE_OF_CONDUCT.md`, `THIRD_PARTY_NOTICES.md`,
  affiliation sentence, issue/PR templates, `CODEOWNERS`.
- Instruction budgets, identity test, and composition-reference validator still hold
  (`validate.py` 22/22 at this SHA).

**What the product is not:**

- Not field-proven for the two missions a first user is told to run (`review-it`, `ship-it`
  are both `doctrine-only`).
- Not Linux-proven by a recorded Orca mission (plugin *install* was witnessed on Ubuntu;
  a fleet *run* was not).
- Not a 1.0 in the stranger-belief sense: no `external-run`, bus factor still one in
  practice, marketplace copy still stale (#235).

---

## 3. Live state (re-derived 2026-10-09)

### Catalog and proof

```
python3 runtime/scripts/proof_status.py --check
# 19 doctrine-only, 3 self-run, 0 external-run, 22 total, exit 0
```

Flagships at bound `self-run`: `clean-sweep`, `harden-it`, `prove-it`. Getting-started
missions (`review-it`, `ship-it`) remain `doctrine-only`. Field-proof plan:
`docs/runs/README.md`.

### 1.0 checklist

`python3 scripts/release_check.py --fast --skip-github` at this worktree:

- 22 PASS (gates 1–6 machine rows, including vf-bench, demo, pin live ≥ 2026-09-16,
  watchdog/gate-batch merged *and used*).
- 1 FAIL: `gate0/tree-clean` — untracked `.claude/` (session artifact, not catalog).
- 10 SKIP (`--fast` suite, `--skip-github` rows).
- 1 INFO: #235 does not gate.

Latest `validate` on `main`: **success** at `a3fba890`
([run 36712229071](https://github.com/ravidsrk/orca-fleet/actions/runs/36712229071),
2026-09-30). No later push, so `main-health` now files stale: issue
[#542](https://github.com/ravidsrk/orca-fleet/issues/542) (2026-10-08, refreshed 2026-10-09).
The suite is not red; the dead-man's switch is doing its job on a quiet repo.

### Open tracker (8 issues)

| # | Role in completion |
|---|---|
| [542](https://github.com/ravidsrk/orca-fleet/issues/542) | Live ops: `main-health` stale (close by re-running `validate` on `main`, not by debugging the suite) |
| [529](https://github.com/ravidsrk/orca-fleet/issues/529) | 1.0: `review-it` → `external-run` with retained artifacts |
| [528](https://github.com/ravidsrk/orca-fleet/issues/528) | Public beta: external monitor. Code + drill exist; **H-09 activation still pending** |
| [527](https://github.com/ravidsrk/orca-fleet/issues/527) | Public beta: one Ubuntu `orca-ide` mission run |
| [526](https://github.com/ravidsrk/orca-fleet/issues/526) | Epic: this plan's destination |
| [515](https://github.com/ravidsrk/orca-fleet/issues/515) | README Proof column **done**; bound external `ship-it` **owed** |
| [508](https://github.com/ravidsrk/orca-fleet/issues/508) | Next pin-it: cadence 2026-12-28, or earlier if drift probe fires |
| [235](https://github.com/ravidsrk/orca-fleet/issues/235) | Marketplace submits (H-02). Does not gate 1.0; undercuts a 1.0 post if left stale |

Release-readiness label `release-readiness-2026-09-28`: **#515 is the only open child.**
#510–#514, #516–#525 closed.

### Human actions still open

| id | Status | Gates announcement? |
|---|---|---|
| H-02 marketplace | open (#235) | no |
| H-09 activate external CI monitor | pending (configured, paused) | **yes** (public-beta draft box) |
| H-10 `agentsalpha` accept invite + approve a PR | pending | no for beta; **yes for 1.0 stranger-belief** |

#530 is **CLOSED** on GitHub. `docs/ops.md` and H-10 still say the close condition is an
actual `APPROVED` review from `agentsalpha` at a PR head. Treat GitHub state as the weaker
claim; H-10 is the honest one.

### Changelog honesty

`CHANGELOG.md` `[Unreleased]` is empty. Thirteen commits after `v0.7.0`
(four of them first-parent merges) include the plugin-install witness (#539), the external poller (#540), and the second-
maintainer CODEOWNERS prep (#541). Same shape as G-17: the version surface undercounts
HEAD. Not a launch S0, but it is the exact failure this repo exists to refuse. Fix on the
next cut (0.7.1 if the shrink forces a new tag; otherwise fold into 1.0 notes).

---

## 4. Research

### Track A — internal archaeology

**Velocity.** Last coherent cut: 0.7.0 (tag published 2026-09-30, CHANGELOG dated
2026-09-28). Then a 30-Sep burst (#538–#541) and nine days of silence. Tracker is not
abandoned; it is waiting on human-side acts.

**Prior plans reconciled.**

- Sept 1–9 `complete-it` freeze (`docs/completion/DEFINITION.md`): GO. Out of scope then:
  advancing doctrine-only missions, marketplace, hosted SaaS. Still out of scope for a
  *catalog* GO. In scope for *public beta / 1.0*.
- 2026-08-28 defensibility plan: VF-Bench, negative-control demo, `attest-it` /
  `access-it`, proof-honesty, native hooks — largely shipped. Remaining from that plan:
  a bound external proof run (#49/#515) and marketplace (#86/#235).
- 2026-09-28 release-readiness review: Tier A landed. Tier B half-landed (CLI resolver,
  Python floor, safety box, plugin witness, in-repo health, Proof column). Tier C is the
  remaining 1.0 work.

**Intent delta.** None. README intent (outcome-named fleets, verified not asserted, three
layers) still matches the tree. Scope creep since the freeze is catalog 13 → 22, which the
repo treats as honesty (doctrine-only until a binding run), not failure.

### Track B — external (category-only)

**R-07 Orca cadence (fetched 2026-10-09).**
Source: [stablyai/orca releases](https://github.com/stablyai/orca/releases).
Latest stable **v1.4.223** (2026-10-08). Pin is **v1.4.215** (witnessed 2026-09-28, live).
Delta = **8 patches**. `upstream-drift.yml` files when a new minor lands or the pin falls
**ten** patches behind — so the probe is **silent and correct**. Orchestration remains
Experimental. v1.4.221–223 notes that matter to the fleet (not yet re-witnessed):

- OpenCode `worker-start` wait-until-submittable (v1.4.222).
- Codex workers accept `max`/`ultra` effort (v1.4.221).
- Agent uses Orca's own `orca` even when shell startup files put an older global first
  (v1.4.221) — related to, not a substitute for, `orca_cli.py`.
- Native chat / Grok 4.7 (v1.4.223) — worker substrate, not CLI-spec.

Effect: **no new mission**. Register on #508. Do **not** silently re-pin; pin-it is the
mission. A public-beta announcement that says "tested against v1.4.209–v1.4.215" is still
true; it is also eleven days behind what a stranger's auto-updater will install.

**R-08 Python lifecycle.** Not re-fetched. 3.11 floor is evidenced (#514) and CI-proven.
No plan effect.

**R-09 Agent Skills spec.** Not re-fetched. Validator still enforces the allowlist.
No plan effect.

**R-10 Competitive landscape.** Not re-scored. The 2026-08-28 snapshot is 42 days old.
The moat claim (mandatory negative control + independent re-derivation) is still the
differentiator *in this tree*; whether Ruflo/gstack closed the gap since August is
**unknown** and must not be restated as fact. A refresh is a research ticket, not a
1.0 gate.

### Track C — synthesis (what "complete" means now)

Complete, for the *public product*, means:

1. A stranger can clone, run catalog gates, and reproduce the moat demo from the README
   (already true; CF-01/CF-04).
2. Both advertised install paths work: symlink (CF-02) **and** plugin (CF-02b witnessed
   2026-09-30). Receipt trees still bloat the plugin copy — unpaid.
3. Independent verifier remains sound (CF-03) and proof honesty remains machine-checked
   (CF-06) — true at HEAD.
4. At least one getting-started mission has been run on **Linux** with `orca-ide` (#527).
5. CI outages are visible **outside** Actions (H-09).
6. The announcement says only what the tree supports (draft gates, then post).
7. 1.0 additionally: one bound external `ship-it` and one bound external `review-it`,
   a pin witnessed this quarter, and a second person who has actually approved a PR.

Marketplace listings (H-02) remain a launch *surface*, not a catalog or 1.0 machine gate.

---

## 5. Public-beta draft vs live evidence

`docs/announcements/public-beta-draft.md` still has every box unchecked. Several are
checkable *paper*, not missing work:

| Draft box | Live evidence | Honest state |
|---|---|---|
| Tagged 0.7.0 + GitHub Release | `v0.7.0` Release 2026-09-30; #511 closed | **MET** — box stale |
| `dist` branch + plugin witness | `refs/heads/dist` exists; CF-02b transcripts; #518 closed | **MET for install/uninstall**; not an Orca run |
| Receipt trees shrunk | still unpaid (draft says this can force a tag after 0.7.0) | **UNMET** |
| Ubuntu `orca-ide` mission | #527 open | **UNMET** |
| External monitor polling Actions | poller + drill in tree; H-09 **paused** | **UNMET as a living watch** |
| Proof paragraph matches README | 3 self-run / 19 doctrine-only / 0 external-run, unchanged | **MET** until an external run binds |

Do not post the draft until the three UNMET rows are evidenced, then tick the MET boxes
in the same docs PR as the post-prep — never in chat.

---

## 6. Plan (dependency order, no invented dates)

Adopt #526's order. A row is done when evidence is in the tree or on GitHub.

### Phase P0 — keep main honest (hours)

| id | What | Evidence | Owner |
|---|---|---|---|
| P0-a | Close #542: `main` is green, stale. Re-run `validate` on `main` (empty commit **forbidden**; a no-op workflow_dispatch or a tiny tracked docs fix is enough) | #542 closed; latest `validate` on `main` < 7 days | maintainer |
| P0-b | Do not commit `.claude/` | `git status --porcelain` empty of that path | anyone |

### Phase P1 — finish public beta (one to two weeks; #526 step 2)

Order: P1-a and P1-b are independent; P1-c may force a **new tag** (draft gate 3);
P1-d is the post.

| id | What | Closes | Size |
|---|---|---|---|
| P1-a | Activate H-09 (Codex Automations watch unpaused, host awake) **or** name a substitute uptime check in `docs/ops.md`. Drill already exists (`T-13-external-monitor-drill.txt`). | #528, H-09 | S, **human** |
| P1-b | One `review-it` **or** `ship-it` on Ubuntu driven by `orca-ide`. Record under `docs/runs/<date>-<mission>-linux/` so `run_report.py` can bind. Then drop "untested" in README + announcement. | #527 | M, needs Ubuntu + Orca |
| P1-c | Shrink or relocate `docs/runs/` + `docs/reports/` receipt trees out of the plugin copy. If this lands after `v0.7.0`, the announced tag is the **next** tag, not 0.7.0. Put the 13 post-cut commits in that tag's CHANGELOG. | draft gate 3; changelog honesty | M |
| P1-d | Tick every MET box in the draft against evidence, then post (GitHub Release summary → README one-liner → listings). Scope the post to the three `self-run` missions. | announcement | S, **human** |

Confirm first scheduled `upstream-drift` weekly run (manual drill already passed). Not
gating if it stays silent at 8 patches.

### Phase P2 — 1.0 stranger-belief (weeks to months; mostly runs)

Any order after the announcement, except P2-d last.

| id | What | Closes |
|---|---|---|
| P2-a | One `ship-it` on an **external** repo to bound `BUILT`, artifacts retained in the run dir | #515 remainder |
| P2-b | One `review-it` external-run with retained artifacts | #529 |
| P2-c | H-10: `agentsalpha` accepts invite `335422854` and is the approving review on one critical-path PR | H-10; makes #530's close honest |
| P2-d | Pin-it on or before 2026-12-28, or sooner if `upstream-drift` fires (8/10 patches today) | #508 |
| P2-e | H-02 marketplace submits, then re-index (non-gating, undercuts a 1.0 post if skipped) | #235 |
| P2-f | `python3 scripts/release_check.py` exit 0 at the cut SHA (no standing SKIP), then ops.md 1.0.0 blocks | #526 close |

**Not in this plan:** new missions, advancing the other 19 to self-run (G-09 / field-proof
plan stays the tracker), hosted SaaS, lowering the 34k activation cap, a competitive
re-score.

### What this plan refuses

- A new 17-angle `complete-it` freeze. The Sept definition answered "can a stranger
  install and trust the catalog." That is GO. Re-scoring it would launder public-beta
  gaps into a fresh percentage.
- Relabeling `ship-it` / `review-it` to `self-run` without a binding report.
- Announcing 0.7.0 as public beta while Linux is untested and the external watch is paused.
- Treating #530 CLOSED as bus-factor-two.

---

## 7. Decision tickets (human; do not auto-answer)

map-it forbids the agent standing in. Three questions are sharp now:

1. **Announce after P1, or wait for P2-a (external `ship-it`)?** #526 says announce after
   P1, scoped to three self-run missions. The 2026-09-28 review called the two external
   runs "the release." Same disagreement as 28 Sep; still a one-way door.
2. **Shrink receipts in 0.7.1, or announce 0.7.0 and disclose full size?** Draft says
   shrink is mandatory and forces a later tag. Disclosing size is explicitly not a
   substitute.
3. **Re-pin now at 8 patches, or wait for 10 / 2026-12-28?** Probe is silent. v1.4.223
   has worker-start behavior a coordinator would notice (OpenCode submit wait).

Not-yet-specified (cannot phrase sharply without a target repo): which external
repository is the `ship-it` / `review-it` subject.

---

## 8. Risks (max 5)

1. **Substrate drift.** Pin 1.4.215 vs live 1.4.223; orchestration still Experimental;
   quarterly pin vs daily upstream. Mitigate: #508 register + don't invite Linux users
   until #527 binds.
2. **Headline vs proof.** README still promises an evidence-verified end state; 19/22
   missions are doctrine-only; first-user missions are two of those 19. Mitigate: Proof
   column (done) + announcement scoped to three self-run + P2-a/b.
3. **Watch paused.** H-09 off means the no-runner outage of 23–25 Sep is again invisible
   outside Actions. `main-health` cannot see that class. #542 proves the in-repo layer
   works for *quiet main*, not for *no runners*.
4. **Bus factor 1 in practice.** CODEOWNERS names `agentsalpha`; invite unaccepted; no
   peer `APPROVED` review. 1.0 should not claim otherwise.
5. **Plugin copy size.** Draft gate 3 unpaid. A public plugin install still copies
   receipt trees.

---

## 9. Sources (2026-10-09)

- Tree: `a3fba890`, `runtime/pins.json`, `docs/completion/*`, `docs/release-1.0-checklist.md`,
  `docs/announcements/public-beta-draft.md`, `docs/runs/README.md`,
  `docs/reviews/2026-09-28-release-readiness-review.md`, `TODOS.md`, `#526` body.
- Commands: `proof_status.py --check`; `release_check.py --fast --skip-github`;
  `gh issue list`; `gh release list`; `gh run list --workflow validate`;
  `gh release list --repo stablyai/orca`.
- External: https://github.com/stablyai/orca/releases (v1.4.223, 2026-10-08).
