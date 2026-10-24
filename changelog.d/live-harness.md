- **Paid live arms run only in a disposable container harness** (the harness PR #668 asked for).
  `scripts/live_container.py build` builds a pinned image: the base by digest, git, and Claude
  Code 2.1.304 by its official installer as a non-root user. `run` starts ONE arm (`wip_curve`,
  `ablation`, `hint_replay`, `trajectories` or `first_run`) in a fresh container beside a
  credential broker in a container of its own. Both run non-root with `--rm`, pids, memory and
  CPU limits, no capability and no host namespace, and see a read-only export of a clean `HEAD`.
  The token is mounted read-only into the broker's container alone (`scripts/live_broker.py`).
  The arm's container shares only the broker's network namespace and holds no credential. Its
  `claude` sends every model call to the broker, which puts the token in place of a placeholder,
  forwards only the Messages API, and refuses any call whose worst case would pass `--cap-usd`.
  It forwards only what it can price: a priced model, the fields it knows, the client's own tools,
  and inline content its bytes bound. It refuses an image or document by URL or file id, a PDF,
  an advisor or server-side tool, a service tier and an unpriced geography, and it prices US
  inference at its 1.1x premium. The arm starts only once the broker answers.
  The broker settles each call as the API bills it and writes its ledger beside the receipt, out
  of the arm's reach. Every output flag of an arm must name a path under `/results`, and an arm
  whose ledger defaults to a temp dir (`first_run`'s workdir included) must name one. A token file
  inside the results or the checkout is refused. One launch runs at a time, under a lock. At
  its wall-clock limit the launcher kills and removes both containers and verifies by the
  launch's nonce that neither exists. A teardown step that fails or times out is recorded, and
  the receipt is always written. The output reaches a 0600 log through a redactor, so no byte of
  the token is written. A JSON receipt records the image, commit, arm, nonce, times, both
  container ids, the broker's spend, the exit status and the verified destroy. Inside,
  `containment.live_disabled()` lifts only with a container marker, the launcher's attestation
  nonce matching the container's hostname, and the strong probe passing. On every other host
  each live path refuses as before. This guards against accidents, not against an operator who
  fakes a container. The operator's page is the [live harness guide](../docs/guides/live-harness.md).
- **The WIP-curve runner meets the harness's three entry criteria** (Codex review of PR #668 at
  `9db89fbe3c`). An uncontained merge gate stops the drain before any bounce or retry, and no
  oracle or gate starts after any failed containment. Recovery and the check before every run
  read the synced gate journal on their own. A report's binding oracle re-run journals and sweeps
  its markers, and it keeps the directory when containment fails, and the next run refuses
  while a marker survives. A failed containment now halts `orphan-alive` over any earlier halt,
  such as a model mismatch, so every guard that asks for it stops (Codex at `47e0616eac`).
- **The changelog and run-index HTML-link check reads complete tags only** (Codex at
  `54fe725bee`). An unclosed `x<a` with `href=value` lines later, `data-href`, and a tag inside a
  code span are no longer refused. A complete tag with an `href` or `src` attribute still is, and
  a code span no longer hides one across a block, such as the next list item (Codex at
  `47e0616eac`).
