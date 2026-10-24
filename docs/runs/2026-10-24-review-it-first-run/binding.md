# Binding verdict: #596 live first runs, 2026-10-24

The coordinator's verdict on the frozen contract (`contract.md`), over the artifacts in this run
directory as committed. This file is the unit's only change. Every artifact it judges is pinned by
sha256 in `manifest.json`, at this commit.

| Criterion | Verdict | Re-derived from |
|---|---|---|
| LR-1 | holds | the four cited receipts: `mac-ro/`, `mac-rw/`, `clean-host/receipt-ro.json` and `clean-host/receipt-rw.json` |
| LR-2 | holds | `isolation/claude-wrapper.py`, each Mac run's transcript, manifest, contract, change and report |
| LR-3 | holds | `clean-host/clean-host.log` and the three scripts beside it |
| LR-4 | holds | `first-attempt/ro.receipt.json` and `first-attempt/rw.receipt.json` |
| LR-5 | holds | `orca-ro-attempt/`: the launch line, the terminal-wait receipt naming `agent-trust-workspace`, the pane, and `spawn.stderr` |

`rederive.py` re-derives each criterion from the files, and `rederive.txt` records its run:
`REDERIVE=OK`, exit 0.

The first `verify.py` run (`verifier.txt`, first ledger record) refused the first shape of this
unit. There the artifacts themselves were the evidence range of a report-only unit, and most of
them are not docs. That refusal is kept. The unit was re-shaped so its range carries only this
verdict, and the artifacts are pinned at its head.

What the runs certify, and what they do not, is stated in the run report and in
`runtime/providers/certification.json`. In short:

- `posix` `ro` and `rw` with Claude Code 2.1.304 are live-witnessed, on two hosts.
- Orca `ro`/`claude` is still owed a fresh witness. The attempt stopped at Claude Code's
  folder-trust prompt, which only the operator may answer.
