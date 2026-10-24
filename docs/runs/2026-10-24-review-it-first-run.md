# Run report — live first runs for provider certification (#596), 2026-10-24

RUN: mission=review-it tier=external-run inventory_at=efc586afd8fba21c784be8d870707329bd5eca48 manifest=docs/runs/2026-10-24-review-it-first-run/manifest.json verifier=GREEN

This report binds the live evidence behind the certification record
([certification.md](../certification.md), `runtime/providers/certification.json`). It is filed
under `review-it` because each first run is a read-only review unit, the review-it shape that
`first_run.py` drives through the public wrappers and preflights as `review-it`. It is **not** a
review-it mission run: no PR was reviewed, and `skills/review-it/` claims nothing from this report.
The tier is `external-run` because every reviewed target is a two-commit repository the run
synthesizes, not this catalog.

| Field | Value |
|---|---|
| Catalog | `b96d47e3354564e1593d34182a817ae04e54545d` (`claude/r03-cert-close`), clean, on every host |
| Route | `posix` provider, `setsid` backend, `PROFILE=ro` and `PROFILE=rw`, harness `claude` |
| Harness | Claude Code 2.1.304, model `claude-opus-5-5` |
| Hosts | the dev Mac (macOS 27.0.1 arm64) through an isolation wrapper; a fresh `ubuntu:24.04` container (aarch64, Linux 7.2.12) on the same Mac's OrbStack |
| Runner | the coordinator session, for the maintainer (Ravindra Kumar), who authorized the live spend |
| Spend | USD 0.0796 (Mac ro), 0.0909 (Mac rw), 0.0843 (clean ro), 0.0895 (clean rw), as the harness reported; the earlier 456051e3ec pair cost 0.1999 and 0.2208; the Orca attempt started no turn |

## Terminal state

**GO** on all four cited runs. `posix` `ro`/`claude` and `rw`/`claude` are live-witnessed, on two
hosts. The Orca `ro`/`claude` re-witness was **not** done: it stopped at Claude Code's folder-trust
prompt before any injection, so that cell keeps its 2026-10-13 witness, marked as owed a new one.

| Run | Host | Profile | Verdict | Turns | Cost (USD) | Elapsed | Receipt |
|---|---|---|---|---|---|---|---|
| Mac ro | macOS 27.0.1 arm64, wrapper | ro | GO, settled `completed` (relayed ro completion line) | 3 | 0.0796 | 11.3 s | `2026-10-24-review-it-first-run/mac-ro/receipt.json` |
| Mac rw | macOS 27.0.1 arm64, wrapper | rw | GO, settled `completed` (`worker_done`) | 5 | 0.0909 | 16.6 s | `2026-10-24-review-it-first-run/mac-rw/receipt.json` |
| Clean ro | ubuntu:24.04 container | ro | GO, settled `completed` | 3 | 0.0843 | 10.7 s | `2026-10-24-review-it-first-run/clean-host/receipt-ro.json` |
| Clean rw | ubuntu:24.04 container | rw | GO, settled `completed` | 4 | 0.0895 | 15.5 s | `2026-10-24-review-it-first-run/clean-host/receipt-rw.json` |

Every cited receipt has every step from `prereqs` to `release` ok, and `verify.py` OK on the
first run's own SHA-bound manifest. Each receipt's `witness` line names its route, harness version
and catalog commit, and the certification record quotes it.

## The runs

**Mac, isolation wrapper.** `isolation/claude-wrapper.py` was the `claude` first on `PATH`
(`isolation/run-596.sh`). It execs the pinned 2.1.304 binary, not the auto-updated symlink, with:

- an allow-listed environment, an empty `HOME` and an empty `CLAUDE_CONFIG_DIR`;
- `--setting-sources project,local`, `--strict-mcp-config`, `--disable-slash-commands` and
  `--no-session-persistence`;
- the subscription token read from a file the wrapper names by path. The token appears in no
  artifact.

