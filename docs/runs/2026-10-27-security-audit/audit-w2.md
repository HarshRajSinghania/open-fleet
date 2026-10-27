# W2 — command construction and quoting

RUN: run_secaudit_20261027 · AUDITOR: w2 (red team) · BASE: review/2026-10-27-security-audit @
15e03dfedbf5 · SCOPE-OWNER: STRIDE **Elevation** (B1 sandbox, B5 untrusted text) · SOURCE:
`threat-model.md` (B1, B4, B5; Elevation) · MODE: static/read-only; scratch PoCs in
`/tmp/opencode`, no tracked file touched

Scope read in full: all 75 in-scope files under `runtime/scripts/**`, `scripts/**`, `hooks/**`,
`install.sh`, plus the argv/shell surface they call into — `runtime/providers/posix.py`,
`base.py`, `_external.py`, `worktrunk.py`, `emdash.py`, `orca.py`. The brief's targets were
enumerated programmatically, not sampled: **210 `subprocess.*` references across 38 Python files**,
13 `Popen(`, every `shell=True`/`os.system`/`eval`/`exec`, every `bash -c`/`sh -c` string, every
interpolated command, and every `git` invocation taking a ref/path/revision/`-c` value from a
variable.

Headline: **there is no shell-injection finding in this tree.** Almost every site uses an argv
list; every one of the four shell-string builders quotes every value with
`shlex.quote`/`shlex.join`; the one `shell=True` is over a string that is fully quoted. What
survives is the *other* half of command
construction — end-of-options discipline. Nothing here is `--`-guarded, and `tmux send-keys`,
`cmux send`, the provider flag parser and `ln` all consume a leading-`-` value as a flag. Every
git site fails closed; the terminal path does not, and reports `accepted: true` for input it
dropped.

Severity: P0 untrusted value reaches a shell/argv with a realistic no-review path · P1 needs a
crafted but accepted record · P2 defense in depth · P3 cosmetic.

## Findings

