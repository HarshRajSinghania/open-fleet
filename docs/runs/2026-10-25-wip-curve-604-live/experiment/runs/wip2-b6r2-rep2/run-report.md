# WIP-curve run wip2-b6r2-rep2

RUN: wip-curve run=wip2-b6r2-rep2 condition=b6r2 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=2` | `throughput=248.06/h` | `latency_median=0.82m latency_max=0.87m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=2` | `throughput=149.70/h` | `latency_median=0.24m latency_max=0.24m` | `rework=1/1` | `freshness=1` |

Derived by `events.py report` for run `wip2-b6r2-rep2` from 75 admitted event(s) of 75 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `d6f4dad67a1bb2188dc446225b54b7e2966074d3e2b99365bae9037fb46c0b56`, head `797f70c474fab118c13b43bf5602c0671edc1a841d4d660ac7c49ad7218e3a9d`.
