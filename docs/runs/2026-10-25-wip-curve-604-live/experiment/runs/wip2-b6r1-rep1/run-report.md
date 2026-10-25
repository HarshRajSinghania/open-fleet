# WIP-curve run wip2-b6r1-rep1

RUN: wip-curve run=wip2-b6r1-rep1 condition=b6r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=1` | `throughput=214.62/h` | `latency_median=1.00m latency_max=1.07m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=1` | `throughput=153.04/h` | `latency_median=0.24m latency_max=0.24m` | `rework=1/1` | `freshness=1` |

Derived by `events.py report` for run `wip2-b6r1-rep1` from 75 admitted event(s) of 75 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `9fafc1ffb8e342e192b4ea3255dcb97402403200aa289061a87687da5623c54e`, head `7b228a69b99db021a961576b47722f49a5a9dc11c31d08b1599f6adeafa2492d`.
