- **The 2026-10-27 security audit's network and egress findings (wave 5) and the bundle half of
  W6-04 are fixed.** `egress.py` receipts are format v2: `id` hashes the record's canonical
  serialisation and a line must be exactly that serialisation, so an extra key, a re-spacing, a
  type swap or a blank line is TAMPER on the last line as on any other; `write` verifies the
  ledger through the descriptor it holds locked, refuses (exit 3, before the send) one the
  verifier would refuse, fsyncs, and prints an id that `verify --expect-ancestor` (now repeatable)
  accepts as an anchor, which binds a receipt written since the last close. The default ledger is
  the repository root's `.orca/egress.jsonl`, a routed ledger is reported, a missing one is not
  "intact", and `grants` verifies first. Pre-v2 ledgers keep verifying in the exact v1 form, as a
  prefix ([runtime-scripts](../docs/runtime-scripts.md#egresspy)). `bundle.py` records the sha256
  of every file it writes and deletes only what still matches, refuses a marker naming anything a
  build does not write or that is a symlink, and fails a mission that ships `.gitignore`,
  `.gitattributes`, `.gitmodules` or `.git`; a `--out` built before digests refuses once
  ([install](../docs/install.md)). `external-ci-monitor.py` never re-sends `GITHUB_TOKEN` on a
  redirect, refuses a foreign origin and an oversized body, and shape-checks `--repo`. The live
  harness's broker bounds idle connections and `count_tokens`, settles every call and records
  faults in its ledger; the launcher refuses an image not built from the committed Dockerfile
  unless `--allow-foreign-image` is passed, refuses any `--mount` path docker would split, and the
  image pins the Claude Code installer and binary by sha256
  ([live harness](../docs/guides/live-harness.md)). `search_sessions.py` caps recall reads per
  file and per scan. The arm's direct network egress (W5-15) is documented, not yet closed.
