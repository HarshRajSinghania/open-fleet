# Integrated acceptance re-review (round 2) — mdtoc

**VERDICT: PASS** at head `046d1f8d0ff63b7193bc06e0c373ba60d9e06849` (`git rev-parse HEAD`; worktree clean, no worktree file modified; probes ran from the scratchpad with PYTHONDONTWRITEBYTECODE=1).

`python3 -m unittest` (Python 3.12.3, from repo root): `Ran 110 tests ... OK`. Round 1 had 95; S5 added tests/test_seams.py (15 tests). Stdlib only. No justfile/pyproject exists, so there is no repo lint command to run. The ">= 3.11" claim in README is unverified: no 3.11 interpreter is installed, and the code uses nothing newer than 3.8.

## 1. F1-F4 repros (byte-for-byte from round 1, run via `python3 -m mdtoc`)

| Finding | Repro | Result at this head |
|---|---|---|
| F1 CR-only idempotence | `printf '# T\r## A\r'`, run, copy, run again, `cmp` | **FIXED.** Run 1 gives `# T\r\r<!-- toc -->\r- [A](#a)\r<!-- /toc -->\r\r## A\r`, all CR, no LF. Run 2 is `cmp`-identical and `--check` rc=0. With markers already present (`<!-- toc -->\r<!-- /toc -->\r# T\r## A\r`) the TOC lines are CR and a second run is identical. |
| F2 BOM | `\xef\xbb\xbf# T\n## A\n` | **FIXED.** BOM stays at byte 0, TOC lands after the H1 (`357 273 277 # T \n \n <!-- toc -->...`), second run identical, `--check` rc=0. A BOM file with markers and CRLF: `--check` reports stale rc=1, a write fills the TOC, and `--check` then gives rc=0. |
| F3 exotic separators | `# T\x0cx\n## A\n` and `# T\xc2\x85x\n## A\n` | **FIXED.** Both headings stay one line (`# T\fx`, `# T\x85x`) and the TOC goes after that line. |
| F4 indent | `#### x`; `###### z` as the first heading | **FIXED.** Both render at column 0 (`- [x](#x)`, `- [z](#z)`) with the default depth and with `--max-depth 6`. |

## 2. Traceability matrix at 046d1f8

| AC | Verdict | Guarding tests | Probe evidence |
|---|---|---|---|
| AC-1 idempotent | PASS (F1 closed) | test_idempotent_with_markers, test_twice_is_byte_identical, test_inserted_markers_make_second_run_in_place, test_crlf_preserved, test_crlf_file_stays_crlf, test_insert_is_cr_only_and_idempotent, test_markers_cr_only | LF, CRLF, CR-only, BOM, BOM+CR, BOM+markers+CRLF, `\r\r\n`, lone-CR/LF mixes, a one-line file and an empty file: every `update_text(update_text(x))` is a fixpoint. |
| AC-2 slugs | PASS | test_duplicates_get_suffixes_in_order, test_generated_suffix_checked_against_taken_slugs, test_duplicate_numbering_counts_excluded_levels, test_duplicate_suffix_counts_depth_filtered_headings, test_nested_list_with_duplicate_slugs | Unchanged by S5 (toc.py slug code untouched: `git diff --stat c9a6f68 HEAD` shows only toc.py and test_seams.py). |
| AC-3 fences | PASS | test_backtick_fence_excluded, test_tilde_fence_excluded, test_other_fence_type_does_not_close, test_unclosed_fence_swallows_rest, test_fence_on_list_item_line_excluded, test_h1_in_fence_is_not_the_anchor, test_fenced_marker_example_is_untouched | A fenced marker under BOM+CRLF is ignored and the real pair is filled. A `\x0c` after the fence opener does not break fence handling. |
| AC-4 check/stdout | PASS | test_check_missing_toc_exits_1_without_writing, test_check_stale_exits_1_without_writing, test_check_current_exits_0, test_check_respects_max_depth, test_stdout_never_writes, test_check_with_stdout_is_argparse_error, test_stdout_prints_updated_document_and_does_not_write | `--check` is 1 on a stale BOM file and 0 after a write, for LF, CRLF, CR and BOM. `--stdout` on a BOM+CR file prints the BOM first, all CR. |
| AC-5 depth | PASS | test_default_depth_h2_to_h4, test_max_depth_limits_levels, test_max_depth_above_default_includes_deeper, test_max_depth_out_of_range_is_argparse_error, test_max_depth_bounds_accepted, test_max_depth_zero_is_argument_error | Unchanged. |
| AC-6 placement | PASS (F2 closed) | test_no_markers_inserts_after_first_h1, test_no_markers_no_h1_inserts_at_top, test_h1_without_trailing_newline, test_h1_only_with_trailing_newline, test_bom_with_h1, test_bom_without_h1_inserts_after_bom, test_bom_first_line_h2_in_toc, test_bom_only_toc_region_changes, test_bom_scan_and_render | BOM, no H1: the BOM stays at byte 0 and the TOC follows. BOM with a `## A` on line 1: A is listed. A BOM-only file gets an empty marker pair after the BOM. |
| AC-7 multi-file | PASS | test_two_good_files_both_updated, test_good_plus_missing_still_updates_good_exit_2, test_good_plus_non_utf8_exit_2_names_file, test_illegal_marker_state_does_not_stop_others, test_check_one_stale_one_current_exit_1, test_check_all_current_exit_0, test_check_error_plus_stale_exit_2, test_stdout_two_files_in_order_no_write, test_stdout_with_error_still_prints_others | cli.py unchanged since round 1. |
| AC-8 suite | PASS | whole suite, 110 tests: SlugTests, ScanTests, UpdateTextTests, CliFileTests, plus the new seam tests | `python3 -m unittest` OK. The round-1 gap (no CR/BOM/separator tests) is closed by tests/test_seams.py. |
| AC-9 errors | PASS | test_missing_file_exits_two, test_missing_file_still_exit_2, test_good_plus_non_utf8_exit_2_names_file | cli.py unchanged; round-1 evidence stands. |

