# Run report — ship-it external-run (ravidsrk/mdtoc, Linux witness, #515), 2026-10-13

RUN: mission=ship-it tier=external-run inventory_at=c8680a68c197ce25c24393db70afe11e93ae756a manifest=docs/runs/2026-10-13-ship-it-mdtoc/manifest-integrated.json verifier=GREEN waves=6

| Field | Value |
|---|---|
| Mission | `ship-it` — mission source revision `caf67c2df0` (catalog main at run start) |
| Tier claimed | `external-run` (run kind: external — the target is a separate product repo, not this catalog) |
| Target | `ravidsrk/mdtoc` (public scratch repo created for this run) — branch `fleet/ship-mdtoc-20261013` |
| Fixed point | BASE `fleet/ship-mdtoc-20261013` · FORK_POINT `0b9f660d93e64cf57e8245b0f1eb6eb0010ae158` (seed) · frozen spec `SPEC.md@0b9f660d` sha256:0fcbad925a7350e3c55311929f703c56dd802672b4c2fd2987c6e697d9c0bfb8 · built head `046d1f8d0ff63b7193bc06e0c373ba60d9e06849` (pushed by the coordinator from the host; `ls-remote` confirms origin tip) |
| Coordinator / workers | coordinator session driving `orca-ide` in the Linux witness VM (run `run_4e3ed8344520`, coordinator `term_de3f1b7c-4e1f-4b8f-93e0-6f63e5044871`) · builders `PROFILE=rw` (custom-argv lane, see Deviations), reviewers `PROFILE=ro` (Claude Code 2.1.296) · TASK packs: matt (tdd, builders), gstack (review, reviewers) — one pack per worker |
| Orca | `orca-ide status --json` → `"state": "ready"`, `appVersion 1.4.224`, reachable (retained at close: `2026-10-13-ship-it-mdtoc/status-linux.json`). Host: Ubuntu 24.04.5 LTS arm64 (OrbStack `orca-linux-witness`); resolved CLI name: `orca-ide` |
| Human gates | Gate #1 spec freeze — maintainer approved `SPEC.md` as drafted (2026-10-13, structured choice). Target + substrate — maintainer chose scratch repo + Linux witness VM. VM Claude auth — maintainer via OAuth consent (long-lived token from `claude setup-token` in the VM; token file mode 0600 in VM home, never in any repo). Release authorization: **BUILT only** — no release/publish gate requested or taken; the built BASE branch was pushed to the target repo, `main` left for the maintainer |

## Terminal state

**BUILT** — every slice landed and proven at the integrated head `046d1f8d`, the highest release state authorized for this run (offline no-gh lane; no promotion PR, release, or deploy was in scope).

| task_id | unit | BUILD_DONE | PR_OPEN | BOT | REVIEWED | MERGED | WT_CLEAN | lighting | park | evidence |
|---|---|---|---|---|---|---|---|---|---|---|
| task_11560fce010c | F0 foundation | t | n/a | n/a | t | t | t | lit | | head 02f1258; review PASS task_7d2ad49a1f14 (`reviews/f0.md`); verify OK executed-NC (`manifest-f0.json`); merged 03e13d38 ancestry-verified |
| task_2e1867b1d215 | S1 scan+slug (AC-2,3) | t | n/a | n/a | t | t | t | lit | | head af83a56 after fix round task_70d29afa81a2; `reviews/s1.md` FAIL → `s1-r2.md` PASS (`reviews/s1-record.md`); verify OK executed-NC (`manifest-s1.json`); merged 4e1ad707 |
| task_a485af881dfc | S2 update+modes (AC-1,4,5,6) | t | n/a | n/a | t | t | t | lit | | head a960241 after fix round task_68f8e06228eb; `reviews/s2.md` PASS+2 MEDIUM → `s2-r2.md` PASS (`reviews/s2-record.md`); verify OK (`manifest-s2.json`); merged fedebc75 |
| task_bfa7e23e0f20 | S3 multi-file+errors (AC-7,9) | t | n/a | n/a | t | t | t | lit | | head 04a9e8f; review PASS (`reviews/s3.md`); verify OK (`manifest-s3.json`); merged c574a547 |
| task_204bc820b2ec | S4 slug hardening (AC-2) | t | n/a | n/a | t | t | t | lit | | head 4aa7755 after fix round task_479d83732bdf; `reviews/s4.md` PASS+1 MEDIUM → `s4-r2.md` PASS no findings (`reviews/s4-record.md`); verify OK (`manifest-s4.json`); merged c9a6f683 |
| task_1dbe4c4cb564 | Integrated acceptance @c9a6f683 | f | n/a | n/a | t | f | t | lit | | FAIL (`reviews/integrated.md`): CR-only idempotence + BOM placement; closed by S5 |
| task_de5d11f52acc | S5 EOL+BOM seams (AC-1,6) | t | n/a | n/a | t | t | t | lit | | head 47ef84f; review PASS (`reviews/s5.md`); verify OK (`manifest-s5.json`); merged 046d1f8d |
| task_fe34045197bf | Integrated acceptance @046d1f8d | t | n/a | n/a | t | t | t | lit | | PASS (`reviews/integrated-r2.md`, `reviews/integrated-record.md`); verify OK executed-NC (`manifest-integrated.json`); BASE pushed — terminal BUILT |

