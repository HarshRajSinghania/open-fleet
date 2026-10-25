# WIP-curve run wip2-b3r1-rep3

RUN: wip-curve run=wip2-b3r1-rep3 condition=b3r1 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=3 reviewers=1` | `throughput=233.04/h` | `latency_median=0.51m latency_max=0.53m` | `rework=0/3` | `freshness=0` |
| `wave=2` | `builders=3 reviewers=1` | `throughput=221.51/h` | `latency_median=0.56m latency_max=0.56m` | `rework=0/3` | `freshness=0` |

Derived by `events.py report` for run `wip2-b3r1-rep3` from 65 admitted event(s) of 65 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `49771bb05712a20dc18acf550305c3c46f5fd38b47c083fc2e55aca720462fbc`, head `9c14d9bd3c8615cd14c00ec0159cade51fd061baa10980a60b2b99712d07acfe`.
