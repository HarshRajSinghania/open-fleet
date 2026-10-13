# Integrated acceptance review — mdtoc

**VERDICT: FAIL** at head `c9a6f683bb497d975e4bcd76b5163689e4da794d` (verified with `git rev-parse HEAD`; worktree clean, nothing modified).

FAIL reasons: AC-1 (idempotence) violated for CR-only files; AC-6 (insert after first H1) violated for files with a UTF-8 BOM, which also moves the BOM mid-file; headings containing U+000B/U+000C/U+0085 etc. are split by the inserted TOC (document corruption). All other criteria PASS.

`python3 -m unittest` (Python 3.12.3): `Ran 95 tests ... OK`. Imports (rg over mdtoc/ and tests/): only `argparse, sys, pathlib, re, unicodedata, typing, subprocess, tempfile, unittest` — stdlib only. No `requires-python` file exists; the >=3.11 claim is README-only (no 3.11 interpreter was run; code uses nothing newer than 3.8).

## Traceability matrix

| AC | Verdict | Guarding tests | Probe evidence |
|---|---|---|---|
| AC-1 | **FAIL (CR-only)**; PASS for LF/CRLF | test_idempotent_with_markers, test_twice_is_byte_identical, test_inserted_markers_make_second_run_in_place, test_crlf_preserved, test_crlf_file_stays_crlf | LF: run twice, `cmp` identical (`idem-ok`). CRLF no-H1: `idem`. Depth change `--max-depth 2` then `--check --max-depth 2` → 0; default `--check` → 1 (correct, stale for different depth). **CR-only, no markers:** `printf '# T\r## A\r' > c2.md; mdtoc c2.md; cp c2.md c2a; mdtoc c2.md; cmp c2.md c2a` → `differ: byte 18` `NOT-IDEMPOTENT` (3rd run stable). No test covers CR-only. |
| AC-2 | PASS | test_duplicates_get_suffixes_in_order, test_generated_suffix_checked_against_taken_slugs, test_duplicate_numbering_counts_excluded_levels, test_duplicate_suffix_counts_depth_filtered_headings, test_nested_list_with_duplicate_slugs | `## A / ### B / ##### D / ## A` → `[A](#a)`, `[A](#a-1)`; `## A ## A` after `## a #` gave `a-1`,`a-2`; numbering counts headings filtered by depth (toc.py:112-114 slugs all headings). |
| AC-3 | PASS | test_backtick_fence_excluded, test_tilde_fence_excluded, test_other_fence_type_does_not_close, test_unclosed_fence_swallows_rest, test_fence_on_list_item_line_excluded, test_h1_in_fence_is_not_the_anchor, test_fenced_marker_example_is_untouched | `~~~ / ## no / ~~~ / ## yes` → only `[yes](#yes)`. |
| AC-4 | PASS | test_check_missing_toc_exits_1_without_writing, test_check_stale_exits_1_without_writing, test_check_current_exits_0, test_check_respects_max_depth, test_stdout_never_writes, test_check_with_stdout_is_argparse_error, test_stdout_prints_updated_document_and_does_not_write | `--check` stale → stderr `table of contents is stale or missing`, rc 1; current → 0. `--check --stdout` → `mdtoc: error: --check and --stdout cannot be combined`, rc 2 (README:14-15 documents it). `--stdout` of readonly file: no write. |
| AC-5 | PASS | test_default_depth_h2_to_h4, test_max_depth_limits_levels, test_max_depth_above_default_includes_deeper, test_max_depth_out_of_range_is_argparse_error, test_max_depth_bounds_accepted, test_max_depth_zero_is_argument_error | default omits H5 (`##### D` absent); `--max-depth 2` lists H2 only. (1 → empty TOC: latched.) |
| AC-6 | **FAIL (BOM)**; PASS otherwise | test_no_markers_inserts_after_first_h1, test_no_markers_no_h1_inserts_at_top, test_h1_in_fence_is_not_the_anchor, test_no_markers_h1_without... (test_h1_without_trailing_newline), test_h1_only_with_trailing_newline | `printf '\xef\xbb\xbf# T\n## A\n' > g.md; mdtoc g.md` → bytes `<!-- toc -->\n- [A](#a)\n<!-- /toc -->\n\n` **then** `357 273 277 # T`: TOC placed at top instead of after H1, BOM now mid-file. No test covers BOM. |
| AC-7 | PASS | test_two_good_files_both_updated, test_good_plus_missing_still_updates_good_exit_2, test_good_plus_non_utf8_exit_2_names_file, test_illegal_marker_state_does_not_stop_others, test_check_one_stale_one_current_exit_1, test_check_all_current_exit_0, test_check_error_plus_stale_exit_2, test_stdout_two_files_in_order_no_write, test_stdout_with_error_still_prints_others | `--check ok.md bad.md nope.md bin.md` → four per-file stderr lines, rc 2 (2 beats 1). `--stdout --max-depth 2 ok.md nope.md ok.md` → both docs printed, error on stderr, rc 2. |
| AC-8 | PASS | whole suite: SlugTests, ScanTests, UpdateTextTests, CliFileTests | 95 tests OK. Gaps: no CR-only, BOM, or exotic-separator tests (see findings). |
| AC-9 | PASS | test_missing_file_exits_two, test_missing_file_still_exit_2, test_good_plus_non_utf8_exit_2_names_file | `mdtoc: nope.md: no such file` rc 2; `mdtoc: bin.md: not valid UTF-8` rc 2; directory → `mdtoc: dd: Is a directory` rc 2; read-only → `mdtoc: ok.md: Permission denied` rc 2. |

