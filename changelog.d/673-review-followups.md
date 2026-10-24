- **The HTML-link check no longer misses a link a renderer shows** (#673). In changelog
  fragments and run-index cells, a tag is skipped only inside a backslash escape or a code span
  that closes on the line it opens. It is skipped only before any point where renderers may
  disagree about what follows: a line that may open raw HTML (past list and quote marks), a `<`
  that may begin raw HTML or an autolink and is not a plain one-line tag, a `[` that may begin
  a link, a bare URL, or a backtick run left open on its line. From there on, backticks and
  escapes are text, and a link tag is read as loosely as a browser reads raw HTML. A
  differential fuzz against Pandoc's CommonMark and GFM readers found 15 misses in 3,000
  documents on the previous check, and none in 39,000 on this one. An inline tag at the start of a line no longer turns a
  code-span example into a refused link.
- **A retried harness teardown keeps the first attempt's diagnostics** (#673). The receipt's
  `destroyed.errors` and `destroyed.nonzero` gather both attempts instead of only the last.
