- **The deny hook closes all eight findings from the 2026-10-29 audit.** A write inside a nested
  body (`sh -c`, `find -exec sh -c`, `xargs sh -c`, sed `e`, awk/perl `system()`) is now held to
  the worktree write boundary (F1). `busybox`/`toybox` shell applets, `hush` included, are judged
  as the shell they run (F2). `git bisect run`, `git rebase --exec/-x` and `git submodule foreach`
  bodies are judged as commands of their own (F3). A `--force-with-lease=<ref>` that does not name
  every pushed ref no longer exempts a forced push (F4). Attached sed `-e'…'` scripts and awk
  `-F`/`-v` operands are parsed as clusters (F5, F6), and `{ receipt; } && send` arms like
  `( receipt ) && send` (F8). Malformed hook events now fail closed: no tool name, a shell event
  with no input, or a command that is neither a string nor a list is refused, and an argv-list
  command is judged as the line it spells (F7).
