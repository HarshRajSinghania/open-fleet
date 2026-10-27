# Audit W5 — network and egress (B2, STRIDE *Information disclosure*)

RUN: run_secaudit_20261027 · WAVE: W5 · AUDITOR: red-team subagent · BASE: review/2026-10-27-security-audit
@ 15e03dfedbf5 · T0: 2026-10-27 · SOURCE: `threat-model.md` §B2 · ROUTING: static/read-only, plus
`ro` scratch PoCs under `mktemp -d` (nothing written under the repo; `scripts/live_container.py`,
`scripts/live_broker.py`, `scripts/_trajectory_live.py` and `scripts/external-ci-monitor.py` need a
network/docker, so they are argued from code and PARKED with their blocker)

Scope read in full: `runtime/scripts/egress.py`, `scripts/live_broker.py`, `scripts/live_container.py`,
`scripts/live_container.Dockerfile`, `scripts/live_container_bin/claude`, `scripts/_trajectory_live.py`,
`scripts/external-ci-monitor.py`, `runtime/scripts/send_msg.py`, `runtime/scripts/search_sessions.py`,
`runtime/scripts/hint_provenance.py` (the path resolver `search_sessions` depends on), `scripts/install.sh`,
`scripts/bundle.py`, `runtime/scripts/upstream_probe.py`, `runtime/scripts/first_run.py`, and every
`urllib`/`http.client`/`subprocess(["curl"...])`/`tar`/`unzip` site under `scripts/` and `runtime/scripts/`
(minus `scripts/vendor/`; there is no root `install.sh` — the installer is `scripts/install.sh`).

**What this wave could not break, in one line:** the token never rides an argv, a URL, a temp file or a
ledger; no first-party code path unpickles, `yaml.load`s or `eval`s a fetched body; there is no
`tar`/`unzip` in the tree at all (so tar-slip/zip-slip is not a class here — only `docker` and `apt`
unpack, both from a digest-pinned base at build time).

---

## Findings

