- **The HTML-link check reads raw HTML blocks and fences as a renderer does** (#673). Each
  fragment and run-index cell is split into raw HTML blocks, fenced code blocks and inline
  Markdown, and the code-span rule applies only to inline Markdown. A fence mark inside a
  `<div>` no longer hides a real link. An inline tag at the start of a line no longer turns a
  code-span example into a refused link. A `<pre>` block that runs past a blank line is still
  read as HTML.
- **A retried harness teardown keeps the first attempt's diagnostics** (#673). The receipt's
  `destroyed.errors` and `destroyed.nonzero` gather both attempts instead of only the last.
