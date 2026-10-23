| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=2 reviewers=1` | `throughput=1.14/h` | `latency_median=22.00m latency_max=24.00m` | `rework=1/2` | `freshness=1` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=0.86/h` | `latency_median=12.50m latency_max=20.00m` | `rework=0/2` | `freshness=0` |

Derived by `events.py report` for run `run-a` from 42 admitted event(s) of 44 line(s) (2 duplicate(s) collapsed, 0 conflict(s), 0 fenced) — record sha256 `2ee35fc6b701161929f76e2c9df84435d47c70e63c4c7528a9186fa23936ab02`, head `78970c4c61c5aa08baa964c23fdfcb3040bd212825787c96aa1a9b96888b040d`.
