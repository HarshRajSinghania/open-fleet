# End-to-end repository review — 2026-10-23 @ 53dd2a8

Reviewed SHA: `53dd2a8ec6` (`origin/main`, merge of PR #610). Every `file:line` below is at that
SHA. Read-only engagement: nothing in the repository changed except this file. Every CI gate was
executed locally, not read, and every P1 was reproduced by the author of this document from a
reviewer's artifact or from scratch. Reviewer-only reproductions are marked.

Method: eight parallel read-throughs, one per layer (evidence verifier and signing; deny-hook and
spawn; coordinator scripts; build and validator scripts; missions and top-level docs; playbooks and
runtime policies; tests, CI and hygiene; human docs and retained runs), each required to reproduce
P1/P2 candidates against the real scripts in a throwaway clone and to name what it ruled out. The
author re-ran every P1 and the highest-value P2s. Host: macOS, Python 3.13.15, git 2.56, tmux 3.8.

Coverage gap: the eighth read-through (human docs under `docs/*.md` and `docs/guides/`, the
retained run reports under `docs/runs/`, the disposition of prior reviews, and `DECISIONS.md`)
was stopped before it reported, to conserve usage. What other reviewers did verify on that layer:
1,241 relative links and anchors resolve, the docs index matches the tree both ways, all five
proof reports bind in `run_report.py`, and every mission guide's proof tier matches its SKILL.
Not checked: prose-versus-JSON consistency inside the run reports, whether prior-review findings
were addressed, the `docs/*.md` command walkthroughs, and the `docs/reports/release-20260912/pin`
tree.

---

## 1. Verdict

**The gates are green, and each of the four mechanisms the repository's thesis stands on has a
confirmed bypass.** The thesis (`ARCHITECTURE.md`) is that "done" is never trusted: an independent
verifier re-derives facts, a deny-hook bounds the worker, a floor guard and a human-signed decision
ledger keep the bar from moving, and CI enforces all of it. At this SHA:

- The verifier says OK on two false dones. A control that breaks the module's syntax is accepted
  as "an assertion failure" whenever the test runner prints `N failed` (pytest with an in-test
  import; Jest and Vitest always), so a test that asserts nothing passes the executed negative
  control. And a `post-checkout` hook in the source repository's `.git` runs during the control
  and can plant a failing test into the control commit, turning a unit the verifier correctly
  grades TAUTOLOGICAL into "RED, as required".
- The deny-hook's hard-deny tier is defeated by putting `timeout`, `exec`, `setsid`, `env -i`,
  `nice -n`, `( … )` or `!` in front of the command. `timeout 30 git push --force origin main`
  is allowed. The hook can also be disarmed by `chmod 000` on its own file.
- The floor guard goes silent when the PR adds a `.gitattributes` line, and it accepts a waiver
  the same PR writes into `docs/DECISIONS.md`. The decision ledger's `check` accepts a
  hand-written, unsigned one-way grant while a human key is pinned.
- Branch protection requires the `gates` context, and `gates` is skipped, not failed, when a test
  shard is red. GitHub counts a skipped required check as success. Two recent runs show exactly
  this shape. No approving review is required on `main`.
- The validator's identity-collision gate does not see identity points written as YAML block
  scalars, and its quarantine gate does not see compositions it charges as activation load.
- Running the test suite on a developer machine that has tmux installed launches the real
  `claude` CLI with `--dangerously-skip-permissions`. It did so on this host, five times.

None of this contradicts the quality of the engineering, which is unusually high: every workflow
action is SHA-pinned and verified against upstream tags, tool installs are hash-locked, the secret
scan carries a planted-key negative control, the verifier scores 0/20 false-done on its corpus and
refuses every evidence-path, option-injection and replace-object trick tried, all five proof
reports re-hash at the commits they name, 1,241 relative links resolve, and the 3,182-test suite is
clean of tautologies. The findings are holes in specific mechanisms, each with a narrow fix. The
repository's own standard ("every guard must be demonstrably capable of failing") is the right
one; these are the places where the guard fails to fail.

## 2. Baseline gates at 53dd2a8

Every CI gate was run locally. All pass except the suite, which has three deterministic
macOS-only failures (§4, P2-29); CI's Ubuntu runners pass it.

| Gate | Result |
|---|---|
| `scripts/validate.py` | 22/22 missions valid; separation holds; evals valid |
| `scripts/eval.py run --suite routing --threshold 1.0` | 95/95 |
| `runtime/scripts/proof_status.py --check` | 17 doctrine-only, 3 self-run, 2 external-run |
| `runtime/scripts/run_report.py` | 5 reports bound |
| `scripts/bundle.py --check` | 22 self-contained missions |
| `bench/vf-bench/gate.py` | PASS, false-done 0/20, controls 3/3, skipped 0 |
| `ruff check` (0.16.7, the lock version) | clean |
| `scripts/gen-badges.py --check` | fresh |
| `agentskills validate` (skills-ref 0.1.1) | 22/22 valid |
| `gitleaks detect` (8.30.1, the CI pin) | 1,678 commits, no leaks |
| `python3 -m unittest discover -s tests` | 3,182 tests, 1,107 s, 2 failures + 1 error (all macOS-only) |
| `scripts/release_check.py --fast` | 32 PASS, 0 FAIL, 1 SKIP (the suite) |
| `runtime/scripts/floor_guard.py --base origin/main` | clean |
| `sh demo/negative-control/run.sh` | PASS (self-scorer GREEN, verify.py RED on the trap) |

Live branch protection on `main` (read through the API): required contexts `gates`, `verdict`,
`guard`, `Greptile Review`; strict; admins enforced; **no required approving reviews**;
conversation resolution required; no rulesets; no tag protection. Open issues: 20, no open PRs.

## 3. P1 findings

Each P1 either defeats a mechanism the repository presents as a boundary, or lets a false "done"
or a lowered bar through unseen. All twelve were reproduced by the author.

### P1-1. A stillborn mutant passes the executed negative control under pytest, Jest and Vitest

- `runtime/scripts/_verify_sig.py:79-93`.
- The stillborn check (a SyntaxError or ImportError is not a kill, `evidence-manifest.md:137`)
  runs only when the runner summary counted zero failures. pytest counts an exception raised
  inside a test as `1 failed`, and Jest/Vitest print `Test Suites: 1 failed` for a suite that
  never loaded. With one or more failures counted, the code skips the stillborn analysis and
  accepts any `ASSERTION_MARKERS` hit, which includes the word "failed".
- Reproduced from the reviewer's fixture: a unit whose test is `import mod; assert True` (it
  asserts nothing about the criterion), a `hand` control that breaks `mod.py`'s syntax on the
  changed line, `--nc-command "python -m pytest -q test_mod.py"`. The control run prints
  `FAILED test_mod.py::test_add - … SyntaxError … 1 failed`; `verify.py` prints `negative control
  EXECUTED — … exited 1 on an assertion failure (RED, as required)` and `verify: OK — all
  required checks passed`, exit 0, on the `--no-gh` lane. In the `dark-eligible` and `--no-gh`
  lanes the executed control is the only oracle, so this is a false done with no review anywhere.
