# harden-it tree-wide code security audit — 2026-10-27

RUN: run_secaudit_20261027 · COORDINATOR: opencode session (Ravindra Kumar) · BASE: review/2026-10-27-security-audit · FORK_POINT: 15e03dfedbf5 (origin/main at T0) · T0: 2026-10-27 · SOURCE: threat-model digest 45a4c67f3ceb539b (2026-10-27-security-audit/threat-model.md) · WIP: auditors=6 verifiers=3

PHASE: THREAT-MODEL done → AUDIT (6 waves) done → PoC ROUTING done → VERIFY done → VERDICT

This is an **audit-only** run: it stops before FIX. Nothing in this run's scope was
remediated, so the terminal is degraded, never CLEAN. The 78 findings are dispositions for a
follow-up fix run, and each P0/P1 below carries a verdict from a fresh-context verifier that
did not write it.

Scope is the tree at BASE, per the [threat model](2026-10-27-security-audit/threat-model.md):
every first-party executable surface (six boundary axes, B1–B6) plus the data parsers they run
over. Out of scope there: model providers, GitHub, the host kernel, Orca (`daemon/`), third-party
binaries except where invoked unsafely. It is deliberately **not** a re-audit of the h409 surface
(`verify.py`/`dispatch-sign.py`/`verify-gate.sh` were CLEAN on 2026-09-21) — W3 hunted only
regressions and new channels *into* it, and cites h409 where the class is closed.

PoC ROUTING was applied before any execution, per `sandbox-policy`: static/read-only → `ro`;
scratch-repo exploit → `rw` under `mktemp -d`; networked or destructive → argued from code and
PARKED with its blocker. No audit or verify step ran on the host beyond read-only inspection.

## Findings

Severity: **P0** = a plain, realistic input yields a silent escape with real effect outside the
boundary, or a false GREEN from the grading plane. **P1** = the same through a crafted but
reachable input, or a hit on an authority with a large blast radius. **P2** = hardening or a
declared-adjacent gap. **P3** = a nit, a wiring gap needing an unusual install, or a
defence-in-depth step. Full exploit steps, exact commands and observed output are in each wave's
audit file — the `evidence` column names the section.

