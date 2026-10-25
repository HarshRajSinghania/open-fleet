# Prompt Recipes for Developers

[Documentation Hub](README.md) · [Mission Selector](missions/README.md#choose-by-task) · [Getting Started](getting-started.md)

Copy and adapt these prompts into your **coding-agent session inside the target repository** after completing [prerequisite setup](getting-started.md#prerequisites).

> [!TIP]
> **Anatomy of a strong mission prompt:**
> 1. **Target & scope:** Name the PR, issue filter, audit file, directory, or user journey.
> 2. **Oracle / baseline command:** State the test, lint, or benchmark command the fleet should use.
> 3. **Stop condition:** Specify which terminal state to stop at (for example, `"Stop at the promotion PR"`).

---

## 1. Plan, Build & Ship

### Chart an ambiguous epic (`map-it`)

Use **[map-it](missions/map-it.md)** when a goal spans multiple subsystems and has unresolved architectural forks:

```text
Map this epic: add multi-tenant workspace isolation to the billing and webhook services.
Inspect src/billing, src/webhooks, and prisma/schema.prisma.
Surface the architectural forks one question at a time with a recommended option,
freeze the decision map, and output a decompose-dag task graph ready for ship-it.
```

### Build and ship a bounded feature (`ship-it`)

Use **[ship-it](missions/ship-it.md)** when requirements are ready to freeze and implement:

```text
Ship this: add GET /healthz to the API using the existing router.
Return version and database connectivity; return 503 when the database is unavailable.
Cover both responses with integration tests using `pnpm test` as the baseline command.
Keep the existing deployment configuration. Stop at the promotion PR (PROMOTION_READY).
```

### Drain an inbound contributor PR queue (`absorb-it`)

Use **[absorb-it](missions/absorb-it.md)** to evaluate, test, and land open community pull requests:

```text
Absorb the open pull requests labeled "community" on this repository.
For each PR, verify a RED test on base and GREEN on head, preserve contributor authorship,
refute invalid PRs with a reproduction, and park PRs needing author changes with a clear ask.
Stop at the promotion PR.
```

---

## 2. Fix, Sweep & Stabilize

### Drain an audit or issue backlog (`clean-sweep`)

Use **[clean-sweep](missions/clean-sweep.md)** for a finite list of defects, tracker issues, or inaccurate documentation claims:

```text
Clean-sweep the findings in docs/audits/retry-path.md.
Reproduce each finding first, fix confirmed defects in isolated PRs against BASE,
and prove each fix with a test that fails on revert.
Re-enumerate the audit at close until DRY, and stop at the promotion PR.
```

### Eradicate flaky tests across a suite (`deflake-it`)

Use **[deflake-it](missions/deflake-it.md)** when intermittent failures break CI:

```text
Deflake the test suite under tests/integration/.
Pull recent failure history via `gh run list`, reproduce each flake under stress,
fix the root timing or state-leak cause, and verify a consecutive-green streak
both locally and in CI.
```

### Reproduce and fix a mobile/device-only bug (`field-test-it`)

Use **[field-test-it](missions/field-test-it.md)** when a bug only manifests on a real device, simulator, or driven browser:

```text
Field-test the checkout sheet keyboard overlap bug on the iOS Simulator (EMULATOR tier).
Reproduce the overlap in a ledgered simulator session, fix the layout constraint,
re-verify at head_sha on the simulator, and run a revert negative control on-target.
```

---

## 3. Review, Diagnose & Prove

### Run a read-only, SHA-bound PR review (`review-it`)

Use **[review-it](missions/review-it.md)** for an independent `GO` / `NO-GO` verdict with zero code modifications:

```text
Review PR <owner/repo>#123 against its description and issue #120.
Evaluate repo standards, spec fidelity, and test adequacy, plus security and data-migration
lenses if triggered by the diff. Return a GO/NO-GO verdict bound to the head SHA,
with an exact file:line quote for every finding.
```

### Diagnose a hard intermittent bug (`root-cause`)

Use **[root-cause](missions/root-cause.md)** when you need a demonstrated explanation before writing a fix:

```text
Diagnose duplicate orders during mobile checkout.
The failing request IDs and timestamps are in docs/incidents/duplicate-orders.md.
Reproduce the symptom in staging, enumerate rival hypotheses, falsify them with
quoted evidence until one survivor remains, and produce a fix handoff brief.
```

### Close test gaps with mutation-audited tests (`prove-it`)

Use **[prove-it](missions/prove-it.md)** when line coverage hides weak assertions:

```text
Close the test gap on refund authorization and webhook signature verification in src/payments/.
Run `pytest tests/payments` as the baseline, freeze the critical paths, and prove that
every new test fails when a behavior-changing mutation is injected.
```

### Establish an enforced CI quality bar (`floor-it`)

Use **[floor-it](missions/floor-it.md)** to wire and prove repository-wide CI gates:

```text
Set the quality bar for this repository across type-checking, lint, secret scanning, and test coverage.
Wire one deterministic check per dimension into CI, prove each check turns RED on an injected
violation before enabling enforcement, and add a floor-guard against bar-lowering diffs.
```

---

## 4. Audit, Harden & Attest

### Close the security loop (`harden-it`)

Use **[harden-it](missions/harden-it.md)** for threat modeling, exploit verification, remediation, and re-attack:

```text
Harden the authentication and session-token endpoints in src/auth/.
Build a threat model, prove exploitable P0/P1 findings with non-destructive PoCs,
land fixes with regression tests, re-attack every fix in a fresh session, and run
a clean re-audit before stopping at the promotion PR.
```

### Meet a quantitative performance budget (`speed-it`)

Use **[speed-it](missions/speed-it.md)** when user journeys exceed latency or throughput targets:

```text
Bring checkout submit and order-history load within a p95 budget of 2.5 seconds.
Freeze the measurement contract on staging with the seeded dataset first,
optimize the bottleneck paths, and re-measure across repeated trials to prove WITHIN-BUDGET.
```

### Drive WCAG 2.2 AA accessibility conformance (`access-it`)

Use **[access-it](missions/access-it.md)** for automated axe-core remediation plus structured human-AT parking:

```text
Bring the onboarding, login, and settings flows to WCAG 2.2 AA conformance.
Freeze the page and flow inventory, fix all deterministic axe-core violations with
revert-to-violation controls, and generate the manual assistive-technology review packet
for criteria beyond the automation ceiling.
```

---

## 5. Evolve, Refactor & Migrate

### Upgrade dependencies safely (`modernize-it`)

Use **[modernize-it](missions/modernize-it.md)** for dependency and framework upgrades:

```text
Update the dependencies for this service using its existing lockfile and package manager.
Prioritize reachable security advisories, then current stable releases.
Keep CI green at every step, document a reason and owner for any dependency that must stay pinned,
and stop at the promotion PR.
```

### Refactor god modules behind narrow interfaces (`reshape-it`)

Use **[reshape-it](missions/reshape-it.md)** to reduce architectural coupling without changing behavior:

```text
Reshape the order-processing module in src/orders/processor.ts.
Pin a characterization test net and mutation baseline before restructuring,
extract narrow domain interfaces, and prove behaviour is unchanged at head_sha.
```

### Execute a zero-downtime schema migration (`migrate-it`)

Use **[migrate-it](missions/migrate-it.md)** for staged expand → backfill → switch → contract database changes:

```text
Migrate the users.billing_address text column to the normalized addresses table.
Execute phase by phase (EXPAND → DUAL-WRITE → BACKFILL → SWITCH READS → ZERO READERS → RETIRE-WRITES → ZERO-WRITERS → CONTRACT),
verifying down-migrations and row-parity probes and pausing for my deploy grant at each phase.
```

---

## 6. Operate, Document & Provision

### Make critical paths operable for on-call (`oncall-it`)

Use **[oncall-it](missions/oncall-it.md)** to add structured telemetry, symptom alerts, and verified runbooks:

```text
Make the payment webhook and payout settlement paths operable.
Ensure every on-call triage question is answered by a quoted metric or log signal,
test-fire symptom alerts with linked runbooks, and verify that a source-blind worker
can diagnose an induced staging failure using only the telemetry and runbooks.
```

### Document an undocumented public surface (`document-it`)

Use **[document-it](missions/document-it.md)** to achieve verified documentation coverage:

```text
Document the public CLI and SDK surface in src/cli/ and src/sdk/.
Extract the public symbol inventory, cover tutorial, how-to, reference, and explanation quadrants,
and bind every factual claim and example to a file:symbol or executable check.
```

---

## 7. Multi-mission sequential chains

When a goal spans multiple outcomes, declare a sequential chain per [`runtime/mission-chaining.md`](../runtime/mission-chaining.md):

```text
Run a sequential mission chain on src/payments/:
1. harden-it (require terminal state: CLEAN)
2. prove-it (require terminal state: COVERED)
3. ship-it (package the release and stop at PROMOTION_READY)
Halt the chain for my approval if any stage finishes in a degraded (-WITH-PARKED / -WITH-OPEN-ITEMS) state.
```