- The vf-bench `stillborn-mutant` trap goes RED only because its fixture runs `python -m
  unittest`, whose summary reads `errors=1`; the corpus never samples a runner that reports a
  load failure as "failed", which is every JS runner.

### P1-2. Git hooks in the source repository run during `--execute-nc` and can fabricate a kill

- `runtime/scripts/verify.py:921-947` (`git_env` closes config exec channels but not
  `core.hooksPath` or `$GIT_COMMON_DIR/hooks`), `:1844` (`worktree add` runs `post-checkout`),
  `:1702` (`checkout <base> -- paths` runs it again), `:1706` (the revert sanity check reads the
  working tree) versus `:1819` (the seal reads the index).
- A `post-checkout` hook in the shared `.git/hooks` runs as the verifier's uid, with its HOME and
  PATH, twice per executed control. Because the sanity check and the seal read different things,
  the hook can stage a failing test into the control commit without any check noticing.
- Reproduced from the reviewer's fixture: a unit whose test is `self.assertTrue(True)` plus a
  four-line hook that writes a blob containing `assertEqual(1, 2)` and runs `git update-index
  --cacheinfo` for `test_mod.py`. Hook not executable: `FAIL: --execute-nc: TAUTOLOGICAL — the
  proof does NOT go RED`, exit 2. Hook executable: `negative control EXECUTED — … exited 1 on an
  assertion failure (RED, as required)`, `verify: OK`, exit 0, working tree clean.
- Precondition: the verifier's `.git` is writable by the graded worker. That is the native lane,
  and every coordinator run inside a worktree that shares `.git` with its workers, which is the
  layout this repository prescribes (`docs/verify-gate.md` describes "every sibling worktree
  sharing `.git`"). A fresh CI clone is unaffected. `docs/reports/h409/reaudit-r2.md:129` graded
  hooks closed on the premise that the hooks directory is "the coordinator's clone".
  `tests/test_posix_provider.py:605` already treats `core.hooksPath` as an attack channel
  elsewhere; a `core.hooksPath=/dev/null` pair in `git_env()` closes it.

### P1-3. Wrapper prefixes defeat the deny-hook's hard-deny tier

- `runtime/scripts/deny-hook.sh:2347-2375` (`strip_prefix`) and `:2660` (HIGH-tier loop).
- The HIGH tier anchors its rules at the start of each segment after a bash `strip_prefix` that
  peels only `sudo env nohup nice time command builtin`, and peels those words without their
  options. Any other leading word de-anchors every rule.
- Reproduced with the test harness's own repo shape (`refs/remotes/origin/main` present,
  `ORCA_UNIT_WORKTREE` set and unset):

```
git push --force origin main              -> DENY  (deny-hook[HIGH]: force-push to the default branch is refused)
timeout 30 git push --force origin main   -> ALLOW
exec git push --force origin main         -> ALLOW
setsid git push --force origin main       -> ALLOW
env -i git push --force origin main       -> ALLOW
nice -n 5 git push --force origin main    -> ALLOW
(git push --force origin main)            -> ALLOW
! git push --force origin main            -> ALLOW
orca orchestration reset                  -> DENY
timeout 5 orca orchestration reset        -> ALLOW
```

- Force-push and `orca orchestration reset` have no never-list fallback, so they pass fully,
  including under `OPEN_FLEET_HEADLESS_STRICT=1`. `rm -rf /` behind the same prefixes degrades
  from deny to ask. The hook's own Python peeler (`_plain_words`, `:1100`) handles `env -i`,
  `nice -n`, grouping and `!` correctly, which is why `(gh release create v1)` is still denied;
  the bash peeler the HIGH tier uses does not, and neither knows `timeout`, `exec`, `setsid`,
  `stdbuf`, `xargs` or `ionice`. The header's #297 claim that a prefixed refused shape is
  "refused wherever it sits" does not hold. Issue #598 tracks the parser-vs-shell class in
  general; this concrete hole is not named there.

### P1-4. A worker can disarm the hook that bounds it

- `runtime/scripts/deny-hook.sh:1823-1871` (`guard_targets`).
- The self-guard extracts write targets for `rm`, `mv`, `cp`, `ln`, `install`, `sed -i`,
  `perl -i`, `truncate`, `tee`, `dd` and `sh -c` bodies. It does not model `chmod`, `sort -o`,
  `ed` or `rsync`. The canonical hook lives outside the unit worktree
  (`runtime/providers/posix.py:187-191`), so the write boundary never applies to it either.
