# WIP-curve run wip2-b6r2-rep1

RUN: wip-curve run=wip2-b6r2-rep1 condition=b6r2 tier=live-unreviewed

## WIP-curve protocol row (derived by events.py report)

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=2` | `throughput=310.55/h` | `latency_median=0.58m latency_max=0.62m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=2` | `throughput=147.16/h` | `latency_median=0.23m latency_max=0.23m` | `rework=1/1` | `freshness=1` |

Derived by `events.py report` for run `wip2-b6r2-rep1` from 75 admitted event(s) of 75 line(s) (0 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `d79f1bffded9e9db90a1272bc59f5528da086a89874696fe6516a952819642e8`, head `965e82199ef26b2c1acafed16a7c167d7cbb95998dd51bfaccb22d8ad738ead6`.