For these posix runs, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=0`: the scrub forces the default
permission mode and breaks the rw bypass. The wrapper hashed
`23e9493996f59c3c81f8784d35cd792f07707cb4adacbfbe177ce39853e0f8bd` at first write. It was edited
once; the retained copy, as it stood for these runs, hashes
`e2c35ae7b1fef3a58ff3595233c048d6cef65305496ef68de4783a368ea07302`. Each Mac run's own first-run
manifest, contract, change, report and harness transcript are retained beside its receipt.

The ro transcript's `init` event lists no `Write` or `Edit` tool, so base.py's `--disallowedTools`
held on the posix ro line. The rw worker committed its report through a Bash heredoc, sent
`worker_done`, then printed the same report as its final answer, as the fixed assignment asks.

**Clean host.** `clean-host/clean-host-596.sh` starts a fresh `ubuntu:24.04` container. The only
credential passed in is `CLAUDE_CODE_OAUTH_TOKEN`, by name. Inside it, `inner.sh` installs the OS
prerequisites as root, and `user.sh` does the rest as a fresh non-root user:

- installs Claude Code 2.1.304 with the official installer;
- clones the public repository at the branch;
- runs `first_run.py --worker live` for `ro`, then `rw`.

`clean-host/clean-host.log` timestamps each step. Prerequisites took 15 s, the install 14 s, the
clone 5 s, the ro run 11 s and the rw run 16 s, 61 s end to end. There were no failures, so no
recovery. The sandboxes went with the container: only the receipts and the log remain.

**Earlier runs at 456051e3ec** (`first-attempt/`). The ro run went GO. The rw run went NO-GO at
`result`: the rw assignment never asked for the report as the final answer that `result` reads.
That finding is fixed at the cited catalog commit.

## Orca ro/claude re-witness attempt (refused, certifies nothing)

From the catalog worktree, with Orca 1.4.229 (equal to the pin) and Claude Code 2.1.304:

- `SW_PRINT_LAUNCH=1 PROFILE=ro spawn_worker.sh … claude` printed
  `LAUNCH=claude --permission-mode plan --disallowedTools=Edit,Write,MultiEdit,NotebookEdit`
  (`orca-ro-attempt/launch.txt`).
- A scratch review unit (`orca-ro-attempt/unit-log.txt`, `change.diff`) was registered with
  `orca repo add`. A coordinator terminal and Run (`run_cd72e660a883`) were created.
- ONE ro worker was started:
  `PROFILE=ro spawn_worker.sh --mark-ready --run … --from … --spec … path:<scratch> orca-ro-witness claude`.

The proposed `new-child` selector cannot reach that lane, because Orca's `terminal create` takes an
existing worktree. `spawn_worker.sh` now refuses it there before any task is created.

The pane started the current row. Claude Code warned that the deny rule `MultiEdit` matches no
known tool: 2.1.304 has no such tool, and the other three rules apply. The pane then stopped at
Claude Code's folder-trust prompt for the scratch folder (`orca-ro-attempt/worker-screen.txt`).
Trust of the parent `~/projects` did not carry over to it.

Orca's `terminal wait` reported `blockedReason: agent-trust-workspace`
(`orca-ro-attempt/terminal-wait.json`), and the spawn failed closed at `wait-tui-idle` before any
injection (`spawn.stderr`). No turn started and nothing was spent.

Answering a trust prompt is a grant only the operator gives, so the coordinator did not answer it.
Clean-up:

- both terminals were closed without trusting the folder; `~/.claude.json` records no trust for it;
- the scratch repository's Orca registration was removed with `orca project setup-delete --force`;
- the scratch folder was deleted.

Task `task_95353ebdda84` is left `ready`, with no worker, in that Run: the Run's coordinator
terminal had been closed, so Orca fenced the cancel (`consumer_fenced`).

To re-witness, the operator first trusts the review folder in Claude Code. Then the commands in
[certification.md](../certification.md#the-orca-path) run unattended to the plan-approval prompt.

## Orca re-witness retry (not run: the Orca app was not running)

A second attempt was authorized for a folder Claude Code **already** trusts, never answering a
trust prompt. First, how Claude Code 2.1.304 decides trust, read from the binary's own code
(`strings` near `hasTrustDialogAccepted`):

- A folder is trusted when `projects[<canonical git root>].hasTrustDialogAccepted` is true, or
  when some directory from the working directory up to its git root is trusted.
- The canonical root of a linked worktree is its main repository's root. It is resolved through
  the `.git` file's `gitdir` and `commondir`.
- Directories above the git root never count. A new repository under a trusted `~/projects`
  therefore prompts, as the first attempt did.

On this Mac, `~/.claude.json` trusts the open-fleet repository only under its symlinked path
`/Users/ravindra/projects/orca-fleet`. Its worktrees' `gitdir` names the real path
`/Users/ravindra/projects/open-fleet`, so a new open-fleet worktree would prompt.
`/Users/ravindra/projects/oss-contribution-agent` is trusted at its real path, registered in Orca,
and has no project `.claude/` settings. A new Orca worktree of it (`orca worktree create --repo
id:635ce96a-… --name of596-ro-witness --no-parent --setup skip`) would inherit trust through its
canonical root, so the witness could run there with no new grant.

The retry stopped at the first Orca call. `orca status --json` read `app.running: false` and
`runtime.state: not_running`, and `worktree create` answered `runtime_unavailable`. Nothing was
created: no worktree, no branch, no terminal, no task. Starting the app was not part of the
authorization, so the coordinator did not start it.

The fresh witness is still owed. It needs either of two things:

- the Orca app running, with the worker run on a new worktree of a repository trusted at its
  real path, as above;
- or the operator trusting open-fleet once at its real path:
  `cd /Users/ravindra/projects/open-fleet && claude`, accept the dialog, then exit.

The leftover `task_95353ebdda84` could not be retried for cancellation either, since every
orchestration command needs the running app.

## Orca re-witness, second attempt (trusted worktree): inject rejected, then Orca restarted as 1.4.238

With the app reopened at 1.4.229, which matched the pin on main, the planned route ran. The
evidence is in `2026-10-24-review-it-first-run/orca-ro-attempt-2/`; it is listed in no inventory,
so it is retained but unbound.

- **Setup.** `orca worktree create --repo id:635ce96a-… --name of596-ro-witness --no-parent
  --setup skip` made a new worktree of the trusted repository. A single scratch commit on its own
  new branch carried the review unit. A coordinator terminal and Run (`run_9059b9ac42b5`) were
  created. `launch.txt` again read
  `LAUNCH=claude --permission-mode plan --disallowedTools=Edit,Write,MultiEdit,NotebookEdit`.
- **Trust held.** With no trust grant, `terminal wait --for tui-idle` was satisfied. The pane
  showed Claude Code v2.1.304 idle in plan mode (`worker-screen.txt`). This confirms the rule read
  from the binary: a linked worktree inherits trust from its main repository's root.
- **The inject was refused.** Orca 1.4.229 answered `dispatch --inject` with `inject_rejected` /
  `no_agent_detected` (`dispatch-inject.json`), although the pane ran
  `claude --permission-mode plan --disallowedTools=…` and showed its TUI.
  `spawn_worker.sh` failed closed at `dispatch-inject`. No prompt reached the worker, no turn
  started, and nothing was spent. The cause is not established. The app was replaced moments
  later, and whether 1.4.229's agent detection reads this launch line is untested.
- **Orca then restarted as 1.4.238.** Every call of the attempt was served by runtime
  `e711afeb…` at 1.4.229. Right after the refusal, `orca status` showed a new runtime
  `489b711a…` at **1.4.238** (`orca-runtime.json`), and the attempt's terminals were orphaned. A
  witness taken from then on would have been at a build other than the pin on main, so the
  attempt stopped. No new dispatch was tried, and no prompt was sent by hand.
- **Cleanup**, all confirmed (`cleanup.json`):
  - this attempt's task was marked `failed` / cancelled;
  - the first attempt's leftover `task_95353ebdda84` was cancelled the same way, after
    `run-use` bound a live terminal to `run_cd72e660a883`;
  - all three terminals were closed, killing the idle worker;
  - Orca removed the worktree;
  - its branch was deleted only if it still held the scratch commit, and Orca's branch config
    entry for it was removed.

  The trusted repository's HEAD, `git status`, branches, stash and worktree list were compared
  before and after, and are identical. The two Runs remain: Orca's CLI has no command to delete
  one. Each holds one cancelled task.

Still owed: a fresh Orca `ro`/`claude` witness on the current row. It can now run only at the
build installed on this Mac, Orca 1.4.238, so it belongs with the pin move to 1.4.238 and
should also establish why the inject was not recognized.

## Verifier outcome (recorded exactly)

The unit binds the run directory under a frozen contract (`contract.md`, LR-1 to LR-5). Its
evidence range carries only the coordinator's verdict (`binding.md`), and every artifact is
pinned by sha256 at the range's head. `rederive.py` re-derives each criterion from the files
(`rederive.txt`: `REDERIVE=OK`). The verifier ran twice, through `evidence-run.py`, and both
records are in the manifest's ledger:

    python3 runtime/scripts/verify.py --manifest docs/runs/2026-10-24-review-it-first-run/manifest.json --contract-source docs/runs/2026-10-24-review-it-first-run/contract.md@6c3a3a4596ea517883cf034a44b38d16b3b54c7a --contract-digest sha256:1ec9bc7886a6948a48d102a73e32d6c391c622ad4963aeb12245b13ac5c9420f --unit-class report-only
    exit 2  (first shape: the artifacts were the range of a report-only unit; verifier.txt)
    exit 0  (re-shaped: the range is binding.md; verify: OK — all required checks passed; verifier-2.txt)

The verifier's notes say what this binding does not establish: `report-only (unsupervised)`, with
no signed dispatch record, and an advisory authority on this host.

## Evidence binding

Coordinator-attested, like every run here. `run_report.py` re-hashes the inventory at
`inventory_at` and checks the ledger's command hash and content object. It does not re-run the
harness. The live facts (model, cost, the pane, the container) are what the receipts, transcripts
and logs recorded at the time.

## Limitations

- Two hosts, one physical machine: the clean host is a container on the dev Mac's OrbStack, not
  separate hardware.
- One model and one run per profile per host; no repeated measured cells.
- `setsid` backend only. tmux and cmux were not run live.
- No live witness yet for Orca `ro`/`claude` on its current row. Not run at all: any other
  provider, any other harness, and Orca on macOS.
- The 2026-10-24 clean-host runs had no failures, so the record shows no recovery from a real
  failure.

## Run-close integrity inventory (sha256)

```
fd2dd53635cf37ed21f5e46309d7463f4b83db37ae5d642b89ff2c142425f8f9  docs/runs/2026-10-24-review-it-first-run/binding.md
1f5680fbf2d6069505601ee357dd376444a9ea5aaf894c8623e4e33d83baf05b  docs/runs/2026-10-24-review-it-first-run/clean-host/clean-host-596.sh
26226023225b43c181d8ab6e8fbae3daa43272bd2406aeb7fc1418f594aed927  docs/runs/2026-10-24-review-it-first-run/clean-host/clean-host.log
094704b1cfa8e07ebbf79094642b12b3b4ccc52072443b87cb1b655d8fcff989  docs/runs/2026-10-24-review-it-first-run/clean-host/inner.sh
0c64b45ec1e63d14e3b8ecfe21576cebf6ff82d38ccbba43ce26f6421cb1e2b9  docs/runs/2026-10-24-review-it-first-run/clean-host/receipt-ro.json
76035b871e51c94bf11aef7c22eebf0657a7dd64c3cd03743b4aa6d00371ee57  docs/runs/2026-10-24-review-it-first-run/clean-host/receipt-rw.json
8132951ef468dade0ebba3858ddb8c7e4ff358416d1da805405635bf551f55d7  docs/runs/2026-10-24-review-it-first-run/clean-host/user.sh
1ec9bc7886a6948a48d102a73e32d6c391c622ad4963aeb12245b13ac5c9420f  docs/runs/2026-10-24-review-it-first-run/contract.md
11a56e3f46877087f04da0f071c697a063d2ce0650f96f8f09c5c08c9a87194c  docs/runs/2026-10-24-review-it-first-run/first-attempt/ro.receipt.json
3eb6326b48937309c6f0bd10e5ea7edcb0e8ed0eb1fc82db3bc00648d60eaf97  docs/runs/2026-10-24-review-it-first-run/first-attempt/rw.receipt.json
e2c35ae7b1fef3a58ff3595233c048d6cef65305496ef68de4783a368ea07302  docs/runs/2026-10-24-review-it-first-run/isolation/claude-wrapper.py
cbff31691d764e7cc0d834cf470dc678fd98eee38f09422185159d9b7491f9c5  docs/runs/2026-10-24-review-it-first-run/isolation/run-596.sh
1f617f34c2177ec834ec610cb9470af9b5a743f016b7c21a064d1fbe627ebb2b  docs/runs/2026-10-24-review-it-first-run/mac-ro/change.diff
76b611efb20f01b6d3512594c06459a7a3c87b753af1e71d6894517540894184  docs/runs/2026-10-24-review-it-first-run/mac-ro/contract.md
991067230a15d18ae1afbe267d340ee21b78e60a739dc7bb020b06bb837a7066  docs/runs/2026-10-24-review-it-first-run/mac-ro/manifest.json
3090a006ad2f145ac0fc50221fa1f1e9b15b8c9e226f2f7deddda7410b2afbc4  docs/runs/2026-10-24-review-it-first-run/mac-ro/receipt.json
e6f92724f40600adf5d381581d774e118cf151b96577006b3ea4dc8180152bc9  docs/runs/2026-10-24-review-it-first-run/mac-ro/report.md
c2c4b65ac5ff1257357a4a6d09a32c1247fe1979f21a71a98f97a782bbfac4a9  docs/runs/2026-10-24-review-it-first-run/mac-ro/transcript.jsonl
09c76bdc599da21720a8705fd739475b5a1bd6adb1b30d2cdaa823999a676741  docs/runs/2026-10-24-review-it-first-run/mac-rw/change.diff
7a3622352c3462c37db3a7e208909b7838be91fff58b6f6c50cb8ffa6b870d44  docs/runs/2026-10-24-review-it-first-run/mac-rw/contract.md
fc3fde343aec0ce7c08a82fc218190bbb65bcf25c68934fbf0670fce1fe12ea6  docs/runs/2026-10-24-review-it-first-run/mac-rw/manifest.json
e7e5668a1ab1db675034760e7083ec103df645a110d0729cddaf08ed20bdc5d0  docs/runs/2026-10-24-review-it-first-run/mac-rw/receipt.json
caec5de1eb4c7ebdcb4f1c6261441978e7030c467ef9652286662a1312b32be7  docs/runs/2026-10-24-review-it-first-run/mac-rw/report.md
9f0c641422e1802c95c9c5c19acf30c191c53da6725dc5f36464e8424467e94d  docs/runs/2026-10-24-review-it-first-run/mac-rw/transcript.jsonl
0124be02346aec14304120ac378ffbe49bd43103812d096e3a28f8080b13fcd9  docs/runs/2026-10-24-review-it-first-run/manifest.json
a157c9f3cee406f74b49d6c60ba90a47f1d797e4a3e566107638ce7332b3bd81  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/change.diff
1278d85252c9ac653b7fdf8a15db1504d861e9d6f0300fcfc159ebe4cfb88d0b  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/claude-version.txt
a53aa0383c7c3f3e301653f125a892e24cdd5581f48560280dda75012f607cf5  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/launch.txt
c8de26e6c0e357091ab48151ef8e194eee26cd85054e96ac120445385974a489  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/orca-version.txt
97d20e43dd0f5ffb815d2fa92f27a9f8005dcb7eecbbbf2374138b7392d9157f  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/spawn.stderr
a60ee85f88d26fdbcde656a5ddf038fb51ce63c84457fec76be9d4e4fbd8f43d  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/spawn.stdout
50cb57b0a3202548146d2d911690098c19e0458e452b8312c19d1cad130e948a  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/spec.txt
a7fa39b2e8868006e408b6eb6173131804469c85e626ecdad19886b2f19ed6c6  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/terminal-wait.json
016164d63bce44ef0172e3399fb898fe411d9d7edd730c1befb5107144d8cd5d  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/unit-log.txt
8b7b5e88cde956ccd1b0792abc302b69e8bfef69599d9c1c7df12f1a5a40938e  docs/runs/2026-10-24-review-it-first-run/orca-ro-attempt/worker-screen.txt
228d1803a1ab0573ab7df44ee90dc46178947b4999c8018829e1c08480f5f4be  docs/runs/2026-10-24-review-it-first-run/rederive.py
b6eafda41f899e7eca744f570fd04337ea670b39347d1d02b2d8193d35b3590e  docs/runs/2026-10-24-review-it-first-run/rederive.txt
164738a4cba78dad1f6211297e30eab2f379fa901175e8c1888a7ad9d36c6d65  docs/runs/2026-10-24-review-it-first-run/verifier-2.txt
23efff186627efa391739e2a61180c2be623b002621fc283b7a813f36b90d86e  docs/runs/2026-10-24-review-it-first-run/verifier.txt
```
