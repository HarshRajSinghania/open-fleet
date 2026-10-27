# Verify V1 — deny-hook (B1)
RUN: run_secaudit_20261027 · VERIFIER: v1 · BASE: 15e03dfe · MODE: read-only, scratch under mktemp -d

Scratch: `mktemp -d` → `/tmp/tmp.HMEMpQQdnc`, fixture worktree = `…/repo` (git init, one commit,
`refs/remotes/origin/main` planted as `tests/test_deny_hook.py` does). Every probe is a real
PreToolUse JSON payload
`{"hook_event_name":"PreToolUse","tool_name":…,"tool_input":…}` piped on stdin, run as
`env -u ORCA_UNIT_WORKTREE OPEN_FLEET_UNIT_WORKTREE=<repo> sh runtime/scripts/deny-hook.sh`
with cwd = the fixture worktree — exactly `HookBase.fire()` (`tests/test_deny_hook.py:89-96`),
which is also the real wiring (the host runs the hook in the worker's session cwd).
Tracked tree untouched (`git status` shows only the pre-existing untracked audit files).

Two controls pin that the boundary is arming at all: `echo pwned > /etc/cron.d/x` → **deny**, and
`Write /etc/hosts` → **deny**; `> notes.txt` and `Write <repo>/a.txt` → **allow**.

## Verdicts
| id | claim | verdict | observed |
|---|---|---|---|
| A1 | leading `~` / `~user` in a write target never expanded → classed inside the worktree | **CONFIRMED (P0)** | silent ALLOW for `> ~/.bashrc`, `>> ~/.bashrc`, `tee ~/.bashrc`, `Write ~/.bashrc`, `Edit ~/.bashrc`, `Write ~root/.bashrc`; real run put the bytes in `$HOME`, nothing under the worktree |
| A2 | `$IFS` separator leaves the head unresolved; refused-head fallback judges the head argument-less | **CONFIRMED (P1)** | silent ALLOW for `rm$IFS-rf$IFS/`, `rm$IFS-rf$IFS~`, `rm$IFS-rf$IFS--no-preserve-root$IFS/`, `git$IFS push$IFS--force$IFS origin$IFS main`, `orca$IFS orchestration$IFS reset`, `rm$IFS-rf$IFS.claude`; FIELDS dump shows the fallback emits bare `C rm` / `C git` |
| A3 | `awk` absent from `_INLINE_FLAGS`/`_RUNNERS` → `awk … system()` judged as inert text | **CONFIRMED (P1)** | silent ALLOW for `awk 'BEGIN{system("rm -rf /")}'` and the same for `git push --force origin main`, `orca orchestration reset`, `rm -rf .claude`; `perl -e`/`python3 -c` equivalents **deny** |

## A1 — CONFIRMED (P0)
- Payload / command (verbatim):
  - `{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"echo pwned >> ~/.bashrc"}}`
  - `…"command":"echo pwned > ~root/.bashrc"`
  - `…"command":"echo pwned | tee ~/.bashrc"`
  - `{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"~/.bashrc","content":"x"}}`
  - `…"tool_name":"Edit","tool_input":{"file_path":"~/.bashrc","old_string":"a","new_string":"b"}`
  - `…"tool_name":"Write","tool_input":{"file_path":"~/.bashrc"}` variants `~root/.bashrc`, `~/sub/dir/file.txt`, `~`
  - control `…"command":"echo pwned > /etc/cron.d/x"`
- Observed (verbatim, all rc=0): every tilde probe → `STDOUT=[]` / `STDERR=[]` → **silent ALLOW**.
  Control → `{"decision": "deny", "reason": "deny-hook: this worker may only write inside its own
  worktree. A shell redirect or tee destination names an absolute path outside the unit boundary.", …}`.
- Mechanism, from the code: `bounded_write` (`5093-5106`) returns at `5095`
  (`case "$_t" in /*) : ;; *) return 0 ;; esac`) before any resolution, so a Bash redirect/tee to
  `~` is not judged at all. The file-tool path does resolve (`check_edit_target` `4284-4299` →
  `resolve_target` `4248` → `resolve_dir` `4224-4231`), but `4227` (`case "$_d" in /*) : ;; *)
  _d="$(pwd -P)/$_d"`) makes `~` a literal directory name: `~/.bashrc` → `$PWD/~/.bashrc`, which
  prefix-matches `$BOUND` at `4292-4296` → allow. `grep -n '~' deny-hook.sh` finds no expansion on
  any write path; the only tilde awareness is the *delete* rule at `4941`
  (`'~'|'~/'|'$HOME'… ROOTY=1`) and `os.path.expanduser(_cd)` for a `cd` at `3950`.
- Real-effect run (proof the bytes leave the worktree):
  ```
  HOME=/tmp/tmp.HMEMpQQdnc/home; printf 'original\n' > $HOME/.bashrc
  HOME=$HOME sh -c 'echo pwned >> ~/.bashrc'          # rc=0
  cat $HOME/.bashrc   → "original\npwned"
  ls -a <repo>        → . .. .git f.txt              # no ./~ created
  ```
  So the hook's model of the path and the shell's disagree; `~` is home, not `./~`.
- Declared / pinned / corpus-covered? **No.** No `~` anywhere in
  `tests/fixtures/deny_hook_conformance.json` (`grep -n '~'` → 0 hits) and no tilde case in
  `tests/test_deny_hook.py`. The header declares the *"relative target"* carve-out (`121-127`,
  `5078-5085`) but never names `~`; a tilde path is not relative in shell semantics, so the
  carve-out does not cover it. Only sibling declaration is `audit-w1.md` §W1-01 (same run,
  `VERIFY_PENDING`) — filed, not fixed.
- Severity you assign and why: **P0, confirmed.** `~/.bashrc` is the line agents actually write;
  the answer is a silent ALLOW with no prompt, the write lands in the host home, and a line there
  executes in every later shell — persistence outside a worktree that is meant to be disposable.
  `~/.ssh/authorized_keys` (`echo ssh-ed25519 AAAA attacker >> ~/.ssh/authorized_keys`) is also
  silent ALLOW. Nothing in the suite would catch a regression. Mitigations that do *not* rescue it:
  the self-guard *does* deny `~/.claude/settings.json` (both tools) because its patterns need no
  cwd — so the guard wiring survives, the rest of home does not. Also note the mirror-image half:
  with the hook's cwd *outside* the worktree, `>> ~/.bashrc` still allows (never resolved) while
  `Write ~/.bashrc` flips to **deny** — the same target, two answers, chosen by an unset cwd.
  Fix shape is small: `case "$_t" in "~"|"~/"*) _t=$HOME${_t#\~} ;; "~"*) _t=<user home>… ;; esac`
  before the `5095` return and before `4227`.

## A2 — CONFIRMED (P1)
- Payload / command (verbatim), all `tool_name":"Bash"`:
  - `{"…","tool_input":{"command":"rm$IFS-rf$IFS/"}}`
  - `rm$IFS-rf$IFS~`, `rm$IFS-rf$IFS--no-preserve-root$IFS/`, `rm$IFS-rf$IFS.claude`
  - `git$IFS push$IFS--force$IFS origin$IFS main`, `orca$IFS orchestration$IFS reset`
  - controls: `rm -rf /`, `rm -rf .claude`, `git push --force origin main`, `orca orchestration reset`
- Observed: every `$IFS` probe → `STDOUT=[]` / `STDERR=[]` / rc=0 → **silent ALLOW**. Every control
  → `"permissionDecision": "deny"` (root delete, own-guard delete, default-branch force, orchestration
  reset). So one unquoted `$IFS` turns each HIGH shape into an ALLOW.
- Mechanism, verbatim FIELDS dump from a copy of the hook with one debug line (scratch copy only):
  ```
  FIELDS<<Bash
  rm$IFS-rf$IFS.claude

  C rm$IFS-rf$IFS.claude
  A rm$IFS-rf$IFS.claude
  C gh
  C git
  C rm
  C orca
  R =rm$IFS-rf$IFS.claude gh ; git ; rm ; orca>>
  ```
  One word (no literal space), so the flags live inside the head word. `_head_bodies` cannot resolve
  `$IFS` (`_SIMPLE_VAR` finds it, `_ASSIGNED` never holds it), so `2440` drops the head and
  `2441-2442` substitutes `_REFUSED_HEADS` (`2282`) — with `rest` empty, because `2440` builds
  `rest` from `ws[1:]` and there is no `ws[1:]`. Each candidate is judged **bare**: `rm` has no
  `-r`, `git` has no `push`. Also visible in the dump: **no `G` record is emitted at all**, so the
  self-guard is blinded too (`rm$IFS-rf$IFS.claude` deletes the hook config unchallenged), which is
  wider than the claim's "HIGH tier and Never-list".
- Real-effect run: `mkdir -p victim/sub; …; sh -c 'rm$IFS-rf$IFS./victim'` → `rc=0`,
  `ls -d victim` → `No such file or directory`. The spelling is live shell, not an artifact.
  Second real run for the boundary half: `>$IFS/tmp/tmp.HMEMpQQdnc/ifsb.txt` → hook ALLOW; under
  `bash` the file really appears (`ifsb.txt` in `/tmp/tmp.HMEMpQQdnc`) while `> /tmp/…/ifs_out2.txt`
  with a literal space **denies**. (Precision: a redirect word is not field-split; bash only trims
  the leading IFS whitespace, dash fails outright — the hook's W record never starts with `/`
  either way, so it is skipped.)
- Declared / pinned / corpus-covered? **No.** `grep -n 'IFS' tests/fixtures/deny_hook_conformance.json`
  → 0 hits; `tests/test_deny_hook.py` → 0 hits (the `IFS=/` seen in
  `tests/test_runtime_providers_core.py:560` is env-scrubbing, unrelated; the `IFS` in
  `scripts/deny_hook_corpus.py:674` is the sentinel's own runtime IFS, not a fixture). Not in the
  header. Only `audit-w1.md` §W1-02.
- Severity you assign and why: **P1, as claimed.** An unbounded class (whole HIGH tier + Never list +
  self-guard + boundary redirects) with a one-token spelling, and the corpus — the file whose job is
  exactly "tokenizer loses the words" — has no case. Not P0 only because it is obfuscation-shaped:
  the plain space form still denies, so a worker hits it by accident rather than by default.

## A3 — CONFIRMED (P1)
- Payload / command (verbatim), `tool_name":"Bash"`:
  - `{"…","tool_input":{"command":"awk 'BEGIN{system(\"rm -rf /\")}'"}}`
  - same with `git push --force origin main`, `orca orchestration reset`, `rm -rf .claude`
  - controls: `python3 -c 'import os; os.system("rm -rf /")'`, `perl -e 'system("rm -rf /")'`,
    `awk '{print $1}' f.txt`, `awk -f x.awk f.txt`, `sed -n '1p' f.txt`
- Observed: every `awk … system()` probe → `STDOUT=[]` / `STDERR=[]` / rc=0 → **silent ALLOW**,
  including the own-guard delete. Both sibling interpreters **deny** (`permissionDecision":"deny"`,
  recursive-delete-of-`/` reason). Plain `awk`/`sed` use → ALLOW, as it should be.
  FIELDS dump for the root case:
  ```
  C awk BEGIN{system(\042rm\040-rf\040/\042)}
  A awk
  A BEGIN{system("rm -rf /")}
  R =awk BEGIN{system("rm -rf /")}>>
  ```
  `awk` is neither in `_INLINE_FLAGS` (`2275-2276`) nor `_RUNNERS` (`4020`), so `_inline_code`
  (`2306`) returns nothing, the `2678`/`2955` "interp" classification misses, and the guard-code
  loop `3911-3914` iterates an empty list. The quoted program is inert. Even the Never-list cannot
  reach it: every rule is anchored `(^|[[:space:]])rm…` (`5132`) and the character before `rm`
  inside `system(…)` is always `"` — verified: `printf '…system("rm -rf /")…' |
  grep -Eq '(^|[[:space:]])rm[[:space:]]+-[a-zA-Z]*[rR][a-zA-Z]*|--recursive'` → rc=1. So awk is
  strictly weaker than a *comment*: a `#` comment is stripped, this body is neither stripped nor read.
- Real-effect run: `mkdir -p victim2/d; printf k > victim2/d/f; awk 'BEGIN{system("rm -rf /tmp/tmp.HMEMpQQdnc/victim2")}'`
  → `rc=0`, `ls -d victim2` → `No such file or directory`. `system()` really fires.
- Declared / pinned / corpus-covered? **No.** `grep -n 'awk'` in
  `tests/fixtures/deny_hook_conformance.json` → 0; in `tests/test_deny_hook.py` → one hit only
  (`_SHIMMED` at `1404`, a PATH-shim list, not a judging case). The header's "beyond it" clauses
  (`54-57`, `121-127`) enumerate interpreter-API writes as uncovered, but python/perl/node/ruby/bun/php
  *are* covered, so awk is an omission in the table, not a declared boundary. Only `audit-w1.md` §W1-03.
- Severity you assign and why: **P1, as claimed.** Complete, silent bypass of the whole HIGH tier and
  the self-guard through a tool every shell has, with the sibling spellings denied — an easy
  `awk 'BEGIN{system("…")}'` wrapper launders any refused command. One-line fix shape: add
  `"awk"`/`"gawk"`/`"mawk"` with the `BEGIN{…}` body lifted as code (it is not an `-c`/`-e` flag
  language, so `_inline_code` needs an awk branch, not a table entry).

## Cross-cutting
- All three are invisible to `tests/fixtures/deny_hook_conformance.json` and to
  `tests/test_deny_hook.py`: the differential corpus cannot find a shape nobody planted, and nothing
  pins the tilde, `$IFS` or `awk` classes. `audit-w1.md:100` already says so; my greps agree.
- Blast radius shared by A1/A2/A3: each is a silent ALLOW, and the header's own polarity claim is
  that only an allow is silent (`20-23`) — so a worker gets no signal at all. A2 and A3 both also
  defeat the self-guard (`rm$IFS-rf$IFS.claude`, `awk 'BEGIN{system("rm -rf .claude")}'`), which the
  header calls the one thing a worker must never touch (`148-160`).
- Fixes should land with a corpus fixture per class, otherwise the same hole re-opens: `~/<home>`
  write, `$IFS` as separator at least on a root delete and a force-push, and `awk system()` at least
  on a root delete.
