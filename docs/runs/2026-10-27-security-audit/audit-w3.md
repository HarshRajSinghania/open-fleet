# Audit W3 — B3/B4 control plane, STRIDE S/T/R (regressions + new channels)

RUN: run_secaudit_20261027 · WORKER: w3 · BASE: review/2026-10-27-security-audit · FORK_POINT:
15e03dfedbf5 · T0: 2026-10-27 · SOURCE: `docs/runs/2026-10-27-security-audit/threat-model.md`
(B3/B4, Spoofing/Tampering/Repudiation) · PRIOR BASELINE: `docs/runs/2026-09-21-harden-409.md`
(CLEAN 2026-09-21) · MODE: read-only; one file written; all execution in `mktemp -d` scratch
copies (the `/tmp/opencode` dir is owned by another uid in this session and is not writable).

Mission: not a re-audit of the h409 surface. Hunt (a) regressions since 2026-09-21 and (b) channels
INTO that surface opened since by hint capture, trajectories, `search_sessions`, `gate-batch`,
`decisions --pin-ref`, inventory retention receipts.

## Toolchain-coverage question (asked directly)

`verify._Transcript.TOOLCHAIN` (verify.py:3091-3092) and `run_report.TOOLCHAIN_FILES`
(run_report.py:518-519) are **complete for every first-party module the verifier loads**, and no new
module was added that they miss. Verified by enumerating every
`importlib.util.spec_from_file_location` in the tree: verify.py loads `diff_scope` (1289),
`_verify_sig` (1931), `inventory` (2966), `ed25519` (3062), `dispatch-sign` (3104); inventory.py loads
`gitexec` (96) and `dispatch-sign` (282); nothing loads a seventh. All seven are listed in both
places, and the three `--provenance`-only path loaders (inventory, gitexec, dispatch-sign) are
covered (*closed* under h409 C4/F-5, extended correctly by #608).

The gap is **non-first-party**: see W3-01. The list is a fixed set of *files*, while the interpreter
resolves `import json` through `sys.path[0]` — which is the same directory. A sibling named after a
stdlib module is loaded by the verifier and hashed by nothing.

## Findings

| id | file:line | sev | class | untrusted input | exploit scenario | gain | why it fails | PoC |
|---|---|---|---|---|---|---|---|---|
| W3-01 | runtime/scripts/verify.py:64-75, 3091; run_report.py:518; verify-gate.sh:224 | **P0** | supply-chain / import shadowing | a committed file `runtime/scripts/<stdlib-name>.py` in the graded PR | worker commits `runtime/scripts/json.py` (proxies the stdlib, rewrites one manifest field in `loads`); gate and CI run `python3 …/verify.py`, `sys.path[0]` = `runtime/scripts`, so `import json` at verify.py:65 is the plant | the verifier judges an object that is not the file: full false GO, `exit 0`, signed transcript whose `manifest_sha256` is the *file's* real bytes, toolchain 7/7 matching the pin — nothing in run_report notices | `-I`/`-P` is nowhere (the repo already uses `python3 -I` in spawn_worker.sh:191,300,445 for the very same class of bug, and deny-hook.sh:4336 + tests/test_deny_hook.py:1999 fixed it for the hook after #592); both toolchain lists enumerate *first-party* files only, so a shadowing sibling is structurally unbindable | **PROVEN**, false GO rc=0 (below) |
| W3-02 | runtime/scripts/verify-gate.sh:141-145 | **P1** | spoofing / key path | `refs/remotes/origin/HEAD` in the checkout the gate runs in | `git symbolic-ref refs/remotes/origin/HEAD refs/heads/<worker-branch>`; `symbolic-ref --short` prints the *target's* short form, so `DEF_REF` becomes a bare **local branch**, and `PUBKEY` is built as `.orca/dispatch-pubkey@<local branch>` | on a lane claiming soundness (`ORCA_PROVENANCE=ci|mcp|sdk|dispatch`) the gate passes a ref-shaped key that a worker can move; worker commits its own pubkey there, signs its own dispatch record, and verify.py prints "signature verified against the supplied key" and exits 0 — the h409 F-2 guard ("never a working-tree pin on a sound lane") is defeated without touching the working tree | the guard at :146-151 tests only *whether* the pin is a tree file, and the ref it prefers is derived from a mutable local symref; `verify.read_source` (296-302) accepts any ref, so nothing re-classes it; docs/verify-gate.md:128 promises `refs/remotes/origin/HEAD` | **PROVEN**, rc=0 (below). Reach: every non-CI clone (the MCP/SDK/dispatch surface on the worker's own machine). In an `actions/checkout` tree the ref is usually absent, so CI is hit only if a step creates it |
| W3-03 | runtime/scripts/verify.py:2980, 3250, 296-302, 3319, 3034 | P2 | spoofing | `--dispatch-pubkey` / `--retention-pubkey` / `--dispatch-record` given as a **bare path** | `ORCA_DISPATCH_PUBKEY=.orca/dispatch-pubkey` (the value docs/verify-gate.md:129 tells operators to avoid) on a sound lane; worker swaps the pin and self-signs both the record and the receipt/inventory chain | both "trusted key" legs collapse to a worker-written file while the verdict keeps saying the signature verified "against the supplied key" | the two forms (`path` vs `path@ref`) are indistinguishable in the transcript and the NOTE: no check, no marker, no `--strict-key`; `read_source` intentionally reads a bare path from the tree; the rule lives only in prose | argued from code + the same PoC tree as W3-02 with the `@ref` stripped |
| W3-04 | runtime/scripts/verify.py:3030-3033 | P2 | repudiation | `provenance.retention` / the receipt's `inventory` | receipt and signed inventory are genuine, but the manifest's bytes are pinned by an entry in the inventory that names a *different path*; the check compares digests only | a manifest is "bound" to a receipt by content while the record's path story is wrong; a byte-copied manifest from another file/unit passes as the pinned artifact | `for _idx, _path, pinned, _shape in entries` discards `_path`; the NOTE (3034-3042) names the receipt, the unit and the inventory, never the matched entry — so an auditor cannot see which path the receipt claims to cover | argued from code |
| W3-05 | runtime/scripts/run_report.py:774, 807-820 (813), 838-842 | P2 | tampering / policy | `runtime/evidence-manifest.md` **at the graded (worker) rev** | PR deletes its own mission from the `**Mutation units** (...)` list (or rewrites the file) in the same commit it is graded on; `_mutation_missions` reads at `rev`, the PR's own commit | the `unit_class != mutation` refusal (775-778) evaporates — a mutation-class mission is graded as `report-only`, shedding the negative control, intent packet, lighting legality and reviewer_mode | the policy is read from the tree the graded party writes; the only fallback (838-842) is the working tree too; nothing prefers the grading base the way `key_rev` (603-620, h409 O-3.3) does for the key | argued from code |
| W3-06 | runtime/scripts/gate-batch.py:40, 124-128, 244-248, 183-188; release_check.py:408-412 | P2 | spoofing / repudiation | `gate-batch.json` + `--source` | worker/agent writes `"status": "answered"`, `"answer": …`, `"source": "human:Ravindra"` (or runs `answer --source human:anyone`) | the run-close "every owed blocker" predicate (`list --status owed --blocking <unit>`, the release gate's own check) is satisfied by a record anyone can type; a reviewer looking for humanity finds a `human:` string | `source` is shape-validated only (`^human:\S+$`, 40/125/245); the store is a plain JSON file with no signature, no author binding, no id/date/resolution cross-check against any external record; `render --check` (574-577) is run by tests only, so the human-readable `.md` view can silently disagree with the store | argued from code |
| W3-07 | runtime/scripts/decisions.py:305-312, 315-349 (334 vs 346); scripts/_trajectories.py:1172-1173 | P2 | spoofing (anchor) | the `--pin-ref` argument | (a) no `--pin-ref` → `grant_pubkey` returns the **working-tree** pin (305-306); (b) `--pin-ref main` names a *local branch* the same repo can `update-ref` (the harness itself does: `_trajectories.py:1196`); (c) rev-parse and `cat-file` are two calls, so the ref can move between them | the #635 protection ("the pin at the ref, not the one the change swapped in") degrades to "the pin at a ref the change can move", or to no protection at all on the default | nothing requires the ref to be remote-tracking, and `_pin_at_ref` re-resolves `ref` in `ls-tree`/`cat-file` (346-348) after validating `ref^{commit}` (334) | argued from code |
| W3-08 | runtime/scripts/verify-gate.sh:138-153; verify.py:3235-3237 | P2 | availability (fail-closed) | checkout shape | on a sound lane in a fresh `actions/checkout` tree there is no `origin/HEAD` and usually no `origin/<BASE>` ref; the working-tree pin is refused by design, so `PUBKEY` stays empty while `ORCA_DISPATCH_RECORD` is set | every gate run BLOCKS with "half-configured" once a dispatch record is dispatched, on the surface that is supposed to be sound | no discovery path is left that is both ref-backed and present in a CI checkout (a `github.event.pull_request.base.sha`-shaped ref, `refs/remotes/pull/*`, or the record's own pinned base) | argued from code |
| W3-09 | repo posture: no `.orca/dispatch-pubkey` anywhere (all refs) | P3 | posture | — | the enforcement switch is dormant: every `run_report` leg here takes the unsigned grandfather lane (`envelope_key` → pub None, no transcript → `[]`, run_report.py:698-699) | nothing signed is checked in this repo's own runs, so W3-01/W3-03-class defects are unobservable through the transcript path | documented (docs/verify-gate.md:120) but worth stating at audit time: the controls audited here are not exercised in production | `git log --all -- .orca/` empty; docs/verify-gate.md:120 |
| W3-10 | runtime/scripts/verify.py:798-804 | P3 | integrity (down-only) | `gitleaks` on PATH | worker plants a `gitleaks` that always exits 0 | the *gitleaks-only* half of redaction disappears (the built-in floor keeps working), and the NOTE frames a worker-writable authority as merely additive | custody is classed and NOTE'd but a worker-writable gitleaks is still consulted on every lane, including sound ones | argued from code; h409 R2 recorded the class |
| W3-11 | runtime/scripts/verify.py:3133-3140, 3651 | P3 | TOCTOU (record vs use) | the executed negative control | `--transcript-out` (no key) after `--execute-nc`: the control runs worker code, then the toolchain is hashed, so the recorded hashes are post-control while every check ran with the pre-control modules | a mid-run sibling rewrite is recorded as if it were the verifier, never detected | `_Transcript.build` re-reads siblings after `verify()` returns; `sign-transcript` re-hashes *its* siblings, which are the same post-control bytes; only the pin comparison in run_report is independent | argued from code |

Dropped after checking (kept out to avoid noise): `diff.external` missing from `_Authority.git_env`
(vs gitleaks' `HARDENED`) — **not** a hole: every content diff in verify.py passes
`--no-ext-diff` (2008, 2165) and tested `git diff --name-only` does not invoke an external diff at
all, so the path lists W3-05 depends on are unaffected. `check_dispatch_provenance`'s double read of
the record (3429-3441 then 3453) is safe: adoption requires an all-NOTE verdict and the second pass
re-verifies signature plus the adopted values against the freshly read record.

## PoC — W3-01 (P0): sibling `json.py` turns a RED verdict GREEN

Scratch: `mktemp -d`; `verify.py` and its siblings copied to `$R/rs`, a two-commit repo with a
docs-only range under `$R/repo`, `runtime/scripts/json.py` dropped beside the copied verifier.
Manifest claims `pr.reviewed_sha = base_sha` while `head_sha` has moved (the stale-review invariant).

```
python3 $R/rs/verify.py --manifest manifest.json --contract-source contract.md@$BASE \
  --contract-digest $DIG --unit-class report-only                      # control, no plant
  FAIL: stale review: reviewed_sha '0118…' != head_sha 'f6da…';  exit 2

# plant: a sibling json.py that proxies the stdlib and rewrites ONE manifest field
python3 $R/rs/verify.py --manifest manifest.json --contract-source contract.md@$BASE \
  --contract-digest $DIG --unit-class report-only --transcript-out t.json
  verify: OK — all required checks passed;                        exit 0
sha256sum manifest.json   → c29fb6da…   (still the stale bytes)
t.json manifest_sha256    → c29fb6da…   (the verdict signs the stale file it never judged)
t.json toolchain.files    → 7 keys, all at the pin; `json.py` absent
# control direction: `mv json.py away` → exit 2 again on the same bytes
```

A `hashlib.py` variant (constant `sha256`) additionally makes `manifest_sha256` and any toolchain
hash constant on both sides — one file, and `run_report`'s re-derivation agrees with the forgery.

## PoC — W3-02 (P1): the "reviewed ref" the gate resolves can be a local branch

```
git symbolic-ref refs/remotes/origin/HEAD refs/heads/workerbranch
git symbolic-ref --quiet --short refs/remotes/origin/HEAD   → workerbranch   (not origin/HEAD)
# the gate's own block then builds PUBKEY=.orca/dispatch-pubkey@workerbranch
python3 $R/rs/verify.py … --dispatch-record rec.json \
  --dispatch-pubkey ".orca/dispatch-pubkey@workerbranch" --provenance ci --repo acme/x
  NOTE: dispatch record signature verified against the supplied key (#135) …
  verify: OK — all required checks passed                            exit 0
# the record is signed by the worker's own key, committed only on the worker's branch:
git show workerbranch:.orca/dispatch-pubkey == cat $R/worker.seed.pub
# the same record under the coordinator-owned ref is refused today:
… --dispatch-pubkey ".orca/dispatch-pubkey@refs/remotes/origin/main"
  FAIL: dispatch pubkey unreadable (… exists on disk, but not in 'refs/remotes/origin/main')
```

Fix shape: `symbolic-ref refs/remotes/origin/HEAD` (full target), require it to start with
`refs/remotes/`, write `PUBKEY=".orca/dispatch-pubkey@$DEF_REF"` with the full ref.

## Cleared areas (no finding; h409 cites where it closed the class)

- **Fail-open exits.** `verify-gate.sh:239-243` captures the real rc and blocks on any non-zero;
  `verify.py:3660` returns 2 on any fatal and 1 when a requested transcript is missing;
  `inventory.py:779-789` separates 2 (could not run) from 1 (mismatch) from 0. Unchanged by later
  work — h409 closed the F-1/G-1 class and `a7d26a9a`. Checked the two new blocks
  (verify-gate.sh:215-238 timeout, 204-210 lane NOTE): both fail closed.
- **Signature over different bytes than consumed.** `canonical_subset` (dispatch-sign.py:201-215)
  is the single form; verify re-derives through the signer itself (`_canonical_dispatch`, 3068-3074)
  and run_report through `canonical_transcript` (728-729); `sig_b64` decodes with `validate=True`
  everywhere (verify 3256, run_report 724, inventory 352) — h409 O-2.2, no regression.
- **Unsigned / unsigned-envelope paths.** Dispatch: neither-record-nor-key → `[]`, one of the two →
  fatal (3233-3237). Transcript: key present + no envelope → refused (run_report 718-722);
  inventory: same, symmetric (649-680) — h409 #281/#386, no regression. The grandfather lane is a
  deliberate door (W3-05/W3-09 note its edges, not its existence).
- **Replayable envelope.** Dispatch record binds `manifest_id` plus every used field, both lane
  waivers, the control's inputs and `base_sha` (3263-3318); retention receipt binds `unit` +
  `source_revision` and the inventory digest (inventory 466-516). Nothing replayable across units.
- **`reviewed_sha` from the caller.** Freshness compares it to `head_sha` and the `_wtree_bound`
  escape recomputes BOTH trees locally (`_tree`, 601-619), so a typed 40-hex cannot pass — h409
  `a7d26a9a` line, no regression; `review_ok` re-derives the veto scope from fetched reviews.
- **`reviewed_sha` / SHA / `pr.number` injection.** Option-shaped SHAs refused before git (577-581);
  `pr.number` must be a positive int (1154-1160); refs and paths reject a leading `-` (290-291).
- **Key custody at use.** `dispatch-sign._seed` (300-344) re-asserts 0600 + not-in-an-unignored-tree
  and names the class on stderr; `_Transcript.seed` reuses it; `--transcript-key` refuses
  `--execute-nc` in the same process (3599-3607) — h409 F-4/F-6, no regression.
- **Toolchain hash vs pin.** run_report refuses an absent file, an unreadable blob, an empty tree and
  the built-in empty tree (479-504, 782-800); `sign-transcript` re-hashes before signing — h409 C4/
  F-5, fully intact and now covering the #608 arrivals.
- **Authorities pinned before the control.** `_Authority.resolve` at 3624-3627, `ensure` at 3406;
  git/gh/gitleaks absolute + custody-probed with every hop and ownership (`_nodes` 845-866,
  `_worker_controls` 869-886, `classify` 889-915) — h409 R1/C-1/C-2/bin-symlink, no regression.
- **Path escapes from the graded party.** `_resolve` (250-279) refuses absolute and `..`; `..`-free
  absolute paths only; receipts and inventory documents read through it (2995); `read_source`'s
  `path@ref` spelling is normalized for git (h409 F-3), no regression.
- **Repo-config execution on git legs.** `git_env` closes fsmonitor, hooks, replace refs and grafts;
  `driver_blanks` neutralises whole filter/diff/merge drivers, fail-closed on an unreadable config
  (986-1045) — #629/#649, no regression; `hint_provenance.git` uses the same hardened path (#605).
- **Retention receipt chain.** Signature under a supplied key over a closed v1 shape, signer-id
  identity, unit and revision equality, the inventory's own signature re-derived from its entries,
  then a digest equality — never a key from inside the receipt (inventory 424-516, verify
  2966-3033). The chain holds; W3-04 and W3-03 are its edges.
- **`--pin-ref` reading.** Refused when option-shaped (320-321), unresolvable (334-335), and a pin
  that exists only in the tree where the ref has none is could-not-run (308-311) — the #546/#635
  fixes hold; W3-07 is the residual anchor question.

## Verdict

1 P0, 1 P1, 6 P2, 3 P3. The P0 is a property of the interpreter invocation, not of any check: the
verifier's own directory precedes the stdlib on `sys.path` and the toolchain list binds files, not
loader behaviour. It is cheap to close (`python3 -I` at verify-gate.sh:224, in the CI steps, and in
`bind_check`/`run_report`/`inventory` invocations) and should land with a regression test that plants
`json.py` and `hashlib.py`. The P1 is the same shape one level up: an authority the gate *resolves*
is chosen by a ref the graded party can write.
