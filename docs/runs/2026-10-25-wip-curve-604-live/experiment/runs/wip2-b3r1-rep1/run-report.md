# WIP-curve run wip2-b3r1-rep1

RUN: wip-curve run=wip2-b3r1-rep1 condition=b3r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=3 reviewers=1` | `throughput=153.62/h` | `latency_median=0.52m latency_max=0.55m` | `rework=1/3` | `freshness=0` |
| `wave=2` | `builders=3 reviewers=1` | `throughput=154.04/h` | `latency_median=0.54m latency_max=0.54m` | `rework=2/3` | `freshness=0` |
| `wave=3` | `builders=3 reviewers=1` | `throughput=184.47/h` | `latency_median=0.41m latency_max=0.45m` | `rework=1/2` | `freshness=1` |

Derived by `events.py report` for run `wip2-b3r1-rep1` from 85 admitted event(s) of 85 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `ba0138611ee86be829598506d7efcfa564980a4a51b27e76fa0b2d7e6d719ea9`, head `fd7dd94a435fd71cb9e9d0e99fb632ca33f12fd438d31670f9702c7f56ae9570`.
