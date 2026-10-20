# Academic research brief for the orca-fleet roadmap

Status: **research complete; independent citation sample checked.** Read-only research worker; no repository changes, issue writes, benchmark runs, or new empirical product claims. Read date: **2026-10-20**. Repository inspected at **d9787142827f4840cd6a20a5fea7d02d683aee40** (PR #592 head, not an assertion that it is merged).

## Question and decision

Which primary arXiv/academic results materially change the evaluation, context/memory, coordination, or security roadmap for orca-fleet's SHA-bound independent verification architecture?

Decision waiting on the answer: which *new, bounded implementation or measurement packages* belong after the runtime-provider integration, without reopening already delivered negative controls, memory hints, handover packets, overlap detection, privilege narrowing, or a generic new mission catalog.

## Answer

The literature supports investing in verification quality and measuring real execution before expanding orchestration. It does **not** establish that a larger agent fleet, longer instruction file, generic memory graph, or model-graded trace makes this product more reliable. Six packages below convert that evidence into local tests. Their priorities and acceptance thresholds are engineering recommendations, not paper results.

The strongest immediate gap is the distance between a frozen, valid *evidence envelope* and complete *semantic behavior*. An independent verifier can faithfully rerun a weak test suite. The existing VF-Bench already says which legs its public corpus does not sample and calls held-out/temporal refresh a follow-up. Separately, the existing behavioral evaluator is explicitly catalog tooling, not proof; the injection suite checks fences and a verdict rubric rather than live unauthorized effects; and episodic hints retrieve historic claims without checking their applicability to the current tree. These are distinct surfaces to measure, not reasons to weaken the existing SHA/review/negative-control protocol. [Local owners: `ARCHITECTURE.md`, `bench/vf-bench/README.md`, `scripts/eval.py:1-33, 907-965`, `runtime/scripts/search_sessions.py:211-278`, `tests/test_injection_drills.py`.]

## Primary evidence register

All URLs below are version-pinned primary paper pages. Abstracts were checked against the arXiv version history; core rows P1–P12 also had full HTML opened, with the relevant sections inspected. No paper result was reproduced locally. Numerical results are deliberately sparse to avoid implying transportability to orca-fleet.

| ID | Primary source, version and version date | Read finding and scope caveat |
|---|---|---|
| P1 | [Why Do Multi-Agent LLM Systems Fail? — arXiv:2503.13657v3, 2025-10-26](https://arxiv.org/abs/2503.13657v3) | MAST separates system design, inter-agent alignment, and task verification failures. Use its taxonomy for failure labeling, not trace grading as the completion oracle. The paper's LLM annotator and observational dataset do not causally prove a particular runtime control works. |
| P2 | [Towards a Science of Scaling Agent Systems — arXiv:2512.08296v3, 2026-04-08](https://arxiv.org/abs/2512.08296v3) | Controlled architecture comparisons find coordination depends on task decomposability and tool workload. The current revision covers 260 configurations and reports cross-validated R²=0.373; search snippets often retain older v1 sample/regression figures. Its body retains the widely repeated ~45% threshold and 17.2×/4.4× *trace-level* error multipliers, but these are not universal safety constants or measurements of our verified-CLOSED throughput. §5 limits cross-domain prediction and larger-collective conclusions. |
| P3 | [Evaluating AGENTS.md — arXiv:2602.11988v3, 2026-09-29](https://arxiv.org/abs/2602.11988v3) | §4 finds no significant general resolution gain from context files while cost increases; developer-written files outperform generated ones. §4.4 finds no strong simple length effect, so “shorter is always better” is also unsupported. §5 limits evaluation to Python task resolution and explicitly leaves security/performance-quality effects open. This is evidence to run a controlled instruction ablation, not to delete governance. |
| P4 | [On Randomness in Agentic Evals — arXiv:2602.07150v3, 2026-03-25](https://arxiv.org/abs/2602.07150v3) | Repeated SWE-Bench-Verified runs vary even at temperature zero; §3 recommends repeated runs and power analysis rather than single-point improvement claims. Two scaffolds and three open-weight model families are studied. Both scaffolds preserve append-only contexts (§2.1), so compaction behavior remains untested. |
| P5 | [UTBoost — arXiv:2506.09289v1, 2025-06-10; ACL 2025](https://arxiv.org/abs/2506.09289v1) | Augmented tests uncover accepted patches that fail to solve the intended issue. The Limitations section says augmentation relies on tasks with at least one original passing candidate, and experiments use one generator model. It supports independent counterexample tests, not automatic trust in model-generated tests. |
| P6 | [SpecBench — arXiv:2605.21384v2, 2026-09-09](https://arxiv.org/abs/2605.21384v2) | Visible feature checks can saturate while held-out feature combinations fail. Appendix A explicitly says a small visible/held-out gap does not certify all specification behavior. Thirty systems tasks and a finite held-out suite do not justify calling every generalization error deliberate cheating. |
| P7 | [SWE-Bench Pro Verified — arXiv:2609.08149v3, 2026-10-09](https://arxiv.org/abs/2609.08149v3) | §3 identifies leakage through residual Git objects, hidden evaluation files, network sources, and task metadata. §5.2 acknowledges domain blocking/cleanup can miss routes and residual data. Apply leak controls to evaluation fixtures only; real work must retain its legitimate ancestry and review history. |
| P8 | [MemTrace: State-Consistent Memory for Long-Horizon Coding Agents — arXiv:2610.04838v3, 2026-10-10](https://arxiv.org/abs/2610.04838v3) | §3 binds immutable observations to state and explicit supersession; §3.3 validates evidence before reuse. For test evidence, unchanged target code alone is insufficient; tests and dependencies matter. A very recent preprint with same-backbone/harness comparisons; reported benchmark gains are unreplicated here. Do not confuse it with two other 2026 papers also named MemTrace. |
| P9 | [Reward Hacking as a Transmissible Strategy in Multi-Agent Coding Systems — arXiv:2610.12822v2, 2026-10-12](https://arxiv.org/abs/2610.12822v2) | §§5–6 show evaluator-bypass strategies propagate via code, shared memory, feedback, and planner instructions. Appendix A limits the setting to Python tasks, three known pytest mechanisms, and controlled source training; it recommends independent hardened evaluation plus treating peer artifacts as untrusted. This is a fresh preprint, not a production prevalence estimate. |
| P10 | [Authority Is Not a String (CapScope) — arXiv:2609.08371v1, 2026-09-08](https://arxiv.org/abs/2609.08371v1) | Evaluates trusted preflight ceilings, per-principal capabilities, and monotonic delegation on five Python tasks/five injection surfaces. §2.2 explicitly excludes confidentiality and transitive effects of permitted commands from its guarantee. Its command wrapper permits read/navigation outside a principal's read scope. A capability table alone is not a sandbox or data-flow boundary. |
| P11 | [MalSkillBench — arXiv:2606.07131v3, 2026-06-19](https://arxiv.org/abs/2606.07131v3) | Runtime-confirmed malicious skills span code and instruction behavior; the abstract warns static code scanners and injection classifiers each cover only part of that surface. Its wild samples are campaign-concentrated. It supports benign controls plus runtime-observed effects in our own skill/update tests, not importing arbitrary malicious skills into host sessions. |
| P12 | [The Verification Horizon — arXiv:2606.26300v2, 2026-06-29](https://arxiv.org/abs/2606.26300v2) | Characterizes verifier quality by scalability, faithfulness, and robustness, examining task-specific test/rubric/user/agent evaluators. Useful for separating our metrics and identifying oracle limits; it is not a proof that any proposed agent judge or our verifier is sound on all tasks. |

Supporting benchmark directions inspected at abstract level (not used for quantitative product claims): [Terminal-Bench, arXiv:2601.11868v1, 2026-01-17](https://arxiv.org/abs/2601.11868v1) provides varied terminal environments with executable checks; [SWE-EVO, arXiv:2512.18470v6, 2026-05-22](https://arxiv.org/abs/2512.18470v6) targets coordinated multi-file evolution; [SWE-Milestone, arXiv:2603.13428v4, 2026-07-21](https://arxiv.org/abs/2603.13428v4) targets continuous milestone DAGs; [SWE-rebench V2, arXiv:2602.23866v2, 2026-06-01](https://arxiv.org/abs/2602.23866v2) offers multilingual executable tasks and confounder metadata. Their task designs are candidates for a small licensed pilot, not evidence that orca-fleet currently passes them.

## Six candidate work packages

### A. Extend VF-Bench with isolated-leg and compositional counterexamples — P1

**Evidence → gap:** P5–P7 show that accepted test results can conceal omitted semantics or leakage. `bench/vf-bench/README.md` explicitly lists unsampled intent, lighting, reviewer-mode, provenance, signed-dispatch, hidden-criterion, zero-kill/mutant-survived, and oracle-scope legs. The missing coverage is acknowledged, so file a narrowly scoped extension rather than claiming a newly discovered bypass.

**Deliver:** extend the deterministic public corpus for those named legs; add a separately versioned challenge set that combines valid envelope fields with an intentionally incomplete behavior (for example feature A and B pass alone, A→B violates an already frozen criterion). Challenge authors and verifier implementers should be separate roles. A holdout can be time-separated from tuning; “private forever” is unnecessary and conflicts with reproducibility.

**Acceptance:** each trap satisfies every other leg, asserts the exact intended rejection reason, and turns GREEN when only its targeted check is disabled. Matched honest controls remain GREEN; add honest variants that differ in implementation to measure false rejection. Record corpus digests, versions, task author, evaluator version, skips, and separate public/challenge denominators. Preserve the existing false-done CI gate; do not combine agent capability and gate soundness into one score. State explicitly that passing this corpus is bounded evidence, not universal soundness.

**Duplication:** #306/#371/#412 already delivered prior traps and CI pinning. This package covers the README's remaining legs and semantic challenge design, not those delivered tasks. A second source inspection found the same unsampled list; the roadmap consolidates it into R07 and a distinct independent-replay follow-up, R08.

### B. Build a repeatable cross-runtime mission outcome pilot — P1

**Evidence → gap:** P4 warns against single-run rankings; the supporting long-horizon benchmarks make cumulative regressions observable. `scripts/eval.py` currently runs one headless agent per case, combines workspace checks with a trace rubric, and labels output catalog tooling. Provider unit tests cannot establish live mission performance across harnesses.

**Deliver:** a small opt-in execution harness for actual mission/runtime combinations: an isolated defect repair, a serialized overlapping change, and a two-or-more-stage evolution/compaction-resume case. Freeze fixtures and acceptance before runs; score exact workspace state with coordinator verification and retained artifacts. Preserve the existing catalog suite's role.

**Acceptance:** pin task/source/image/harness/model versions and budgets; run at least three independent pilot attempts per measured cell, then publish uncertainty and a power/sample plan before any claimed small improvement. Record first-attempt success, all-attempt consistency, verified closure, false-done/false-refusal, wall time, verification latency, and usage where available. Unavailable credentials, unsupported capabilities, and skips remain explicit missing cells. A harmless runner shim proves matrix wiring in CI; real agent results remain opt-in, never fabricated from shim passes.

**Duplication:** does not reopen #560 injection fence tests, the closed RPI adapters, or promote behavioral traces to mission proof. Search across all issue titles found no open outcome-pilot issue; #526 remains the release parent. Coordinate with any real-provider qualification issue from the other research unit.

### C. Publish the first protocol-compliant WIP throughput curve — P1/P2

**Evidence → gap:** P2 makes topology/task dependence a measurement problem. `runtime/attention-budget.md` still says **ASSERTED**, requires ≥3 differing WIP runs, and explains why the historical solo run does not count. Closed #51 supplied the measurement protocol; it did not supply its qualifying curve.

**Deliver:** a preregistered, comparable workload at `builders=1`, `2`, and `3`, with a fixed review/verification budget, repeated enough to show variance. Record verified-CLOSED units/hour, queue latency, rework, freshness violations, and model/tool spend. Balance task difficulty and account for cache/warmup/order effects; neither more builders nor more simultaneous reviewers should silently increase the resource budget.

**Acceptance:** retain ≥3 protocol-compliant run reports at differing WIP settings, with every wave's existing required row and exact-SHA closure evidence; plot throughput and rework with raw denominators and uncertainty; explicitly distinguish builder utilization from verified closure. Recommend a cap from these data or leave it ASSERTED when the experiment is inconclusive. Negative data is acceptable. No adaptive cap increase ships before qualification.

**Duplication:** new empirical follow-through to [closed #51](https://github.com/ravidsrk/orca-fleet/issues/51), not another protocol-writing task. Existing `attention-budget.md` and `run_report.py` stay authoritative. The paper's thresholds do not replace the local curve.

### D. Qualify instruction load with safety-preserving ablations — P2

**Evidence → gap:** P3 is directly relevant to the large mandatory activation surface, but does not justify assuming that raw token reduction improves outcomes. `ARCHITECTURE.md` deliberately carries a 34,000-token activation cap and says a contract/reference restructuring is an unattempted option.

**Deliver:** extend B's fixtures with current full activation vs a phase-loaded candidate containing the same normative contracts, with document version/digests captured. Governance and one-way-door controls remain mechanically identical in both arms. Analyze which instructions are actually needed per phase before changing any cap.

**Acceptance:** preregister task/agent/budget/attempt pairing; compare verified outcome, gate violations, unauthorized effects, cost, and context use. A mutant deleting a required rule or bypassing a deferral cue must fail its relevant workspace/gate check. Publish neutral/negative findings; change a mission's loading contract only after no safety regression and a supported local benefit, otherwise preserve the existing load. Treat paper findings on Python resolution as external motivation, not a predicted local percentage saving.

**Duplication:** existing activation-load accounting/deferral #276/#303 is shipped. This is the empirical efficacy qualification it does not provide, not another static length lint or automatic AGENTS.md rewrite. Depends on B's outcome instrumentation.

### E. Make episodic hints explicit about stale and superseded state — P2

**Evidence → gap:** P8 distinguishes historical evidence from currently applicable evidence; P9 makes peer memory another influence channel. `build_episodic_hint` already sanitizes and caps hints, but emits `(status)`/`invariant`/`parked` snippets from matching manifests without checking ancestry, current entity hashes, or later unit supersession.

**Deliver:** optional structured source metadata for existing hints: source repo/run/unit, source head/tree or file digest when known, observation class, and explicit supersedes links. Preserve useful historical lessons while labeling observations as current, historical, superseded, or unknown. Do not turn a retrieved old test pass into completion evidence; only a new independent verification can do that.

**Acceptance:** fixtures cover failure→fix→pass, later regression, branch divergence, unchanged source with changed test/dependency, rename/deletion, missing source metadata, and malicious snippet/banner. Current-state hints cannot assert a resolved failure is still active or reuse a stale pass; historical queries can still retrieve both with labels. Unknown dependencies imply unknown/currentness, not freshness. Retain ≤15-line default, injection fencing, and deterministic ranking. Compare usefulness on B before introducing an embedding store or full repository graph.

**Duplication:** episodic hints and failure handover are already delivered in the 2026-10-18 research adoption; this is validity/supersession metadata and tests only. No title-matching open or closed issue named “memory” was found; broader issue search also found no open duplicate.

### F. Run live, paired effect-based security and propagation drills — P1

**Evidence → gap:** P9–P11 distinguish text detection from effects under authority. Closed #560 explicitly landed the corpus/runbook while leaving the live worker leg owed. Current injection tests validate labels/fences and a returned verdict rubric; those are not a measurement of unauthorized writes or sibling contamination during actual execution.

**Deliver:** use disposable fixture repositories, synthetic credentials, a local recording endpoint, and two workers with distinct roles. Exercise poisoned issue text, test output, repository instructions, skill update text, peer handover, and episodic hints. Include a plan/code/memory chain that proposes disabling the independent oracle; the acceptance oracle itself remains outside the worker. No real credential or production target is needed.

**Acceptance:** paired benign and injected cases run under pinned real harness/provider/profile combinations. Report separately injection detection, requested unauthorized action, actual side effect, benign task completion, and false-positive denial. Filesystem/network/process receipts and final repository state are the oracle; the worker saying “I resisted” is insufficient. A deliberately disabled enforcement control must cause a harmless canary side effect, proving the drill can detect failure. Record coverage gaps per provider; a successful subset cannot certify all 14 adapters or all nine harnesses. Use in-boundary backdoor attempts as well as obvious out-of-tree writes, because granted authority can be misused.

**Duplication:** explicit follow-through to [#560](https://github.com/ravidsrk/orca-fleet/issues/560), not a new generic injection corpus; #590 already shipped monotonic profile narrowing, so do not file that again. Coordinate with the parent security/containment package; capabilities may be investigated later, but shell string checks and the CapScope paper are not sufficient grounds to claim OS isolation.

## Suggested ordering and limits

Start A and B alongside the release's existing human-owned gaps. F uses B's real-provider harness but can develop harmless fixtures independently. C uses B's outcome accounting. D waits for B; E can start with deterministic currentness fixtures, with usefulness measured through B. These additions should not silently make every research experiment a 1.0 blocker: retain #526's existing release contract, and add a blocker only for a demonstrated product defect or a deliberately agreed release criterion.

Reject for now: a new mission named for memory or coordination (these are runtime mechanisms); a full graph/vector database before local hint measurements; fixed agent-count rules imported from P2; self-review or trace monitors replacing independent acceptance; forced removal of AGENTS.md/governance from P3; wholesale deletion of real repository history based on benchmark leakage research; importing malicious public skills into host workers; a public leaderboard before the corpus/runner has independent reproducibility. These are product judgments inferred from the source limits and the repository architecture, not paper conclusions.

Searches included combinations of arXiv agent verification/reward hacking, multi-agent scaling/failure, SWE-bench/Terminal-Bench reliability, AGENTS.md/context, long-horizon coding memory/evolution, prompt injection/capabilities, and malicious skills. Secondary discovery hits were followed to primary arXiv pages and never used as claim authorities. GitHub open issue inventory contained only #528/#526/#508/#235 at read time; closed #51/#560/#590 and all-state evaluation/verifier searches were checked for duplicate scope. This is a targeted deep sample, not an exhaustive literature review or evidence about unpublished/private products.

Open residue: results from the newest October papers require independent replication; behavior on orca-fleet is unmeasured; available compute/authentication may constrain the pilot matrix; a source-reachable held-out set is only time-separated, not permanently secret; translated generated tests require review; dependency-complete state validity is harder than file-hash equality. A verifier worker must now sample claims/versions/ownership and record failures before this brief may support a freeze.

## Independent verification leg

A separate reader reopened full version-pinned HTML for P2, P3, P4, P5, P8 and P9;
all six supported the scoped claims and limitations. [The verification record](verification.md)
names the checks. P1, P6, P7, P10–P12 and the four abstract-level benchmark leads were
not independently sampled. No paper's measured gains are claimed for this product;
priorities and acceptance thresholds remain engineering proposals, not paper results.