`VERIFIED` is the independent verifier's disposition, not the auditor's: `yes` (reproduced at the
recorded severity, `verify-v*.md`), `downgraded` / `refuted` with the verifier's file, or
`not verified` where only P0/P1 were routed to verification (the mission's bar).

| task_id | finding | class | VERIFIED | BUILD_DONE | PR_OPEN | BOT | REVIEWED | MERGED | REATTACKED | WT_CLEAN | lighting | park | evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| waves | W1-01 (P0) `~` never expanded on the write-boundary path — `> ~/.bashrc` silent ALLOW | boundary escape | yes (v1) | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-01, verify-v1 §A1 |
| waves | W1-02 (P1) `$IFS` as separator loses every argument (HIGH tier, Never-list and self-guard bypass) | tokenizer | yes (v1) | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-02, verify-v1 §A2 |
| waves | W1-03 (P1) `awk … system()` absent from the interpreter table — arbitrary shell | interpreter table | yes (v1) | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-03, verify-v1 §A3 |
| waves | W1-04 (P2) relative redirect after `cd` is boundary-blind | boundary escape | not verified | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-04 |
| waves | W1-05 (P2) `tar`/`unzip`/`patch`/`busybox` absent from the self-guard head list | self-guard disarm | not verified | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-05 |
| waves | W1-06 (P2) root-class target tested as literal spellings, not classes | Never-list | not verified | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-06 |
| waves | W1-07 (P3) `--settings` emits the hook path unquoted — a space in the install path stops the hook | wiring | not verified | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-07 |
| waves | W1-08 (P3) `--settings` pins the legacy boundary var while the reader prefers the new one | wiring | not verified | — | — | — | — | — | — | — | lit | open | audit-w1 §W1-08 |
| waves | W2-01 (P2) `terminal send --text` has no `--` — a `-`-leading payload is eaten by `tmux` and still `accepted: true` | argv option injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w2 §W2-01 |
| waves | W2-02 (P3) launch env **keys** interpolated unquoted into a `shell=True` line | shell-string assembly | not verified | — | — | — | — | — | — | — | lit | open | audit-w2 §W2-02 |
| waves | W2-03 (P3) `OPEN_FLEET_CLI_COMMAND` returned verbatim as one argv token | argv[0] resolution | not verified | — | — | — | — | — | — | — | lit | open | audit-w2 §W2-03 |
| waves | W2-04 (P3) nine git call sites take a value in option position with no `--` | argv option injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w2 §W2-04 |
| waves | W2-05 (P3) `--skills-dir` reaches `ln` as an option | argv option injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w2 §W2-05 |
| waves | W3-01 (P0) `sys.path[0]` is `runtime/scripts` — a committed sibling `json.py` turns a RED verdict GREEN, unbound by the toolchain hash | supply chain | yes (v2) | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-01, verify-v2 §B1 |
| waves | W3-02 (P1) the gate's dispatch-pubkey ref is `symbolic-ref --short` of `origin/HEAD` — a movable local branch | spoofing | yes (v2) | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-02, verify-v2 §B2 |
| waves | W3-03 (P2) a bare-path `--dispatch-pubkey`/`--retention-pubkey` is indistinguishable from a ref pin | spoofing | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-03 |
| waves | W3-04 (P2) manifest binding compares digests and discards the entry's path | repudiation | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-04 |
| waves | W3-05 (P2) the mutation policy is read at the graded rev — a PR can delete its own mission from it | tampering | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-05 |
| waves | W3-06 (P2) gate answers are unsigned plain JSON with a free-text `source` | spoofing | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-06 |
| waves | W3-07 (P2) `--pin-ref` may name a local branch, and re-resolves it between rev-parse and cat-file | spoofing | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-07 |
| waves | W3-08 (P2) no ref-backed pin discovery path exists in a CI checkout, so a sound lane blocks | availability | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-08 |
| waves | W3-09 (P3) no dispatch pubkey is committed anywhere here — the whole enforcement switch is dormant | posture | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-09 |
| waves | W3-10 (P3) a worker-planted `gitleaks` is consulted on every lane | integrity | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-10 |
| waves | W3-11 (P3) toolchain hashed after the executed control runs, not before | TOCTOU | not verified | — | — | — | — | — | — | — | lit | open | audit-w3 §W3-11 |
| waves | W4-01 (P0) `posix._git` runs bare `git` with `env=None` — a repo-declared hook or smudge filter runs as the coordinator, with its whole environment | sandbox escape | yes (v2) | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-01, verify-v2 §B3 |
| waves | W4-02 (P1) `wtree.sh` leaves global config live, and `~/.gitconfig` is worker-writable — runs a command and chooses the fingerprint | ACE + evidence | yes (v2) | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-02, verify-v2 §B4 |
| waves | W4-03 (P2) the deny-hook arming gate gets an expected boundary only for `path:` selectors | guard identity | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-03 |
| waves | W4-04 (P2) the parent-profile cap is fed by worker-set env and is inert on the Orca lane | profile escalation | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-04 |
| waves | W4-05 (P2) `ro` is a tool filter, not a filesystem one — plan-mode Bash still writes | tier weaker than contract | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-05 |
| waves | W4-06 (P2) an unset settings var only warns, and `ro` skips the arming block entirely | fail-open default | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-06 |
| waves | W4-07 (P3) `wtree.sh` never scrubs `GIT_DIR`/`GIT_WORK_TREE`/`GIT_EXTERNAL_DIFF` and re-resolves `PATH` | custody floor | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-07 |
| waves | W4-08 (P3) `worktree rm` reads the `.git` pointer twice (decide, then act) | check/use | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-08 |
| waves | W4-09 (P3) the boundary path is compared with globbing on, so `q*/f` denies | boundary | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-09 |
| waves | W4-10 (P3) a recipe id matches any dict *key*, not a recipe field | recipe identity | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-10 |
| waves | W4-11 (P3) receipts and pane fields print raw ANSI/bidi into the coordinator's terminal | untrusted text | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-11 |
| waves | W4-12 (P3) the task title is unbounded and becomes a filename — 300 chars fails after the task is spent | unbounded name | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-12 |
| waves | W4-13 (P3) the first `python3` in `spawn_worker.sh` is the one site without `-I` | interpreter | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-13 |
| waves | W4-14 (P3) `diff_scope` falls back to bare `git` when absent at import | resolution | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-14 |
| waves | W4-15 (P3) `orca_cli` trusts the CLI-command env value unvalidated | command identity | not verified | — | — | — | — | — | — | — | lit | open | audit-w4 §W4-15 |
| waves | W5-05 (P1) a key appended to the ledger's last line is hashed by nothing and `verify` still says intact — and in `--expect-ancestor` mode a receipt written since the last close can be rewritten whole, `host` included | receipt forgery | yes (v3, stronger than filed) | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-05, verify-v3 §C1 |
| waves | W5-08 (P1→P2) `GITHUB_TOKEN` attached with `add_header` is re-sent to a redirect target | credential to a foreign origin | downgraded (v3) | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-08, verify-v3 §C2 |
| waves | W5-10 (P1) the bundle ownership marker sits inside the tree it authorises deleting — forged JSON deletes files, `settings.json` among them | trusted forged record | yes (v3) | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-10, verify-v3 §C3 |
| waves | W5-01 (P2) the writer decodes leniently and the verifier strictly — one bad byte bricks the evidence permanently | write/read asymmetry | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-01 |
| waves | W5-02 (P2) `prev` is read by path, not from the locked fd | TOCTOU | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-02 |
| waves | W5-03 (P2) the ledger path is env/relative, so receipts can land elsewhere and close-time verify still passes empty | fail-open provenance | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-03 |
| waves | W5-04 (P2) `egress.py grants` prints forgeable consent strings without verifying the chain | forged consent | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-04 |
| waves | W5-06 (P2) `flush()` without `fsync()` loses the tail receipts a send depends on | durability | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-06 |
| waves | W5-13 (P2) `from_committed_dockerfile` is recorded and never gated on | provenance | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-13 |
| waves | W5-14 (P2) a comma in `TMPDIR` breaks every derived `--mount` | mount-string injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-14 |
| waves | W5-15 (P2) `--network container:` shares the broker's namespace — the arm is not egress-controlled | uncapped egress | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-15 |
| waves | W5-19 (P2) `send_msg` sender identity is self-asserted from the worker's own env | sender identity | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-19 |
| waves | W5-07 (P3) `--payload-file` is read whole just to hash it | unbounded read | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-07 |
| waves | W5-09 (P3) `--repo` is interpolated into the API URL unquoted | URL component | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-09 |
| waves | W5-11 (P3) the marker itself is outside the symlink check and is written through a link | symlink | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-11 |
| waves | W5-12 (P3) `curl \| bash` for the harness installer, version-grepped not digest-pinned | supply chain | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-12 |
| waves | W5-16 (P3) `ThreadingHTTPServer` with no socket timeout — connection parking | DoS | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-16 |
| waves | W5-17 (P3) `count_tokens` relays unpriced and unbounded | metering | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-17 |
| waves | W5-18 (P3) a `settled()` type surprise skips `settle` and the traceback is discarded | silent fault | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-18 |
| waves | W5-20 (P3) `first_run` hands the worker the operator's whole environment | ambient credential | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-20 |
| waves | W5-21 (P3) recall reads whole files and whole manifests with no byte cap | DoS | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-21 |
| waves | W5-22 (P3) installer takes option-shaped values and aborts on unset `HOME` | argv/`set -u` | not verified | — | — | — | — | — | — | — | lit | open | audit-w5 §W5-22 |
| waves | W6-01 (P1) a `pull_request` run loads its workflow from the PR — the graded party supplies the grader | elevation | yes (v3) | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-01, verify-v3 §C4 |
| waves | W6-02 (P2) the coverage floor is measured on an artifact the PR uploads | tampering | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-02 |
| waves | W6-03 (P2) `.gitleaks.toml` is not on the guard surface, so a path allowlist waives the scan | tampering | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-03 |
| waves | W6-04 (P2) a committed `skills/*/.gitignore` silently drops files from the published `dist` | payload loss | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-04 |
| waves | W6-05 (P2) fork-token repo setting decides whether a fork PR can write `main`; nothing records it | elevation | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-05 |
| waves | W6-06 (P2) `verdict-gate` proves SHA binding, not that anyone read the diff | spoofing | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-06 |
| waves | W6-07 (P3) PR-tree checkouts keep `persist-credentials` and then run PR code | disclosure | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-07 |
| waves | W6-08 (P3) a `preparing` row in `releases.json` turns the badge-equality gate off | tampering | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-08 |
| waves | W6-09 (P3) `releases[-1].commit` reaches an argv option position unvalidated | argv injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-09 |
| waves | W6-10 (P3) release gate 3 is satisfied by the word `negative-control` in any `run:` line | repudiation | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-10 |
| waves | W6-11 (P3) `release.yml` never shape-checks `inputs.tag` and has no newest-tag guard | release path | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-11 |
| waves | W6-12 (P3) gate 4 requires a green `install` on `main` while the documented cut runs on a release branch | gate denial | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-12 |
| waves | W6-13 (P3) seven mutable container tags in the demo compose file | supply chain | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-13 |
| waves | W6-14 (P3) `<script>` with no `href`/`src` passes both generators into published Markdown | injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-14 |
| waves | W6-15 (P3) 46 SHA-pinned `uses:` with no test to keep the next one pinned | supply chain | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-15 |
| waves | W6-16 (P3) `publish-dist` interpolates the dispatch tag into `ref:` before validating it | injection | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-16 |
| waves | W6-17 (P3) the failure alert matches workflows by display name | repudiation | not verified | — | — | — | — | — | — | — | lit | open | audit-w6 §W6-17 |

Counts: 3 P0, 7 P1, 28 P2, 40 P3 (78 findings) — the P1 total is after V3's downgrade of W5-08;
the `finding` column keeps the auditor's grade where a verifier moved it, marked with `→`.

## Verification

Every P0 and P1 went to a fresh-context verifier that saw only `file:line` and the construct,
never the auditor's conclusion, and had to reproduce it independently before grading it. Three
verifiers ran in parallel, one per axis group, each writing its own file. P2/P3 were left as the
auditors reported them; the mission's bar does not route them, and they are cheap to re-check when
they are picked up for a fix.

| claim | verifier | verdict |
|---|---|---|
| W1-01 `~` write target | v1 (with [A1](2026-10-27-security-audit/verify-v1.md)) | **confirmed P0** — six spellings across Bash `>`/`>>`/`tee` and `Write`/`Edit`; real run put the bytes in `$HOME` and created no `./~` |
| W1-02 `$IFS` separator | v1 (with [A2](2026-10-27-security-audit/verify-v1.md)) | **confirmed P1** — and wider than filed: no `G` record is emitted either, so the self-guard is blinded |
| W1-03 `awk system()` | v1 (with [A3](2026-10-27-security-audit/verify-v1.md)) | **confirmed P1** — `perl -e` and `python3 -c` controls deny, and the Never-list regex cannot reach an embedded `rm` |
| W3-01 sibling `json.py` | v2 (with [B1](2026-10-27-security-audit/verify-v2.md)) | **confirmed P0** — the same bytes go exit 2 → exit 0; `-I` and `-P` each neutralise it |
| W3-02 pubkey ref from `origin/HEAD` | v2 (with [B2](2026-10-27-security-audit/verify-v2.md)) | **confirmed P1** — the worker's self-signed record passes, the same record at `refs/remotes/origin/main` is refused, and moving the branch again swaps the accepted key |
| W4-01 `posix._git` bare | v2 (with [B3](2026-10-27-security-audit/verify-v2.md)) | **confirmed P0** — `post-checkout` and `smudge` fired on the coordinator-side `worktree add`, `fsmonitor` on `reset`, with `GH_TOKEN` in the hook's view |
| W4-02 `wtree.sh` global config | v2 (with [B4](2026-10-27-security-audit/verify-v2.md)) | **confirmed P1** — a tampered tree printed the pristine `HEAD^{tree}` and the identical record was called FRESH; under `GIT_CONFIG_GLOBAL=/dev/null` it prints a different hash and is called STALE |
| W5-05 last-line forgery | v3 (with [C1](2026-10-27-security-audit/verify-v3.md)) | **confirmed P1, stronger** — an anchored receipt written since the last close can be rewritten whole with `host` changed and a recomputed `id`, and the strongest anchored mode still reports intact |
| W5-08 token across a redirect | v3 (with [C2](2026-10-27-security-audit/verify-v3.md)) | **downgraded P1→P2** — mechanism confirmed on a loopback 302; lowered because TLS is verified and the path is opt-in (`--transport rest`) |
| W5-10 forged bundle marker | v3 (with [C3](2026-10-27-security-audit/verify-v3.md)) | **confirmed P1** — two forged names, two foreign files deleted, rc 0, silent; a symlinked marker is followed and its target rewritten |
| W6-01 PR supplies its own grader | v3 (with [C4](2026-10-27-security-audit/verify-v3.md)) | **confirmed P1** — and narrowed: deleting a workflow file leaves the PR blocked, editing the job empty does not |

All 11 reproduced; none was refuted. Two rows changed in the ledger as a result: W5-08 is P2 now,
and W5-05 carries the anchored-mode case V3 found, which is worse than the filed one.

The verifiers also corrected two framings without moving a grade. W1-01's file-tool half is
cwd-dependent (with the hook's cwd outside the worktree, `Write ~/.bashrc` flips to deny) while its
Bash half is not, so the same target has two answers. W4-01 is an escape from the deny hook and a
`GH_TOKEN` read, not a uid change — same-uid fleets were already mixed.

Three tests were found to pass under the defect they should catch: `test_egress.py:297-307` is
saved only by the line-break rule, `test_external_ci_monitor.py:170-191` asserts through
`get_header()`, which reads both header maps, and `test_bundle_out.py:157-185` covers only
malformed markers. Each confirmed finding's row says whether a test or the corpus pins it; for the
four deny-hook shapes and both git-custody channels, nothing does.

## What the audit could not break

Recorded because "no finding" is only worth the sweep behind it — full detail and the empty-class
reasoning are in each wave file:

- **No shell-injection finding exists in this tree.** All 210 `subprocess.*` sites across 38 files
  pass argv lists; the one `shell=True` runs a string built from `shlex.quote`d elements. The
  survivors are end-of-options discipline (W2), not injection.
- **The deny hook fails closed on garbage** at three byte scales, and its peeler (29 forms),
  quoting removal, substitution heads, symlink-chain resolver (32-hop cap) and corpus polarity all
  hold.
- **Worktree names cannot escape:** doubly sanitised (`tr` + `_worktree_slug`), and removal
  validates after full symlink resolution with no `rmtree` fallback.
- **The CI pipeline is the strongest surface in the tree:** no `pull_request_target`, zero inline
  `${{ }}` in a `run:`, all 46 actions on full SHAs, no secret reachable from a fork PR, and
  releases carry no substitutable assets.
- **The verifier's own controls hold:** fail-open exits, signature-over-different-bytes, unsigned
  and replayable envelopes, `reviewed_sha` re-derivation, authority custody, path escapes from the
  graded party, and the retention receipt chain (h409 classes, no regression).
- **Secrets never ride an argv, a URL, a temp file or a ledger** in the live lane; no first-party
  path unpickles, `yaml.load`s or `eval`s a fetched body; there is no `tar`/`unzip` in the tree.

## Terminal state

**HARDENED-WITH-OPEN-ITEMS** (degraded — no fix landed in this run). The audit is complete and
every P0/P1 has a disposition: reproduced and open, or refuted by its verifier. The follow-up fix
run takes the confirmed P0s first, in this order — W3-01 and W4-01 are coordinator-side code
execution and false-GREEN from ordinary worker actions, W1-01 is a line every agent writes — then
the P1s, each with the exploit test from its audit row as the red test.

## Deviations and lessons

- **Audit-only, by request.** The mission's pipeline continues into FIX → REVIEW → RE-ATTACK →
  RE-AUDIT; this run stops at VERDICT. A CLEAN terminal is therefore impossible here and is not
  claimed.
- **The mission says PoCs are written and NOT executed at the AUDIT step, and executed only after
  routing.** Auditors were instead asked to execute each routed scenario as they wrote it, because
  a parser finding that is not run is a guess. Every execution stayed inside `mktemp -d`; the
  routing decision was still recorded per scenario before running, so the profile rule held.
- **`/tmp/opencode` is not writable in this session** (owned by another uid). All six auditors and
  all three verifiers were moved to `mktemp -d`; two wave headers still say `/tmp/opencode` and
  correct themselves in the same sentence.
- **The transcript said "3 P0s and 7 P1s"; there are 8 P1s.** All 8 were verified. The count was
  low by one, not the routing. One of the 8, W5-08, was downgraded to P2 by its verifier.
- **A verifier may widen a finding.** W1-02's missing `G` record and W5-05's anchored-mode rewrite
  both came from verification, not the audit, and are recorded in the ledger row rather than left
  in the verifier file. A verifier could equally narrow one; none did.
- **P0/P1 counts here are audit-time counts.** Two wave files state their own downgrade conditions
  (W2-01 → P1 if a caller ever passes attacker-chosen text); those are for the fix run, not a
  retro-change to this ledger.
- **The base was already red on one test.** `origin/main` at `15e03dfe` has a failed `validate` push
  run (`40478247382`) on exactly `tests (6)`, `floor (3.11, 6)` and `gates`, from
  `test_posix_provider.TestTmuxWorkerLifecycle.test_a_server_the_spawn_starts_never_hands_one_workers_launch_env_to_the_next`
  — the same test that fails on a clean `main` worktree on this machine, with the other assertion
  (`launch env leaked`). On CI the tmux server dies at `new-session` instead. It is shard-6 only and
  unrelated to a docs change, so this report is not the place to fix it; it is a fourth
  machine-and-CI-visible failure alongside the three known ones, and belongs in the fix run.
- Verified P2 candidates that the auditors had ranked higher were not re-graded upward; a verifier
  may downgrade, and the fix run should re-read any it picks up.

## Run-close integrity inventory (sha256)

Run-owned artifacts, produced by the run's auditors, verifiers and coordinator on 2026-10-27:

| Artifact | sha256 | producer |
|---|---|---|
| `docs/runs/2026-10-27-security-audit/threat-model.md` | `61c0a4c78985a0f1cd18254d2432d9a61556f1c113bbe5f7deec66870242567a` | coordinator, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/audit-w1.md` | `d674e2284bfa7f4e988872b7a5d8c5f248e3b6ee99e5c2ed0a342aabc198bd64` | auditor w1, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/audit-w2.md` | `b581bf4e9e6586ef529f872968a39c037c64556bc5a2732e70668c6c7c00ea0b` | auditor w2, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/audit-w3.md` | `3f16e116c654edd1fc51f436283bc275e9c595d1a1b6eddd6a87668629a070cb` | auditor w3, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/audit-w4.md` | `ccfde055673d2a239c73427985255f1c72a808ec84b199be0f9f60f8f9b4ba28` | auditor w4, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/audit-w5.md` | `c6bb30b4330d732dede3fb7e81b2122ce379df52b6fa6d0d8ead063bb4f76d58` | auditor w5, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/audit-w6.md` | `14f69dbf59dfe39e3a88d1a2b5fcb12f98708834dbbb9ec227e1ec278aaf47ff` | auditor w6, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/verify-v1.md` | `7e9a09ac281136439374e64b9db1194cd1c4436af67e066a9e69bc10b8228dd2` | verifier v1, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/verify-v2.md` | `8434799a525b7a1af0f6e6ee2e2c585df486bf6eb0d7b7c598c23954af665c97` | verifier v2, 2026-10-27 |
| `docs/runs/2026-10-27-security-audit/verify-v3.md` | `7755550304b122ea10a89dd300bb9384f2b8861090ec78d8a844327126905bc3` | verifier v3, 2026-10-27 |

## Gates

The audit is documentation-only: no executable surface changed. The gates a change to this tree
must still pass were run at the report head — `python3 scripts/validate.py`,
`python3 runtime/scripts/floor_guard.py check`, and the affected `tests/` modules; the exact
commands and exits are pasted in the pull request.
