# Slice contracts — mdtoc ship-it run (frozen at decompose)

Frozen spec: ravidsrk/mdtoc `SPEC.md` @ 0b9f660d93e64cf57e8245b0f1eb6eb0010ae158
(maintainer-approved 2026-10-13). Union of slice criteria = AC-1..AC-8.

## F0 — foundation scaffold
- FC-1: `mdtoc` package exists (`mdtoc/__init__.py`, CLI module) and
  `python3 -m mdtoc --help` exits 0 (stdlib only).
- FC-2: `python3 -m unittest discover` runs and is green with a smoke test.
- FC-3: README has a Usage section stub naming the CLI surface.

## S1 — heading scan + GitHub slug + TOC render (AC-2, AC-3)
- AC-2: TOC links use GitHub anchor slugs, incl. `-1`/`-2` for duplicates.
- AC-3: Headings inside fenced code blocks are ignored.

## S2 — file update + modes (AC-1, AC-4, AC-5, AC-6-placement)
- AC-1: markers insert/update, idempotent.
- AC-4: `--check` exit 1 stale / 0 current; `--stdout` never writes.
- AC-5: default H2–H4; `--max-depth 1..6`.
- AC-6p: without markers, insert after first H1, else file top.

## S3 — multi-file + error model + docs (AC-6-errors, AC-7)
- AC-6e: missing or non-UTF-8 file → stderr message, exit 2.
- AC-7: multiple files per invocation; per-file errors don't abort; exit
  aggregates.

## Integrated (coordinator, at BASE head)
- AC-8: full `python3 -m unittest` green at the integrated head and every
  AC above maps to a passing test in the traceability table.