| id | file:line | sev | class | untrusted input | exploit scenario | gain | why validation fails | PoC |
|---|---|---|---|---|---|---|---|---|
| W2-01 | `runtime/providers/posix.py:3084` (tmux), `:3093` (cmux); cause upstream at `runtime/providers/base.py:512-526` (`_parse_flag_map`), reached from `:630-635` (`terminal send`) and `runtime/scripts/spawn_worker.sh:1566` | P2 | argv option injection at the terminal delivery layer — a dropped payload is recorded as delivered | the `--text` operand of `terminal send`: operator-typed text, or the dispatch preamble in the #680 no-inject fallback | `terminal send --terminal t1 --text "-R" --enter` (or any text whose first character is `-`). `_deliver_terminal_input` runs `["tmux","send-keys","-t","t1","-l","-R"]`; tmux parses `-R` as *reset-terminal*, exits 0, and no text reaches the pane. `terminal_send` then returns `{"accepted": true}`, writes the text to `.open-fleet/inbox.jsonl`, and `spawn_worker.sh` prints `SPAWN=NOTE` rather than `SPAWN=FAILED`. With a `-h`-shaped payload tmux errors instead (`unknown flag -h`), which at least surfaces | a dispatch the fleet believes it delivered (and whose inbox says so) never arrives, so the worker idles to its timeout with no error to act on. Not code execution: the value stays one argv element | no site appends `--`. `tmux send-keys` has no `-l`-then-value form that absorbs a dash, and `cmux send --workspace <id> <text>` puts the text in the last positional. One layer up, `_parse_flag_map` is not `--`-aware either: `--text --hello` yields `text=True` (a bool) so `text + "\n"` at `posix.py:3073` raises `TypeError`, and the `--text=` form is unsupported (the key becomes `text=-R`) | **EXECUTED** (tmux 3.4): `-R` → rc 0, pane stdin receives only `\n`; `-hello world` → `rc=1 command send-keys: unknown flag -h`; `-l -- '-hello world'` → text arrives. `--text --hello` → `{'text': True}`. cmux: STATIC_ONLY (no `cmux` here) |
| W2-02 | `runtime/providers/base.py:148` (`shell_launch_line`), `runtime/providers/posix.py:1364` (`_docker_command`) | P3 | shell-string assembly — env **key** interpolated unquoted | the `env` dict keys of a launch (`launch["env"]`, and `identity_env` merged in at `posix.py:1610-1616`) | both build `f"{k}={shlex.quote(str(v))}"` and feed a `shell=True` line (`posix.py:1202-1204`) or a `docker run … sh -c` string. Value is quoted, key is not. Today every key is a literal (`OPENCODE_CONFIG_CONTENT`, `HERMES_WRITE_SAFE_ROOT`, `OPEN_FLEET_*`), so this is not reachable — but a key is a *shell word* position and one future `env[f"OPEN_FLEET_{x}"]` closes the gap | none today; a key containing a space silently becomes a command (`A B=v` runs `A`), one containing `;` executes | keys are never validated or quoted; the code quotes the half an attacker is likelier to reach and leaves the half that is a word | **EXECUTED**: render of `{"A B": "v"}` → `A B=v`; `sh -c 'A B=v env'` → `sh: 1: A: not found` |
| W2-03 | `runtime/scripts/orca_cli.py:109-111` and `:141`; contrast `runtime/scripts/upstream_probe.py:337-342` | P3 | argv[0] resolution — an env value is returned verbatim as one executable token | `OPEN_FLEET_CLI_COMMAND` / `ORCA_CLI_COMMAND` (coordinator env; also what Orca exports into sessions) | `OPEN_FLEET_CLI_COMMAND="python3 /tmp/orca.py"` → `resolve()` returns the two-word string, `run_json` runs `subprocess.run(["python3 /tmp/orca.py", …])`, which is not a path, so every Orca call dies with `[Errno 2]`. No shell, so no injection; the failure is what is wrong, and the cause is not named. `upstream_probe.resolve_cli` guards the same variable with `shutil.which` and states the rule in words (`upstream_probe.py:45`, `:340-341`: "it must name one executable, without arguments") — `orca_cli` has the same rule in its docstring and no check | every fleet script routes through this resolver, so one mis-set variable breaks every dispatch with an opaque errno instead of a named cause | two resolvers, two policies for the same env var: one checks, one only `.strip()`s. `eval.py:1427` shows the third correct answer (`shlex.split`, argv, no shell) if multi-word were wanted | **EXECUTED**: `run_json` → `could not run orca: [Errno 2] … 'python3 /tmp/w2t/bin'`; `upstream_probe.resolve_cli` → `ProbeError … is not on PATH (it must name one executable, without arguments)` |
| W2-04 | `runtime/providers/posix.py:994` (`worktree add … <base>`); `runtime/scripts/first_run.py:542-543` and `:555-556`; `scripts/check_trailers.py:55,66`; `scripts/bind_check.py:74`; `runtime/scripts/pin_review.py:116`; `runtime/scripts/inventory.py:248`; `scripts/ablation.py:954`; `scripts/hint_replay.py:169,172` | P3 | argv option injection — a value in option position with no `--` | `--base`/`--head` (first_run, check_trailers), the CI-supplied base ref (bind_check), `--to`/`--old` (pin_review), `--at` (inventory), a prereg `commit` (ablation), corpus `branch` (hint_replay), a worktree `base` (posix) | `first_run.py run --base=--show-toplevel --head=HEAD` → `rev-parse --verify --show-toplevel^{commit}` → `fatal: Needed a single revision`. Same shape at the other eight sites (`git log --all..HEAD` → `unrecognized argument`; `merge-base HEAD --all` → usage; `cat-file blob --batch:x` → `unknown option`; `archive --format=tar --all` → `unknown option`; `checkout -b -B` → `'-B' is not a valid branch name`) | a clean error, never a wrong answer — which is why this is P3 and not P1. The one place it is quiet: `inventory.sha256_at` swallows a `cat-file` failure into `None`, but `rev_exists` (`:559`) gates first, so `--at` still errors | the values are only ever shapes that happen not to start with `-` (a SHA, `origin/main`, `v1.2.3`), and nothing asserts it. `decisions.py:320-321` is the one module that checks (`ref.startswith("-")` → `DecisionsError`) and is the model for the rest | **EXECUTED** (all nine, in `/tmp/opencode/w2opt`): every one fails closed |
| W2-05 | `scripts/install.sh:217`; value at `:44` | P3 | argv option injection in the installer | `--skills-dir=DIR` | `sh scripts/install.sh --skills-dir=-x` → `ln -sfn "$ROOT/skills/$m" "-x/$m"`, and GNU `ln` reads `-x/$m` as an option cluster (`-x` is not an `ln` flag) → `invalid option -- 'x'`, rc 1 | the documented flag form produces a hard failure with no hint about the cause; the directory is still created by earlier steps, so half the install ran | `$SKILLS_DIR` is concatenated into a *destination* argv element and never prefixed with `./` or `--`. The source is absolute (`/…`), so it never protects the destination position | **EXECUTED**: `ln -sfn /tmp/lntest/src '-x/dest'` → `invalid option -- 'x'`, rc 1 |