## Findings

### F1 — HIGH — AC-1 violated: CR-only files are not idempotent and get mixed EOLs
`mdtoc/toc.py:151` `eol = "\r\n" if "\r\n" in text else "\n"` only recognises CRLF; `text.splitlines(keepends=True)` (toc.py:128,163) splits on bare CR. Probe `# T\r## A\r` (no markers):
run 1 → `# T\r\n<!-- toc -->\r\n- [A](#a)\r\n<!-- /toc -->\n\n## A\r`; run 2 changes bytes again (byte 18); run 3 stable. The first run's output is also mixed CR/CRLF/LF, and `--check` immediately after run 1 would report stale. With markers already present a CR-only file is stable (probe `cr-idem`) but receives `\n` TOC lines (mixed EOL; related to latched mixed-EOL limit but a separate defect since the first-seen EOL is not even recognised). Fix direction: detect the first line terminator among `\r\n`, `\r`, `\n`.

### F2 — HIGH — AC-6 violated, document altered: UTF-8 BOM defeats H1 detection and is moved mid-file
`mdtoc/cli.py:55` `open(path, encoding="utf-8", newline="")` keeps `﻿` at the start of line 0, so `_HEADING` (toc.py:12 `^ {0,3}(#{1,6})`) no longer matches the H1. Probe output: `<!-- toc -->…<!-- /toc -->\n\n\xef\xbb\xbf# T\n## A\n`. Later runs are stable, so the damage persists. Same BOM also breaks the first-line heading in the TOC (a BOM'd `## A` first line would be dropped from the TOC).

### F3 — MEDIUM — Exotic line separators split a heading/line; TOC inserted mid-line
`mdtoc/toc.py:32,128,163` use `str.splitlines()`, which also breaks at `\x0b \x0c \x1c-\x1e \x85    `; Markdown does not. Probe `# T\x0cx\n## A\n` → `# T^L\n\n<!-- toc -->\n- [A](#a)\n<!-- /toc -->\n\nx\n## A` (heading "T\fx" cut in two; `x` pushed below the TOC). Same with `\xc2\x85`. Data is not lost but the document is structurally changed. Fix direction: split on `\r\n|\r|\n` only.

### F4 — LOW — Nested TOC indent can become an indented code block
`mdtoc/toc.py:116` `f"{'  ' * (h.level - min_level)}- [{label}](#{slug})\n"`. First heading `#### x` → `    - [x](#x)` (4 spaces); `###### z` first → 8 spaces. In CommonMark that is an indented code block, not a link list. Spec does not define nesting, so no AC violation; a relative-to-shallowest-level indent would avoid it.

### F5 — LOW — `## #` is an empty heading but is listed as `[#](#)`
`mdtoc/toc.py:12` closing-sequence group needs preceding whitespace that the text group already consumed. Probe `## #` → `- [#](#)`; CommonMark/GitHub treat it as empty (no TOC entry). `## a \#` → `[a \#](#a-)` (label keeps the backslash; GitHub renders `a #`). Cosmetic. Plain `# a #`/`## b ##  ` trimming is correct; `##`, `#` empty headings are omitted but consume a slug slot (test_empty_heading_not_rendered_but_consumes_slot).

### F6 — INFO — Test gaps backing F1-F3
No tests for CR-only, BOM, or non-LF/CR Unicode separators (`rg 'x85|BOM'` in tests: no hits).

## Seams checked, no defect
- Mode interplay: `--check`/`--stdout` mutually exclusive (rc 2); `--stdout` + multi-file prints in argument order, still prints survivors when one file errors; `--check` + `--max-depth` consistent with write mode; exit 2 takes precedence over 1.
- Marker edge states: lone open (`<!-- toc -->` only) → error, no write; close-before-open → error; duplicate pairs → error; markers only inside fences → ignored, real pair inserted; same-line `<!-- toc --> x <!-- /toc -->` replaced inline correctly.
- CRLF: preserved, idempotent, no-H1 insertion keeps CRLF. Missing final newline preserved.
- Deep nesting: H6 under `--max-depth 6` handled (only the indent issue, F4).
- Writes only happen when output differs (`cli.py:65`), so current files are not touched; failed write (read-only) reports a clean error.

## Latched limits — spec-defect judgement
None of the latched limits contradicts a spec criterion: inline-code markers paired, mixed EOL, non-atomic writes, setext, `--max-depth 1` empty TOC, duplicate FILE args, unresolved reference links — all outside AC-1..AC-9 wording. (Non-atomic write: a crash mid-`open(path,"w")` can truncate a file; it is a robustness risk but not a spec criterion.) Note the CR-only defect F1 is distinct from the "mixed EOL keeps first-seen" limit.

## README vs binary
No contradictions found for documented behavior (usage, `--check`/`--stdout` exclusivity, exit codes 0/1/2 with 2 over 1, `mdtoc: FILE: message` format, marker rules, fence skipping). README is silent on CR-only and BOM files; README:13 "running it again changes nothing" is false for CR-only input (F1) and README:38 "after the first H1" is false for BOM'd input (F2).