- Reproduced: `chmod 000 <hook>`, `chmod -x <hook>` and `sort -o <hook> /dev/null` are ALLOWED;
  `truncate -s0 <hook>` and `rm <hook>` are DENIED. The header at `:84` notes that OpenHands and
  jcode fail open when the hook errors, so after `chmod 000` every later tool call on those
  harnesses is unguarded.

### P1-5. A red test shard cannot block a merge through `gates`

- `.github/workflows/validate.yml:107-108` (`needs: [tests, floor]`, no `if: always()`),
  comments at `:19-20` and `:63-64`.
- The workflow's comment says the suite blocks the merge "through" the required `gates`
  context. When a shard fails, `gates` is skipped, not failed. GitHub's documentation on
  required status checks says: "Successful check statuses are `success`, `skipped`, and
  `neutral`", and for a job that depends on a failed job, "The dependent job is skipped and may
  not block merging. Use `always()` with `needs`."
- Observed in the run history: run 39386063357 (`tests (3)` failure, `gates` skipped) and run
  38533245355 (`tests (4)`, `floor (3.11, 4)`, `floor (3.12, 4)` failures, `gates` skipped).
- `tests/test_shard_tests.py:231-246` pins the mistaken assumption as a contract. Of the four
  required contexts, none depends on the suite once `gates` is skipped. Combined with the
  absence of a required approving review, a PR with a red suite is mergeable if `guard`,
  `Greptile Review` and `verdict` pass. Not exercised with a live merge.

### P1-6. The floor guard is blanked by a `.gitattributes` line in the PR

- `runtime/scripts/floor_guard.py:238` (`diff_options`), `:253` (untracked `--no-index`).
- The diff is taken without `--text`, so git honours the PR's own `.gitattributes`. A path
  marked `-diff` renders as `Binary files … differ` with no content lines, and every rule
  (guard-surface, silenced-checker, test-made-easier, threshold-lowered, assertion-removed) is
  silent for tracked and untracked files alike.
- Reproduced from the reviewer's clone: a PR adding `* -diff`, lowering `.coveragerc`
  `fail_under` 80 to 10, adding a `noqa` comment, adding a test-skip decorator and lowering a CONSTRAINTS row
  prints `floor-guard: clean`, exit 0. The same edits without the attribute print two
  `[guard-surface] .coveragerc:2` violations, exit 1. Adding `--text` restores the diff.

### P1-7. The floor guard accepts a waiver the PR writes for itself

- `runtime/scripts/floor_guard.py:561-562` (waivers read from the checked-out tree),
  `:500-507` (any active `allow` of any class).
- `CONSTRAINTS.md:96-98` says thresholds move only by a one-way human decision. The guard reads
  `docs/DECISIONS.md` as it stands in the PR's working tree, and a waiver needs only the id
  `floor-waiver:<rule>:<path>` and answer `allow`; the class may be `taste`, no human source or
  signature is required, and `decisions.py append --ts 2099-…` out-ranks a prior human `deny`
  in `active()`.
- Reproduced: a PR that adds a `noqa` comment to `src/app.py` and one line to `docs/DECISIONS.md`
  prints `floor-guard: clean (1 waived)`, exit 0. At the merge base the waiver file does not
  exist, so reading waivers from the base ref would have refused it.

### P1-8. `decisions.py check` accepts an unsigned one-way grant under a pinned key

- `runtime/scripts/decisions.py:341-363` (`validate`).
- The signature requirement lives only in `cmd_append` (`:506-510`). `validate()`, which `check`
  and the verifier run, verifies a signature only when one is present (`elif sig is not None`).
  The ledger is a plain Markdown file any worker can append to.
- Reproduced with `.orca/human-grant-pubkey` pinned: `append --class one-way … --source
  human:lia` is refused ("requires --grant-sig"); the same line written by hand with no `sig=`
  passes `check` ("1 record(s) valid", exit 0) and `active` lists it as the live grant.
- Related (P2-3): the grant payload binds id, answer, why and task but not `ts` or class, so a
  signed `approved` line can be replayed with a later timestamp to out-rank a later signed
  `superseded`.

### P1-9. The identity-collision gate is blind to YAML block scalars

- `scripts/validate.py:323-330` (nested `metadata:` reader has no `>`/`|` branch),
  `scripts/_identity.py:136-137` (empty token set scores 0.0).
- A folded scalar (`unit: >-` plus indented text) under `metadata:` is read as the literal
  string `>-`, which tokenizes to nothing, so the point scores 0.0 against every mission and
  neither the "same six" nor the paraphrase error can fire. `METADATA_VALUE_MAX`,
  `IDENTITY_POINT_MAX_TOKENS` and the A2A export are blind to the same form.
- Reproduced from the reviewer's clone: `oss-contribute` carrying `clean-sweep`'s six points
  verbatim, all folded, prints "All 22 missions valid", exit 0, no warning. Folding is the
  natural style for 100-160 character points under a 34-line frontmatter cap.

### P1-10. The quarantine gate misses compositions the validator itself counts as mandatory

- `scripts/validate.py:1111-1120` (`compose_clause_backticks` only) versus `:766-768`
  (`transitive_load` counts backticks and bare `name.md` tokens) and
  `runtime/scripts/quarantine_check.py:194-199` (counts both).
- A playbook composed by a `name.md` token inside the clause is charged as activation load but
  never checked against `runtime/quarantine.json`. A playbook named only in a DEFERRED READS
  paragraph is checked by nothing.
- Reproduced in a throwaway clone with one fixture edit: `ship-it`'s clause respelled from
  `` `build-change` `` to `build-change.md` (at the reviewed SHA the live clause,
  `skills/ship-it/SKILL.md:38`, uses the backticked form, which the gate does see). With
  `playbook:build-change` quarantined, `validate.py` then flags clean-sweep, deflake-it,
  oss-contribute and prove-it and reports `ok ship-it`, while `quarantine_check.py --mission
  ship-it` reports QUARANTINED, exit 2. The CI gate sees a strictly smaller composition set than
  the CLI. The live tree carries one candidate of the same shape: `skills/migrate-it/SKILL.md:46`
  names `release.md` in prose that `transitive_load` charges; with `playbook:release`
  quarantined the reviewer saw `validate.py` exit 0 and `quarantine_check.py --catalog` report
  migrate-it QUARANTINED (reviewer). Transitive playbook-to-playbook edges (24 in the catalog)
  and body mentions are also unchecked by `preflight.py --mission` (P2-11).