## 3. New-seam hunt (all clear, no defect)

- **Marker offsets with CR/BOM.** `update_text` strips the BOM and re-prepends it before any offset math, so `_marker_region` never sees it. `_lines` (the `_LINE` regex) and `_EOL.split` both break only on CRLF, CR and LF, so the line indexes agree. `_marker_region` offsets are correct for CR-only, CRLF, `\r\r\n`, lone-CR/LF mixes, fenced markers before the real pair, and markers on the same line as text (`x\r<!-- toc --> old <!-- /toc --> y` is replaced inline, `y` is kept).
- **BOM + markers + CR combined.** `﻿<!-- toc -->\r<!-- /toc -->\r# T\r## A\r` is filled in place with CR lines and is idempotent.
- **First terminator when line 1 has none.** A one-line file with no terminator (`## A`, `# T`) falls back to `\n`. An H1 at EOF without a terminator (`# T\r## A`) uses the first terminator seen. Inserted lines take the first-seen terminator (the latched mixed-EOL limit): `x\r# T\n## A\n` gets CR TOC lines and `# T\n\r<!-- toc -->`. That is mixed but not corrupting, and re-running is stable.
- **Relative indent versus depth filtering.** `render_toc` takes `base` from the shallowest heading that survives the depth filter, i.e. after filtering (`items` is filtered before `min`). On `## A / #### x / ### y / ##### z`, `--max-depth 3` gives `- [A]` and `  - [y]`, and `--max-depth 2` gives `- [A]` only. A document whose first included heading is deeper than a later one indents that first item (`#### x` before `## A` gives `    - [x](#x)`). This is exactly the latched "first heading deeper than a later sibling" limit, so I did not re-derive it. It is cosmetic and not a spec criterion.
- **Exotic separators.** U+2028 and `\x0c` inside a heading or fence line are kept as part of the line, and the idempotence probes pass.
- **README vs behavior.** README:13 "running it again changes nothing" and README:38 "after the first H1" now match behavior for LF, CRLF, CR-only and BOM input. README is silent on EOL/BOM; there is no contradiction.

## 4. Latched limits
None contradicts AC-1..AC-9. Non-atomic writes, setext headings, `--max-depth 1` giving an empty TOC, duplicate FILE args, unresolved reference links, the sentinel collision, the double BOM and `## #` as `[#](#)` are all outside the criteria wording. Mixed-EOL insertion and the first-item-deeper indent are cosmetic and stable on re-run. None is a spec defect.

## 5. Not verified
Python 3.11 was not run (not installed); the README's `>= 3.11` claim is checked by reading only. Windows stdout newline translation under `--stdout` was not tested (Linux only).