| id | file:line | sev | class | untrusted input | exploit scenario | gain | why it fails | PoC |
|---|---|---|---|---|---|---|---|---|
| W5-05 | `runtime/scripts/egress.py:96,136-143,272-273` | P1 | receipt forgery / repudiation | any process that can append one line to `.orca/egress.jsonl` | Append `,"note":"<any text>"` (or `,"payload":"…"`, a second `host`, a `consent` explanation) inside the braces of the ledger's **last** line. `verify` recomputes `prev` only from the *previous* line and `id` only over `FIELDS`, so the extra key is hashed by nothing. `verify` prints *chain intact* and exits 0; once one more receipt is appended the tampered line's raw bytes are baked in and every later link is consistent, so it stays invisible for the rest of the run. | a receipt says what the writer wants and the check cannot tell: the ledger can be made to carry what its docstring says it never carries (payload text, a token), and a receipt's `id` no longer names its own bytes | `id` covers `FIELDS` only, `prev` covers the previous line only, and nothing covers the *current* line's raw bytes — the last line is unbound by construction | **executed** — forged key on the last line accepted (`verify` rc=0, only the head moved); a further `write` then locked it in |
| W5-08 | `scripts/external-ci-monitor.py:68-76` | P1 | credential to a foreign origin | the 3xx `Location` (and any on-path proxy) in front of `api.github.com`; `GITHUB_TOKEN` from the env | `rest_json` adds the bearer with `request.add_header`, which urllib **re-sends on a redirect** to whatever host the `Location` names: `GITHUB_TOKEN` → `http://127.0.0.1:9999` (or `https://attacker`). The sibling script `upstream_probe.py:207` already uses `add_unredirected_header` and documents exactly this hazard, so this is a known-shape miss, not a design choice. The body is also read unbounded (`response.read()`), so a redirect to a 4 GiB endpoint is an OOM in the alerting path. | a live PAT handed to an origin the repo does not control; monitor OOM (→ exit 2, "CI could not be read") | no origin pin across redirects (unlike `upstream_probe._origin`), no `MAX_BODY` | written demonstration (urllib redirect handler keeps `Request.headers`; `unredirected_hdrs` is the fix). PARKED: needs a server |
| W5-10 | `scripts/bundle.py:327-345,358-377` | P1 | trusted forged record → file deletion | `<out>/.open-fleet-bundle.json`, which sits **inside** the write target and is therefore writable by anything that can write there (e.g. a worker in a shared `--out`) | Write `{"generator":"x","files":["settings.json","CLAUDE.md"]}` into `~/.claude/.open-fleet-bundle.json`, run the documented `bundle.py --out ~/.claude`. `_owned()` returns the attacker's list, `_claim()` passes (only *parents* of owned paths are checked, and the marker itself is not checked at all) and unlinks every listed file. | silent, exit-0 deletion of any file *inside* `--out` — including `~/.claude/settings.json`, where the completion gate / deny-hook wiring lives, so the hook can be disabled by a build that reports success | the ownership record is a plain file in the tree it governs, with no digest and no cross-check against what the previous build actually wrote | **executed** — forged marker deleted `settings.json` and `CLAUDE.md`, exit path clean |
| W5-01 | `runtime/scripts/egress.py:160` vs `:229-235` | P2 | write/read asymmetry, evidence DoS | one byte appended to the ledger by a non-writer | `printf 'note=\377\n' >> .orca/egress.jsonl` (a latin-1 note — the shape `last_raw_line` explicitly tolerates via `errors="replace"`). `write_receipt`'s own read **succeeds**, so every subsequent receipt is written and its id printed, `&&` fires, the send happens — but `read_ledger` decodes with strict `read_text`, so `verify` and `head` exit 3 forever after. | the run emits N successfully-receipted sends and the evidence artifact is unreadable at close; the write path never notices | the writer decodes leniently (`errors="replace"`, :160) and the verifier strictly (:229), so the writer cannot detect what bricks the verifier | **executed** — write rc=0 twice after the bad byte, `verify`/`head` rc=3, permanently |
| W5-02 | `runtime/scripts/egress.py:150-153,199-207` | P2 | TOCTOU on the chain `prev` | a concurrent process with write access to the ledger's directory | The receipt's fd is opened with `O_NOFOLLOW`+`flock` (:199-206) and then `prev` is computed by re-opening the **path** (`last_raw_line(path)`, :207 — no `O_NOFOLLOW`, different inode, not the locked fd). Swap the path for a stale copy of the ledger after the open: `prev` is derived from a file that is no longer the one being appended, and the appended record is orphaned into the unlinked inode, so the receipt is silently lost while `write` exits 0. | a receipt that "succeeded" and is not in the ledger at all (fail-open on the `&&` coupling) | read and write are two different opens of a name, not one fd | written demonstration (`last_raw_line` opens by name at :152 while the lock is held on the earlier fd) |
| W5-03 | `runtime/scripts/egress.py:92,110-117,195` | P2 | fail-open path provenance | `OPEN_FLEET_EGRESS_LEDGER` / `ORCA_EGRESS_LEDGER` (env, per the threat model's untrusted-input list) or a `cd`, since the default is a **relative** `.orca/egress.jsonl` | `OPEN_FLEET_EGRESS_LEDGER=/tmp/mine.jsonl egress.py write …` (or run the send from a subdirectory) → every receipt lands outside the canonical ledger. Close-time `egress.py verify` then reads an absent `.orca/egress.jsonl` as an empty chain and prints *chain intact, 0 receipt(s)* with **exit 0**; nothing compares the receipt count to the number of sends and the receipt does not record its own path. | the control reports green while recording nothing; the very first receipt is also free to create any directory tree (`path.parent.mkdir(parents=True)`, :195) | the ledger location is a mutable input to the record, and "no receipts" is not distinguished from "all fine" | **executed** — routed write rc=0, `.orca/` empty, canonical `verify` rc=0 "(empty)", `--expect-ancestor` only then rc=3 |
| W5-04 | `runtime/scripts/egress.py:371-396` | P2 | forged consent accepted | the ledger body | Add `,"consent":"grant:merge-anything"` (or any string) to a line and run `egress.py grants`; it prints the forged consent as a standing grant and exits 0 **without verifying the chain at all**, even on a ledger `verify` calls TAMPER. No consent string is checked against `runtime/one-way-doors.json` or any grant list, so the command that answers "what is the fleet allowed to do" is whatever the file says. | a human auditing consents reads claims that no check backs, from a file that can be tampered | `cmd_grants` parses only (`read_ledger`, :374) and consents are free text | **executed** — forged consent printed; `verify` on the same file rc=3 |
| W5-06 | `runtime/scripts/egress.py:212-213` | P2 | lost receipt on crash | the ordering of `flush` vs the process/host dying | `flush()` without `os.fsync()`: the caller's `&&` fires and the send leaves the machine while the receipt is still only in the page cache. A killed coordinator, a closed laptop or a power cut after a send loses exactly the tail receipts — the ones an incident review needs. `live_broker.Ledger.write` (:239-242) does fsync; the egress ledger, which is the evidence artifact, does not. | sends with no surviving receipt, unrecoverably | durability is assumed from the flush, and there is no fsync of the file or its directory | argued from code (contrast `live_broker.py:242`) |
| W5-13 | `scripts/live_container.py:225-235,483` | P2 | provenance recorded, not enforced | `--image`, or a `docker build --dockerfile` from a modified/uncommitted Dockerfile | `image_facts` computes `from_committed_dockerfile` and stamps it in the receipt, but `run()` never refuses on it and the *tag* is accepted as given; `docker create` then uses the resolved id of whatever that image is. A worker running the launcher chooses the harness image the arm runs in. | the receipt says the image was not built from the committed Dockerfile and the launch proceeds anyway — a self-attesting gap, exactly the "receipt names a fact, nothing gates on it" shape | the field is presentation; there is no `if not image["from_committed_dockerfile"]: refuse` | argued from code (grep: `from_committed_dockerfile` appears only at :235 and in the receipt) |
| W5-14 | `scripts/live_container.py:471-473` vs `:293-295,309-311` | P2 | mount-string injection | `TMPDIR` (the staging dir is `tempfile.mkdtemp()` inside it) | `--results/--receipts/--token-file` are rejected if they contain a comma (:471-473) because a `docker --mount` is comma-separated — but the *staging* paths (`export`, `attestation`, `settings`) are built from `mkdtemp()` and never comma-checked, and they are interpolated into `--mount type=bind,src=…`. `TMPDIR=/tmp/a,b` produces `src=/tmp/a,b/of-live-x/repo` with an unknown key `b/…` on every mount. | the launch dies at `docker create` with an opaque error after the export and both containers are staged (a `Refused`, so it tears down cleanly — a usability break more than a hole) | the comma rule is applied to three caller paths and not to the three derived ones | argued from code (docker mount grammar: `src=/tmp/a,b/repo` parses as `src=/tmp/a` + bare `b/repo`) |
| W5-15 | `scripts/live_container.py:307`; claim at `scripts/live_broker.py:10-11` | P2 | uncapped, unreceipted egress | anything the arm runs | `--network container:<broker>` shares the broker's whole namespace, **including its `eth0`** — so the arm opens its own sockets straight out (`curl https://anywhere`), not through the broker. The broker's "refuses every other request" covers only requests *to the broker*. | unbounded exfiltration from inside the "sealed" arm, and it is invisible in the broker ledger and in the egress ledger | network namespace sharing is isolation-between-containers, not egress control; there is no proxy, no `--network internal` and no DNS allowlist | argued from code; already half-admitted in `egress.py:67-69` ("cannot be without a proxy"), not in the broker's own docstring, which reads as a closed door |
| W5-19 | `runtime/scripts/send_msg.py:70-79,161` | P2 | sender identity is self-asserted | `ORCA_TERMINAL_HANDLE` (env, settable by the worker) | `resolve_from` accepts `--from` whenever it *equals* the ambient handle — but the ambient handle is the worker's own env, so `ORCA_TERMINAL_HANDLE=sibling egress…` lets a `worker_done` speak as the sibling pane. The docstring's claim ("passing another pane's handle would speak as that worker") holds only against an *accidental* mismatch. `format_send` also prints `relay.messageId` with no folding, so a newline in it forges extra receipt lines. | a lifecycle signal attributed to another worker; a forged line in the coordinator's receipt | one of the two sides of the comparison is attacker-controlled | argued from code |
| W5-21 | `runtime/scripts/search_sessions.py:331-335,489-493,900-906` | P3 | unbounded parse (DoS) | the session stores under `$HOME` and every `*manifest*.json` under `--runs-dir` | `_read_jsonl`/`_read_json`/`read_bytes` for each file with no per-file or per-run byte cap, and `_prior_hints` `rglob`s every manifest and `json.loads` each whole. One 500 MB `.jsonl` (or a `--runs-dir` naming a big tree) makes a recall scan hold it all in memory before any output. | slow/OOM on the recall path used to build a dispatch packet | only the *output* is bounded (`SNIPPET_LIMIT=500`, `max_lines`), the input is not | argued from code |
| W5-22 | `scripts/install.sh:35,44,63,186,217` | P3 | option-shaped values, unbound var | `--skills-dir=`, `$HOME`, mission directory names | `--skills-dir=-p` → `mkdir -p "$SKILLS_DIR"` (:186) receives `-p` as the *option*, not the operand (no `--`); a mission directory named `-x` reaches `ln -sfn "$ROOT/skills/$m" "$SKILLS_DIR/$m"` (:217) as a flag. `set -u` + unset `HOME` aborts at :35. | a wrong/absent install directory, or an outright abort | no `--` separators and no name validation on a value used as an operand | argued from code (needs a crafted name that must also pass `validate.py`, hence P3) |
| W5-07 | `runtime/scripts/egress.py:284` | P3 | unbounded read | `--payload-file` | a 2 GiB payload is `read_bytes()`'d whole just to hash it, in the pre-send step of the `&&`. | memory spike (or kill) immediately before the send, which then does not run | the hash is computed from a full read, not a stream | argued from code |
| W5-09 | `scripts/external-ci-monitor.py:92-111` | P3 | unquoted URL component | `--repo` | `--repo 'a/b?x=y'` or `--repo '../gists'` is formatted into `f"{API}/{path}"` with no quoting, so it changes the requested endpoint or the query; GitHub's parser ignores extra path segments. | the monitor reads something other than the intended repository and reports green/red for it | the value is interpolated, not `urllib.parse.quote`d | argued from code |
| W5-11 | `scripts/bundle.py:329-333,387-391` | P3 | symlink followed for the new marker | a symlink at `<out>/.open-fleet-bundle.json` | Every other symlink under `--out` is refused as foreign (:358-364), but `MARKER` is not in `planned`, so the check never sees it; `_record` then writes the new marker *through* the link (`write_text`), replacing whatever it points at. | another tree's ownership record (or any marker-shaped file) is overwritten, so that tree's next build either refuses or deletes by a list that is now this build's | the one path with the most authority is the one path excluded from the symlink check | **executed** — symlink survived and its target was rewritten by `_record` (a non-JSON target instead refuses, rc=2) |
| W5-12 | `scripts/live_container.Dockerfile:28-29,13-14` | P3 | `curl \| bash`, mutable URL | whatever `https://claude.ai/install.sh` serves at build time | `curl -fsSL https://claude.ai/install.sh \| bash -s 2.1.304`: the *script* is unpinned (no digest) and fetched from a branch, and the only verification afterwards is `--version \| grep -q '^2\.1\.304 '` — a string the installer itself prints. `apt-get install` takes rolling distro versions of `git`, `curl`, `ca-certificates`. Base is digest-pinned (:7), which is the strongest element here. | a build-time compromise of the installer runs arbitrary code as `runner` inside the image and can satisfy the version grep | a version *argument* is not a pin; no checksum of the script or the binary | argued from code; human-run (`build` once), and the blast radius is the build container + `$HOME` of `runner`, so P3 |
| W5-16 | `scripts/live_broker.py:301-314,418-419` | P3 | thread exhaustion | a client connection that never sends | `ThreadingHTTPServer` with `daemon_threads` and no socket timeout: open N connections and send no request line, or a `Content-Length` then no body — each parks a thread in `rfile.read()`. The broker's `--pids-limit 64` caps it, after which the arm's own model calls 502. | the arm loses its model path for the rest of the run | no `timeout` on the handler socket and no accept backlog discipline | argued from code |
| W5-17 | `scripts/live_broker.py:315-316` | P3 | unpriced, unbounded calls | the arm's request loop | `POST /v1/messages/count_tokens` relays with `call=None`: nothing is reserved, nothing is settled, and the number of them is unbounded. | free-path hammering is unmetered and unseen in the cap (and in the ledger) | the free path is treated as costless rather than as bounded-but-free | argued from code |
| W5-18 | `scripts/live_broker.py:397`; `scripts/live_container.py:285` | P3 | silent broker faults | the API's `usage` object | `settle(call, settled(usage, …) if complete else None, …)` evaluates `settled(...)` as an *argument*, so a type surprise inside it (e.g. `usage.iterations[i].input_tokens` not int-coercible → `int()` TypeError, `priced` :105) means `settle` never runs: the `start` line stays unsettled and its reservation is held for the process's life. The exception escapes `do_POST` into `http.server`'s stderr — which nobody keeps, because the broker runs `--log-driver none` (`live_container.py:285`). | a call whose cost is never settled and whose reservation permanently shrinks the cap; the traceback is discarded | `settled()` is computed outside the `Ledger.lock`, and the container has no log sink | argued from code |
| W5-20 | `runtime/scripts/first_run.py:329-341` | P3 | ambient credential to worker code | the operator's whole `os.environ` | `Sandbox.env = {**os.environ, …}` is handed to the worker (the arm), unlike the container lane which deliberately mounts no credential. On a host where `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY` is exported, any command the worker runs can read it — and `--worker live` now exists specifically to run a real agent. The receipt records env *keys* only (:409), so the gap is invisible. | the worker (or the code it writes and runs) holds the credential the "disposable" lane exists to hide | the on-host path reuses the ambient env with no allowlist, and drops the container lane's guarantee quietly | argued from code (contrast `live_container.py:90,160`, which strips `TOKEN_ENV` from the docker client's env) |

---

## Top three

1. **W5-05** — a receipt's last line can be extended with arbitrary content and `verify` still says *intact*
   (executed). The artifact the whole wave exists to protect can say things it never hashed.
2. **W5-08** — `GITHUB_TOKEN` is attached with `add_header`, so urllib re-sends it to any redirect target;
   the sibling probe already fixed this shape (`add_unredirected_header`).
3. **W5-10** — the bundle's ownership marker lives *inside* the directory it authorises deleting, so two
   lines of forged JSON delete arbitrary files there (executed): `~/.claude/settings.json` is the one that
   costs, because the deny-hook wiring is in it.

## Cleared, with the reason each holds

- **`egress.py` chain shape (the parts that do hold).** Field order fixed (:96); `\n`/`\r` refused in fields
  (:169-171) so the `k=v` join is unambiguous; `ts` shape- and instant-validated (:123-133); `prev` binds the
  previous *raw* line and a single edited line breaks every later one; wholesale rewrite is out of scope by
  design and answered by `--expect-head`/`--expect-ancestor` (:332-343); the head is printed only after a
  verify (:361-367) and the empty chain round-trips to `(empty)` (:299-304); ledger opened `O_NOFOLLOW`,
  `0600`, `flock`ed, non-regular refused (:199-206); exit 3 is documented as "never a permission to send".
  The anchor is real doctrine (loop-log line at `runtime/conductor-close.md:47-49`), not a slogan.
- **No content in a receipt by construction.** Only `sink`/`host`/`payload_class`/`consent` free text
  (≤512 B) plus a sha256 and a byte count; `--payload-file` is hashed, never stored (:282-290).
- **No secret anywhere in the clear in the live lane.** The token is read with `O_NOFOLLOW` from a 0600
  regular file, refused if any group/other bit is set (`live_container.py:180-202`); it is passed by *path*
  (`--token-file`), so `ps` shows no byte of it; the receipt carries the path and a three-word description
  and asserts the token is absent before writing (`:601-603`); container output passes a rolling redactor
  that holds back a split prefix across reads (`:372-390`); the wrapper `execve`s with the placeholder and
  the broker substitutes the real header (`live_broker.py:341`); the broker's ledger holds no token, request
  or response (`:30-32`).
- **Outbound request shape (`live_broker.py`).** Fixed `UPSTREAM`, no URL from the client; only two exact
  path constants accepted; host headers dropped; `Content-Length` bounded to 64 MiB and a non-int refused;
  TLS via `HTTPSConnection` with default verification; **no** `http_proxy`/`HTTPS_PROXY` honoured by
  `http.client`, so a worker-set proxy cannot redirect the credentialed call; `json` only, no
  `pickle`/`yaml.load`/`eval`; the cap is a genuine reservation ledger with the body's bytes as an input-token
  floor and `max_tokens` as an output ceiling, refusing anything it cannot price (unpriced model, extra
  field, server-side tool, file id, PDF, non-standard tier/geo).
- **`upstream_probe.py` network trust is the model for the rest.** Token is `add_unredirected_header` and
  only over https or loopback (:182-207); `rel=next` is origin-pinned and refused off-origin (:228-229);
  pagination capped; token never in a URL or an argv. `capture` reference names pass
  `^[A-Za-z0-9][A-Za-z0-9._-]*$` (:93) so no `../` can be written, and every surface filename is a
  constant.
- **`_trajectory_live.py`.** Task rides stdin, never argv (:609-613); env filtered of `ABLATION_*`/`EVAL_*`;
  `SHELL=/bin/sh` so no rc file reorders PATH; the CI log is a data file `cat`ed from a sh-quoted path, never
  shell source; `prompt_sha256` only in `results.json`; the `-I` harness keeps the agent out of the
  interpreter's user paths.
- **`search_sessions.py` forwarding.** Snippet bounded (`SNIPPET_LIMIT`), body indented inside a
  `guard_text.envelope`, every HIT-line field folded to one line with `defuse_banners` and directive labels,
  so a transcript cannot forge a `HIT`/`SNIPPET` line or close the envelope (:689-767). Read-only store
  access; `mode=ro`/`immutable=1` so no `-wal`/`-shm` is created beside a harness's data (:936-966).
- **Path escape from a recorded path (the B4 cross-over).** `hint_provenance._inside` confines live reads and
  artifact checks to the root (:375-383), used by `live_text` (:524) and `_disk_bytes` (:616); diffs run
  `--no-ext-diff --no-textconv`; a record naming `/etc/passwd` resolves to nothing, not to the file.
- **`bundle.py` deletion scope.** Only paths in the marker are unlinked; `..` and absolute paths are refused in
  the marker (P2-21/#623 regression is genuinely closed); *parents* of every path written or deleted are
  refused if they are symlinks (PR #631); a directory where a file goes is refused; the source catalog can
  never be the `--out` target.
- **`install.sh` download posture.** No network at all: hard prerequisites, `validate.py`, bounded symlink
  checks with realpath comparison, `ln -sfn` (so `-n` covers a link-to-directory without writing inside the
  target), and a refusal over an existing non-symlink or another clone's link without `--force`.
- **`send_msg.py` injection posture.** argv is a list end to end; `--payload` must parse as JSON; type closed
  to nine values; `--outcome` only on `worker_done`; lifecycle messages cannot target a `@group`;
  `--to`/`--subject` are non-empty-checked and ride after their flag.
- **`first_run.py` receipt hygiene.** Per-command `env` is recorded as **keys only** (:409), so an exported
  token does not land in `receipt.json`; `git add`/`commit` use `--` before the path; the committed bytes,
  not the tree, are what `verify.py` binds.
- **No `tar`/`unzip` anywhere.** Downloads are unpacked by `docker` (image layers, digest-pinned base) or
  `apt` (root-owned paths, `runner` non-root afterwards), so tar-slip / zip-slip / `unzip`-overwrite and
  post-unpack file modes are not reachable in this tree.
- **Container hardening that holds.** `--cap-drop ALL`, `no-new-privileges`, no `--privileged`, no host
  namespace, `--rm`, pids/memory/CPU limits, `--init`, `--log-driver none`, an id (not a tag) used for
  `create`, a clean `git init`+`fetch --depth=1` export so no host `.git`/untracked/ignored file is mounted,
  a read-only repo mount, the token outside both mounts (`:477-480`), one launch under `flock`, and a
  verified-destroyed teardown that is recorded and never raised so the receipt is always written.
- **`bundle.py` write targets.** `_entries_under` never follows a symlink; the marker write is the sole
  exception (W5-11); `dangling()` re-resolves every link and flags escapes.

## Not W5's to fix, but seen

- `runtime/scripts/deny-hook.sh` "receipt arming" is structural: it checks that `egress.py write` is
  `&&`-preceding the send, not that the receipt *succeeded* (the `&&` supplies that) and not that the ledger
  is the canonical one — so W5-03 also routes around the hook's intent without tripping it.
- The egress ledger is gitignored (`.gitignore:18-20`), so it is never committed with the run; only the head
  anchor survives. Deleting the ledger between closes turns the next `--expect-ancestor` into a TAMPER
  (correct but noisy) — worth stating in `conductor-close.md`.
