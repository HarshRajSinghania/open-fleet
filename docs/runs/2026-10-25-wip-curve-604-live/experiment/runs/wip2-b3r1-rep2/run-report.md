# WIP-curve run wip2-b3r1-rep2

RUN: wip-curve run=wip2-b3r1-rep2 condition=b3r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=3 reviewers=1` | `throughput=213.49/h` | `latency_median=0.57m latency_max=0.60m` | `rework=0/3` | `freshness=0` |
| `wave=2` | `builders=3 reviewers=1` | `throughput=223.04/h` | `latency_median=0.55m latency_max=0.57m` | `rework=0/3` | `freshness=0` |

Derived by `events.py report` for run `wip2-b3r1-rep2` from 65 admitted event(s) of 65 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `d9ac8efb172f795601f519481eb4d8093c881c4a71962da595444750654cb4d4`, head `f71692b3f960859a63e2547855aecb0c86f6805010cf16cce61235b98f8d721e`.