### P1-11. The test suite launches the real `claude` CLI with `--dangerously-skip-permissions`

- `tests/test_posix_provider.py:457-477` (`TestTmuxWorkerLifecycle`),
  `runtime/providers/posix.py:1159` (`env_vars`), `runtime/providers/base.py:179-184`.
- The worker's launch env carries only worktree, profile, identity and state-DB keys; `PATH` is
  not among them. Under a pre-existing tmux server the monitor builds `worker_env` from the
  server's environment, so `PATH` is whatever started the server. The test starts a
  "preexisting" server from the test process's environment, which lacks the fake-agent `bin`
  directory, so `claude` resolves to the real binary on the developer's `PATH`.
- Observed on this host: the test fails deterministically (3/3 isolated runs), and the lane's
  `events.jsonl` holds a real API response and a real tool call (`ls -la; cat README.md; git
  branch -a; git worktree list; ls ~/.claude/projects/…/memory/`) executed by
  `claude -p --dangerously-skip-permissions` in the temp worktree. Each suite run on a tmux host
  spawns one such session. CI's Ubuntu 24.04 image ships no tmux, so the branch never runs
  there and the suite is green. `CONTRIBUTING.md` tells every contributor to run the suite
  locally.
- The provider half is a real defect: a worker launched into an existing tmux server inherits
  that server's `PATH` and environment, and only the two signing seeds are stripped
  (`posix.py:296`).

### P1-12. Three missions let the fleet walk through registered one-way doors

- `runtime/one-way-doors.json` enumerates `deploy` and `freeze`; `runtime/gate-classification.md:54`
  marks them HUMAN ONLY, never auto-resolved.
- `skills/migrate-it/SKILL.md:72-81`: every phase runs "build-blind REVIEW → LAND → deploy →
  BAKE, then the next phase is dispatched"; the Gates section (`:119-121`) names only CONTRACT
  as the human gate and says to "open the promotion PR and stop". `release.md`, which carries
  the recorded-grant deploy rule, is neither composed nor deferred. As written the pipeline is
  also unreachable: ZERO-READERS needs production telemetry from a deployed SWITCH-READS, yet
  the fleet stops at one promotion PR.