## Why the shell-injection classes are empty

Stated as a negative result with the evidence, because "no findings" is only worth as much as the
sweep behind it:

- **Every `subprocess` call in the 75 in-scope files passes a list**, and so does every one in the
  provider surface they call. The brief's `shell=True` question has one answer tree-wide:
  `runtime/providers/posix.py:1202-1204`, on the generated monitor script. The string it runs is
  built at `:1373` from `shlex.quote`d argv joins and `shlex.quote`d mounts, so the only unquoted
  token is an env key (W2-02).
- **The shell-`-c` sites are `shlex.join`/`shlex.quote` throughout**: `install_worktree_hooks`
  (`posix.py:298-301`), `prepare_hermes_home` (`:731-733`), `_docker_command` inner (`:1373`,
  `:1605`). Each quotes the path/hook that could carry `$`, a backtick or `"`.
- **The two deliberate `sh -c` hosts are correct by design**: `merge_queue._run_gate` runs the
  operator's `--gate-cmd` (`:1391`, `Popen(["/bin/sh","-c", gate_cmd])`) — a gate *is* a shell
  command, and no PR-supplied value is interpolated into it; `shell_launch_line` builds the worker
  launch line for `shell=True`, quoting every argv element.
- **`-c` values are constants**, never variables: `core.quotePath=false`,
  `core.hooksPath=/dev/null`, the `diff.*` block in `floor_guard.py:237-239`, the override pairs in
  `_trajectories.py:811,1629` (whose *keys* are a fixed tuple). `git config key value` is a
  two-argument form that cannot absorb a dash.
- **`--` discipline is right where `-` really can appear**: `git add -f --`, `git diff -- <paths>`,
  `git ls-tree … -- <rel>`, `git archive … -- <paths>`, and `git push --force-with-lease=…`
  where the `=`-form absorbs a dash-leading branch.

## Cleared areas (checked, no finding)

- **`_docker_command` (`posix.py:1344-1374`) and its mounts.** Every `-v` operand is
  `shlex.quote`d; `--user` is `shlex.quote(user)` from env; the image is quoted; `inner` is a
  quoted-argv join. `--name openfleet-{dispatch_id}` is `disp_<10 hex>`.
- **Monitor-script generation (`posix.py:1167-1340`).** All interpolation is `repr()` of already
  `shlex.quote`d text or of a literal; the env file is JSON (0600) and read with `json.load`, never
  shell-expanded; `deny` patterns are a `repr`'d list consumed by `fnmatch`, not by the shell.
