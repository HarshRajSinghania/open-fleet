# WIP-curve run wip2-b6r2-rep3

RUN: wip-curve run=wip2-b6r2-rep3 condition=b6r2 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=2` | `throughput=302.71/h` | `latency_median=0.61m latency_max=0.65m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=2` | `throughput=144.21/h` | `latency_median=0.24m latency_max=0.24m` | `rework=1/1` | `freshness=1` |

Derived by `events.py report` for run `wip2-b6r2-rep3` from 75 admitted event(s) of 75 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `1bfc4de2f876f63e71bad5c6107f239263144dd8998741948d3c32184295d002`, head `d7fb3be6892f08919fb86b2f7e5f7c5899bd92df42542d8858645153a2b599d0`.
