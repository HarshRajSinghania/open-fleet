# Audit W1 — B1 sandbox: `deny-hook.sh` parser, boundary and self-guard

RUN: run_secaudit_20261027 · WORKER: w1 · BASE: review/2026-10-27-security-audit · FORK_POINT:
15e03dfe · T0: 2026-10-27 · SOURCE: `docs/runs/2026-10-27-security-audit/threat-model.md`
(B1 — "peeler/segment gap, a HIGH-tier shape that gets ALLOW, fail-open on a missing parser") ·
PRIOR BASELINE: none (harden-409 never touched this file) · MODE: read-only; no tracked file
modified; all execution against scratch copies and scratch boundaries under `/tmp/aud`
(`/tmp/opencode` is owned by another uid in this session and is not writable).

## Scope and method

This is a red team of `runtime/scripts/deny-hook.sh` (5,182 lines) as the B1 carrier, plus the
`hooks/hooks.json` / `hooks/settings-snippet.json` / `hooks/print-settings-snippet.sh` wiring and the
files that pin its behaviour (`tests/test_deny_hook*.py`, `scripts/deny_hook_corpus.py`,
`tests/fixtures/deny_hook_conformance.json`; `evals/deny-hook-corpus*` does not exist). Method:
read the contract header and the whole decision path first, then attack in the threat model's order
— fail-closed on unreadable input, the peeler/segment splitter, quoting and substitution, the
boundary resolver for every write carrier the hook claims (redirect, `tee`, `Edit`/`Write`/`MultiEdit`/
`NotebookEdit` field), the self-guard write list, and the root-class rule — driving each candidate
through a JSON `PreToolUse` payload on stdin with `OPEN_FLEET_UNIT_WORKTREE=/tmp/aud/wt` and
classifying the three-way answer (silent ALLOW / `ask` / `deny`). Every finding below was executed;
nothing here is argued from code alone. Where an ALLOW would be a claim rather than an observation,
the same command was also run for real (`awk …` proved it executes `system()`, `> ~/.bashrc` proved
the write landed in `$HOME`, a tarball proved it replaced the guard file) so the decision and the
effect are both observed. Acceptance bar applied: a shape is a finding when the hook is *silent* or
*asks* where its own contract says DENY, or when its model of the target differs from the shell's.

## Severity

P0 needs all of: a plain realistic line, a silent ALLOW, an **undeclared** gap (the header at 112-135
lists what the Bash half does not cover), and a real effect outside the boundary. P1 is the same with
an unusual-but-reachable spelling, or a hit on a declared-adjacent shape with a large blast radius.
P2 is a silent escape on a declared gap, or an `ask` where the contract promises deny — both count
for more than a policy nit here because strict mode is not the default: `ask` only becomes a deny
under `*_HOOK_STRICT_EXIT`/headless (805-826), so W1-04's silence and W1-06's `ask` both reach an
ordinary interactive worker as "proceed". P3 is a wiring nit that needs an unusual install shape.

**1 P0, 2 P1, 3 P2, 2 P3.**

## Findings

