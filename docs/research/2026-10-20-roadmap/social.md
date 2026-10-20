# Practitioner signals and release-state research — 2026-10-20

Question: Which practitioner signals and observable release gaps should influence orca-fleet's next roadmap without repeating shipped work?

Decision waiting on the answer: recommend the order of release assurance, portability evidence, and evaluation investment; this research does not authorize a release or new runtime policy.

## Answer

Prioritize independently witnessed reliability and review capacity over adding more orchestration topology. This is a recommendation, not a measured product outcome. The existing product already supplies worktrees, scheduling policies, SHA-bound manifests and retry handovers; the useful next step is measuring their end-to-end behavior.

## Sources and discovery pointers, read 2026-10-20

- https://addyosmani.com/blog/orchestration-tax/ (page date 2026-05-24): the author describes review and integration as a serial human bottleneck and recommends sizing concurrency to review capacity. This is practitioner opinion, not a controlled experiment. https://x.com/addyosmani/status/2059844244907696186 is a related X publication located through search; direct fetch returned 403, so its exact contents and date are not independently verified here. The website is the supported citation.
- https://addyosmani.com/blog/loop-engineering/ (page date 2026-06-07): the author's proposed loop combines discovery, worktrees, skills, connectors, subagents and durable state, with explicit token-cost concerns. The product-availability comparisons on that page were NOT adopted as verified platform facts.
- https://x.com/tinkerersanky/status/2063904707345563648 — unverified discovery pointer from indexed search. Direct post retrieval was unavailable; exact content, date and product availability are not verified.
- https://x.com/odysseus0z/status/2063957851052347901 — unverified discovery pointer from indexed search; no exact wording, date or observed implementation claim is used.
- https://x.com/premqnair/status/2061921827270906028 — unverified discovery pointer; direct open returned 403. No feature, launch-date, performance or adoption claim is used.
- https://github.com/ravidsrk/orca-fleet/issues/526 and https://github.com/ravidsrk/orca-fleet/issues/528: live bodies/comments show Linux proof and external ship/review runs landed, with external CI monitor activation still open. Four issues were open at enumeration: #235, #508, #526, #528. Snapshot only.
- https://api.github.com/repos/ravidsrk/orca-fleet/branches/main/protection (authenticated `gh api` read): required status contexts are `gates`, `verdict`, `guard`, `Greptile Review`; `verdict` has app_id 15368; required_pull_request_reviews is null. This establishes current settings, not the absence of every other possible authorization check. The observed fields are independently repeated in the verification record; no credential or secret values were retained.
- Tree at main `42d28e4c7413fc369ebe79ae909fce613ca216b7`: `TODOS.md` and `.github/workflows/verdict-gate.yml` already document the old-name/source-forgery gap and its trusted-workflow mechanism. `docs/completion/HUMAN_ACTIONS.md` leaves H-10 peer acceptance and review pending. `runtime/attention-budget.md` explicitly labels WIP caps ASSERTED; #51 closed the measurement-protocol work, not the >=3-run experiment.

## Searches and limitations

Searched indexed X pages for coding-agent orchestration, worktrees, verification, review costs, and the named authors Addy Osmani, Boris Cherny, Peter Steinberger and Cory House. Many searches returned only unrelated X transparency reports, machine-generated trending summaries, or nothing. Those results were rejected. No claim of comprehensive X coverage or recent demand quantification is made. Direct opens of the posts above and X links in the author's blog returned 403. Treg CLI 0.26.0 was present but `treg balance` reported unauthenticated; no platform API batch was run and no paid calls were made. No local scrapers, cookies or login bypasses were used.

## Product implications (inferences)

1. Create a settings-completion issue for authenticated `verdict-gate` activation and a separate independent-review witness issue, referring to the already closed implementation tickets #452/#530. Do not duplicate #528 monitor activation or #235 marketplace submissions.
2. Measure verified-CLOSED throughput and review wait time using the existing attention-budget protocol before proposing larger worker caps. Keep raw event identity and scope stable across retries and takeover; distinguish missing billing information from zero cost.
3. Treat recurring loops and multi-provider support as existing architecture. File empirical certification and recovery drills instead of another orchestration framework.
4. Keep public-beta, 1.0, and post-1.0 research scopes separate. New evaluations should not silently rewrite the September frozen completion definition.

## Independent verification

The separate reader checked 15 social/release references or state observations:
14 supported within their stated limits, one direct X source unverifiable. Six
additional checks included four supported observations and two GNU sources limited
to indexed owning text. See [the full record](verification.md). Every X exact-content
or date claim remains unverified; only the accessible author-owned sites and official
repository observations support the recommendations. No market-demand measurement is claimed.
