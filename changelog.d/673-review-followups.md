- **The HTML-link check can no longer be talked out of a real link** (#673). In changelog
  fragments and run-index cells, a tag is skipped only inside a backslash escape or a code span
  that opens and closes on one line. It is skipped only before any line that may open a raw
  HTML block, which is recognised past list and quote marks under the CommonMark and GFM rules;
  from that line on, backticks are text. A code span that wraps a line, and a fenced block, are
  read as text. Fragments allow no blank line and run-index cells no newline, so neither is
  needed, and reading them as text can only reveal a link. An inline tag at the start of a line
  no longer turns a code-span example into a refused link.
- **A retried harness teardown keeps the first attempt's diagnostics** (#673). The receipt's
  `destroyed.errors` and `destroyed.nonzero` gather both attempts instead of only the last.
