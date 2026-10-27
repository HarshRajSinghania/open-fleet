- **The 2026-10-27 security audit's network and egress findings (wave 5) and the bundle half of
  W6-04 are fixed, except the arm's direct network egress (W5-15).** `egress.py` receipts are
  format v2: `id` hashes the record's canonical serialisation and a line must be exactly that
  serialisation, so an extra key, a re-spacing, a type swap or a blank line is TAMPER on the last
  line as on any other, and every line's text, a pre-v2 line's included, is printable ASCII;
  `write` verifies the ledger through the descriptor it holds locked, refuses (exit 3, before the
  send) one the verifier would refuse, streams `--payload-file`, fsyncs, and prints an id that
  `verify --expect-ancestor` (now repeatable) accepts as an anchor, which binds a receipt written
  since the last close; `merge_queue.py` keeps the id of every receipt it writes in its own
  receipts and writes them to the ledger `egress.py`'s default picks. That default is the
  repository root's `.orca/egress.jsonl`; a routed ledger is reported; a `.git` nested below the
  root refuses unless it is a linked worktree whose `.git/worktrees/<name>/gitdir` back-link
  agrees; `grants` verifies first; everything printed is inert; and no receipts is never reported
  as an intact chain: `verify --require-receipts`, the form the close runs, exits 4 on them. Pre-v2
  ledgers keep verifying in the exact v1 form, as a prefix, and the docs say how to recover a
  broken ledger ([runtime-scripts](../docs/runtime-scripts.md#egresspy)). `bundle.py`'s ownership
  marker only names candidates: a listed file is overwritten, or deleted once stale, only when a
  build record kept outside `--out` (in the clone's git directory) holds its exact bytes, when the
  source repository committed them at the path the build copies it from, or when they are the
  bytes the build writes anyway, so a forged marker with true digests deletes or overwrites
  nothing, inside a mission directory too; otherwise an overwrite refuses and a stale file is left
  in place and reported. Every check, delete and write walks `--out` from one directory handle
  without following a link, and each overwrite or delete is one atomic exchange or quarantine
  rename whose displaced file must be the exact file checked (inode and sha256) before it is
  destroyed, else it is put back and the build refuses; a marker naming anything a build does not write, carrying a malformed
  name, or that is a symlink or FIFO refuses; a mission that ships `.gitignore`, `.gitattributes`,
  `.gitmodules` or `.git` fails the build; and a `--out` built before digests or without a build
  record refuses once if the build changes anything there ([install](../docs/install.md)).
  `external-ci-monitor.py` never re-sends `GITHUB_TOKEN` on a redirect, refuses a foreign origin
  and an oversized body, and shape-checks `--repo`; the paperclip and OpenHands adapters' keys never
  follow a redirect either. The live harness's broker cuts off idle and trickling connections and
  evicts a stalled request when its slots are full, so trickling connections never keep the arm's
  calls out; it bounds `count_tokens`, settles every call, and counts refusals, drops and faults
  per kind with bounded text, so the arm cannot grow the host's ledger. The launcher runs only an
  image whose id its own `build` recorded (from `--iidfile`) from the committed Dockerfile unless
  `--allow-foreign-image` is passed, and refuses any `--mount` path docker would split; the image
  pins the Claude Code installer and binary by sha256 ([live harness](../docs/guides/live-harness.md)).
  `search_sessions.py` reads only regular files (a link, FIFO or device is said, never opened) and
  only a SQLite store's plain tables' stored columns (never a view, virtual table or generated
  column), capped per file and per scan as the bytes arrive, a row's stored size charged as
  SQLite reads it so no value past either cap ever reaches Python, and a store over 1 GiB never
  opened; a `.zst` transcript is walked frame
  by frame in linear work, a damaged tail kept up to its last whole frame and said; a record nested
  past the parser's depth is skipped, never fatal; and a store swapped for a FIFO during SQLite's own
  open fails closed and is said, never hangs recall.