- `skills/offload-it/SKILL.md:56,65,79-80`: preflight runs in `--mode readonly` ("for
  report-only fleets that never open PRs"), then SCAFFOLD writes `scripts/orca-vm/` and WIRE
  writes `orca.yaml` on the PRIMARY checkout, with no BASE, PR, review or evidence class.
  `README.md:604-610` says a fleet that touches the default branch is a bug;
  `runtime/evidence-manifest.md:151-160` lists offload-it in no mission class.
- FREEZE is performed by the coordinator with no human gate in `skills/access-it/SKILL.md:56`,
  `skills/attest-it/SKILL.md:55-59` and `skills/migrate-it/SKILL.md:65`. speed-it, prove-it,
  oncall-it, document-it, reshape-it and floor-it all gate it. In a headless or scheduled run
  these three auto-decide a door `runtime/mission-scheduling.md:53-55` says must park.

## 4. P2 findings

Real defects with a narrower trigger, or a documented guarantee the code does not provide.
Items marked (reviewer) were reproduced by the layer reviewer and read, not re-run, by the author.

### Verifier

- **P2-1 the "never revert the oracle" bind is a filename test.** `verify.py:1388-1400`
  (`_is_oracle_path`) uses fixed config names, the `diff_scope.py:129` TESTS regex
  (`tests?/`, `spec/`, `test_*`, `.test.`, …) and only explicitly named proof inputs. A test at
  `checks/add_check.py` (pytest `python_files = *_check.py`), or under `specs/`, `qa/` or
  `features/`, is classified production, so `negative_control.paths` may revert it and the RED
  comes from the old oracle failing against head. Renaming the same file to `checks/test_add.py`
  is refused. (reviewer)
- **P2-2 dispatch records signed with `--profile` never verify.** `verify.py:2478-2483`
  (`_canonical_dispatch`, `_DISPATCH_FIELDS` only) versus `dispatch-sign.py:188-197,337-345`
  (append `_PROFILE_FIELDS` when present). A genuine coordinator signature over a
  profile-narrowed dispatch (#590) is reported "INVALID … forged or wrong key"; the docstring's
  "byte-for-byte … a cross-tool test guards this" is false because the parity tests sample only
  profile-free records. Fail-closed, so no false done, but the enforcement lane is unusable for
  any `rw`/`danger` narrowing. (reviewer)

### Runtime scripts

- **P2-3 decisions.py grant replay.** `decisions.py:236-239` signs id/answer/why/task only;
  `:425-434` picks newest by `ts`. A signed `approved` copied with a later `ts` out-ranks a
  later signed `superseded`. (reviewer)
- **P2-4 floor_guard diff prefixes.** Repo-local `diff.mnemonicPrefix` or `diff.srcPrefix`
  relabels `a/`/`b/` and `strip_prefix` (`floor_guard.py:301-307`) no longer matches; guard-surface
  and assertion-removed go silent. `gitexec.py:49-58` does not pin these keys. (reviewer)
- **P2-5 floor_guard threshold-lowered.** `floor_guard.py:408-421` needs an in-place edit of the
  same row key; deleting the row, re-keying it (`D1b`), or replacing the number with a word is
  silent. CONSTRAINTS.md is not on the guard surface. (reviewer)
- **P2-6 floor_guard assertion-removed.** A renamed test file (delete+add under `--no-renames`,
  `:398-406`) or a non-ASCII path (C-quoted header, `:280-283`) exempts dropped assertions.
  (reviewer)
- **P2-7 watchdog never fires on missing timestamps.** `watchdog.py:361-371` defaults a missing
  `dispatched_at` to now and a missing `last_movement_at` to dispatch time, and clamps a future
  movement time to 0 idle; a producer that drops a field blinds the watchdog instead of failing
  loud. (reviewer)
- **P2-8 watchdog signs pending CI as failure.** `:773-775` skips only
  success/neutral/skipped/passed; `in_progress`/`PENDING`/`QUEUED` burn the single CI nudge, and
  the real failure 90 minutes later is withheld ("budget spent (1/1)"). (reviewer)
- **P2-9 diff_scope drops the old path of a rename.** `diff_scope.py:223-226` uses `--name-only`
  without `--no-renames`; moving a file out of `db/migrate/` or renaming `session_guard.py`
  never sets the MIGRATIONS/AUTH lens. (reviewer)
- **P2-10 deny-hook ANSI-C quoting.** `$'\x72m' -rf /` is ALLOWED (`_split` `:740` keeps the
  single-quote body literal; the never-list sees no `rm` substring). Reproduced. Execution
  depends on bash/zsh, which CI and macOS both use.
- **P2-11 quarantine is direct-clause only.** `quarantine_check.py:183-219` and
  `preflight.py:211-249` resolve the mission's own clause; a quarantined playbook reached
  through `acceptance-review → risk-review`, or named in the body, starts. (reviewer)
- **P2-12 never-list "history-discarding local git" is two forms.** `deny-hook.sh:2872-2873`
  matches `git reset --hard` and bare-dot `checkout|restore .`; `git branch -D main`,
  `update-ref -d`, `reflog expire`, `stash drop`, `filter-repo`, `worktree remove --force`,
  `checkout -- .`, `restore -- .` and `clean -fd` run with no ask. (reviewer)
- **P2-13 egress receipt bypass.** `_is_send` (`:1170`) sees `gh` only as segment head after the
  Python peeler; `timeout 5 gh pr merge 12`, `exec gh …`, `bash -c "gh pr merge 12"`, `eval …`
  and `xargs gh …` run with no ledger line. (reviewer)
- **P2-14 destructive `gh` verbs outside rule 5.** `gh repo delete --yes`, `gh workflow run`,
  `gh gist create`, `gh variable set`, `gh cache delete` are neither receipted nor asked
  (`SEND_VERBS` `:947`, `_is_send` scope `:1175`). (reviewer)
- **P2-15 sandbox doctor judges `/home` by the coordinator's `$HOME`.** `sandbox_doctor.py:201`
  compares a mount source to `expanduser("~")` of the judging process. A macOS coordinator
  (`/Users/x`) clears a Linux recipe that bind-mounts `/home`; the same check passes with
  `HOME=/home/tester`. This is also the `test_sandbox_doctor` failure on every macOS host.

### Build and validator scripts

- **P2-16 length caps measured on the first line.** `validate.py:331-344` drops continuation
  lines of a plain multi-line scalar; a 2,194-character description measures 59, a
  905-character compatibility measures 5. The skills-ref CI step likely backstops this;
  `install.sh` gates on `validate.py` alone. (reviewer)
- **P2-17 paraphrase rule escapes on one point.** `validate.py:834,895` requires all six points
  at ≥0.5 containment; rewording one point with words outside the 23-entry concept table
  (`_identity.py:43-70`) scores it 0.0 and the pair passes with at most a WARN; all six reworded
  is silent. `AGENTS.md:116-118` says a paraphrase fails "however it is worded". (reviewer)
- **P2-18 typo'd backticked names ignored.** `BACKTICK_RE` (`:170`) accepts `[a-z0-9-]` only;
  `` `Build-Change` ``, `` `build_change` `` and `` `playbooks/build-change` `` in a clause are
  neither resolved nor flagged, while the `.md` spellings are. (reviewer)
- **P2-19 `skills/_x/` and `skills/.x/` skip every rule.** `validate.py:1156-1157` skips them,
  but `skills/*/SKILL.md` globs in `eval.py:209`, `bundle.py:291` and `install.sh:192` pick them
  up; a 404-line body with no metadata passes the build. `install.yml` and the agentskills loop
  would red `_draft`; `.hidden` escapes both. (reviewer)
- **P2-20 the SHA-bound-evidence floor is an allowlist.** `MUTATING_MISSIONS`
  (`validate.py:112-130`) is hand-maintained; a renamed code-landing mission that drops its
  `evidence-manifest`/`sandbox-policy` rides passes with no error. (reviewer)
- **P2-21 `bundle.py --out` deletes the user's directories.** `bundle.py:277-287` rmtrees
  `<out>/.claude-plugin`, `hooks`, `runtime` and `skills` when they are not the source's own.
  `--out ~/.claude` removes the user's own `~/.claude/skills`, which is where the README's
  symlink install puts missions, with exit 0 and no prompt. The only guard (`:424-430`) is the
  `--out .` case.

### CI and tests

- **P2-22 `verdict` is self-triggerable.** `verdict-check.yml:3-8,61-66` runs the PR's copy of
  the workflow on `pull_request_review` and accepts a `VERDICT: GO` COMMENTED review from the PR
  author. Known and tracked as #594 (p1, needs-human); listed because it is live today and it
  is one of the three contexts left once `gates` is skipped (P1-5).
- **P2-23 any write-access tag push publishes.** `release.yml` and `publish-dist.yml` run on
  `push: tags: v*` with `contents: write` and `publish-dist.yml:114` force-pushes `dist`;
  `docs/ops.md:27-29` says only Ravindra authorises a cut. No tag protection or ruleset exists
  (verified through the API).
- **P2-24 the suite can rewrite the live README.** `tests/test_architecture.py:260-266` and
  `:294-300` call `gen.write()` with `gen.README` unpatched; `gen-badges.py:334-341` ends with
  `write_readme()`, which writes `ROOT/README.md` when the proof block is stale. A no-op on a
  clean tree, so CI never shows it.
- **P2-25 two validator gates have no validate-level negative fixture.** `check_quarantine()`
  (`validate.py:1096-1131`) and `check_evals()` (`:953-955`) are tested only at their engines;
  deleting either call from `main()` leaves the suite green. The repo's own #303 test
  (`ValidatePyRunsTheLayerChecks`) exists because this exact mutant once passed. (reviewer)

### Missions, playbooks and runtime doctrine

- **P2-26 ship-it solo run "stop at `BUILT`".** `skills/ship-it/SKILL.md:56-57` names the wave
  state; the source rule (`playbooks/acceptance-review.md:19-20`) says the per-unit build state.
  A solo coordinator reports `BUILT` for a branch with zero merged units.
- **P2-27 a playbook ship-it loads says ship-it is doctrine-only.**
  `playbooks/acceptance-review.md:21-22` versus `proof: external-run` in the frontmatter and
  `proof_status.py`. Reproduced by reading.
- **P2-28 modernize-it has no negative control.** No negative/revert/control/failing-first
  mention in `skills/modernize-it/SKILL.md`; `runtime/evidence-manifest.md:151-153` lists it as a
  mutation unit whose control is executed per §2. Reproduced by grep.
- **P2-29 the suite is red on macOS.** Three deterministic failures:
  `tests/test_diff_scope.py:559` writes a filename with an invalid UTF-8 byte (APFS refuses it,
  Errno 92); `tests/test_sandbox_doctor.py:284` assumes `$HOME` is under `/home` (P2-15);
  `tests/test_posix_provider.py:477` (P1-11). No platform skip guards exist, and
  `docs/development.md` and `CONTRIBUTING.md` do not mention the platform.
- **P2-30 harden-it, floor-it and root-cause plan on a lane the policy blocks.**
  `runtime/sandbox-policy.md:104-105` says every Orca danger spawn is refused and no mission may
  plan on that lane; `skills/harden-it/SKILL.md:18-19,65-66` makes it a hard dependency and the
  guide's worked example (`docs/missions/harden-it.md:164-167`) shows it running.
- **P2-31 routing dead-ends.** `speed-it:10` and `oncall-it:10-11` route "post-deploy watch
  alone" to ship-it, whose entry (`ship-it:77-81`) accepts only a spec, raw intent or a map-it
  handoff; `docs/research/REJECTED.md:27` rejected the standalone mission. `document-it:11-12`
  routes doc-sync to a ship-it unit that exists only inside a wave ship-it built.
- **P2-32 oss-contribute defers a doc to a phase it lacks.** `skills/oss-contribute/SKILL.md:43`
  reads `reviewed-sha-freshness.md at LAND`; the pipeline has no LAND (`:77` "No conductor") while
  the proof (`:82`) requires the freshness rule. The guides for oss-contribute (`:243-252`) and
  clean-sweep (`:245-246`) list deferred docs under "At activation".
- **P2-33 field-test-it is written as two tiers and owns five.** `SKILL.md:34` "(PHYSICAL or
  EMULATOR)" versus the ladder at `:67-68`; the guide never names BROWSER, DESKTOP or CLEAN-ENV,
  and `compatibility` requires an emulator or device, yet `README.md:331` and REJECTED.md route
  web-journey and fresh-box asks here.
- **P2-34 review-it guide promises zero in-run gates.** `docs/missions/review-it.md:142` versus
  `skills/review-it/SKILL.md:38-39` (posting the verdict is a one-way gate with a recorded grant).
- **P2-35 the "single home" tooling table covers 10 of 22 missions.**
  `docs/getting-started.md:58-75`; absent rows each carry a hard extra in `compatibility`
  (absorb-it, access-it, attest-it, document-it, migrate-it, oncall-it, offload-it,
  oss-contribute).
- **P2-36 the `deletion` door nets routine teardown.** `runtime/one-way-doors.json:72-94` keys
  "delete the branch" and "delete the worktree"; `merge-serialization.md:49` and
  `dispatch-lifecycle.md:144-149` make those ungated conductor steps. Reproduced: `decisions.py
  append --class mechanical … "gh pr merge --merge --delete-branch succeeded; worktree retired"`
  is refused as a one-way match.
- **P2-37 threat-model says the hook refuses Never shapes; it asks.** `runtime/threat-model.md:30-32`
  cites `sandbox-policy.md`, which never mentions the hook; `deny-hook.sh:24-28,56-57` denies the
  HIGH tier and asks on the Never list. Boundary 3 (`threat-model.md:65-66`) also credits the
  deny-hook with quarantine enforcement; the hook never reads `quarantine.json`.
- **P2-38 acceptance-review tells the reviewer worker to fan out.**
  `playbooks/acceptance-review.md:24,36` ("isolated parallel sub-agents … separate fresh-context
  workers") versus `runtime/dispatch-lifecycle.md:67-69` (workers do not dispatch; the
  coordinator dispatches the axes).
- **P2-39 release.md's gates have no protocol where they run.** `release.md:30-33,37-39`
  (doc-sync unit, operability gate) name neither `doc-coverage` nor `instrument`, which each
  claim to be that protocol; ship-it and migrate-it compose neither.
- **P2-40 playbooks delegate to playbooks the missions never load.** `remediate-finding.md:13`
  hands the fix to `build-change`, which 12 of its 16 composers do not load;
  `human-handoff.md:17` to `agent-brief` (9 of 9); `triage-state.md:38` to `human-handoff`
  (3 of 3); `compound-learn.md:44,53` to `encode-lesson` (16 of 17) and `diagnose` (15 of 17);
  `evidence-manifest.md:105` sends the verifier command line to `build-change.md` (17 of 22
  riders). (reviewer, mechanical)
- **P2-41 the Orca pin's witness level disagrees with itself.** `runtime/pins.json:8` says
  `"witness": "live"`; `runtime/orca-pin.md:19` and `docs/runs/2026-10-17-pin-it-229.md:3` say
  `source`; `orca-pin.md:10` says the two never disagree. `tests/test_pins.py:203` checks
  membership only. Reproduced by reading.

## 5. P3 findings and hygiene

- Verifier: `pr.number` is not validated before interpolation into the `gh api` path
  (`verify.py:1049,676-685,953`; github.com rejects dot-segments, so it fails closed today);
  `verify-gate.sh:61-73,123-125` reads an undocumented `OPEN_FLEET_*` family that overrides
  every documented `ORCA_*` input, including the class and review-waiver switches;
  `run_report.py:485`'s "wtree resolves to a real tree" floor is satisfied by the empty-tree
  constant; the dispatch canonicalization is written three times (`dispatch-sign.py:188-197`,
  `:337-345`, `verify.py:2478`) and `_fresh_command_records` (`verify.py:1145-1160`) carries a
  stale rationale; `docs/verify-gate.md:149` budgets "2 checkouts + 2 runs" for a control that
  runs three phases and four checkouts.
- deny-hook: `curl | sh` ask evaded by `wget | sh`, `curl | sudo sh`, `sh <(curl …)`,
  `curl | python3`, `curl -o … && sh …` (`:2869`); HIGH-tier matching fails open if `grep` is
  absent (`:2648`, plausible, not reproduced).
- floor_guard: `self.skipTest(`, `raise unittest.SkipTest`, `t.Skipf(` and `def test_x` →
  `def _test_x` are not test-made-easier patterns (`:103-112`).
- chain_check: classification is case- and spelling-sensitive; `Done-With-Parked` proceeds
  (`chain_check.py:36-43`). diff_scope's inlined git hardening omits `GIT_CONFIG_GLOBAL`,
  `GIT_CONFIG_NOSYSTEM` and `safe.directory` that `gitexec.py` sets.
- validate.py: a `---` inside a description crashes it through `gen-badges.py:251-254` before
  `check_quarantine` runs; a BOM-prefixed frontmatter under `playbooks/` escapes the lower-layer
  check (`:669-674`); `../../docs/x.md` links from a SKILL are resolved against ROOT and
  reported dangling (`:271`); routing coverage is satisfied by an `expected_any` row the mission
  never wins (`eval.py:537-549`); the activation-load cap is one catalog-wide 34,000, so 21 of 22
  missions can grow by thousands of tokens (`:727-733`); five divergent frontmatter readers
  (`validate.py:296`, `proof_status.py:28`, `eval.py:154`, `release_check.py:424`,
  `gen-badges.py:247-255`); `quarantine_check.py:59-61` copies `COMPOSE_CLAUSE_RE` that
  `validate.py:157-158` says callers import; `verdict_check.py:104-109` reads `VERDICT: GO`
  followed by `VERDICT: NO-GO` as GO; `release_check.py:486-497` "CI runs X" is satisfied by any
  text mention.
- Tests: `tests/test_shard_tests.py:96-105` compares two literal sets and cannot fail.
- CI: `fixture-target-app.yml:39` runs unpinned `uvx ruff`; `alert-on-failure.yml:87,95,96`
  interpolate step outputs inline (digits, not exploitable; the hygiene regex in
  `test_repo_hygiene.py:370` misses `ref_name`, `inputs.*`, `steps.*`); `negative-control.yml:27-33`
  sets `pipefail` under `bash -e`, so its `PIPESTATUS` diagnostic is unreachable.
- Commit hygiene: 12 of the last 200 commits carry trailers `CONTRIBUTING.md:157` forbids (8
  `Co-Authored-By: Claude Opus 5.5` on 2026-10-20, e.g. `d978714282`; 4 copilot merges, e.g.
  `acecf00a7c`); nothing mechanical enforces the rule.
- Doctrine: `evidence-manifest.md §3` classifies 21 of 22 missions (offload-it absent);
  `worker-supervision.md:63-74` says every threshold lives in `watchdog.json` but
  `max_ci_nudges_per_dispatch` lives only in `watchdog.py:90`; six playbooks have no
  `## Completion` (build-change, characterize, encode-lesson, explain-the-number,
  remediate-finding, upstream-contribution) and three carry no `Recipe:` line; superset,
  paperclip and openhands advertise `danger` with no `cap:sandbox-vm`; two playbooks adapt
  pstack 0.15.20 with no `pins.json` entry; `clean-env-drive.md:3` prescribes
  `--worktree new-top-level`, which `dispatch-lifecycle.md:56-58` reserves for unsupervised
  handoffs; `orca-pin.md:123-125` corrects a line that no longer exists; `attention-budget.md:24-26`
  calls the 2026-07-15 chimely run "measured" with no retained report; `ARCHITECTURE.md:107`
  names `spec-to-ship`, a mission that does not exist; `docs/getting-started.md:306-313` lists
  four interrupt points and omits at least eight.
- Mission bodies rely on docs neither composed nor deferred (`access-it:79` human-handoff;
  `migrate-it:46` release.md; `offload-it:101-105` ledger-contract and liveness-resume;
  `modernize-it:76` agent-brief); `modernize-it:45` and `migrate-it:103` send an agent to
  `docs/missions/*.md`, which `bundle.py` does not ship.
- D9 coverage: the last committed evidence is 81 % (2026-09-16); `CONSTRAINTS.md:45` still reads
  "75 % BELOW BAR"; scripts have grown since with no re-measurement committed.
- vf-bench's 0 % is a lower bound over 20 sampled legs with one runner; unsampled:
  non-unittest runners (P1-1), author-as-approver, symlinked or escaping negative-control
  artifact, missing artifact path, dismissed-then-replaced approval, intent-packet absence,
  lighting swap, hidden criteria (#600 tracks part of this).
- A 16.2 MB video (`assets/orca-fleet-reel.mp4`) is tracked.
- The primary checkout's local `main` is one commit ahead of `origin/main` (`41f37271d3`, adds
  `.claude/skills/*` symlinks only); it looks like local wiring, never pushed.

## 6. What is genuinely good

- The verifier refuses every evidence-path escape tried (absolute, `..`, symlink out of root,
  tracked directory as artifact), reads each artifact once, never spawns a shell, refuses
  option-shaped SHAs and refs, closes replace objects, grafts, `fsmonitor` and `protocol.ext`,
  pins `gh`/`git`/`gitleaks` to absolute paths with custody checks, requires the clean command to
  pass before and after the control, refuses a control whose tree equals head, binds `hand` hunks
  to the base..head change, and recomputes the reviewed-tree equality locally. Ed25519 matches
  RFC 8032 constants and test vectors and rejects non-canonical, small-order and wrong-length
  inputs. The bench gate cannot pass vacuously.
- Every `uses:` in 13 workflows is SHA-pinned and the six distinct pins match upstream tags.
  No `pull_request_target`; no tainted `${{ }}` reaches a `run:` block outside `env:`;
  permissions are least-privilege per workflow; the fork filter on `alert-on-failure.yml` holds.
- Tool installs are `--require-hashes` from one lock; gitleaks is pinned by version and sha256,
  runs with `--redact`, and the workflow plants a key in the waived file and requires red.
- The validator rejects every proof-evidence traversal, symlink and foreign-report shape tried
  (9/9); the proof ratchet fires on a 23rd doctrine-only mission; the activation-load cap really
  has ~0 headroom for ship-it; the sharder's union-equals-discovery contract catches a dropped
  test file.
- The deny-hook correctly handles binary-path and quote laundering of the command name,
  env/VAR= and sudo prefixes with assignments, git global options, push long-option
  abbreviations and lease semantics, JSON-level tricks, missing python3 (fail-closed), the
  worktree write boundary with 32-hop symlink resolution, and `apply_patch`/heredoc targets.
- egress.py is an append-only hash chain under `flock` with 0600 files and fail-closed exits.
- decisions.py refuses credential-shaped answers, a `--source` typed into prose, and a one-way
  line with no human source; keygen refuses an unignored worktree and writes the seed 0600.
- Of 3,017 test methods scanned, none asserts on literals, none wraps an assertion in an
  except clause that only passes, none patches the function under test, none needs the network, and every
  committing test sets its own git identity. All 18 skip sites are conditional and none is
  always-true on CI.
- 1,241 relative links and anchors across the top-level docs, 22 mission guides and 22 SKILLs
  resolve; the docs index matches the tree both ways; all five bound run reports re-hash at the
  commits they name.

## 7. Suggested order

1. Verifier: add the `core.hooksPath=/dev/null` config pair to `git_env()` (or run controls from
   a hook-free clone) and make the seal and the sanity check read the same object; run the
   stillborn analysis regardless of the counted failures, or treat SyntaxError/ImportError
   markers as stillborn even beside `N failed`; align `_canonical_dispatch` with the signer and
   extend the parity tests to profile fields; add pytest and Jest-style stillborn traps to
   vf-bench.
2. Deny-hook: route the HIGH tier through the same peeler the egress side uses and add
   `timeout`, `exec`, `setsid`, `stdbuf`, `xargs`, `ionice` to it; model `chmod`, `sort -o`,
   `ed`, `rsync` in `guard_targets`; treat `$'…'` as a decodable word. Add each ALLOW line in
   P1-3/P1-4/P2-10 as a pinned deny test.
3. CI: `if: always()` on `gates` with a first step that fails unless `needs.tests.result` and
   `needs.floor.result` are `success`; or require the shard contexts directly. Consider a
   required approving review and the #594 identity.
4. Floor guard and ledger: pass `--text` and `-c diff.mnemonicPrefix=false -c diff.srcPrefix=a/
   -c diff.dstPrefix=b/` on every diff; read waivers from the base ref, require class
   `one-way` plus a verified signature for `floor-waiver:*`; make `validate()` require a
   signature on every one-way line when a key is pinned and bind `ts` into the grant payload.
5. Validator: parse block scalars under `metadata:`; make `check_quarantine` use the same
   composition set as `transitive_load` plus deferred reads and transitive playbook edges.
6. Suite safety: carry `PATH` (or an explicit agent path) in the worker env file, and make the
   tmux test fail closed when the fake agent is not the one that ran; add `darwin` skips or
   portable fixtures for the three macOS failures.
7. Doctrine: gate deploy and freeze in migrate-it, access-it, attest-it; give offload-it a
   BASE, a PR path and a mission class; fix the stale proof tier in acceptance-review.md and the
   `BUILT`/`BUILD_DONE` sentence; reconcile the `deletion` door with WT_CLEAN.

## 8. Evidence

The reproduction fixtures were built in throwaway clones on the author's machine and are not
retained in this repository. Each finding above names the exact source lines, the input shape
(the fixture edit, the command, the payload) and the observed output, which is what a
maintainer needs to rebuild it; the repository's own standard is that a guard's negative-path
fixture lives beside the guard as a test, so the durable form of each reproduction is the
regression test that should land with its fix, not a file in `docs/`. The deny-hook probes used
the invocation shape of `tests/test_deny_hook.py`; the verifier fixtures mirror the
`bench/vf-bench` fixture; the floor-guard and ledger fixtures are one-file repositories built
with `git init` plus the single edit each finding describes.

Branch protection, rulesets and tag protection were read with `gh api`; GitHub's skipped-check
semantics were read from docs.github.com (troubleshooting-required-status-checks); the runner
image inventory from actions/runner-images (Ubuntu 24.04 README). No tracked file other than
this document was added or modified.
