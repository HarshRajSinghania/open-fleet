# Verify V3 — egress, bundle, CI (B2/B3/B6)
RUN: run_secaudit_20261027 · VERIFIER: v3 · BASE: 15e03dfe · MODE: read-only, scratch under mktemp -d

Re-derived from code at `15e03dfedbf5a1cfe30bf7813edafb8445711f7b` (clean tree apart from this
run's untracked directory). Read first: `threat-model.md` (B2/B3/B6, acceptance bar 100-104),
`runtime/scripts/egress.py` docstring 16-42, `runtime/conductor-close.md:48-51`. Every claim was
executed unless marked otherwise; all scratch lived under `mktemp -d` (`/tmp/tmp.szjNCPF97G`,
`/tmp/tmp.bVVxV3n4KQ`, `/tmp/tmp.EhwsNVp9Nv`). No tracked file was modified except this one.
Reproducing the urllib behaviour needed only two loopback `http.server` sockets; the one external
read (GitHub's event docs) succeeded, so nothing is PARKED.

## Verdicts

| id | claim | verdict | observed |
|---|---|---|---|
| C1 | `egress.py` `id`/`prev` leave the ledger's last line unhased; `verify` still says intact | **CONFIRMED** | forged key on last line → `verify` rc 0 "chain intact"; forged line then locked in by the next `write`; and the far stronger case — a never-anchored line rewritten field-by-field with a recomputed `id` — still passes `verify --expect-ancestor <last close's head>`, rc 0, and the close then anchors the forgery |
| C2 | `external-ci-monitor.py` `add_header` re-sends the bearer across a redirect; sibling uses `add_unredirected_header`; `read()` unbounded | **DOWNGRADED** (P1→P2) | executed on a loopback redirect pair: `add_header` → token arrives at the second origin, `add_unredirected_header` → `auth: null`; urllib's `redirect_request` copies `req.headers` only. Mechanism fully confirmed; grade lowered because TLS is verified by default and the path is opt-in (`--transport rest`) |
| C3 | marker inside the tree, `_claim` checks only *parents*, marker itself never checked → forged JSON deletes arbitrary files in `--out` | **CONFIRMED** | real marker from the documented build, two forged filenames, both foreign files gone, rc 0, nothing printed. Also confirmed the sibling half: a symlinked marker is followed and its target rewritten |
| C4 | PR-supplied workflow YAML governs the required contexts; no code-owner review | **CONFIRMED** | `pull_request_target` absent (0 hits), every `uses:` 40-hex, 0 `${{ }}` inside any `run:` — the classic holes are closed, which leaves the YAML trust the whole exposure; GitHub docs: the `pull_request` event "runs in the context of the merge commit… as the `pull_request` event does" vs `pull_request_target`'s default-branch context; `docs/ops.md:50-51` "No approving review is required" |

## C1 — CONFIRMED

Claim: `id` hashes only `FIELDS` (`egress.py:96`, `record_id` 136-143) and `prev` only the previous
line (`:208`), and `verify` compares exactly those two things (`:266-273`), so an extra key inside
the braces of the **last** line is hashed by nothing.

- Command (verbatim)

```
E=…/runtime/scripts/egress.py; L=$S/egress.jsonl
python3 $E --ledger $L verify                     # empty chain
python3 $E --ledger $L write --sink pr-open --host github.com --payload-class pr-body --consent grant:pr-open-on-base --bytes 12
python3 $E --ledger $L write --sink issue-close --host github.com --payload-class issue-comment --consent grant:pr-open-on-base --bytes 3
python3 - "$L" <<'PY'                              # append a key INSIDE the braces of line 2
import json,sys
p=sys.argv[1]; lines=open(p).read().split("\n"); r=json.loads(lines[-2])
r2=dict(r); r2["note"]="FORGED-IN-AFTER-THE-FACT"
lines[-2]=json.dumps(r2,separators=(",",":")); open(p,"w").write("\n".join(lines))
PY
python3 $E --ledger $L verify
```

- Observed (verbatim, rc)

```
egress: chain intact, 0 receipt(s) in /tmp/tmp.szjNCPF97G/egress.jsonl — head (empty) (UNANCHORED: …)
rc=0
{"id":"2e6f49f0…b88f0", … ,"prev":"c983a84f…40d","note":"FORGED-IN-AFTER-THE-FACT"}
egress: chain intact, 2 receipt(s) in /tmp/tmp.szjNCPF97G/egress.jsonl — head c8f6db2e…6406 (UNANCHORED: …)
rc=0
```

Locked in, and still invisible — one more `write`, then `verify` (rc 0) and `grants` (rc 0,
the forged key appears nowhere in the output). Editing the now-mid-chain forged value alone does
fail — `prev` covers the line's *bytes*: `TAMPER at …:3 — prev does not match the previous raw line`, rc 3.

Two contrasts, both from the same ledger: `verify --expect-ancestor <pre-forgery head>` and
`verify --expect-head <pre-forgery head>` both return rc 3 — the anchor catches a forgery of an
**already-anchored** line, so the hole is not "the anchor is useless". Which leaves the real
window, exercised on a fresh ledger (`close2.jsonl`): anchor at close N, `write` a second
receipt, rewrite its `host` `evil.example`→`github.com` and `bytes` 2→4 with `id` recomputed —
the realistic shape, since a forger recomputes:

```
egress: chain intact, anchored head present, 2 receipt(s) in …/close2.jsonl — head ac54c6df…472d
rc=0
```

and `head` then prints the forged digest, so the next close anchors it. Every receipt written since
the last close is therefore fully rewritable, `host` included, and `verify` reports health even in its
strongest anchored mode. `id` names "the line and its position in the chain" (docstring 33-35) only
for the fields the writer chose to put in `FIELDS`; nothing covers the current line's raw bytes.
Empty-chain contrast: a missing ledger verifies clean at rc 0 (`0 receipt(s)`, head `(empty)`) — an
anchored `(empty)` is the only thing that distinguishes it from a real chain.

- Pinned by a test? No. `tests/test_egress.py:280-286` edits a **middle** line; `:288-295` edits a
  field and relies on the un-recomputed `id`; `:297-307` recomputes `id` on a **single-line** ledger
  and only the line-break rule catches it — i.e. that test's record would otherwise pass. No test
  mentions an unknown key or a last-line rewrite; `grep -n "extra" tests/test_egress.py` hits only
  the CLI helper parameter.
- Severity: **P1**, the audit's grade holds. Not because a merge decision reads the ledger (it does
  not — docstring 17-20 calls it forensic observability, and only `conductor-close.md:49-51` /
  `merge_queue.py` touch it), but because the ledger is the run's *evidence* that something left the
  machine, `conductor-close.md` runs this exact check at close, and the strongest anchored mode
  reports intact over a receipt that now lies about its destination. Repair is cheap: bind the
  line's own canonical bytes, not a field list.

## C2 — DOWNGRADED (P1→P2)

Claim: `rest_json` attaches the bearer with `request.add_header` (`external-ci-monitor.py:73`),
which urllib re-sends to whatever `Location` names; `upstream_probe.py:207` uses
`add_unredirected_header`; `response.read()` (`:76`) is unbounded.

- Command (verbatim) — loopback pair, port A 302s to `http://localhost:<port B>`, B echoes the header

```
r = urllib.request.Request(f'http://127.0.0.1:{PA}/start', headers={'User-Agent': 'probe'})
getattr(r, kind)('Authorization', 'Bearer TOPSECRET')     # kind = add_header | add_unredirected_header
urllib.request.urlopen(r, timeout=5).read()
```

- Observed (verbatim, rc)

```
add_header           -> {"auth": "Bearer TOPSECRET"}
add_unredirected_header -> {"auth": null}
rc=0
```

Mechanism, from this interpreter's own stdlib: `HTTPRedirectHandler.redirect_request` builds
`newheaders = {k: v for k, v in req.headers.items() …}` and returns `Request(newurl, headers=newheaders, …)`
— `unredirected_hdrs` is not carried, so it starts empty. `add_header` writes `req.headers`,
`add_unredirected_header` writes `req.unredirected_hdrs`; `do_open` merges with
`headers = dict(req.unredirected_hdrs); headers.update(…)` — unredirected wins on send, and is
absent on redirect. The sibling is exactly right: `upstream_probe.py:182-186,206-207`.

Unbounded read confirmed: `:76` is a bare `response.read()`; no `Content-Length`/`MAX_BODY`
anywhere in the file (`grep -n "read(\|MAX\|limit\|Content-Length"` → only `:76` and the gh
`--limit 1`), so a redirect to an endless endpoint is an OOM in the alerting path. Note the
"sibling diverges" framing does not extend to this half: `upstream_probe.py:210` is also a bare
`resp.read()`.

- Pinned by a test? No. `tests/test_external_ci_monitor.py:170-191` asserts the header on the
  **first** request via `Request.get_header()`, which reads `unredirected_hdrs` before `headers` —
  the assertion passes under either API. `grep -n "redirect" tests/test_external_ci_monitor.py` hits
  only `redirect_stdout`.
- Severity: **P2**, down from P1. What holds: the token rides to a foreign origin, executed, and the
  in-repo fix is one word. What does not: urllib verifies TLS here, so an on-path attacker cannot
  forge the 3xx without breaking the cert — the leak needs a GitHub-issued redirect (renames stay on
  `api.github.com`), a MITM proxy, or a hijack. It is also opt-in: `rest_json` runs only for
  `--transport rest` (`:93`, `:103`, `:110`); the default transport shells out to `gh`, which does
  not have the defect. A leaked `GITHUB_TOKEN` is still a real loss, so P2, not P3; the unbounded
  read alone is P3.

## C3 — CONFIRMED

Claim: the marker `<out>/.open-fleet-bundle.json` (`bundle.py:304`) lives inside the tree it
authorises deleting; `_owned` (`:327-344`) reads it, `_claim` checks *parents* only (`:358-361`)
and never the marker, then unlinks every listed path (`:374-377`).

- Command (verbatim)

```
python3 scripts/bundle.py --out $S/out                      # real marker, rc 0
mkdir -p $S/out/my-notes && echo "keep me" > $S/out/my-notes/keep.txt
echo "my own settings" > $S/out/settings.json
python3 - $S/out/.open-fleet-bundle.json <<'PY'             # forge two filenames
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d["files"] += ["settings.json","my-notes/keep.txt"]; json.dump(d,open(p,"w"),indent=2)
PY
python3 scripts/bundle.py --out $S/out ; ls -l $S/out/settings.json $S/out/my-notes/keep.txt
```

- Observed (verbatim, rc)

```
forged entries appended: ['settings.json', 'my-notes/keep.txt']
== re-run bundle.py --out ==
rc=0
after:
ls: cannot access '/tmp/tmp.EhwsNVp9Nv/out/settings.json': No such file or directory
ls: cannot access '/tmp/tmp.EhwsNVp9Nv/out/my-notes/keep.txt': No such file or directory
```

Nothing on stdout/stderr, exit 0 — the promise at `docs/install.md:172` ("refuses (exit `2`) to
overwrite untracked files or symlinks") is silently void. `grep` confirms the asymmetry: the
parents of every owned path are inspected (`:358-361`), the entries a *planned* path would collide
with are inspected (`:362-364`), the marker is in neither set, and `_claim` never compares the
marker's list against what the previous build actually wrote.

The marker's other half — never checked at all, so a symlink is followed — also reproduces: valid
marker copied outside, `ln -s $S/outside-marker.json $S/out2/.open-fleet-bundle.json`, rebuild →
rc 0, `settings.json` deleted, the symlink survives, and `_record` overwrote the outside file.

- Pinned by a test? No. `tests/test_bundle_out.py:157-162` covers *malformed* markers (unparseable,
  wrong type, `"../../etc/passwd"` — traversal is refused), and `:166-185` appends a path that a
  build legitimately wrote. A well-formed list naming files the build never wrote is untested.
- Severity: **P1**, the audit's grade holds, and the authority is the one the finding names. The
  code comment at `:297-303` says the marker exists because `--out ~/.claude` used to eat the
  user's skills; `~/.claude/settings.json` is where `docs/install.md:13,75` puts the
  `verify-gate.sh` completion-gate hook, so a forged marker is a silent, exit-0 way to unwire the
  gate on a build that reports success. Bounded by `--out` (no traversal — `..` is refused), and it
  needs write access to that directory, which the threat model grants the untrusted worker anyway.

## C4 — CONFIRMED

- Command (verbatim)

```
git rev-parse HEAD                                        # 15e03dfedbf5…
grep -rn "pull_request_target" .github/workflows/         # NONE
grep -rhn "uses:" .github/workflows/*.yml | grep -vE "uses: *[^ ]+@[0-9a-f]{40}( |$)"
python3 - <<'PY'   # ${{ }} inside any `run:` block, all 13 files
… tracks `run: |` extents and prints interpolations inside them …
PY
grep -n "No approving review" docs/ops.md
```

- Observed (verbatim)

```
NONE                                     # pull_request_target: 0 hits
85:      statuses: write                  # the only two non-`uses:` lines the regex flagged
107:          permission-statuses: write
(no output)                              # ${{ }} inside a run: block: zero, all 13 workflows
50:No approving review is required: the owner is the only collaborator, and GitHub does not let an
```

Triggers: `validate.yml:3-6`, `guard.yml:19-20`, `negative-control.yml:8-11` are all
`pull_request` (+ `push: [main]`), none `pull_request_target`, and none of the three is reachable
from a `workflow_run` (only `verdict-gate.yml`, `verdict-check.yml`, `alert-on-failure.yml` are).
`docs/ops.md:44-51`: the required contexts are `gates`, `guard`, `pinned-demo` (app 15368) plus
`verdict-gate` (app 5451539), and "No approving review is required". `CODEOWNERS:4-8` names
`@ravidsrk` on `*` and on `runtime/`, `scripts/`, `.github/`, `docs/ops.md`, with `@agentsalpha`
inert (`:2-3`, and `ops.md:32-35`: the invitation "was never accepted").

Merge ref, from GitHub's own event reference (fetched 2026-10-27): for `pull_request`,
`GITHUB_REF` is `refs/pull/<n>/merge` and `GITHUB_SHA` is "the last merge commit of the pull request
merge branch"; the page contrasts `pull_request_target` as running "in the context of the default
branch of the base repository, rather than in the context of the merge commit, as the `pull_request`
event does". The workflow definition is resolved from the run's ref, so the PR's YAML — the PR's
commit as merged into base — is what executes. In-repo corroboration of the same hazard for the one
gate that was hardened: `verdict-check.yml:3-8` ("a `pull_request_review` run loads THIS file from the
PR, so a PR can rewrite the `verdict` job below") and `:15-18` ("checking out the merge ref and
running its scripts/verdict_check.py let a PR rewrite the very check that gates it").

Does the authority follow — green while nothing ran? Yes, for an *edit*, not a delete:

- Required contexts are matched by context name and app id, not by workflow file or body. A PR that
  rewrites `gates` (and `guard`, and `pinned-demo`) to `steps: [{run: echo ok}]` produces check runs
  with those three names from app 15368 concluding success on the head SHA, and every real gate —
  six shards, secret scan, vf-bench, coverage floor, floor-guard, trailer rule — is skipped.
- Deleting the file instead leaves the PR **blocked** (no context ever reported), so the attack is
  edit-not-delete. `guard.yml`'s base-sourced checker (`:37-44`) does not help: the PR can empty the
  job that runs it, and `floor_guard.py`'s surface (`:195-202`) covers `.coveragerc`, ruff,
  `.gitleaksignore`, ROUTING_MIN_SCORE, the vf-bench corpus — not `.github/workflows/`.
- Nothing compensates: no required approval (`ops.md:50-51`), CODEOWNERS inert, and `verdict-gate`
  is the only pinned-identity context (`ops.md:53-69`) — it attests a verdict, not that any build
  gate ran.
- Pinned by a test? Partly, and not for this. `tests/test_repo_hygiene.py:416-440` pins job
  timeouts and that no `run:` interpolates a PR-controlled context (matching the zero above);
  `:564` pins tools to the lock; `:652` indexes `_jobs(text)["pinned-demo"]`, which breaks on
  deletion but not on emptying. No test asserts the shape or step count of any job, and any such
  test would itself run from the PR's tree.
- Severity: **P1**, the audit's grade holds. CI is the only merge barrier on this repo and the PR
  supplies the grader; one owner click merges code that passed nothing, and post-merge `push` runs
  on `main` are not required contexts. Thinnest part of the claim is volume of harm, not mechanism:
  it takes a PR that means it, and a human does press merge.

## Side observations (not graded here)

- `egress.py` treats a *missing* ledger as a clean chain (rc 0). With an anchored `(empty)` head it
  is caught; unanchored, "no ledger" and "empty ledger" are indistinguishable from healthy.
- `docs/install.md:172` over-promises "refuses to overwrite … symlinks" against C3's two paths.
- C4's mitigation shape already exists in-tree (`verdict-gate.yml` on `workflow_run` from `main`);
  extending it to the three build contexts is a wiring change, not a design one.
