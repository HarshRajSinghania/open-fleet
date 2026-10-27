- **The control plane no longer imports a graded tree's stdlib-named siblings, and on a sound
  lane it reads trust keys only at a commit id or the coordinator's own remote-tracking refs**
  (2026-10-27 security audit, W3-01 to W3-11 except W3-07). A committed `runtime/scripts/json.py`
  used to be the verifier's `json` and turned a stale-review RED into GREEN (W3-01, P0): every
  control-plane entry point now drops its own directory from `sys.path` before any other import,
  `verify-gate.sh` runs the verifier with `-I`, and `tests/test_entrypoint_guard.py` plants every
  stdlib module name beside all 25 of them. The gate reads `.orca/dispatch-pubkey` only where a
  ref's final target is remote-tracking — `origin/HEAD`'s (W3-02, P1) or `origin/<base>`'s — and,
  in a fresh CI checkout, at the pull request's base commit (W3-08); on a `--provenance` lane
  `verify.py` refuses a bare-path, local-ref or symbolic-to-local trust key, reads it at the one
  commit its ref resolves to, and every NOTE says where the key came from (W3-03). A
  remote-tracking ref is what the clone's own fetch wrote — the coordinator's or the CI runner's
  on a sound lane; on a worker's machine the in-session lane stays advisory. A retention receipt
  binds the manifest's path as well as its digest (W3-04); `run_report.py` reads the mutation-unit
  list where it reads the key, not at the graded commit (W3-05); once `.orca/human-grant-pubkey`
  is pinned a gate-batch answer needs the human's signature or it stays owed, a sound lane must
  name `--pin-ref`, and the release gate reads the key at `refs/remotes/origin/main` and runs
  `render --check` (W3-06). A worker-writable `gitleaks` is not run on any lane claiming soundness
  (W3-10), and a toolchain file that changes while the verifier runs fails the run (W3-11). Two
  items wait on a human: tightening `decisions.py --pin-ref` (W3-07) changes two existing
  assertions and needs a one-way floor-guard waiver first, and committing the dispatch pubkey that
  switches enforcement on (W3-09, see
  [the verify gate](../docs/verify-gate.md#signed-dispatch--what-it-binds-and-where-the-key-comes-from-135)).
