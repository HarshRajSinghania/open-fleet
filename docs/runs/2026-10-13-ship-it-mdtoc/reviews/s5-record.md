# Review record — S5 (coordinator attestation, no-gh lane)

- reviewed_sha: 47ef84f2f0463c191b83182b77ddf3f0c641ec51
- origin: integrated acceptance FAIL (reviews/integrated.md findings F1-F4 against c9a6f683)
- review: task_598a9408a628 — PASS, artifact reviews/s5.md (sha256 pinned in manifest-s5.json); all four originating repros re-run byte-for-byte
- builder dispatch: task_de5d11f52acc (head 47ef84f)
- coordinator probes: independent F1-F4 battery green pre-review (CR-only idempotence x3, exotic separators, BOM placement, relative indent)
- disposition: land. LOW test gaps (BOM+CR combined, BOM-only file, late BOM, lone CR, CR-then-CRLF stability) are probed-correct and folded into the retained integrated battery instead of a fix round. New known limits recorded: first heading deeper than a later sibling still indents the first TOC item (shallowest-relative rule); double BOM hides the H1 (byte-0-only rule by design).
- reviewer build-blind (not the builder); freshness: reviewed_sha == manifest head_sha.