## Convergence proof

- **Traceability, two-level.** The frozen spec's denominator is AC-1..AC-8 (`SPEC.md@0b9f660d`, digest above); the run's criterion set is AC-1..AC-9 because the placement criterion's error half was split out as AC-9 at decomposition (recorded in `slice-contracts.md`). Each slice manifest binds its own contract at a signed digest (f0 FC-1..3; s1 AC-2,3; s2 AC-1,4,5,6; s3 AC-7,9; s4 AC-2; s5 AC-1,6); the union covers AC-1..AC-9 with no criterion unclaimed. At the integrated head, the build-blind re-review's traceability matrix (`reviews/integrated-r2.md` §2) names the guarding tests per criterion, and the coordinator's retained battery (`prove/integrated-probe.py`, output `prove/int-battery-fixed.txt`) exercises every criterion end-to-end at `046d1f8d`. Suite: 110 tests green.
- **Every slice landed and fresh.** Each slice merged locally into BASE (offline lane: PR_OPEN/BOT `n/a`, deviation recorded in `ledger.md`), ancestry-checked with `git merge-base --is-ancestor` before the next wave; `reviewed_sha == head_sha` in every manifest (no rebase-after-review). Negative controls: every unit's hand mutant was EXECUTED by `verify.py --execute-nc` in a throwaway worktree (RED at the unit head, green when clean); on top of that the round-2 S4 reviewer ran three fresh-worker mutations of the new guards and the integrated reviewers probed the assembled product — the ≥10% fresh-worker revert audit is discharged by those reviewer-run mutations, not by a separate audit dispatch (stated plainly; no stronger claim).
- **Terminal named with evidence.** BUILT at `046d1f8d0ff63b7193bc06e0c373ba60d9e06849`, pushed to `origin/fleet/ship-mdtoc-20261013` from the host (`git ls-remote` re-derived). No promotion, release, or deploy state is claimed.

## Pipeline evidence (per phase)

