# Integrated contract — mdtoc (frozen SPEC.md @0b9f660, AC-9 is the error half of the spec's placement criterion)

- AC-1: `mdtoc FILE` inserts or updates a TOC between `<!-- toc -->` and `<!-- /toc -->` markers; running twice produces no further change (idempotent).
- AC-2: TOC links use GitHub anchor slugs, including `-1`, `-2` suffixes for duplicate headings.
- AC-3: Headings inside fenced code blocks are ignored.
- AC-4: `--check` exits 1 when the TOC is stale or missing, 0 when current; `--stdout` prints the result and never writes the file.
- AC-5: Default depth is H2-H4; `--max-depth N` (1..6) limits included levels.
- AC-6: Without markers, insert the TOC after the first H1 if present, otherwise at the top of the file.
- AC-7: Multiple files may be given in one invocation; a per-file error does not stop the others, and the exit code aggregates failures.
- AC-8: A unittest suite covers slugging, code-fence exclusion, in-place update, and check mode; `python3 -m unittest` is green.
- AC-9: A missing or non-UTF-8 file is a clean error (message on stderr, exit 2).
