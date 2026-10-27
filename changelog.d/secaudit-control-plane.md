- **The control plane no longer imports a graded tree's stdlib-named siblings, and its trust
  anchors are refs the graded change cannot move** (2026-10-27 security audit, W3-01 to W3-11
  except W3-07). A committed `runtime/scripts/json.py` used to be the verifier's `json` and turned
  a stale-review RED into GREEN (W3-01, P0): every control-plane entry point now drops its own
  directory from `sys.path` before any other import, `verify-gate.sh` runs the verifier with `-I`,
  and `tests/test_entrypoint_guard.py` plants every stdlib module name beside all 25 of them. The
  gate reads `.orca/dispatch-pubkey` only at `origin/HEAD`'s full remote-tracking target (W3-02,
  P1) and, in a fresh CI checkout, at the pull request's base commit (W3-08); on a `--provenance`
  lane `verify.py` refuses a bare-path or local-ref trust key and every NOTE says where the key
  came from (W3-03). A retention receipt binds the manifest's path as well as its digest (W3-04);
  `run_report.py` reads the mutation-unit list where it reads the key, not at the graded commit
  (W3-05); once `.orca/human-grant-pubkey` is pinned a gate-batch answer needs the human's
  signature or it stays owed, a sound lane must name `--pin-ref`, and the release gate runs
  `render --check` (W3-06). A worker-writable `gitleaks` is not run on a sound lane (W3-10), and a
  toolchain file that changes while the verifier runs fails the run (W3-11). Two items wait on a
  human: tightening `decisions.py --pin-ref` (W3-07) changes two existing assertions and needs a
  one-way floor-guard waiver first, and committing the dispatch pubkey that switches enforcement
  on (W3-09, see
  [the verify gate](../docs/verify-gate.md#signed-dispatch--what-it-binds-and-where-the-key-comes-from-135)).
