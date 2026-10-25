# WIP-curve run wip2-b6r1-rep2

RUN: wip-curve run=wip2-b6r1-rep2 condition=b6r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=1` | `throughput=204.33/h` | `latency_median=1.08m latency_max=1.10m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=1` | `throughput=118.81/h` | `latency_median=0.26m latency_max=0.26m` | `rework=1/1` | `freshness=1` |

Derived by `events.py report` for run `wip2-b6r1-rep2` from 75 admitted event(s) of 75 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `7dfafa7479850cd5955ed64bc4feadbdaba6fb2912366920e416dc418bf9de8a`, head `966084abd042ff8a9c64e6a77dc8f4574429792424be55bcbcb51d5fed330165`.