| id | file:line | severity | class | untrusted input | exploit scenario (exact command) | what the attacker gains | why it works (parser gap) | PoC status |
|---|---|---|---|---|---|---|---|---|
| W1-01 | runtime/scripts/deny-hook.sh:4224-4231, 4284-4299, 5093-5106 | **P0** | boundary escape (path model) | `Write.file_path` / `Edit.file_path`, or a Bash redirect target | a `Write` payload with `file_path: "~/.bashrc"` — or, division-proof, the Bash line `echo pwned > ~/.bashrc` | a silent ALLOW to write `$HOME/.bashrc`, `~/.config/*`, `~root/x` — outside the worktree, and no other rule in the hook looks at that path; a worker persists code into the human's shell, and `~root/` can target another user | the hook never expands a tilde. `bounded_write` (5095) returns 0 for anything not starting with `/`, so `~…` is classed *relative* and never resolved; `check_edit_target` → `resolve_dir` (4224) sees a relative path, prefixes `$PWD`, and yields `$BOUND/~/.bashrc` — a path that does not exist — which prefix-matches `$BOUND/` and passes. `_guarded_exact` (3491-3494) *does* `expanduser`, so the guard half and the boundary half disagree about what `~` means | **EXECUTED** — ALLOW for `file_path "~/.bashrc"`, `"~root/x"`, and `echo pwned > ~/.bashrc`; the real run created `$HOME/.bashrc` and `ls /tmp/aud/wt/'~'` is ENOENT, i.e. the hook's model is provably not the shell's |
| W1-02 | runtime/scripts/deny-hook.sh:2282, 2410-2443 | **P1** | tokenizer (`$IFS` as separator) | the bash command string | `rm$IFS-rf$IFS/` — one word, no spaces | silent ALLOW of the whole HIGH tier and the Never-list: `rm${IFS}-rf${IFS}--no-preserve-root$IFS/`, `git$IFS push$IFS--force$IFS origin$IFS main`, `gh$IFS pr$IFS merge$IFS 34`, `orca$IFS orchestration$IFS reset`, and the boundary `echo pwned >$IFS/tmp/aud/ifs_y` (run for real: the file appears) | `$IFS` is neither assigned on the line nor in `_ASSIGNED`, so `_head_bodies` cannot resolve the head and takes the refused-head fallback. That fallback keeps only the words *after* the head word (`rest`, 2441) — but with no literal space the flags and operands are still inside the head word, so every candidate head (`gh`, `git`, `rm`, `orca`) is re-judged **with no arguments**. `rm` alone has no `-r`, `git` alone has no `push`: nothing fires | **EXECUTED** — ALLOW for all five, and the redirect was run for real (file created); the `/` case is silent on a full root wipe and `--no-preserve-root` is the one rule the header calls non-negotiable |
| W1-03 | runtime/scripts/deny-hook.sh:2275-2276, 2306-2329, 2678, 2955, 3911-3914 | **P1** | interpreter table (inline code) | the bash command string | `awk 'BEGIN{system("rm -rf /")}'` | silent ALLOW of arbitrary shell from inside an interpreter: root wipes, `git push --force`, release steps — and, since the guard half rides the same list, `awk 'BEGIN{print "x" > ".claude/settings.json"}'` rewrites the hook config silently | `_inline_code` returns `[]` for any head not in `_INLINE_FLAGS` (`python`, `perl`, `ruby`, `node`, `nodejs`, `bun`, `php`), and a head in the table is required both for `-c`/`-e` extraction and for `interp` classification (2955). `awk` is in neither set, is not a `_RUNNERS` shell, and has no `_inner_body`, so its program text is never read. The commonest one-liner interpreter on any box is missing from a table with `bun` and `php` in it | **EXECUTED** — ALLOW; the same command run for real created the file, so `system()` really fires. Control in the covered direction: `node -e 'require("child_process").execSync("rm -rf /")'` → deny |
| W1-04 | runtime/scripts/deny-hook.sh:5095-5096; declared 122-124; pinned ALLOW tests/test_deny_hook.py:1277-1283 | P2 | boundary escape (cwd blind) | a relative redirect/`tee` target after a `cd` | `cd /etc && echo pwned > crontab` | silent ALLOW to write `/etc/crontab`, a dotfile in `$HOME`, any directory the model names; `cd /etc && echo … > crontab` is a root cron entry — full code execution as root on the next minute | a write target that does not start with `/` returns 0 immediately (5095), because the hook is not handed the worker's cwd. The machinery to do better is already in the file: `_cd_target` (3628, 3947-3955) track `cd` segments and drive the *guard* check (3954) — the boundary check simply does not consult them | **EXECUTED** — ALLOW; a test pins the current answer, so this is a designed hole, not a regression |
| W1-05 | runtime/scripts/deny-hook.sh:3845-3906 (no entry), 3640-3641 | P2 | self-guard disarm (write-shaped verbs) | the bash command string | `tar -xf /tmp/e.tar` (tarball holds `.claude/settings.json`) | the guard file is replaced with no deny and no prompt, so the next tool call is judged by the worker's own rules — persistence, not a one-shot escape. Same for a repo patch and an archive unpack, which is how a real payload arrives | `guard_targets` dispatches on an explicit head list (`rm` 3845, `mv/cp/ln/install` 3847, `sed/perl -i`, `truncate`, `tee`, `dd of=`, `chmod/chown/chgrp`, `sort -o`, editors, `rsync`, `curl/wget`, shells via `_inner_body`). A head outside it contributes nothing; the final branches only recurse for launchers and interpreters. `tar`, `unzip`, `patch` and `busybox` are all absent, and the object filenames an archive carries are never read | **EXECUTED** — ALLOW; the extraction was run for real and `.claude/settings.json` changed contents while the decision stayed ALLOW |
| W1-06 | runtime/scripts/deny-hook.sh:58-59 (claim), 4939-4943, 4947-4950 | P2 | Never-list (root-class target set literal) | the bash command string | `rm -rf /*/` and `rm -rf ~/.` | a full root or home wipe downgraded to `ask` — in the ordinary (non-strict) worker case that is a prompt an autonomous fleet is supposed to have pre-answered, and a `--release` run can proceed on it | the token set at 4942 is compared with a quoted `case` pattern, so only the exact strings in that list are root-class. `/*/` (with its trailing slash), `~/.`, `${HOME}/.` and `$HOME/*` all fall to `*) SAFE=1` and lose the deny. Line 58 promises "every target is `/`, `~`, `$HOME` or `/*`"; the code tests spellings, not the classes | **EXECUTED** — `ask` for all four, `deny` for `/`, `/*`, `~`, `$HOME`, `${HOME}`, `//`, `///` and `"$HOME"` |
| W1-07 | runtime/scripts/deny-hook.sh:244-253 | P3 | wiring (shell quoting of the emitted command) | the worktree path handed to `--settings` | `sh 'a b/deny-hook.sh' --settings /tmp/aud/wt` → `"command": "/tmp/aud/a b/deny-hook.sh"` | if any component of the install path contains a space (or `$`), the registered command is torn by the host's `sh -c`; the hook never starts, so every boundary, HIGH and guard control is off — silently | the emitter passes `sys.argv[2]` straight into `json.dumps` with no shell quoting. `json.dumps` makes valid *JSON* but not a valid *command*; the two layers are separate. The repo already does this correctly twice — `hooks/hooks.json` wraps `${CLAUDE_PLUGIN_ROOT}`'s path in quotes and `print-settings-snippet.sh` runs it through `shlex.quote` (its comment at 28-32 names exactly this bug class, #382) | **EXECUTED** — the emitted command run through `sh -c` gives `sh: 1: /tmp/aud/a: not found`, rc=127 (a hook error, which every audited host reads as allow) |
| W1-08 | runtime/scripts/deny-hook.sh:791 vs 246 | P3 | wiring (boundary precedence) | a stale `OPEN_FLEET_UNIT_WORKTREE` inherited from a parent shell | settings written by `--settings` pin `ORCA_UNIT_WORKTREE`, but with `OPEN_FLEET_UNIT_WORKTREE=/tmp/aud/outside` also exported, a write to `../outside/probe` | the boundary the settings file pinned is silently replaced by the parent's; guards the pinned value would refuse become ALLOW, and the settings file reads as if it were in force | `UNIT_WORKTREE=${OPEN_FLEET_UNIT_WORKTREE:-${ORCA_UNIT_WORKTREE:-}}` (791) prefers the NEW name, while `--settings` (246) writes the LEGACY one. A stale new-name variable, or any reader migrating in the other direction, wins over the explicit per-worktree pin | **EXECUTED** — `ORCA_UNIT_WORKTREE` alone → deny; adding the stale `OPEN_FLEET_UNIT_WORKTREE` → ALLOW (empty output) on the same payload |

## Variants (one line per confirmed finding; each was run)

- **W1-01** `~/.bashrc`, `~root/x`, `~/.config/nvim/init.vim` → ALLOW; the same target spelled
  absolute (`/etc/cron.d/x`) or with `..` (`../x`) → deny. `$HOME/.bashrc` is ALLOW for the same
  reason (`$` is not expanded on the edit path either). Reachability depends on the tool expanding
  `~`; the Bash carrier always does.
- **W1-02** separator variants of one command each: `rm${IFS}-rf${IFS}/`, `rm$IFS-rf$IFS/*`,
  `rm$IFS-rf$IFS--no-preserve-root$IFS/` → ALLOW, `git$IFS restore$IFS.claude/settings.json` → ALLOW,
  `cp$IFS a$IFS /etc/x` → ALLOW, `cat$IFS a$IFS>$IFS/etc/x` → ALLOW, `rm$IFS-rf$IFS.claude` → ALLOW
  (a guard delete). Real tabs (`rm\t-rf\t/`) are fine — the splitter handles whitespace; `$IFS` is
  only interesting because it is *not* whitespace in the text.
- **W1-03** `gawk`, `mawk` and `busybox awk` `'BEGIN{system("…")}'` → ALLOW; `lua -e 'os.execute(…)'`,
  `deno eval 'new Deno.Command(…).outputSync()'`, `julia -e 'run(…)'`, `Rscript -e 'system(…)'`,
  `tclsh <<< 'exec rm -rf /'`, `sed 'e git push --force origin main' f` (a silent force push),
  `sed 's/a/b/e' f` → ALLOW. `sqlite3 d '.shell rm -rf /'` and `sed -i 'e rm -rf /' f` → `ask` only
  (downgrade, not deny). Covered controls in the same family: `node -e`, `python3 -c`, `sh -c`,
  `find -exec sh -c`, `xargs -I{} sh -c` → deny.
- **W1-04** `(cd /etc && echo x > crontab)`, `cd ~ && echo x > .bashrc`, `cd /etc; echo x > crontab`
  → ALLOW; an absolute target after the same `cd` → deny.
- **W1-05** `unzip -o e.zip`, `tar -C /tmp/aud/g -xf /tmp/aud/e2.tar`, `patch -p1 < d.patch`, `nano`,
  `busybox cp x .claude/settings.json` → ALLOW; `busybox rm -rf .claude` → `ask` (`busybox` is not
  peeled, so a delete only reaches the generic recursive-delete prompt instead of the guard deny).
  Deny controls on the same file: `>`, `sed -i`, `cp`, `cp -a`, `mv`, `ln -sf`, `vim -c wq`.
- **W1-06** `/*/`, `~/.`, `~/*`, `${HOME}/*`, `${HOME}/.` → `ask`. Three near neighbours deny only by
  luck: `/.`, `/./` and `/dev/../` each fold to a string a `GUARD_DIRS` pattern happens to match, so
  the class is right for an unrelated reason and a rewrite of the guard patterns would take it away.
- **W1-07** a space in any path component is enough; the emitted JSON stays valid, so nothing
  complains at registration time (`--verify-settings` parses the JSON and is satisfied).
- **W1-08** the reverse order (legacy set, new name unset) is fine; only the stale new name wins.

## Fix sketches (P0/P1 only; not applied — this audit is read-only)

- **W1-01** expand a leading `~`/`~user` on the edit path before `resolve_dir` and before
  `bounded_write`'s absolute test (one `expanduser` at the top of both, matching `_guarded_exact`),
  then add corpus rows for `~/` and `~root/`.
- **W1-02** in `_head_bodies` (2408), when a head stays unresolved, re-split it before handing it to
  the fallback: substitute `$IFS`/`${IFS}`/`${IFS:0:1}` → space in the joined line and `shlex.split`
  it, so the flags come back as words and the candidate heads are judged *with* arguments. Judge only
  where the substring sits outside quotes — inside quotes bash does not split on `$IFS` either.
- **W1-03** add `awk`/`gawk`/`mawk`/`nawk`/`busybox awk` (`-f` takes a program file, not code — the
  program is the first non-option word), `lua`/`luajit` (`-e`), `deno` (`eval`), `julia`/`Rscript`
  (`-e`), `tclsh`, `osascript` (`-e`), `sqlite3` (`.shell`/`.system` row) to
  `_INLINE_FLAGS`/`_inline_code`, and give `_CODE_WRITES` the `system|exec` it already has for shells.
  `sed`'s `e` deserves its own extraction (`_operands` of the script), not the inline table.

## Corpus and test gap

All eight shapes are invisible to the conformance corpus: `$IFS`, `awk `, `~/`, `tar -x`, `unzip`
and the string `.claude` occur **zero** times in `tests/fixtures/deny_hook_conformance.json` (2,573
lines), and `cd ` occurs once. The root-class spellings in `tests/test_deny_hook.py` are the
canonical ones only (`/`, `/*`, `~`, `$HOME`), so every W1-06 variant passes the suite by omission.
`tests/test_deny_hook.py:1277` pins the W1-04 ALLOW on purpose, which is the right way to hold a
declared gap — the other seven are unpinned in either direction.

## Cleared areas (no finding; where looked)

- **Fail-closed on unreadable input.** Empty stdin, `not json`, JSON `[]`, no `python3` on PATH,
  missing `grep`/`sed`/`tr` (shimmed PATH) → deny **and** exit 2, with the reason on stderr
  (4146-4160, 805-826). A missing `dirname` only corrupts `DH_SELF`. Byte-scale: a 200 KB command,
  a 900 KB `Write` body, and a 200 KB command followed by `rm -rf /` all still decide correctly —
  nothing truncates into a fail-open.
- **Peeler.** 29 forms all reached the payload: `sudo -u root`, `doas`, `env -S`, `nohup`, `nice`,
  `time`, `stdbuf`, `ionice`, `chrt`, `taskset`, `timeout -s KILL`, `exec`, `setsid`, `xargs -I{}`,
  `chroot`, `unshare`, `nsenter -t`, `strace`, `command -p`, `su -c`, `script -c`, `watch`, `flock`,
  `parallel`, `ssh`, `find -exec sh -c`, `trap`, `eval`, and 4-deep `sh -c` nesting.
- **Quoting and word-splitting inside a token.** `r''m`, `"rm"`, `r\m`, `'git' push`, `pu''sh`,
  `-'f'`, `--for''ce`, `$'\x72m'` (ANSI-C), `{rm,-rf,/}` — all deny. Quote removal happens before
  `policy_word`, so `rm -rf "/;x"` → `ask` on the stripped `/` (correct, not a bypass).
- **Substitution and variable heads.** `$(…)`, backticks, `<(…)` heads, `$c` with `c=rm` assigned,
  `$(echo git) push --force …`, and an *unset* `$G` head (refused-head fallback) → deny. W1-02 is
  specifically the case where the variable is *inside* the word rather than the whole head.
- **`gh` and receipt arming.** `$GH pr merge 34` denies via the refused-head body; a receipt suffix
  after `;` does not arm the next segment; `gh` `-o`/`-p` operands are skipped correctly; `gh alias
  set` produces the whole-line `D` record.
- **Boundary resolver mechanics.** A symlink inside the worktree pointing out is denied by where it
  ends up, at 1 and at 3 hops (the #297 chain walk, 4247-4265), and a >32-hop chain fails closed.
  `tee`, `tee --`, `( tee )`, two `tee`s in one line, `stdbuf tee` and `env tee` are all judged;
  `/dev/null`, `/dev/std*` and `/dev/fd/*` are exempt by name and `> /dev/sda` is not.
- **Corpus polarity.** Every `boundary`-class fixture is a true false-deny (no HIGH shape is
  documented as `ask`); the `wipe` payload `rm -r -f ./build` → `ask` and `--delet…` → `ask` are
  correct; `rm -rf "/;x"` → `ask` is correct. The suite's deny/allow polarity is sound — the gaps are
  omissions, not inversions.
- **Root-class rule mechanics.** Quoted targets are stripped first, so `"$HOME"`, `'/'` and `"/*"`
  deny; `--no-preserve-root` anywhere on an `rm` line denies regardless of target. W1-06 is the
  spelling set, not the mechanism.
- **Hooks wiring.** `hooks/hooks.json` quotes `${CLAUDE_PLUGIN_ROOT}`; `print-settings-snippet.sh`
  template-substitutes through parsed JSON plus `shlex.quote`, so `&`, `|`, `\`, `"`, space and `$` in
  the clone path are all covered (#382). Only the deny-hook emitter (W1-07) lags.

## Dropped after execution (kept out to avoid noise)

`git --exec-path=/x` — denied; only the separated `--exec-path /x` runs nothing, which is a git fact,
not a hook gap. `time -o FILE` — `time` is a bash keyword, so `-o` is
not an operand and nothing is written; the hook is right to allow. `> #f` — a bash syntax error
before the hook's business. `rm -f -r /` — denies; the `-r` regex is not token-adjacent to `-f`.

## Verdict

One P0, and it is a modelling error rather than a missing pattern: the hook holds two different
definitions of `~` (expanded in `_guarded_exact`, literal everywhere on the boundary path), and the
literal one is the one that decides. `echo pwned > ~/.bashrc` is a line every agent writes and it is
silent. The two P1s are the tokenizer losing every argument when `$IFS` supplies the separator, and an
interpreter table that stops at `php` and misses `awk` — both give a full bypass of the HIGH tier with
the flags intact. All three are cheap to close and each needs corpus rows, since none of the eight
shapes exists in the conformance fixture today. What holds up well: fail-closed on garbage at every
size, the peeler, quoting and substitution, the symlink-chain resolver, and the polarity of the
suite.