| Phase | Command / action | Result | Evidence |
|---|---|---|---|
| FREEZE | maintainer approved `SPEC.md` as drafted (human gate #1); BASE `fleet/ship-mdtoc-20261013` cut at seed `0b9f660d`; `preflight.py --offline` in VM | exit 0 (gitleaks absent: warn) | `ledger.md` |
| DECOMPOSE | per-slice contracts `contracts/{f0,s1,s2,s3}.md` committed @`ece80424` (s1 amended @`dfe7457c`); signed dispatch records (`dispatch-record-*.json`, pubkey `dispatch-pubkey.hex`) | denominators frozen before build | `slice-contracts.md`, `contracts/` |
| BUILD+REVIEW (per slice) | builder dispatch → build-blind review → fix round when a verdict demanded it → `verify.py --execute-nc` → local merge + ancestry check | 6 slices landed; 3 fix rounds (S1, S2, S4); merge SHAs in the terminal table | `manifest-{f0,s1..s5}.json`, `reviews/`, `deliveries/` |
| INTEGRATED PROVE (r1) | whole-diff acceptance vs frozen spec @`c9a6f683` | **FAIL** — CR-only idempotence, BOM placement (2 HIGH + 1 MEDIUM) | `reviews/integrated.md` |
| SEAM FIX | slice S5 (line-ending model, BOM, indent) through the same lane | PASS, landed `046d1f8d` | `reviews/s5.md`, `manifest-s5.json` |
| INTEGRATED PROVE (r2) | F1-F4 repros byte-for-byte + all-criteria matrix + seam hunt @`046d1f8d`; coordinator battery `prove/integrated-probe.py` | **PASS**, no new seams | `reviews/integrated-r2.md`, `prove/int-battery-fixed.txt` |
| VERIFY | `verify.py` executed-NC per unit + integrated (below) | OK, exit 0 | `prove/*-verifier.txt`, `prove/int-verifier-rerecord.txt` |
| LAND | host `git push origin fleet/ship-mdtoc-20261013`; `ls-remote` re-derived | origin tip `046d1f8d` | this report's Fixed point row |

## Verifier outcome (recorded exactly)

The binding record is `verifier-integrated-rerecord` in `manifest-integrated.json`, evidence-run in the VM on a clean committed tree (recorded commit `f04ed24d287c86bdf565a21c4636308fe57865ef`, `wtree` that commit's tree). A first record (`verifier-integrated`, `prove/int-verifier.txt`) was taken on an uncommitted tree and is retained, not relied on. The verify legs resolve the target repo's SHAs because the coordinator fetched the target's refs into the catalog clone's object store (no refs created) — recorded here so a re-derivation knows why `cat-file` resolves.

Invocation (as recorded by evidence-run):

`python3 runtime/scripts/evidence-run.py --label verifier-integrated-rerecord --manifest docs/runs/2026-10-13-ship-it-mdtoc/manifest-integrated.json --artifact docs/runs/2026-10-13-ship-it-mdtoc/prove/int-verifier-rerecord.txt -- python3 runtime/scripts/verify.py --manifest docs/runs/2026-10-13-ship-it-mdtoc/manifest-integrated.json --contract-source docs/runs/2026-10-13-ship-it-mdtoc/contracts/integrated.md@faf90eb293702af50e8e9310c26cab90f3cac16a --contract-digest sha256:01b5aea7cd817b4170207ca627ceaa8db3732866eea0581fe69d865d22f1ad4e --unit-class mutation --dispatch-record docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-integrated.json --dispatch-pubkey docs/runs/2026-10-13-ship-it-mdtoc/dispatch-pubkey.hex --repo ravidsrk/mdtoc --no-gh --execute-nc --nc-command 'python3 -m unittest discover'`

Output (verbatim, also in `prove/int-verifier-rerecord.txt`): `NOTE: --base not given — ancestry check skipped (pre-merge/offline)` · `NOTE: dispatch record signature verified against the supplied key (#135) — a soundness boundary only if that key is trusted (off-worker: CI/MCP/SDK or an auditor)` · `NOTE: commands ledger FRESH — 3 exit-0 record(s) bound to head_sha's tree 1b0866726013` · `NOTE: negative control EXECUTED — with the hand control applied at head_sha the bound command exited 1 on an assertion failure (RED, as required)` · `NOTE: the same command exits 0 at clean head_sha` · `NOTE: no-gh review is coordinator-attested via the frozen out-of-band contract (local reviewer artifact at head_sha) plus an EXECUTED negative control, not GitHub-verified — the weaker guarantee (merge-serialization.md)` · `verify: OK — all required checks passed` · exit 0.

Per-slice verifiers (same lane, each exit 0, each evidence-recorded in its manifest): `prove/f0-verifier.txt`, `prove/s1-verifier.txt`, `prove/s2-verifier.txt`, `prove/s3-verifier.txt`, `prove/s4-verifier.txt`, `prove/s5-verifier.txt`. Dispatch records were coordinator-signed per slice (seed custody: VM `~/.dispatch-sign/seed` mode 0600, outside any work tree; pubkey retained in the run directory).

## WIP-curve protocol row

Waves are the six slice build waves (F0, S1, S2, S3, S4, S5); the two integrated acceptance dispatches are the convergence gate, not builder waves, and are reported in the pipeline table. The ledger ran at `WIP: builders=2 reviewers=2`; the slice DAG was a chain, so observed concurrency never exceeded one builder plus one reviewer. Metrics re-derive from the target repo's git history: wave wall-clock = previous merge → this merge (wave 1 from the seed); throughput = landed units / wave hours; latency = first `worker_done` head commit → merge (verified) — one unit per wave, so median = max; rework = fix-round bounces / units; freshness = reviews voided by `reviewed_sha != head_sha`.

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=2 reviewers=2` | `throughput=2.1/h` | `latency_median=16m latency_max=16m` | `rework=0/1` | `freshness=0` |
| `wave=2` | `builders=2 reviewers=2` | `throughput=1.7/h` | `latency_median=32m latency_max=32m` | `rework=1/1` | `freshness=0` |
| `wave=3` | `builders=2 reviewers=2` | `throughput=2.2/h` | `latency_median=25m latency_max=25m` | `rework=1/1` | `freshness=0` |
| `wave=4` | `builders=2 reviewers=2` | `throughput=5.7/h` | `latency_median=9m latency_max=9m` | `rework=0/1` | `freshness=0` |
| `wave=5` | `builders=2 reviewers=2` | `throughput=2.9/h` | `latency_median=17m latency_max=17m` | `rework=1/1` | `freshness=0` |
| `wave=6` | `builders=2 reviewers=2` | `throughput=2.8/h` | `latency_median=10m latency_max=10m` | `rework=0/1` | `freshness=0` |

## Deviations and lessons (recorded, not hidden)

- **Offline no-gh lane.** The VM holds no GitHub credentials, so slices landed by local merge into BASE (PR_OPEN/BOT `n/a`) with build-blind local reviews + executed negative controls as the oracle, and BASE was pushed from the host at close. Weaker than the GitHub-verified lane by design of the substrate; recorded in `ledger.md` at F0, not retrofitted.
- **Spawn lane.** The supervised worker-start lane was unusable twice over (bypass-permissions first-acceptance timed out readiness; then READY spawns read LAUNCHED_UNUSABLE because the host's agentDefaultArgs lack `--dangerously-skip-permissions`). Builders ran the custom-argv lane (`WORKER_CMD='claude --dangerously-skip-permissions'`) into coordinator-created worktrees with folder trust pre-seeded. Failed attempts `ctx_4684039b34d8`, `ctx_5c107c24e37a` settled; details in `ledger.md`.
- **Two extra slices beyond the decomposition.** S4 (slug hardening) and S5 (EOL/BOM seams) were opened when integrated probes and the integrated FAIL showed criterion-level defects the slice reviews had accepted as carries. The frozen spec never changed; the coordinator-authored slice contracts did the partitioning.
- **Contract amendments.** `contracts/s1.md` was amended mid-run (@`dfe7457c`) and `contracts/s3.md` reworded (@`27cc97ef`) because a prose criterion mention shrank the verifier's extracted denominator — each re-pinned and re-signed before its verify, digests in the manifests.
- **Coordinator judgment calls (recorded in review records):** S2's `--stdout` prints the full updated document (spec "prints the result"); inline-code-span markers and ten other edges latched as known limits after reviewer judgment that none contradicts a criterion; the F4 indent rule is shallowest-included-relative, leaving a deeper-first-heading TOC indented (cosmetic, stable).
- **Substrate notes for the pin:** `orchestration check` replays the oldest unacknowledged batch until `--ack <delivery_id>`; plan-mode reviewers stop at a plan-approval prompt the coordinator approves in-pane; spawns read UNPROVEN on this substrate and were proven live by screen reads + deliveries. A leftover worker-start worktree in the VM (`~/orca/workspaces/mdtoc/build-f0-foundation-216950265`) is prunable residue, not evidence.

## Run-close integrity inventory (sha256)

| Artifact | sha256 | producer |
|---|---|---|
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/f0.md` | `af975e05cdda982ab506d8a192a0af412d408218e0f6844b00101c7255e418fe` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/integrated.md` | `01b5aea7cd817b4170207ca627ceaa8db3732866eea0581fe69d865d22f1ad4e` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/s1.md` | `02a4f8efe04825ee7ef3848006d09f6dec959df6ada9ee74b53d2bfa08247e99` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/s2.md` | `b34d2c016f48a1a2542f2a286928afe4df72867b33cbf0c26bc7e74045408cf9` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/s3.md` | `32fbb80a0594296c8a1751422108d235d73bbdc260d0915bcfc6dab5feb929e2` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/s4.md` | `058443a30f3a4f93a2a996f62ebfe8ab09a24cedf82498ed5fcc11c581113b93` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/contracts/s5.md` | `7a5bf38bc72770452d40cdbcf468220463f2a9d25a91bfd635ea63c694caadc4` | coordinator (frozen slice contract) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/f0-review-done.json` | `8c7a085014fc4aa8769c607594579ce5c0fcefa191516e1220bdf6c700f3f099` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/f0-worker-done.json` | `0e3d11604fed9b85e6a021dd2ee3a5853dd13812544380ee4eb9bf4899107872` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/int-rereview-done.json` | `b538d5c8a06cdbadb54bca58f913953dd00fb168aa77752a35535b16a18dc992` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/int-review-done.json` | `ba9d58bf5246bd6d23b1e8738fa74c674aafa77e87d46edd5714e37afbda9bc0` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s1-fix-done.json` | `3aca6f4ec567b8a15c9bdf881a7e16fc88d5faad87a84fddf2e8a47c95a51c75` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s1-rereview-done.json` | `de0dd1fc76ef6564ac93295e2d95cba8284c3762ed5ab0db07f91fcfe9391a7c` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s1-review-done.json` | `05f0d0f70cc3b78ee9437d4d5d732e2b283049284656b92f2fdd0ddb287c6f45` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s1-worker-done.json` | `ca21c056f8383244afbee672e81f43a3ff31679c6613883fbd528127bcc535f0` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s2-fix-done.json` | `0622c118e56900d16679437aacb32f45d8067f26dd0c95a843230448146d2994` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s2-rereview-done.json` | `5ead44a89c995bef26354a0177883d9c5b9fada8d79aabeb4fc47650107f99d2` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s2-review-done.json` | `d71c113be94690b5bbd70948cef180ae5e09fc1e46377e823b7e8af995391471` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s2-worker-done.json` | `aa30c9526524a23c7d494a6997496b3bc618ad254e8fa5be4afff2f82aabe147` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s3-review-done.json` | `a65b41d91e5da3e90306fcb5a5600aa1279b7bfce71e6a7bb2f1c493fc61072d` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s3-worker-done.json` | `b73eedbcfba59f2d0c7dcc36ec44bac77d825a563a9dd86f61b0d98ba5960cb4` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s4-fix-done.json` | `b788b0b488def63b97c609a7ff6983ab3dc6c77e339bbd065bb8f5635f381330` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s4-rereview-done.json` | `f22021b935576da2df06c45e6bff398ef31f0f1148780dedc893e89164e6bd23` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s4-review-done.json` | `fb17cdac7d008f4ed9844317364b535c37a73bff48a38237c3c4369215f27c08` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s4-worker-done.json` | `bc2e39fd985c565b83fd0d28dc24951af4afd6a0ef317038151d3cdafa7aa3d9` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s5-review-done.json` | `19a6bfafecb37b98c8167b6d41aee13ce397fc6d55febbec401bd6df6da8ae9d` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/deliveries/s5-worker-done.json` | `6b7ebc7b42cf41a5f6b1a7a4fe324948a638d425b0a3d1c8c801b165a8887f65` | orca-ide orchestration check 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-pubkey.hex` | `4063344914de0fd53c0bc2e8d756419d828f1b54a29340c2c19e10184cdeaf31` | dispatch-sign.py gen-key 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-f0.json` | `850393ed81e4abe780cb165bac903ada718d215cda4584fc30676639f6f79ec5` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-integrated.json` | `a2261ed2cfde85b7981d8f3056aa69f2514568147256760a7117db82670ee543` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-s1.json` | `c2c08409d1a0d56d25e01fafa6439978ee5d16fd575b554df0161584e73e6e12` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-s2.json` | `7dde87d8404993a43eaff2b4e59b16d9be0f4d7203833ccd5079185c5fed7c3f` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-s3.json` | `0e466d266dff0ebbdb94f4942ae3dd178b72d3525fe53d811e578f334bf56bb3` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-s4.json` | `7b359244bc879204e356171f6392f52d4f10d96e2882ca0da1de6a91594e5a42` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/dispatch-record-s5.json` | `51729ce55160e0c1e52c7836439afc6b98c083cf3fdfe63179e6c6b1e9aebe8b` | dispatch-sign.py sign 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/ledger.md` | `0496ad4e49bd33a473862278cc3e82dcc6eea1e51b5bdd65b4b7e4c6972a8a20` | coordinator ledger 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-f0.json` | `3163f34049e6c35cb37a5ddfe8503819b4412bddc87bf3524ca2793218aab852` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-integrated.json` | `f1cd70920dff5b79116759dda6cae54122cd0adc3abfc3be217e4ad6bb7ba84a` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-s1.json` | `cf646d1e2753020459722f467fc47514c1fe5a67edbba869e52fd5c673a61dd9` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-s2.json` | `23eab9430b2fc0e608ffbc86f6be301c0f206165769ae0e80b5fe69d15df008e` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-s3.json` | `0c7d1265422c5192524042516237982d7d6c82ece6da95ed39d8b9676c0bb0a3` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-s4.json` | `f0dfad0010038957590259a34300391a39446bc87a3bbfeb7c396c3445fd745c` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/manifest-s5.json` | `e4b947251bb95ad69b085fdaea7dce8212cdad11acb2c96fd299b29c85ff72e6` | coordinator + evidence-run.py 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/f0-nc.txt` | `a38ea8d3e49452e6d6df3cfee38e997b63aaf832dc03362d6092f30aa8e7d206` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/f0-prove.txt` | `2eda090e3971334fc9f342d262b75b0de1fc737a1d0106701fe49b5307c16528` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/f0-tests.txt` | `ce90ee7eab549d6484639696e8119f808394e6f2f36bc0c23b00be57b7acb179` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/f0-verifier.txt` | `a9ffa9cb6ed59ff90f107d1613b739b8e3dcf828a99fc7f07976aa6729ae13fd` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-battery-fixed.txt` | `a12f88c6e7c8de415a26d4c398724c875680418be4c474c8a303b12bebf568f4` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-battery.txt` | `a2b010fcb6ce3075d357428e508fa0cc707d76513d11fe09faecb5e66af17e9b` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-nc-fixed.txt` | `297169237fa6fe7b54c9578d641729feb0d93c3db4382358673b29c46e099970` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-nc-run-fixed.txt` | `9ab837fd15775c073947d35da242bb7b9558f3e471001051b5e8ce3c35384aa0` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-nc-run.txt` | `2a4ac4a670a1c70a78069afffc54e80046b3bb3430ef6484f437c444dfb49aa6` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-nc.txt` | `c29cd8d4ea2eba90ecbc193115f31166f32dc2411d081bd1839e427ea8a035ea` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-prove-fixed.txt` | `8dd50026580593f2e633833894a7a98ec5bdead216c5db4522cbc95c2088c12f` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-prove.txt` | `8dd50026580593f2e633833894a7a98ec5bdead216c5db4522cbc95c2088c12f` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-tests-fixed.txt` | `bfaf00929c9b500fd2f41893e5d0a27329d5f4349ce8eb3a440a31fe4c088e20` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-tests.txt` | `35355a683b00eebadce4238a9c50fcadd2b512f9387d7db716f77e5eeff9c23f` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-verifier-rerecord.txt` | `50793f96e46b5780d40489f26fa3361157cfb57e2017c6a42f06dc011642688d` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/int-verifier.txt` | `50793f96e46b5780d40489f26fa3361157cfb57e2017c6a42f06dc011642688d` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/integrated-probe.py` | `3a71659d5b5998388f9be7b38637e223140d5b4b41cad692e1d7735263133ad7` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-nc-run.txt` | `bfabe95006528506b251f9503eed04c64317650d6a60096e0089c739a2277298` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-nc.txt` | `69ece8f7d1b7d6c73b92dfac5840d8aacfe7b8b7b7c2f98bf750a59f7d91da1b` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-prove-fixed.txt` | `90468d52985fd09653f75d3036f3cdcc760ee8cae4ba1593f28b0d6b8e047f0f` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-prove.txt` | `90468d52985fd09653f75d3036f3cdcc760ee8cae4ba1593f28b0d6b8e047f0f` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-tests-fixed.txt` | `3e25a278fc9c69baae0963e335ecb23e45f5991695dfba9876c3e08f3e4f1a79` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-tests.txt` | `fd062a59cac8803c7bc3721b57991d21cd77c38d5111678c3b3161cc110d9467` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s1-verifier.txt` | `950453dc2aec88ddcd7a4d5f3a247eb9df44600ae7ab3ff84bf98ac7c66b6289` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-nc-fixed.txt` | `939458eb6a46bfaee357d12f609659617f3738c553f355cba25a29a964f72429` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-nc-run-fixed.txt` | `aeca732a276251d1a750ab0e4717d7d9d5df29967d58c808bdcec201624d6462` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-nc.txt` | `494d5a1a8920eeefafe8bebda3984a35503883f2cfb2f689caa6363aea2e5332` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-prove-fixed.txt` | `72fed77514f448387929858be27e43471fe1513ac8d0642cd541a6da9525a8b6` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-prove.txt` | `72fed77514f448387929858be27e43471fe1513ac8d0642cd541a6da9525a8b6` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-tests-fixed.txt` | `268a25ddb952c38a16e958f165c6b773cbbff605adbd930b99d1aff9049787a2` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-tests.txt` | `08a15606bded1907db04a4c9ddc4a5c305da88d1dcf6a991993066e7f4c80e45` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s2-verifier.txt` | `0981fbd4735d1ed7bdc90b45eac3eaa940715f863614823684f4f212f94e04c9` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s3-nc-run.txt` | `fe63d702380592a85f0869b24e443827cdec390ea74be0b79fe87a995e38e0ab` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s3-nc.txt` | `d27b032240ae976abb6268472e64a3c538e2e87c1ca9b4c105f2883bcca70356` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s3-prove.txt` | `cd1a04e909af22203db9dfea37ae4b26fb140a38788ea94872c9333a43e72ec3` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s3-tests.txt` | `b78460fda6b6044c446d9a71fa27632f8d30b4ffd55e9a3b339faf9380b31fde` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s3-verifier.txt` | `759427b4aea0eec0187536b2c3ac22616c6252a0a8546c24e9056c49338a8d51` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-nc-fixed.txt` | `6a672ab37ddd1c130fea8837f6ba5c385ca1ec25e1988e2a26dbfda6a834f4ec` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-nc-run-fixed.txt` | `cf259964d283e878346d6e8b363181070bbcb96cdace098a69b91a5ab4f92f8e` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-nc-run.txt` | `eaafa1d1d7d34226221a9a938214dbaf75fe69e542cfcf3993d609abef569e33` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-nc.txt` | `f1594fae839efb2da722f9c2b7cdd63fd3a62a2529d49648f31696b83305cde1` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-prove-fixed.txt` | `58a7b8e965e219ee5fb16ea1ba8d9217068edecfae612d8e7f8f281de40d1531` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-prove.txt` | `58a7b8e965e219ee5fb16ea1ba8d9217068edecfae612d8e7f8f281de40d1531` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-tests-fixed.txt` | `e24f22bef3877acb6e5a7271f34d179ad3d6768a618c0ee800c60f7c06ae0e44` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-tests.txt` | `7c9df1c6e0f9c9fcf322caead4d7ddf9bb055748aeca7a1ba50f5eb5c64f451e` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s4-verifier.txt` | `acd37824eceffa08984735bbf41517deec4a564dc59bfa2dc46dfe1758abb8b2` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s5-nc-run.txt` | `7aaf313fbedc16584fe236d8fc59034c37d9480d1cd9011a63c57b18f0581a58` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s5-nc.txt` | `aed254af504e7a7f0a584e91aceb2e0a152fa78b4401cb2cbf8b052b8a44e80b` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s5-prove.txt` | `08488cf1becadfb7842f2d058d85fe658ed0628c8c5471a8525bcbbd807b1cd6` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s5-tests.txt` | `25a72d6fa99279992bbb29291d9cf9c57baae155d5726417fb7f5332609b2c0b` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/prove/s5-verifier.txt` | `efda0e8cd326b67049ac1be594c7e74116c5c7849b33f71833dcbf906ab7f2f7` | evidence-run.py / coordinator 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/f0-record.md` | `37b098e13ec8ab619b0875d4966c988d6a602093f0d947486ca02c8972f38db4` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/f0.md` | `d008ddfbc3cb86adbe5c69d866736d98393cc59dcaccf04c014a74490fc6318b` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/integrated-r2.md` | `db432946a1cfa25330b87975074c15eaec13678970965cd3170d5bc95428f576` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/integrated-record.md` | `28053586fe16f09c867526436fc0ffcf60ad54605a80ffbccbb74a25a6d52df2` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/integrated.md` | `8ebc5bc2ff78980e8e9822310d3cbb782fc22377c0aad444bca67a75881e14a3` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s1-r2.md` | `8a040867ec09d7702fa08b0ca4369aa9881d04e07436e242bbed05c1c643a7d8` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s1-record.md` | `5d6ae2d534bb5d1e6918548cb5dfca9fedff1af5be7b062fd3249392816b8f13` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s1.md` | `47f026a3a85352e9d57b780d8a6d4d128df5510bbf390b875e39c952e9de62fc` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s2-r2.md` | `2c5cb38d0a6f1d6228c52035aa64f34cc8a6f0af2062805a399d76d064ff75bd` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s2-record.md` | `2262c731f11db273edcc7edb9aea97857b35f89a9e385f5ebdc8a7ed21793aa2` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s2.md` | `846486dbbb2281befca69a88078c368d38323ec6df8b3242bb32a151011c4b54` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s3-record.md` | `c9180d436082fc0e3809ed356f86d27b5bd290f7b822f80b6be49e601665cd4f` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s3.md` | `a65973e742eff7a7aa01cf37802148115477a569f5fced48b9d56ff8e3bf9b83` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s4-r2.md` | `b1e80e7126c80be6f3fea6dc46dc0d91f64cfbe17384d0529d255a22f8acabd2` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s4-record.md` | `cb4fd221325087d232c200347dd1fbb0f053142a34fd0b2f278a881711d9b538` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s4.md` | `c3811d6a3e3ed85cf4b12f5fa503bbf76051c8af7bcb098195c18f28cb0987fe` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s5-record.md` | `7ed9e8f8045c3f65d6f25d4e8dae2f2997a9eb484f1c39ec47206135f607caf4` | coordinator attestation 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/reviews/s5.md` | `449a44a9ddd72c5f0e4954d603b1777ea51a7271d72eaa7222f9c6ae19d205d4` | claude reviewer worker (build-blind) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/ship-driver.py` | `2ca3a2ce4d63cd74783c66b6349c46431a15801f0bffc01977c22e9c81bc0691` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/slice-contracts.md` | `cdf45db731bc72018dca2fa80677cb44e19f16aa9f25f114767677170ff96968` | coordinator (contract index) 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/integrated-fix-review.txt` | `528b73d694c19796d94412868fca7448f28753ff65548701f501ff090647c003` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/integrated-review.txt` | `0f8019004b3c8e1ea3c6effbe18c62d5f9823a9703f4bb7c9e10c4410b38b90d` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s1-fix.txt` | `703eee48f256e303ef9d3fe43f91cfee99988d8923e5d710ee52350fbd2f5566` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s1-rereview.txt` | `cba8048a359feb69efba3a55bee449add0b72c4cfa53db9379242c78f2116947` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s1-review.txt` | `2ff97f95edfe05c155230b3da1badfb9440a7a2db69e4acf5c9f1cc39baa3538` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s1.txt` | `a47050ceedba9732fea80b70b0331498555f3b121cd5ae0fdb3b6ef8537c34f6` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s2-fix-review.txt` | `79ad49dd36478e34a9a485a92fc3ec6b9442919a97350afeb5083be914a2a8ad` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s2-fix.txt` | `91437cc53f4aa84487a055d413496cfb66e840e902898a347560a8276b129d50` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s2-review.txt` | `b64b972791e01d1903912ae6d7af6b8d6930e1ad87662508900fb1d0d870fd87` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s2.txt` | `98c9947c0a02880b568033abff0a73e1fcc4f29aba053987e7703eeb67a3fb8d` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s3-review.txt` | `052457b537066dc6d24a625dee5df134c2a1ec7201c3c3ce1fe7aa8077c911bd` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s3.txt` | `f36d510774b54b888429d6078ffde275572795cb22a8979a88424e4de24605d4` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s4-fix-review.txt` | `0cdc04f946862d8b6f1018841e326f2907914c4124c4e61274fc9ae8fb93cf5f` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s4-fix.txt` | `1f6501ae834feaba144ca310c1d29c87818e7e7cb03a86174a50f317e790fd21` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s4-review.txt` | `ce86eca02df5d2d4963dba0308570a5b5066484dee8d3b66d857c54fc76a44a8` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s4.txt` | `e6259853b820a12ff021561d3a43aee6b7007238d4fa987585eb8f0abda7e0b2` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s5-review.txt` | `df4199c05712fe32e41bd5e9dd8ec3cc84cc04de4ba759a6c2ae7ad8a67a8eef` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/specs/s5.txt` | `b427f400b9d01202a23b43ba4b22f13ce29ddbddc1f1395a5e2512236eeb8e23` | coordinator TASK spec 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-build.py` | `7d4de426cd3958ec0d114ff099b7c18ebfd75949d2b5aa3a33be1cc1e17eae99` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-evidence-integrated.py` | `6f36c0174f74408f7e65318731d216d0452472819822fe4adda85f673b81d2a3` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-evidence-s2fix.py` | `b0a583922a73385a636689f2367453ecc19a1d77fef2ddde680d93b6d89cf5b5` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-evidence-s3.py` | `ee8439500f3d58390c74f4c037c3492957e3d486531299d396d6141988f75e92` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-evidence-s4.py` | `5a060345b15e0b02e5989599fd59f05998cc3261867fc4163f8895d685ef3cfd` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-evidence-s5.py` | `a1ec968c0de6b6aea4332d1d86ad12a1e7cea1646b0cff36fbf564fb7890a993` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-finalize-integrated.py` | `a2d5648e477eb393cffa96f91291adb1af6e0c358027d7c84a91f2417eed6f23` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-finalize-s2.py` | `1c69f75d812806d2d75415fa0c12c98a7481652d2d43a6a98c4a59b968b81af9` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-finalize-s3.py` | `6ba5c8497c6bc5901fc6fdbb40013774960971c542760b11870200a0f15f97d4` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-finalize-s4.py` | `f7c1ef91031f1fda39db2386179b342db48cab5cfa7b7be5046caad71e87334e` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-finalize-s5.py` | `266bc9565f4fbe0b98955d078b92783a612acf04cc570921177d59d95e09dbb4` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/stage-review.py` | `88fb6bb5dbeaea84ac51c3bc0e27e9e9eaa5ecc266d228336aabdeeea748701c` | coordinator driver script 2026-10-13 |
| `docs/runs/2026-10-13-ship-it-mdtoc/status-linux.json` | `c9991cfae057369c9b756033f837c6df253a0e9b50606626de7e9545847ec426` | orca-ide 1.4.224 status (recorded at close) 2026-10-13 |

## Gates

Target-side (at built head `046d1f8d`, VM + host): `python3 -m unittest discover` → 110 tests OK (evidence-bound per unit in the manifests; integrated: `prove/int-tests-fixed.txt`). The target repo has no linter/justfile/pyproject; `SPEC.md` names unittest as the oracle, Python ≥3.11 stdlib-only (verified by import scan in both integrated reviews; a 3.11 interpreter was not run — reading-only claim, code uses nothing newer than 3.8 constructs). Catalog-side (this repo at landing): `python3 scripts/validate.py`, `python3 -m unittest discover -s tests` (sharded), `python3 runtime/scripts/proof_status.py --check`, `python3 scripts/bind_check.py --base origin/main`, `python3 runtime/scripts/floor_guard.py --base origin/main` — results recorded in the landing PR.

## Evidence binding

Artifacts are retained in this run's own directory at `inventory_at` (`c8680a68`); the graded manifest is among the hashed paths. `inventory.py check --at c8680a68` and `run_report.py` (mission=ship-it, tier=external-run) were run by the coordinator before landing, including from a fresh clone of the landing branch; results recorded in the landing PR. The target repo's objects are not in this repository — the verifier's SHA legs resolved them from the coordinator's fetch into the catalog object store (noted in the Verifier outcome section), and the built revision itself lives at `ravidsrk/mdtoc` `046d1f8d`.
