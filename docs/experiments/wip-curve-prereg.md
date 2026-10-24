# WIP-curve experiment: pre-registration

[Documentation](../README.md) · [Attention budget](../../runtime/attention-budget.md) ·
[Event record (`events.py`)](../runtime-scripts.md#eventspy) · [Merge queue](../runtime-scripts.md#merge_queuepy)

[`runtime/attention-budget.md`](../../runtime/attention-budget.md) labels the fleet's WIP caps
**ASSERTED**: no run has yet measured how verified-CLOSED throughput changes with the number of
concurrent builders. This page pre-registers that measurement (issue
[#604](https://github.com/ravidsrk/open-fleet/issues/604), roadmap package R11) and describes the
tooling that runs it. The design is fixed here before any live run, so no result can reshape it.

The machine-readable registration, [`wip-curve-prereg.json`](wip-curve-prereg.json), is
authoritative. It binds the task set, [`wip-curve-taskset.json`](wip-curve-taskset.json), by
sha256 and binds the seed commit that the task set builds. Where this page and the JSON disagree,
the JSON wins.
[`scripts/wip_curve.py`](../../scripts/wip_curve.py) checks the registration, runs it, and reports
on it. Its tests are in [`tests/test_wip_curve.py`](../../tests/test_wip_curve.py).

## Status: what is implemented and what remains

| Part | State |
|---|---|
| Pre-registration (task mix, machine/provider/model/harness fields, WIP settings, reviewer availability, repetitions, order, isolation, confounds, stopping rule, cost cap) | **Implemented.** `wip_curve.py check-prereg` checks it. |
| Fixed task set: six named tasks on a synthetic package, with oracles that discriminate | **Implemented.** Each oracle fails on the seed and passes on the reference edit. All six references compose in forward and reverse order. |
| Runner on the posix provider, with build-blind reviewers, a coordinator-run oracle and the merge queue | **Implemented.** Exercised only with the inert stand-in. |
| Reporter: throughput, verification latency, rework, freshness, conflicts, tokens and cost with uncertainty, and every failed, stopped or parked run | **Implemented.** The reporter derives these from each run's [events.py](../runtime-scripts.md#eventspy) record and the merge queue's receipts. |
| Verification: independent recomputation, git and review authority for every terminal outcome, and detection of an altered metric row | **Implemented** and pinned by tamper tests. |
| Dry run of the whole pipeline with an inert stand-in | **Implemented.** All 12 scheduled runs complete and verify (fixture tier: no evidence). |
| Cost cap | **PENDING OWNER AUTHORISATION.** The proposed value is 150.00 USD. The runner refuses to start without an explicit cap. |
| At least three protocol-compliant **live** runs at differing WIP settings, retained with raw observations | **REMAINING.** Needs model spend that the owner authorises (see [Running it](#running-it)). |
| A published recommendation to keep or change the caps, with evidence links | **REMAINING.** It follows the live runs. A cap change is a separate human-reviewed policy change. |

Until the live runs are retained, the caps in `attention-budget.md` stay ASSERTED.

## The question

How does verified-CLOSED throughput change with the number of concurrent builders when review
capacity is held fixed? How does that change verification latency, rework, review freshness,
merge conflicts and model spend?

## Task mix

The target is `stocklib`, a synthetic stdlib-only Python package of five small modules with a
visible test suite. The task set adds six fixed, named tasks. Each task has a statement, which is
all a worker receives, and an oracle: a unittest module that the coordinator runs at the worker's
head in a clean checkout. Workers never receive the oracle. Difficulty labels are nominal and
were assigned before any run.

| Task | Change | Difficulty | Edits | Conflicts in one wave with |
|---|---|---|---|---|
| T1 | `slugify` transliterates accented letters | S | `textutil.py` | — |
| T2 | `Ledger.remove` refuses to overdraw | S | `ledger.py` | T5 |
| T3 | `convert` supports pounds and ounces | M | `units.py` | — |
| T4 | `report.to_csv` exports the ledger | M | `report.py` | T6 |
| T5 | `Ledger` keeps an audit history | L | `ledger.py` | T2 |
| T6 | `summary` ends with a TOTAL line | L | `report.py` | T4 |

The two pairs edit the same region. A wave that builds both tasks of a pair from one base can
meet a merge conflict, which a serial wave never does. This is one mechanism by which wider
parallelism can cost throughput, and it is measured rather than assumed. Each task's `reference`
edit is the inert stand-in's answer, and it shows that the oracle measures something. A live
worker never receives the reference.

## Machine, provider, model and harness

These fields are filled at run time and recorded in every run's `run.json`:

- **Provider:** `posix` with the `setsid` backend, fixed for the whole experiment.
- **Machine:** the host facts the runner records (platform, CPU count, Python and git versions).
  The event clock is labelled with a hash of the host name, so a published record identifies the
  machine without carrying its name.
- **Harness:** `--agent`. The runner records the harness binary's `--version`.
- **Model:** `--model` is required for a live run. Every model that the usage record observes
  must equal the pin.

Builders run with `PROFILE=rw`. Reviewers run with `PROFILE=ro` on the same harness and model.
After every spawn, the runner checks that the deny hook the provider installed in the worker's
tree is armed, as `first_run.py` does. If it is not, the runner stops the worker and the run fails.

## WIP settings and reviewer availability

| Condition | Builders | Reviewers | Role |
|---|---|---|---|
| `b1r1` | 1 | 1 | The serial baseline (builders=1) |
| `b3r1` | 3 | 1 | The current asserted default cap |
| `b6r1` | 6 | 1 | Wider parallelism with unchanged review capacity |
| `b6r2` | 6 | 2 | Reviewer-capacity control: the cap's one reviewer per three builders |

A wave dispatches at most `builders` units, and carried (bounced) units go first.
`reviewers=<n>` is the number of build-blind review units in flight at once. A done unit waits
for a free reviewer in worker_done order. The reviewer rubric is fixed: the reviewer receives the
task statement and the diff, and answers `approve` or `changes` on one `WIP-REVIEW` line. The exact
text each builder and reviewer receives is registered in the JSON's `contracts`, not written in
the runner, so the registration's digest pins it. The line
may be wrapped in markdown, but it must carry the review's nonce and the reviewed head. A review
with no such line ends the attempt `review-failed`, and the unit is rebuilt like any other bounced
unit. No human reviewer sits in the measured loop. Human review capacity is a separate experiment.

## Repetitions, order and isolation

There are three repetitions of each condition, so 12 runs in total. Conditions follow a Williams
balanced Latin square: repetition *r* runs row *r*, so across three repetitions each condition
takes three of the four positions. Each run's task order is the task ids sorted by
`sha256('<seed>:<run id>:<task id>')`. Anyone can recompute it from the JSON, and nobody chose it.
`wip_curve.py plan` prints the schedule.

Each run gets a new sandbox containing a fresh local-state store, a fresh merge-queue store, and
a fresh bare origin and clone. The clone is built from the task set's seed with a fixed author,
committer and date, so every run starts at the same registered seed commit. The runner and the
verifier both check this. A task always starts from the integration head at the moment its wave
opens. A bounced task is rebuilt from scratch from the integration head at that time. No
worktree, branch, store or transcript is shared between runs.

## Confounds and how each is separated

- **Cache and warmup:** the condition order is counterbalanced. Live runs are separated by a
  cooldown of at least 10 minutes, which is longer than the default prompt-cache lifetime; the
  runner waits it out, and the report checks it from the run timestamps. Each run gets a fresh
  sandbox. Cache-read tokens are reported per run, so any residual cache effect is visible.
- **Task difficulty:** every run uses the same six tasks in a randomised order. Per-task outcomes
  and latencies are reported for every run, so a difficulty effect can be read within each task.
- **Model changes:** one model pin and one harness version cover the whole experiment. A run whose
  observed models differ from the pin is not compliant. It is reported and never pooled.
- **Reviewer effort:** the rubric, profile and model are fixed. Reviewer capacity is the only
  review variable, and only one arm varies it (`b6r1` against `b6r2`). Reviewer usage is recorded
  per review dispatch.

## Stopping rule

- A run is complete when every task is CLOSED (verified, reviewed and landed by the merge queue)
  or parked.
- A task is bounced when the oracle fails, the review asks for changes or gives no verdict, the
  merge conflicts, the merge gate fails, or the builder fails. A task bounced three times is parked
  `attempts-exhausted`.
- Dispatch timeouts are 30 minutes for a builder and 15 minutes for a reviewer. A run's
  wall-clock limit is 180 minutes.
- **Cost:** before each wave, the observed spend plus that wave's worst case must stay within the
  cap. The worst case is two dispatches per unit at the reservation. If the next wave does not
  fit, the run parks every unit still in flight as `stopped-cost-cap`, so the record still
  derives every metric, and no further run starts.
- **Experiment:** run exactly the scheduled runs, then stop. No run is added, dropped or repeated
  because of its results. A run that fails for an infrastructure reason may be re-run once under
  a new attempt id (`<run>-a2`), and both runs are reported. A null or negative result completes
  the experiment.

## Cost cap

`cost.cap_usd` is **PENDING OWNER AUTHORISATION**. The proposal is 150.00 USD, with a 2.00 USD
reservation per dispatch, which is also pending. Twelve runs of six tasks need 144 dispatches
before retries (a builder and a reviewer per task). The runner never picks the spend:

- `run` refuses to start without `--cost-cap-usd`. A live run also refuses without
  `--reservation-usd` (the reservation is never taken from the pending registration), refuses a
  zero cap or reservation, and refuses to run without `--model`.
- Before a unit's builder starts, the runner holds the worst case of every call the unit makes:
  its builder and its reviewer, each at the reservation. No grader calls a model.
- Each dispatch starts only while measured spend, the charges for unobserved dispatches and every
  hold, its own included, stay within the cap. The exact boundary is admitted; a cent over is
  not. A builder that spent past its hold therefore refuses its reviewer before the reviewer
  starts, and the unit is parked `stopped-cost-cap`.
- Spend is read from the harness's own result lines through `events.py ingest-usage`. A dispatch
  whose cost is not observed is charged the full reservation and is never treated as free.
- The cap covers every run in one results directory.

No per-call limit reaches the harness: the posix launch table
(`runtime/providers/base.py`) passes no budget flag to any harness. A dispatch that is already
running can therefore overrun its reservation, and the dispatch timeouts bound that in time, not
in money. Choose the reservation with that in mind. Each run records this as
`cost.per_call_limit`.

## Metrics and uncertainty

`events.py` derives the per-wave WIP-curve rows from each run's append-only record. The record
holds launches, worker_done messages and deaths from the store; reviews; oracle verdicts; closes
and parks; and usage. The experiment report adds the following per run:

- **Throughput:** verified-CLOSED units per hour of summed wave wall-clock. This is the primary
  outcome.
- **Verification latency:** median and maximum, pooled from every unit that reached
  verified-or-parked. A wave in which no unit did, such as a `builders=1` wave whose only unit
  was bounced, contributes no observation. Its own row prints `unavailable`, and under
  `run_report.py` that row cannot bind.
- **Rework:** bounced unit-waves over all unit-waves. **Freshness:** approving reviews voided
  because the unit closed at another head. **Retries.**
- **Conflicts and gate failures:** the merge queue's `failed` receipts. Each conflict is
  re-derived from git with `git merge-tree` against the prefix commit that the run pinned.
- **Tokens and cost:** per model and per run. An unobserved field is `unavailable` and never 0.

For each condition the report gives the mean, the sample standard deviation and a two-sided 95%
Student-t interval over its runs, and it lists every run's value. Rework is reported as a pooled
proportion with a 95% Wilson interval. With three runs per condition the intervals are wide, and
the report states them at that width.

## Protocol compliance

A run counts toward the curve only if all of the following hold:

- A live worker ran it.
- It used this registration and this task set.
- It started at the seed commit.
- It recorded a model pin and a harness version, and observed only the pinned model.
- `events.py` derives the run's throughput, latency, rework and freshness.
- Every terminal outcome binds (see [Verification](#verification)).
- The run finished complete.
- The cooldown before the run was kept.

The report lists every run. For each failed, stopped, parked or non-compliant run it names the
reasons.

## Decision rule

The decision rule is fixed in the JSON:

- **Raise:** a condition above the cap (`b6r1` or `b6r2`) is a candidate when the lower bound of
  its 95% throughput interval exceeds the upper bound of `b3r1`'s interval, its pooled rework is
  at most 0.10 above `b3r1`'s, and its mean freshness violations per run are at most 1 above
  `b3r1`'s.
- **Lower:** a candidate when `b1r1`'s interval lies above `b3r1`'s.
- **Keep:** otherwise, including every null or negative result.
- **Not issued:** fewer than three compliant runs, or compliant runs at fewer than three settings.

A recommendation is never a change. Changing a cap is its own human-reviewed policy change, and it
must cite the report.

## Running it

Check the registration and print the schedule:

```bash
python3 scripts/wip_curve.py check-prereg
python3 scripts/wip_curve.py plan
```

The dry run uses the inert stand-in. It calls no model and spends nothing, and its runs are
labelled `fixture-tested`:

```bash
python3 scripts/wip_curve.py run --results /tmp/wip-dry --cost-cap-usd 0 --all
python3 scripts/wip_curve.py report --results /tmp/wip-dry --basis all
python3 scripts/wip_curve.py verify --results /tmp/wip-dry --report /tmp/wip-dry/report.json \
  --report-md /tmp/wip-dry/report.md
```

The stand-in answers to the harness name from a private bin directory that sits first on PATH,
behind a tripwire for every other harness name. It runs with a private `HOME` and with
`SHELL=/bin/sh`. Its default script includes one oracle miss (T3) and one review that asks for
changes (T1), so the dry run exercises rework as well as conflicts and closes.
`--inert-script` and `--inert-cost-usd` change that script and the synthetic cost the stand-in
reports. The synthetic cost is not a spend. It lets the cost cap be exercised.

**Live run.** This needs the owner's authorisation, because it spends:

```bash
python3 scripts/wip_curve.py run --results <dir> --worker live --agent claude \
  --model <pinned model id> --cost-cap-usd <the authorised cap> --next 1
```

Path arguments may be relative: the runner resolves every one of them to an absolute path before
anything runs. It refuses a results, output or sandbox path that resolves to, inside or around the
repository's sources (`skills/`, `playbooks/`, `runtime/`, `scripts/`, `docs/`, `tests/` and the
rest) or the registered pre-registration and task set, with symlinks followed. A sandbox must be a
new or empty directory, because a complete run deletes it, and it may not overlap the results. Run one scheduled run at a time with `--next 1`, or name runs with `--runs`. Each run takes its
condition, repetition, position and task order from the schedule. The results directory is
append-only. A live run's receipt is labelled `live-unreviewed` until a maintainer binds it.

## What a run retains

Each `<results>/runs/<run id>/` holds the following:

- `events.jsonl`, the run's hash-chained event record.
- `run-report.md`, the run's WIP-curve rows as `events.py report` derived them.
- `target.bundle`, a git bundle of every branch, the integration branch, and each pinned conflict
  prefix.
- `state.db`, a copy of the local-state store.
- `merge-receipts.json`, the merge queue's receipts.
- `oracle/*.json`, the oracle transcripts.
- `reviews/*.txt`, each reviewer's final answer.
- `streams/*.jsonl`, each dispatch's output stream, which is the source of its usage.
- `run.json`, written last. It binds every file above by sha256.

## Verification

`report` reads only these sources and fails closed in four cases:

- a bound file is missing;
- a bound file no longer hashes to its digest;
- an unbound file has appeared;
- the event chain is broken.

It re-checks every CLOSED unit against git and review authority:

- The head is on the integration branch in the bundle, and its tree is the recorded tree.
- An approving review of that head came from a dispatch other than the unit's builders, and its
  retained answer still hashes to the recorded bytes and ends in that verdict.
- A retained oracle transcript records a pass at that head.
- The oracle passes again on a fresh extraction of that head.

It also checks that every parked unit's head is in the bundle and is not on the integration
branch, and that every recorded conflict re-derives with `git merge-tree`.

`verify` recomputes the report from the same sources. It names every JSON field and every
`report.md` line that disagrees. A deliberately altered metric row is therefore caught. It then
runs `events.py check` on each run's `run-report.md`, anchored to the record head that the
published report names. `tests/test_wip_curve.py` makes each of these alterations and requires
the tool to detect each one.

## Limits on generalizing

- The target is one synthetic, six-task, stdlib-only Python package. Larger tasks, other
  languages and real repositories may bend the curve differently.
- The experiment uses one host, the posix provider, one harness and one model. Orca and other
  providers schedule and isolate workers differently.
- Only agent reviewers are measured. Human review capacity, the serial bottleneck that the
  attention budget names, is not.
- Three runs per condition are enough to see a large effect, not to rule out a small one.
- The oracles live in the catalog clone. A live worker could read the catalog through
  `$OPEN_FLEET_ROOT`, and a transcript would show it.

## Changing the registration

Everything the measurement depends on is pinned:

- The task set (statements, oracles, reference edits and seed files) is pinned by its sha256 in
  the JSON, and the seed commit it builds is pinned too.
- The builder and reviewer contracts live in the JSON itself.
- `run` performs the whole `check-prereg`, seed and oracles included, before anything starts. A
  moved input is refused there, never recorded as a failed run.
- A results directory holds one registration. A run is refused when the directory already holds
  a run made under another pre-registration or task-set digest.
- A live run is refused while any experiment input (`scripts/wip_curve.py`, `docs/experiments/`,
  `runtime/`) has uncommitted changes. Every run records the digest of each input, and a live run
  on inputs other than the first live run's is not compliant, so it is never pooled.

After the first live run, any change to the task set, the contracts, the conditions, the order,
the stopping rule or the analysis is therefore a new `version`, with new run ids and a new
results directory.
