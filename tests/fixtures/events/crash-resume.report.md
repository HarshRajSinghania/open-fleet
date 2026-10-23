| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=2 reviewers=1` | `throughput=unavailable` | `latency_median=unavailable latency_max=unavailable` | `rework=0/2` | `freshness=0` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=unavailable` | `latency_median=unavailable latency_max=unavailable` | `rework=unavailable` | `freshness=unavailable` |
| `wave=3` | `builders=1 reviewers=0` | `throughput=unavailable` | `latency_median=unavailable latency_max=unavailable` | `rework=unavailable` | `freshness=unavailable` |

Derived by `events.py report` for run `run-b` from 30 admitted event(s) of 34 line(s) (0 duplicate(s) collapsed, 1 conflict(s), 2 fenced) — record sha256 `430ed3b1955da50b0eb7443efc9527012f13aeb42f5bfd9970ce70f5fb0b108c`, head `58b1a405eb8d799e8270548b5aec5945bd0905dc922b7cbc1ad14848a344ad85`.

Unavailable — the record does not support a measured value, and none was estimated:
- wave 1 `throughput`: wave 1 wall-clock: wave.open and wave.close are on different clocks (host-a, host-b); no common clock, no interval
- wave 1 `latency_median`: unit u1 latency: task.done and verify.verdict are on different clocks (host-a, host-b); no common clock, no interval
- wave 1 `latency_median`: unit u2 latency: task.done was recovered after a coordinator resume, so its time is when it was rebuilt, not when it happened
- wave 1 `latency_max`: unit u1 latency: task.done and verify.verdict are on different clocks (host-a, host-b); no common clock, no interval
- wave 1 `latency_max`: unit u2 latency: task.done was recovered after a coordinator resume, so its time is when it was rebuilt, not when it happened
- wave 2 `throughput`: wave 2: ['u4'] not observed CLOSED or parked — a pending or unrecorded close would change the count
- wave 2 `throughput`: wave 2: wave.close not observed, so the wall-clock is unknown
- wave 2 `latency_median`: unit u3 latency: negative on clock host-b (-300.00s) — the clock stepped back or the events are misattributed; never clamped to 0
- wave 2 `latency_median`: unit u4: no verified-or-parked observation (open)
- wave 2 `latency_max`: unit u3 latency: negative on clock host-b (-300.00s) — the clock stepped back or the events are misattributed; never clamped to 0
- wave 2 `latency_max`: unit u4: no verified-or-parked observation (open)
- wave 2 `rework`: wave 2: ['u4'] not yet verified or parked — a later bounce could still land
- wave 2 `freshness`: wave 2: ['u4'] not closed or parked; a review is voided at merge, which has not happened yet
- wave 3 `throughput`: unit.suspect recorded under epoch 1 after epoch 2 was declared — a fenced coordinator's write
- wave 3 `latency_median`: unit.suspect recorded under epoch 1 after epoch 2 was declared — a fenced coordinator's write
- wave 3 `latency_max`: unit.suspect recorded under epoch 1 after epoch 2 was declared — a fenced coordinator's write
- wave 3 `rework`: unit.suspect recorded under epoch 1 after epoch 2 was declared — a fenced coordinator's write
- wave 3 `freshness`: unit.suspect recorded under epoch 1 after epoch 2 was declared — a fenced coordinator's write
