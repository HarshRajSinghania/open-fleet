# Product roadmap research — 2026-10-20

> **Dated snapshot (2026-10-20).** Read against main `42d28e4c` and the separately
> identified, unmerged PR #592 head `d9787142`. This is a research synthesis, not a
> new completion freeze, product benchmark result or mission proof-tier promotion.

The recommended direction is **reliable, independently evidenced portability**:
complete the existing launch controls, certify the runtimes already implemented,
and measure verification quality and operating cost before expanding the catalog.
The [current roadmap](../roadmap.md) carries priorities and issue links.

## Question and method

Which developments in GitHub implementations, practitioner discussion and academic
research materially change the next work for this product, after subtracting what
the current tree and closed issues already deliver?

Three research tracks answered that question: code/protocol inspection, academic
papers, and practitioner/release-state inspection. A separate reader checked a sample
of the primary citations and live repository state. Full briefs and limitations:

- [GitHub implementations and protocol contracts](2026-10-20-roadmap/github.md).
- [Academic evidence and bounded experiments](2026-10-20-roadmap/papers.md).
- [Practitioner signals and live release state](2026-10-20-roadmap/social.md).
- [Independent citation verification](2026-10-20-roadmap/verification.md).
- [Exact-commit GitHub source inventory](2026-10-20-roadmap/github-sources.json).

This is a targeted deep sample, not an exhaustive search of every repository, post
or paper. Twelve GitHub repositories received discovery checks; eight of those
received substantive source inspection, with `mvdan/sh` inspected additionally.
Twelve core papers had relevant full-text sections inspected; four further benchmark
papers were abstract-level discovery. The briefs distinguish those levels.

X access was limited. Indexed public posts supplied discovery pointers, but direct
post retrieval returned 403 and there was no authenticated platform search. Treg
was installed but unauthenticated, so no paid platform calls were made. X text, dates,
engagement, sentiment and demand are not treated as verified evidence. Accessible
author-owned writing supports the narrow practitioner observations below.

## Verified current state

