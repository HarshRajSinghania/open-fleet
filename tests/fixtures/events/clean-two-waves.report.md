| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=2 reviewers=1` | `throughput=1.14/h` | `latency_median=22.00m latency_max=24.00m` | `rework=1/2` | `freshness=1` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=0.86/h` | `latency_median=12.50m latency_max=20.00m` | `rework=0/2` | `freshness=0` |

Derived by `events.py report` for run `run-a` from 38 admitted event(s) of 40 line(s) (2 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `8739f2b8138bd7ca0cd3281d8cfaa22a777ac0ed3acf00aafb90a6abee65a7e6`, head `4223dbcbd75487a738ba6c9173269fd012dc984cb00207160220b084b39d61ab`.
