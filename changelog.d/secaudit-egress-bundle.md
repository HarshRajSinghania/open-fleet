- **The 2026-10-27 security audit's network and egress findings (wave 5) and the bundle half of
  W6-04 are fixed.** `egress.py` receipts are format v2: `id` hashes the record's canonical
  serialisation and a line must be exactly that serialisation, so an extra key, a re-spacing, a
  type swap or a blank line is TAMPER on the last line as on any other, and every line's text is
  printable ASCII; `write` verifies the ledger through the descriptor it holds locked, refuses
  (exit 3, before the send) one the verifier would refuse, fsyncs, and prints an id that
  `verify --expect-ancestor` (now repeatable) accepts as an anchor, which binds a receipt written
  since the last close; `merge_queue.py` keeps the id of every receipt it writes in its own
  receipts. The default ledger is the repository root's `.orca/egress.jsonl`, a routed ledger is
  reported, a `.git` nested below the root refuses unless it is a linked worktree, `grants`
  verifies first, everything printed is inert, and `verify` finding no receipts exits 4 unless
  the run declares it sent nothing (`--allow-empty`). Pre-v2 ledgers keep verifying in the exact
  v1 form, as a prefix, and the docs say how to recover a broken ledger
  ([runtime-scripts](../docs/runtime-scripts.md#egresspy)). `bundle.py`'s ownership marker only
  names candidates: a listed file is overwritten, or deleted once stale, only when a build record
  kept outside `--out` (in the clone's git directory) holds its exact bytes, when the source
  repository committed them at the path the build copies it from, or when they are the bytes the
  build writes anyway, so a forged marker with true digests deletes or overwrites nothing, inside a
  mission directory too; otherwise an overwrite refuses and a stale file is left in place and
  reported; every check, delete and write walks `--out` from one directory handle without
  following a link; a marker naming anything a build does not write, carrying a malformed name, or
  that is a symlink or FIFO refuses; a mission that ships `.gitignore`, `.gitattributes`,
  `.gitmodules` or `.git` fails the build; a `--out` built before digests or without a build record
  refuses once if the build changes anything there ([install](../docs/install.md)).
  `external-ci-monitor.py` never re-sends
  `GITHUB_TOKEN` on a redirect, refuses a foreign origin and an oversized body, and shape-checks
  `--repo`; the orchestrator adapters' API keys (paperclip, OpenHands) never follow a redirect either. The live harness's broker bounds idle and trickling connections and `count_tokens`,
  settles every call and records every fault and dropped connection in its ledger; the launcher
  runs only an image its own `build` recorded from the committed Dockerfile unless
  `--allow-foreign-image` is passed, refuses any `--mount` path docker would split, and the image
  pins the Claude Code installer and binary by sha256
  ([live harness](../docs/guides/live-harness.md)). `search_sessions.py` reads only regular files
  and SQLite tables, capped per file and per scan as the bytes arrive, every frame of a `.zst`
  transcript included. The arm's direct network egress (W5-15) is documented, not yet closed.