At enumeration, the only open issues were [#235](https://github.com/ravidsrk/orca-fleet/issues/235),
[#508](https://github.com/ravidsrk/orca-fleet/issues/508),
[#526](https://github.com/ravidsrk/orca-fleet/issues/526) and
[#528](https://github.com/ravidsrk/orca-fleet/issues/528). The whole issue metadata
inventory was searched, including closed work, before drafting follow-ups.

| Surface | Observation | Roadmap consequence |
|---|---|---|
| Product identity | [Architecture](../../ARCHITECTURE.md): outcome missions, callable playbooks, runtime mechanisms and independent evidence | Keep new mechanisms in runtime/tooling; no new mission justified by this scan |
| Proof | `proof_status.py --check`: 2 external-run, 3 self-run, 17 doctrine-only at the inspected tree | Preserve earned tiers; published runs do not certify every adapter |
| Release | v0.7.1 published; Linux and external ship/review witnesses landed after October 9 | Do not recreate packaging or flagship-proof issues |
| Portability | #591 merged fourteen adapters; #592 corrections are a separate open PR | Follow with versioned, live conformance evidence; depend on the fixes before live certification |
| Branch protection | API requires `gates`, `verdict`, `guard`, `Greptile Review`; old verdict source is app 15368 | Finish the already implemented trusted `verdict-gate` deployment |
| Independent reviewer | H-10 still pending; `agentsalpha` permission read-back was `read`; reviewed-by search had no results | A real peer witness remains distinct from CODEOWNERS configuration |
| External monitor | #528 has implementation/drill receipts but the schedule is paused | Reuse #528 for activation, not another monitoring implementation |
| Attention budget | Existing policy says ASSERTED and defines a multi-run WIP protocol | Measure the curve; don't file another protocol-writing issue |

The GitHub settings facts above are observations of the read time, not permanent
properties. Search absence alone is not proof of no review anywhere. The API access
check and the written H-10 acceptance condition are the actionable evidence.

## GitHub findings that change the plan

| Owning source inspected | What it establishes | Local delta |
|---|---|---|
| [LangGraph conformance runner](https://github.com/langchain-ai/langgraph/blob/1400d25b7b88cfa055c55b8a82bd95b7c25caef1/libs/checkpoint-conformance/langgraph/checkpoint/conformance/validate.py) | Capabilities can be evaluated with explicit pass/fail/skip observations | Distinguish adapter declarations, mocked tests and installed-runtime certification |
| [OpenHands hook executor](https://github.com/OpenHands/software-agent-sdk/blob/33d8aa29c3078d074799e2fbf5e847aeb2d71360/openhands-sdk/openhands/sdk/hooks/executor.py) | Hook exit semantics matter at the actual consumer | Verify a released upstream consumes and enforces our emitted hook configuration |
| [mvdan/sh parser tests](https://github.com/mvdan/sh/blob/f6d205ab76b3e5e89073130c2229a43be04e1e2a/syntax/parser_test.go) | External-shell checks and dialect-specific tests are implemented | Turn the repeated heredoc/escape regressions into a bounded differential corpus |
| [LangGraph checkpoint ordering](https://github.com/langchain-ai/langgraph/blob/1400d25b7b88cfa055c55b8a82bd95b7c25caef1/libs/langgraph/langgraph/pregel/_loop.py) | Persistence ordering is an explicit recovery concern | Reproduce hard-kill windows and add durable launch intent/reconciliation if confirmed |
| [gstack train verifier](https://github.com/garrytan/gstack/blob/c580561e8a5ac08e6cbdd52c7a0ce521ab6310a5/lib/ship-queue-train-verify.ts) | Current-head/prefix-tree checks are executable | Mechanize the existing single-conductor rule and resumable merge receipts |
| [A2A owning proto](https://github.com/a2aproject/A2A/blob/1205f45951ca97c209634ce6046180e38c5dfb30/specification/a2a.proto) | A transport AgentCard has defined interfaces, versions, modes and skills | Our custom offline descriptor is not evidence of standard transport compatibility |
| [Matt's memory recipe](https://github.com/mattpocock/skills/blob/5beb35b040e3de97e54fa9e386d7e42d15c295c2/skills/in-progress/chief-of-staff/SKILL.md) | Dated, commit-cited memory is a proposed working method | Add inspectable provenance/currentness to existing bounded hints; no memory platform needed |

The launch-window item is a code-derived hypothesis awaiting the proposed crash
test, not an observed data-loss incident. The conductor finding is scoped to the
inspected tree. Mutable upstream main is not a selected production dependency.

Two earlier competitive claims need qualification. [Superpowers' verification recipe](https://github.com/obra/superpowers/blob/bb92a77741419a4ab5f06e711a283343f1ada0c3/skills/verification-before-completion/SKILL.md)
already describes fresh evidence and a revert-based regression check; a recipe is
not the same as runtime enforcement, but that overlap must be acknowledged.
[Ruflo's witness entry point](https://github.com/ruvnet/ruflo/blob/f5f2e40c318c3c390b057333bd971a6d5a9d5e28/plugins/ruflo-core/scripts/witness/verify.mjs)
checks signatures and marker/hash state. We did not observe acceptance-test or
mutation execution in that entry point; this says nothing universal about all its
other paths. The inspected witness key is deterministically derived from public
commit data, so that signature is not evidence of an independently trusted signer.
No competitor adoption forecast or zero-prior-art claim survives this scan.

## Academic findings that change the plan

Every implication in the final column is our inference. These papers were read,
not reproduced on this product; the newest preprints especially need replication.

| Primary paper | Bounded finding | Resulting work |
|---|---|---|
| [Why Do Multi-Agent LLM Systems Fail? v3](https://arxiv.org/abs/2503.13657v3) | Failure taxonomy separates design, alignment and verification | Label observed failure events without using traces as completion proof |
| [Scaling Agent Systems v3](https://arxiv.org/abs/2512.08296v3) | Coordination effectiveness depends on task structure and tool load | Measure verified-CLOSED throughput at varied WIP; import no universal agent-count threshold |
| [Evaluating AGENTS.md v3](https://arxiv.org/abs/2602.11988v3) | Context-file benefits and cost are not automatic in the studied tasks | Run paired, safety-preserving instruction-load ablations; don't delete governance |
| [Randomness in Agentic Evals v3](https://arxiv.org/abs/2602.07150v3) | Agent evaluation varies across runs, including low-temperature settings | Repeat measurements and show uncertainty instead of single-run rankings |
| [UTBoost](https://arxiv.org/abs/2506.09289v1) | Added tests expose weaknesses in some accepted patches | Add counterexamples and independently authored tests |
| [SpecBench v2](https://arxiv.org/abs/2605.21384v2) | Visible feature checks can miss held-out feature combinations | Separate public development traps from independently held challenge cases |
| [SWE-Bench Pro Verified v3](https://arxiv.org/abs/2609.08149v3) | Evaluation artifacts/history can leak information | Audit benchmark fixtures for leakage; preserve legitimate project history |
| [MemTrace v3](https://arxiv.org/abs/2610.04838v3) | Recalled evidence can become invalid after state changes | Bind hints to source state, tests and dependencies; mark unknown/superseded |
| [Transmissible reward hacking v2](https://arxiv.org/abs/2610.12822v2) | Bypass strategies can propagate through code, plans and memory in the studied settings | Test multi-step worker/handover attacks against an external action/state oracle |
| [CapScope](https://arxiv.org/abs/2609.08371v1) | Capability-scoped authority is narrower than arbitrary text instructions | Test actual authorization boundaries; don't confuse capabilities with full containment |
| [MalSkillBench v3](https://arxiv.org/abs/2606.07131v3) | Static scanning and instruction detection cover different attack surfaces | Include benign controls and observed effects in skill/update drills |
| [The Verification Horizon v2](https://arxiv.org/abs/2606.26300v2) | Verification quality has distinct faithfulness/robustness/scaling questions | Report false acceptance, false rejection, coverage, time and oracle limits separately |

The [paper brief](2026-10-20-roadmap/papers.md) records exact version dates, full-text
sections, additional benchmark leads and important limitations. It also rejects
older-version sample/regression figures as current facts and universal readings of
the scaling paper's thresholds. No headline gain is promised for orca-fleet.

## Practitioner signals and provenance standards

[The Orchestration Tax](https://addyosmani.com/blog/orchestration-tax/) and
[Loop Engineering](https://addyosmani.com/blog/loop-engineering/) are author-owned
design arguments about review capacity and persistent workflows. They reinforce
the measurement direction; they are not customer interviews, adoption counts or
controlled productivity evidence. X-derived posts remain unverified leads in the
social appendix. Machine-generated X trending summaries were discarded.

[SLSA v1.2 artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts)
distinguishes signature, subject digest and configured trust identity from a field
being present. Our [provenance documentation](../compliance-provenance.md) already
states that the offline retention-receipt binding is unimplemented. Complete that
specific binding; do not claim log availability, retention enforcement, or legal
conformance from it.

## Prioritization and rejected directions

The [roadmap](../roadmap.md) maps findings to W0–W3 and detailed GitHub issues.
Prioritize directly observed launch controls first, then portable-runtime safety and
verification coverage, then measurements and context/interoperability refinements.
Do not let the larger research program silently become a new 1.0 release gate.

Existing work reused: #235 marketplace, #508 re-pin cadence, #528 monitor activation,
#526 release checklist, initial VF-Bench, negative controls, signed dispatch, injection
envelopes, episodic hints, overlap prediction, handover packets and RPI adapters.
No new missions are justified by an ingredient such as memory or protocol transport.

Deferred for lack of a validated incremental case: more adapters before certification,
a hosted control plane, a new vector/graph memory database, automatic policy learning,
a public competitive leaderboard before reproducibility, and automatic default-branch
promotion. Newer upstream code is a research input, not permission to re-pin it.

## Review status

This report supports a proposed roadmap and filed work; it does not certify any of the
proposed mechanisms. The independent citation report records the checked sample and
failed/limited retrievals. Scope, developer-experience and engineering review outcomes
are recorded in the roadmap's terminal review section. Human release and spending
decisions remain open rather than being supplied by the research agents.
