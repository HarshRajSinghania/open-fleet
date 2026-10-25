# WIP-curve run wip2-b1r1-rep2

RUN: wip-curve run=wip2-b1r1-rep2 condition=b1r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=1 reviewers=1` | `throughput=132.81/h` | `latency_median=0.25m latency_max=0.25m` | `rework=0/1` | `freshness=0` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=136.64/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=3` | `builders=1 reviewers=1` | `throughput=0.00/h` | `latency_median=unavailable latency_max=unavailable` | `rework=1/1` | `freshness=0` |
| `wave=4` | `builders=1 reviewers=1` | `throughput=42.07/h` | `latency_median=1.22m latency_max=1.22m` | `rework=1/1` | `freshness=0` |
| `wave=5` | `builders=1 reviewers=1` | `throughput=139.20/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=6` | `builders=1 reviewers=1` | `throughput=163.98/h` | `latency_median=0.22m latency_max=0.22m` | `rework=0/1` | `freshness=0` |
| `wave=7` | `builders=1 reviewers=1` | `throughput=150.59/h` | `latency_median=0.21m latency_max=0.21m` | `rework=0/1` | `freshness=0` |

Derived by `events.py report` for run `wip2-b1r1-rep2` from 83 admitted event(s) of 83 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `ac1f1e8ba606ee0ece042c133eed4d99d42d3639e27f145a442d57a9379c4b15`, head `3e8ed4289e61610d502ed33871963982833947bb55075021f185d9ffcc391aaf`.

Unavailable — the record does not support a measured value, and none was estimated:
- wave 3 `latency_median`: wave 3: no unit reached verified-or-parked after an observed worker_done
- wave 3 `latency_max`: wave 3: no unit reached verified-or-parked after an observed worker_done