- **`base._build_harness_command` / every harness branch.** `argv` plus the prompt as its own
  element; the human-readable `command` label is never executed (documented, `:118-123`).
- **`merge_queue` git/gh argv.** `--force-with-lease=refs/heads/<branch>:<sha>` (the `=`-form),
  refspec `:<refs/heads/branch>`, `gh api … -f base=<base> -f head=<sha>`, host from a set checked
  against `GITHUB_HOSTS_ENV`; `_bound_remote` re-proves the push URL at the send.
- **`verify.py`.** `_Authority` builds every git/gh argv itself with HEX40/int gates, and `api()`
  (`:1048`) path-checks before use; `_run_at` (`:1191`) is argv-only by contract.
- **`gitexec.py`.** `env()` hardens the whole git environment and `driver_blanks()` rebuilds a
  driver string with `--`-safety; `argv()` prefixes the constant `-c` set.
- **`wtree.sh`.** `GIT_CONFIG_KEY_*`/`GIT_CONFIG_VALUE_*` travel as positional pairs (numbers are
  integers), so a value with `=` or a space cannot shift them.
- **`guard_text.py --fetch` and `evidence-run`.** Both take `argparse.REMAINDER` and hand it on as
  an argv, so a `-`-leading remainder reaches the child's own parser, not ours.
- **`deny-hook.sh`.** 5,182 lines of *parsing*, not execution: no `eval`, no `sh -c` of a judged
  command; `PROBE_ARGV` is passed as `${…[@]}`.
- **`hooks/print-settings-snippet.sh`, `hooks/settings-snippet.json`.** Static text; the one
  variable (`$0`-derived path) is `shlex.quote`d.
- **`terminal_create --command` (`posix.py:2919-2939`).** Intentional `shell=True` on the caller's
  string — documented behaviour, not a bug; the caller asked for a command line.
- **`_resolve_worktree_path`** returns a path used as `cwd=` and quoted in `-w`; a `-`-leading
  relative path is safe in both. `_worktree_slug` (`:542-543`) keeps only `[A-Za-z0-9._-]` and
  strips `-`, so a name can never present as an option.
- **`backend_ref` → `-t`/`--workspace`** (`:2960-2961`, `:3084`, `:3093`). Always `openfleet-<handle>` or an id
  parsed from `cmux` output; `-t`/`--workspace` take the next token.
- Observation, not a finding: `prepare_hermes_home` writes a `shlex.quote`d hook command into a
  config Hermes runs *without* a shell (docstring, `:698`). If Hermes does not `shlex.split`
  it, a worktree path with a space arrives with literal quotes in `OPEN_FLEET_UNIT_WORKTREE`. Not
  reachable without a spaced path and not an injection either way.

## What would move a row up

- W2-01 → **P1** the moment a caller passes attacker-influenced text to `terminal send` without a
  JSON prologue: `dispatch_inject` is safe only because its payload is `{`-prefixed
  (`posix.py:3175`), and `spawn_worker.sh:1566` is safe only while Orca's preamble does not start
  with `-`. A PR-body or issue-body excerpt sent down `--text` makes the drop attacker-chosen.
- W2-04 → **P1** if any of those revs ever becomes PR-supplied rather than operator-typed; it
  already fails closed, so the gain is a denied gate rather than a wrong one.

## Fix shape (one line each)

`--` before the text at `posix.py:3084` and `:3093` (tmux 3.4 verified to accept it; `cmux` unverified here), and
`--`-terminate `_parse_flag_map` (plus support `--key=value`); `shlex.quote(k)` at `base.py:148`
and `posix.py:1364`; route `resolve()` through `shutil.which` with `upstream_probe`'s message;
append `--` at the nine W2-04 sites; `ln -sfn --` at `install.sh:217`.
