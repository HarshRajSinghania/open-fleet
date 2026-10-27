- **The deny hook's write boundary, interpreter table and self-guard close a batch of 2026-10-27
  security-audit findings, and the `ro` tier gains a real write floor** (W1-01..03, W1-05..08,
  W4-03, W4-05, W4-06, W4-09). A leading `~`/`$HOME` is expanded on every write-boundary path, so `echo > ~/.bashrc`
  and a `Write` of `~/.bashrc` are judged where the shell writes, not silently allowed (W1-01); an
  unquoted `$IFS`/`${IFS}` separator is field-split so each candidate head is judged with its
  arguments (W1-02); the inline-interpreter class is closed beyond python/node — the awk family,
  lua/luajit/julia/Rscript `-e`, deno `eval`, a busybox applet, and sqlite3 `.shell`/`.system` and
  sed `e` are read for the shell they launch, awk collects EVERY program source so a benign `-f`
  file never hides a refused `-e` and an unreadable `-f`/`-E` program file fails closed, and an
  arg-taking option (`python -W error`) no longer hides the `-c` after it (W1-03); `tar`/`unzip`/
  `patch`/`cpio`/`pax`/`bsdtar`/busybox reach the self-guard — a guard file named as `tar -cf`/
  `patch -o` output is denied, and an extraction or patch whose destination equals, sits inside or
  contains a guard directory (`tar -C .claude …`, any `-C`/`-d`/`--directory` spelling) is asked,
  with every guard directory and guard file's directory compared wherever its symlinks resolve, so a
  `.claude` linked outside the worktree is still the guard (W1-05); the root/home delete class is normalised rather than spelled out, so `/*/`,
  `~/.`, `${HOME}/*` and `/dev/../` deny (W1-06); `--settings` shell-quotes the hook path and pins
  both boundary names so a space in the install path or a stale inherited variable cannot disarm
  it (W1-07, W1-08); `lexical_abs` no longer pathname-expands a path segment and a glob in a shell
  write target is judged by every path it expands to (W4-09). The spawn arming gate now receives
  the worktree for every selector that names an existing tree, not just `path:` (W4-03), and runs
  for every profile including `ro`, which used to skip it entirely (W4-03). W4-06 now enforces the
  guard where it is installed: the posix provider verifies the registration inside `worker-start`
  — the file exists, names the hook that loads, pins the boundary, answers a deny probe — AFTER
  installing it and BEFORE the agent process starts, and aborts the launch (`deny_hook_unverified`)
  if any check fails, so a `new-child` spawn that the coordinator's pre-launch gate cannot verify
  is still enforced; the openhands provider runs the same check on the `hook_config` its
  agent-server executes, before the conversation exists (named worktree) or before the `/run`
  that starts the agent (server-cut worktree). `spawn_worker.sh` defers to those two and ordinary
  dispatch needs no opt-out; another non-Orca provider, which installs without verifying,
  proceeds with an `UNVERIFIED` warning naming the runtime; on Orca (whose `worker-start` wires no
  open-fleet guard) an unset settings var still refuses, every profile, unless
  `OPEN_FLEET_ALLOW_UNVERIFIED_DENY_HOOK=1` opts out. `OPEN_FLEET_REQUIRE_DENY_HOOK=1` is checked
  before any deferral or opt-out and refuses an unset var on every runtime. A new `OPEN_FLEET_HOOK_READONLY` write
  floor (wired with `deny-hook.sh --settings <wt> --readonly`; no provider sets it on its own)
  lets the hook deny every write it can see on the `ro` tier — in a `-c` body, a substitution or a
  program piped to a shell too, and `echo x > -` writes a file named `-` — and refuse a shell fed
  a program it cannot read (`cat f | sh`, `sh < f`): defense-in-depth over the channels plan-mode
  `Bash` left open, not a filesystem sandbox, which stays the disposable environment's job (W4-05).
