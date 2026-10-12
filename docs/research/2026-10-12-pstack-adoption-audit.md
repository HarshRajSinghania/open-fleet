# pstack adoption audit — 2026-10-12

> **Dated snapshot.** Clones were taken on 2026-10-12. The canonical tree is
> [cursor/plugins](https://github.com/cursor/plugins) `pstack` **0.15.20** at
> `1b6d44ff26d4e242f4e8f68c391e6d2f7ca16def` ("chore(pstack): bump to 0.15.20").
> This is not a new mission and does not change any `metadata.proof` value.

**Date:** 2026-10-12
**Catalog HEAD this was written against:** `b94b4b28` on `docs/post-070-honesty-20261012`
(the post-0.7.0 notes commit; the fold described below lands after it).
**Question:** the September audits compared this catalog to mattpocock/skills, garrytan/gstack,
and addyosmani/agent-skills. pstack (Lauren Tan, @poteto) has since drawn the attention those
packs had. What in 0.15.20 would make orca-fleet better, and what would erase the discipline?

---

## 1. What was cloned

Shallow clones, kept outside this repo (`/tmp/pstack-sources`). Nothing from them is vendored.

| Tree | Commit | What it is | Used as |
|---|---|---|---|
| cursor/plugins `pstack/` | `1b6d44ff` 2026-10-12 | Upstream plugin, version 0.15.20. 52 `SKILL.md` files (24 of them `principle-*`), 23 playbooks under `poteto-mode`. MIT, Copyright (c) 2026 Lauren Tan. | **Canonical.** Every adoption below was read here. |
| poteto/plugins | `74dd2291` 2026-06-06 | Author's plugins monorepo. pstack README sync, then four months of silence. | Stale. Not a source. |
| michael-denyer/pstack-claude | `1bfdab42` 2026-10-11 | Claude Code / Codex / Pi port. Its own `VERSION` file says `0.9.82`. | Not re-diffed against 0.15.20. |
| mdsmithaustin/pstack | `253a46e1` 2026-10-12 | CLI-agnostic port, including a Grok Build install path (`npx skills`). | Not re-diffed. The workflows are still poteto's. |
| ericlitman/open-pstack | `c5c8e237` 2026-10-11 | Port built on pstack-claude. Its README says Open Pstack 1.6.1 tracks pstack **0.15.17** at `978ca6e9`. | Three patches behind today's plugin. |
| painhardcore/pstack | `04830a98` 2026-08-27 | OpenCode-oriented port, self-described 1.1.0. Omits `automate-me`, `reflect`, `setup-pstack`, and several autopilot playbooks. | Too old to adopt from. |

The hype and the plugin disagree with each other by a few weeks. Articles from August and
September still say 21 principles and 23 skills. The tree on 12 October has 24 principle skills,
23 playbooks, and 52 skill files. Counts below are from the clone, not from the posts.

---

## 2. What pstack actually is

A Cursor plugin. `/poteto-mode` matches a task to one of 23 playbooks, copies that playbook's
steps into a todo list, and calls the other skills when a step needs them. Around that sit
principle skills (apply when a situation comes up; they do not auto-invoke) and a handful of
direct skills (`/how`, `/why`, `/interrogate`, `/correct`, `/tdd`, …).

The README's own claim: throughput without quality is not the goal; go deep on one agent, then
parallelize; the best spec is the code. Default routing in 0.15.20 sends code delegates to Grok
and the hardest judgment to Opus 5.5, overridable with `/setup-pstack`. The README names
that pair as the default panel.

That is a **worker style**, the same layer as matt / addy / gstack. It is not an outcome
catalog, and it has no independent verifier. Several of its principles ("prove it works",
"explain the number", "encode lessons in structure") are weaker forms of rules this repo
already enforces with a SHA-bound manifest. Copying the plugin in would add a second router
next to AGENTS.md and blow the instruction budget. The one-pack-per-worker rule exists because
routers fight.

---

## 3. Playbooks against the catalog

| pstack playbook | Already here | Decision |
|---|---|---|
| investigation | `research-brief`, `diagnose` | leave |
| bug fix | `root-cause` + `diagnose` | leave. pstack fixes in the same playbook; this catalog splits diagnosis from the authorized fix on purpose |
| perf | `speed-it` | fold the missing measurement questions; see §5 |
| hillclimb | `speed-it` keep-or-revert loop | rejected as a mission (`REJECTED.md`). A target instead of a budget does not change the oracle |
| runtime forensics / trace forensics | `root-cause`, `diagnose` | leave. No new oracle |
| feature | `ship-it` | leave |
| refactoring | `reshape-it` | leave |
| prototype | `design-twice` | leave |
| visual parity | `field-test-it` proof shape | rejected as a mission. A pixel oracle would be a tier. No tier was added |
| authoring a skill | this repo's own skill rules | leave |
| eval | `skills/*/evals/` | rejected as a mission. It tests the fleet, not the user's repo |
| babysit / shipping / autopilot-full / autopilot-stack / opening a pr | `ship-it`, `absorb-it`, `release` | **refused.** "Land even if CI flakes" contradicts `reviewed-sha-freshness` and the rule that a green check is not a review |
| autonomous run / orchestrate | the coordinator model | leave. Naming the technique is the ingredient-shaped entry this catalog removes |
| session pickup / pause safely | `liveness-resume` | leave |
| multi-phase plan | `mission-chaining`, `decompose-dag` | leave |
| worktree cleanup | `worktree_ops.py` | not a mission. Not touched |

---

## 4. Skills worth a decision

**Folded**

- `benchmark-checklist` + `principle-explain-the-number`. speed-it already required a sample
  size, a spread, pinned conditions, and a profiled bottleneck. It did not require the limiter
  ("why not twice as good?"), the arithmetic that a 10% slice cannot make the run 30% faster,
  an error count inside the timed region, or proof the timed work happened. An inconclusive
  number is now `unmeasured`. Playbook: `explain-the-number`. speed-it composes it. The
  performance lens in `risk-review` refuses a delta the playbook calls inconclusive.
- `/correct` + `principle-encode-lessons-in-structure`. compound-learn already refused silent
  `AGENTS.md` edits and already said "route a check to the suite". It did not say that a
  correction seen twice is a structure, in the order architecture → types → lint → test, docs
  last, proved RED on a past specimen. That ladder is `encode-lesson`, composed by floor-it
  (the mission whose oracle is a gate that fires). compound-learn points at it in one line.
  The ladder is not inside compound-learn: field-test-it's activation load was ~33,909 of
  34,000, and a page of new retro text there puts it over the cap.

**Taken in one sentence, not as a procedure**

- `blast-radius`. The job is not the caller list. It is the one fact the change is safe
  because of, proved by a run. `risk-review`'s completion line now says a clearance that
  rests on one safety fact is unproven until a run shows it. The playbook is at its 90-line
  cap, so the rest of the skill (the five-step certainty ladder, arena on wide diffs) was
  not copied.

**Already stronger here, so not adopted**

- `principle-prove-it-works`. "Run the real thing, not a proxy" is `runtime-prove` Part B
  plus the evidence manifest. pstack still allows a one-time eyeball. This catalog does not
  grade a trace.
- `show-me-your-work`. An append-only TSV the author writes, audited against their own
  transcript, is a weaker oracle than the manifest `verify.py` re-derives. Rejected as a
  mission.
- `create-verification-skill` / `maintain-verification-skill`. Generating
  `.cursor/skills/verify-<app>/` is a harness. Driving the real entry point and asserting
  persisted state is already Part B of `runtime-prove`, and on a device it is `field-test-it`.
- `principle-never-block-on-the-human`. `gate-classification` already auto-picks the
  reversible and parks the one-way door. pstack is more willing to skip the ask. Adopting
  that would weaken the one-way rule.
- `principle-sequence-verifiable-units`, `principle-make-operations-idempotent`,
  `principle-test-behavior-not-implementation`. The first two are `decompose-dag` /
  `mission-chaining` and the migration playbooks. The third is what `prove-it`'s mutation
  requirement is for. No new text.
- `/tdd`. `build-change` is already failing-first. pstack skips TDD unless asked or the bug
  is cheap to pin. This catalog does not skip it.
- `/interrogate`, `/arena`, `/swarm`, `/how`, `/why`. Review panels, parallel candidates,
  and code walkthroughs are worker-pack techniques (review-it, design-twice, research-brief).
  A mission named for the technique fails the identity test.
- `/unslop`, `/no-comments`, `/technical-writing`, `/typescript-best-practices`, `/bro`,
  `/ketchup`, `/teach`. Style and session-UX. Not outcomes.
- `/reflect`, `/automate-me`, `/recall`. compound-learn is the retro, and it is human-gated
  because auto-written agent rules are a known negative. Mining transcripts into a personal
  mode skill is the opposite of that finding.
- `/setup-pstack`, `/poteto-help`, `/make-bot-ui`. Plugin setup and a Grok Bot UI. Out of
  scope for a fleet catalog.

---

## 5. What changed in this tree

- `playbooks/explain-the-number.md`, composed by `speed-it`. The mission's measurement
  contract treats an inconclusive verdict as `unmeasured`. The attempt ledger still owns
  repeatability; the playbook does not restate the median-of-five rule.
- `playbooks/encode-lesson.md`, composed by `floor-it`. `compound-learn` points at it when
  a correction has happened twice, and still forbids a worker from committing `AGENTS.md`.
- `playbooks/risk-review.md`. The performance lens cites `explain-the-number`. Completion
  requires a run behind a one-fact clearance. The file stays at 90 lines.
- `THIRD_PARTY_NOTICES.md` names the MIT source. The playbooks are rewritten in this
  catalog's voice. They are not copies of the skill files.
- `docs/research/REJECTED.md` records the mission-shaped candidates this pass refused.
- No `metadata.proof` moved. Both new playbooks are doctrine. Neither has a binding run.

---

## 6. What this pass did not do

- Did not vendor pstack, poteto-mode, or any principle skill into `skills/`.
- Did not add a mission. The identity test was applied in `REJECTED.md`; a paraphrase of
  speed-it or floor-it would fail `validate.py`.
- Did not re-pin Orca. The 2026-10-09 completion plan still holds: pin is behind upstream,
  and pin-it is the mission that moves it.
- Did not add a `PIXEL` tier to field-test-it. The proof shape matches; the oracle does
  not exist here yet.
- Did not re-score gstack or the September packs. Those audits stand until something in
  them changes a proof.

The product gap pstack does not close is the one the 2026-10-09 plan already named: public
beta is blocked on a Linux mission run, a live external CI watch, and receipt-tree size.
A sharper measurement rule does not witness those.
