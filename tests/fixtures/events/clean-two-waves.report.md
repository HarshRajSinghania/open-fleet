| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=2 reviewers=1` | `throughput=1.14/h` | `latency_median=22.00m latency_max=24.00m` | `rework=1/2` | `freshness=1` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=0.86/h` | `latency_median=12.50m latency_max=20.00m` | `rework=0/2` | `freshness=0` |

Derived by `events.py report` for run `run-a` from 38 admitted event(s) of 40 line(s) (2 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `a26ce8a719d6808126643e8f03e4f4f106f92f088457e497485771b8579c937e`, head `3618702b3330710e733b69331416fb2f1adeca1f2a59ae288b800265525a9e63`.
