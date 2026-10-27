- **The deny hook's write boundary, interpreter table and self-guard close a batch of 2026-10-27
  security-audit findings, and the `ro` tier gains a real write floor** (W1-01..08, W4-03, W4-05,
  W4-06). A leading `~`/`$HOME` is expanded on every write-boundary path, so `echo > ~/.bashrc`
  and a `Write` of `~/.bashrc` are judged where the shell writes, not silently allowed (W1-01); an
  unquoted `$IFS`/`${IFS}` separator is field-split so each candidate head is judged with its
  arguments (W1-02); the inline-interpreter class is closed beyond python/node — the awk family,
  lua/luajit/julia/Rscript `-e`, deno `eval`, a busybox applet, and sqlite3 `.shell`/`.system` and
  sed `e` are read for the shell they launch (W1-03); a relative redirect after a `cd` the line
  names is composed with it (W1-04); `tar`/`unzip`/`patch`/busybox reach the self-guard — a guard
  file named as `tar -cf`/`patch -o` output is denied and an extraction over the guard region is
  asked (W1-05); the root/home delete class is normalised rather than spelled out, so `/*/`,
  `~/.`, `${HOME}/*` and `/dev/../` deny (W1-06); `--settings` shell-quotes the hook path and pins
  both boundary names so a space in the install path or a stale inherited variable cannot disarm
  it (W1-07, W1-08); `lexical_abs` no longer pathname-expands a path segment and a glob in a shell
  write target is judged by every path it expands to (W4-09). The spawn arming gate now receives
  the worktree for every selector that names an existing tree, not just `path:` (W4-03), and runs
  for every profile including `ro`, which used to skip it entirely; a hardened coordinator sets
  `OPEN_FLEET_REQUIRE_DENY_HOOK=1` to make an `rw`/`danger` spawn refuse when its guard settings
  var is unset rather than proceed on a warning (W4-06, partial — the default stays a warning
  pending a coordinated `first_run.py` change). A new
  `OPEN_FLEET_HOOK_READONLY` write floor (wired with `deny-hook.sh --settings <wt> --readonly`)
  lets the hook deny every write it can see on the `ro` tier, defense-in-depth over the channels
  plan-mode `Bash` left open — not a filesystem sandbox, which stays the disposable environment's
  job (W4-05).
