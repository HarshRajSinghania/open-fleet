# WIP-curve run wip2-b6r1-rep3

RUN: wip-curve run=wip2-b6r1-rep3 condition=b6r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=1` | `throughput=217.06/h` | `latency_median=1.00m latency_max=1.06m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=1` | `throughput=139.57/h` | `latency_median=0.22m latency_max=0.22m` | `rework=1/1` | `freshness=1` |

Derived by `events.py report` for run `wip2-b6r1-rep3` from 75 admitted event(s) of 75 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `767c3ccb2be3f087df14ce4171d35e472588efe19fd131840eae6d7b48362bd5`, head `6a336d1a099954d60de1138f42e529df105c06ceb10ce2f2f52e7a88d5e97236`.
