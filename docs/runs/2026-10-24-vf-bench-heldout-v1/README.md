# VF-Bench held-out v1: authored by an independent holder, evaluated once (#601)

A benchmark evaluation, not a mission run: it binds no mission's proof tier. What binds it is
`bench/vf-bench/heldout.py validate`, which checks `evaluations[0]` of
[`heldout-protocol.json`](../../../bench/vf-bench/heldout-protocol.json) against git and against
the bytes of [`report.json`](report.json) (below).

| Fact | Value |
|---|---|
| Date | 2026-10-24 |
| Holder | OpenAI Codex, an AI system (`codex-cli` 0.163.0, model `gpt-6.1-sol`, reasoning effort xhigh, as its run log's header reports), designated by the repository owner |
| Verifier pinned before authoring | `runtime/scripts/verify.py` blob `08f568946c1f797207c096a38da93227bfc31c31` at `456051e3ec` (committed 2026-10-24T10:47:58+05:30) |
| Cases authored | 2026-10-24T06:00:45Z to 06:00:46Z, all after the pin |
| Held-out set | 89 cases: 66 traps, 23 valid controls, 22 categories; set digest `bc03442ee3bb9090a8af7e26d4ede904eb58fe9ff8a961d5740f5d8ab62b3f89` |
| Where it is held | `~/of-live/heldout/v1/cases` on the owner's machine, mode 0700, outside every git repository |
| Evaluated revision | `ed8f3bcf255c90ae396540c0e9c5a11e571f653a` (same `verify.py` blob as the pin) |
| Report | [`report.json`](report.json), sha256 `7e8eb6683548eb1eb0c71f56b7d08c9f036323877a9882b2ada122dfa98c5a13`; [`summary.txt`](summary.txt) |

## Result

Three runs, 2026-10-24T06:09:10Z to 06:13:59Z, on macOS with Python 3.13.15 and `/usr/bin/git`
2.54.0, in the replay's built environment.

| Configuration | False acceptance | False rejection | Refused for another reason | Inventory rows sampled | Wall time per run | Run-to-run spread |
|---|---|---|---|---|---|---|
| open-fleet `verify.py` (sound) | 0/66 | 0/23 | 4/66 | 66 of 95 | 79.6 to 98.4 s (mean 90.4) | none: every count and every case verdict identical in all three runs |
| self-scoring (naive), the synthetic baseline, never a product score | 66/66 | 0/23 | not judged (it gives no reasons) | 66 of 95 | under 1 ms | none |

- **Verdict classes** for `verify.py`: 62 traps `refused`, 4 `refused-wrong-reason`
  (`hv1-008`, `hv1-014`, `hv1-044`, `hv1-074`), 23 controls `accepted`. Each case's id and class
  per run is in `report.json`; nothing else about a case is.
- **Not scored:** none. No case was skipped, unsupported, timed out, crashed, raised or answered
  malformed.
- **Coverage:** the traps sample 66 of the 95 rows of the verifier-check inventory: all 44 rows
  the development corpus samples (status `trap`) and 22 rows it does not (status `deferred`),
  across 22 of the inventory's 26 checks. No trap named a row that does not exist.
- **External verifiers:** unmeasured, score null. The candidates checked are in the VF-Bench
  README's "External adapter contract" section; none accepts a work unit's evidence manifest.

## What this shows, and what it does not

- `verify.py` refused all 66 held-out traps and accepted all 23 held-out controls, at one pinned
  revision, on cases its authors have not seen. That is evidence the 0% on the public corpus is
  not only a fit to the public corpus.
- The 4 refusals for another reason are unexplained on the developer side by design: whether each
  is a case whose declared reason is worded or planted differently from what `verify.py` refuses,
  or a trap that `verify.py` catches by another leg, can be told only when the set is revealed.
  The scoring treats them as refused, never as accepted.
- The holder is an AI system, not a person. The content is withheld from this repository and from
  the Claude-operated developer agents by procedure, not technically: the holder directory sits
  under the OS account those agents run as, and the machine's owner can read it. The protocol's
  `holder.limits` states each limit.
- Codex read the public repository while authoring, `verify.py` and the development corpus
  included. The cases are unseen by the verifier's authors, not written blind to its source.
- One holder, one set, one verifier revision, one host. Not a statement about any other revision
  or any other verifier.

## How it was run

Every command, in order. `$SCR` is the coordinating agent's scratch directory; it holds the stub
`claude` (a script that logs a line and exits 97, never invoked during the run) and an empty git
config file.

1. Tooling first, at `234a21adc9`: `heldout.py vet` and `digest --summary`, the filled holder role
   and the pin.
2. The holder directory and a read-only snapshot for Codex to read:

       umask 077; mkdir -p ~/of-live/heldout/v1/{cases,published,private,tmp}
       git clone --quiet --no-hardlinks --single-branch --branch claude/r08-heldout-holder \
         <worktree> ~/of-live/heldout/src-234a21adc9 && chmod -R a-w ~/of-live/heldout/src-234a21adc9

3. Codex, non-interactive, from the holder directory, 2026-10-24T05:57:14Z to 06:01:06Z, with the
   brief on stdin ([`authoring-brief.md`](authoring-brief.md)) and its final message held to
   [`authoring-final-message.schema.json`](authoring-final-message.schema.json) (counts, two paths
   and the set digest only; the message is [`authoring-final-message.json`](authoring-final-message.json)):

       cd ~/of-live/heldout/v1 && env PATH="$SCR/codex-bin:$PATH" SHELL=/bin/sh \
         TMPDIR=~/of-live/heldout/v1/tmp GIT_CONFIG_GLOBAL=$SCR/empty-gitconfig \
         GIT_CONFIG_NOSYSTEM=1 PYTHONDONTWRITEBYTECODE=1 \
         codex exec --skip-git-repo-check --ephemeral -s workspace-write -C ~/of-live/heldout/v1 \
         --output-schema authoring-final-message.schema.json -o ~/of-live/heldout/v1/codex-final.json \
         - < authoring-brief.md > ~/of-live/heldout/v1/private/codex-run.log 2>&1

   Per the brief, Codex ran `vet` and then `digest --summary` itself. Its run log stays in the
   holder directory; the developer side read only its header lines (model, provider, sandbox,
   reasoning effort).
4. The developer side, reading no case: `heldout.py vet ~/of-live/heldout/v1/cases --pin
   456051e3ec` (89 cases, 0 problems, 0 copies of a development case); a script that hashed each
   case file and compared the hashes with Codex's `published/digests.json` (89 of 89, same set);
   then `cp ~/of-live/heldout/v1/published/digests.json bench/vf-bench/heldout-v1-digests.json`,
   committed in `847ac54e5f` with the protocol's figures.
5. The leakage checks, clean each time: `python3 bench/vf-bench/heldout.py check --digests
   bench/vf-bench/heldout-v1-digests.json` at `847ac54e5f` (3,055 blobs) and, after the
   evaluation, `--rev ed8f3bcf25` (3,055 blobs) and `--all-history` (9,892 blobs).
6. The evaluation:

       python3 bench/vf-bench/replay.py run --rev ed8f3bcf25 --heldout ~/of-live/heldout/v1/cases \
         --runs 3 --out report.json --summary summary.txt

   Before the report was read, `heldout.py`'s scanner was run over it, the summary and the
   replay's stdout: no digest, embedded case or canary.
7. `python3 bench/vf-bench/heldout.py validate`, which binds this report through
   `evaluations[0]`.

## Deviations, recorded

- **The first evaluation attempt crashed before scoring anything.** At `847ac54e5f` the replay's
  own fixture preflight raised `AttributeError: 'str' object has no attribute 'get'`: one held-out
  case's manifest lists a non-object in `artifacts[]`, and the runner assumed every entry is an
  object. The traceback named no case and quoted no value, but it did tell the developer side that
  one structural fact about one case. No case had run, so no verdict informed the fix:
  `301522b788` makes the preflight skip what pins nothing, with a regression test, and changes
  nothing in `verify.py`. The evaluation was then rerun in full at `ed8f3bcf25`.
- **The copy check came after authoring.** An ad-hoc script first measured how far the set sits
  from the development corpus (numbers only); `vet` was then given the same measure and a refusal
  of copies, and the set passed it unchanged.
- **The leakage checks at the evaluated revision ran after the evaluation**, not immediately
  before it as the protocol asks. The two commits between the last pre-evaluation check
  (`847ac54e5f`) and the evaluated revision change only `replay.py`, its tests, the workflow and
  one heldout test.

## Integrity inventory (sha256)

    7e8eb6683548eb1eb0c71f56b7d08c9f036323877a9882b2ada122dfa98c5a13  report.json
    c045650989ced0933f5eca988043959f15b8c33474bc4a35c4725cd6e34e2bc6  summary.txt
