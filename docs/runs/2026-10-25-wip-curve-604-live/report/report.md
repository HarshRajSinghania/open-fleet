# WIP-curve experiment report

Pre-registration `docs/experiments/wip-curve-prereg-v2.json` v2 (sha256 `c30c2c15890d565af64c126dd456de4a09310c757ad33975a310e170412e1aa8`); task set sha256 `4ea82a93f093372d169f845e0dd6631b7fc3ae62bafb89b5d8efafd83a95f5e4`.
Evidence: live. Basis of the condition rows: all runs. Runs present: 12 of 12 scheduled; protocol-compliant: 12.

## Conditions

| Condition | WIP | Runs | Throughput /h, mean [95% CI] | Latency median min, mean [95% CI] | Rework (pooled, 95% Wilson) | Freshness | Conflicts | Gate failures | Cost USD |
|---|---|---|---|---|---|---|---|---|---|
| `b1r1` | `builders=1 reviewers=1` | 3 | 119.64 [58.13, 181.14] (n=3) | 0.24 [0.21, 0.27] (n=3) | 2/19 = 0.105 [0.029, 0.314] | 0 | 0 | 0 | 0.4228 [0.3504, 0.4953] (n=3) |
| `b3r1` | `builders=3 reviewers=1` | 3 | 202.71 [116.23, 289.20] (n=3) | 0.53 [0.45, 0.61] (n=3) | 4/20 = 0.200 [0.081, 0.416] | 1 | 1 | 0 | 0.4413 [0.2625, 0.6200] (n=3) |
| `b6r1` | `builders=6 reviewers=1` | 3 | 194.08 [168.86, 219.31] (n=3) | 1.01 [0.88, 1.14] (n=3) | 6/21 = 0.286 [0.138, 0.500] | 3 | 3 | 0 | 0.4581 [0.4435, 0.4727] (n=3) |
| `b6r2` | `builders=6 reviewers=2` | 3 | 247.16 [195.84, 298.48] (n=3) | 0.66 [0.36, 0.96] (n=3) | 6/21 = 0.286 [0.138, 0.500] | 3 | 3 | 0 | 0.4618 [0.4570, 0.4666] (n=3) |

## Confounds read within the data

Reviewer effort: tokens (input + output) per review, mean [95% CI] — `b1r1` 660.34 [614.72, 705.97] (n=3); `b3r1` 661.07 [617.72, 704.42] (n=3); `b6r1` 637.19 [577.03, 697.35] (n=3); `b6r2` 684.95 [658.49, 711.42] (n=3).

Task difficulty: verified-CLOSED/runs and median unit latency in minutes, per task and condition.

| Task | `b1r1` | `b3r1` | `b6r1` | `b6r2` |
|---|---|---|---|---|
| T1 | 3/3, 0.24 | 3/3, 0.50 | 3/3, 1.01 | 3/3, 0.61 |
| T2 | 3/3, 0.22 | 3/3, 0.52 | 3/3, 1.07 | 3/3, 0.58 |
| T3 | 3/3, 0.24 | 3/3, 0.55 | 3/3, 1.06 | 3/3, 0.63 |
| T4 | 3/3, 0.25 | 3/3, 0.51 | 3/3, 0.98 | 3/3, 0.60 |
| T5 | 3/3, 0.23 | 3/3, 0.54 | 3/3, 0.60 | 3/3, 0.64 |
| T6 | 3/3, 0.23 | 3/3, 0.54 | 3/3, 1.06 | 3/3, 0.56 |

## Registered metrics by condition

Every field `metrics.report_fields.condition` registers, in order.

| Metric | `b1r1` | `b3r1` | `b6r1` | `b6r2` |
|---|---|---|---|---|
| `role` | serial baseline (builders=1) | the current asserted default cap | wider parallelism, review capacity unchanged | reviewer-capacity control: the cap's 1 reviewer per 3 builders |
| `throughput_per_h` | 119.64 [58.13, 181.14] (n=3) | 202.71 [116.23, 289.20] (n=3) | 194.08 [168.86, 219.31] (n=3) | 247.16 [195.84, 298.48] (n=3) |
| `latency_median_min` | 0.24 [0.21, 0.27] (n=3) | 0.53 [0.45, 0.61] (n=3) | 1.01 [0.88, 1.14] (n=3) | 0.66 [0.36, 0.96] (n=3) |
| `latency_max_min` | 0.59 [-0.78, 1.95] (n=3) | 0.57 [0.52, 0.62] (n=3) | 1.08 [1.03, 1.12] (n=3) | 0.71 [0.37, 1.05] (n=3) |
| `rework` | 2/19 = 0.105 [0.029, 0.314] | 4/20 = 0.200 [0.081, 0.416] | 6/21 = 0.286 [0.138, 0.500] | 6/21 = 0.286 [0.138, 0.500] |
| `freshness` | 0 | 1 | 3 | 3 |
| `conflicts` | 0 | 1 | 3 | 3 |
| `gate_failures` | 0 | 0 | 0 | 0 |
| `retries` | 1 | 2 | 3 | 3 |
| `review_queue_median_min` | 0.09 [0.08, 0.11] (n=3) | 0.24 [0.20, 0.27] (n=3) | 0.38 [0.22, 0.55] (n=3) | 0.21 [0.18, 0.24] (n=3) |
| `review_queue_max_min` | 0.11 [0.09, 0.14] (n=3) | 0.38 [0.33, 0.43] (n=3) | 0.74 [0.70, 0.78] (n=3) | 0.39 [0.21, 0.57] (n=3) |
| `input_tokens` | 83.33 [68.15, 98.51] (n=3) | 88.67 [47.00, 130.34] (n=3) | 92.67 [86.93, 98.40] (n=3) | 94.00 [89.03, 98.97] (n=3) |
| `output_tokens` | 9511.00 [7854.73, 11167.27] (n=3) | 9951.00 [4905.71, 14996.29] (n=3) | 10333.67 [9680.58, 10986.75] (n=3) | 10587.67 [10276.38, 10898.96] (n=3) |
| `cache_read_input_tokens` | 633262.67 [515719.25, 750806.09] (n=3) | 675209.00 [342369.56, 1008048.44] (n=3) | 704400.00 [652490.34, 756309.66] (n=3) | 716304.33 [672766.72, 759841.95] (n=3) |
| `cache_creation_input_tokens` | 105688.67 [87641.16, 123736.18] (n=3) | 109622.00 [71629.15, 147614.85] (n=3) | 113670.67 [111811.98, 115529.35] (n=3) | 113640.67 [111495.57, 115785.77] (n=3) |
| `cost_usd` | 0.4228 [0.3504, 0.4953] (n=3) | 0.4413 [0.2625, 0.6200] (n=3) | 0.4581 [0.4435, 0.4727] (n=3) | 0.4618 [0.4570, 0.4666] (n=3) |
| `cost_per_verified_closed_usd` | 0.0705 [0.0585, 0.0825] (n=3) | 0.0735 [0.0437, 0.1034] (n=3) | 0.0763 [0.0739, 0.0788] (n=3) | 0.0770 [0.0762, 0.0777] (n=3) |
| `review_tokens_per_review` | 660.34 [614.72, 705.97] (n=3) | 661.07 [617.72, 704.42] (n=3) | 637.19 [577.03, 697.35] (n=3) | 684.95 [658.49, 711.42] (n=3) |
| `tasks` | T1: 3/3; T2: 3/3; T3: 3/3; T4: 3/3; T5: 3/3; T6: 3/3 | T1: 3/3; T2: 3/3; T3: 3/3; T4: 3/3; T5: 3/3; T6: 3/3 | T1: 3/3; T2: 3/3; T3: 3/3; T4: 3/3; T5: 3/3; T6: 3/3 | T1: 3/3; T2: 3/3; T3: 3/3; T4: 3/3; T5: 3/3; T6: 3/3 |

## Registered metrics by run

Every field `metrics.report_fields.run` registers, in order, for every run.

| Metric | `wip2-b1r1-rep1` | `wip2-b3r1-rep1` | `wip2-b6r2-rep1` | `wip2-b6r1-rep1` | `wip2-b3r1-rep2` | `wip2-b6r1-rep2` | `wip2-b1r1-rep2` | `wip2-b6r2-rep2` | `wip2-b6r1-rep3` | `wip2-b6r2-rep3` | `wip2-b3r1-rep3` | `wip2-b1r1-rep3` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `status` | complete | complete | complete | complete | complete | complete | complete | complete | complete | complete | complete | complete |
| `throughput_per_h` | 129.24/h | 162.85/h | 262.05/h | 201.13/h | 218.16/h | 182.44/h | 91.52/h | 223.58/h | 198.68/h | 255.85/h | 227.13/h | 138.15/h |
| `latency_median_min` | 0.25 | 0.50 | 0.58 | 0.97 | 0.56 | 1.07 | 0.23 | 0.80 | 0.99 | 0.60 | 0.53 | 0.23 |
| `latency_max_min` | 0.29 | 0.55 | 0.62 | 1.07 | 0.60 | 1.10 | 1.22 | 0.87 | 1.06 | 0.65 | 0.56 | 0.25 |
| `rework` | 0/6 | 4/8 | 2/7 | 2/7 | 0/6 | 2/7 | 2/7 | 2/7 | 2/7 | 2/7 | 0/6 | 0/6 |
| `freshness` | 0 | 1 | 1 | 1 | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 0 |
| `conflicts` | 0 | 1 | 1 | 1 | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 0 |
| `gate_failures` | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `retries` | 0 | 2 | 1 | 1 | 0 | 1 | 1 | 1 | 1 | 1 | 0 | 0 |
| `review_queue_median_min` | 0.10 | 0.22 | 0.20 | 0.32 | 0.25 | 0.45 | 0.09 | 0.20 | 0.37 | 0.22 | 0.24 | 0.09 |
| `review_queue_max_min` | 0.12 | 0.36 | 0.32 | 0.74 | 0.40 | 0.72 | 0.10 | 0.47 | 0.75 | 0.38 | 0.38 | 0.11 |
| `input_tokens` | 78 | 108 | 94 | 94 | 78 | 94 | 90 | 92 | 90 | 96 | 80 | 82 |
| `output_tokens` | 9203 | 12296 | 10662 | 10350 | 8773 | 10588 | 10276 | 10658 | 10063 | 10443 | 8784 | 9054 |
| `cache_read_input_tokens` | 590349 | 829567 | 715134 | 716802 | 589112 | 716122 | 684001 | 699394 | 680276 | 734385 | 606948 | 625438 |
| `cache_creation_input_tokens` | 101872 | 127280 | 112669 | 114482 | 100936 | 113522 | 114066 | 113933 | 113008 | 114320 | 100650 | 101128 |
| `cost_usd` | 0.405900900000000000 | 0.524332700000000013 | 0.459993900000000019 | 0.461573199999999998 | 0.399137200000000012 | 0.461485200000000002 | 0.456505100000000028 | 0.461535900000000004 | 0.451357600000000024 | 0.463860500000000020 | 0.400319800000000013 | 0.406067800000000008 |
| `cost_per_verified_closed_usd` | 0.0677 | 0.0874 | 0.0767 | 0.0769 | 0.0665 | 0.0769 | 0.0761 | 0.0769 | 0.0752 | 0.0773 | 0.0667 | 0.0677 |
| `review_tokens_per_review` | 677.33 | 677.38 | 672.71 | 614.14 | 663.17 | 662.43 | 640.86 | 690.00 | 635.00 | 692.14 | 642.67 | 662.83 |
| `parked` | none | none | none | none | none | none | none | none | none | none | none | none |

## Runs (every run, failed, stopped and parked included)

| Run | Condition | Tier | Status | Throughput | Latency median/max min | Rework | Freshness | Conflicts | Retries | Cost USD | Compliant |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `wip2-b1r1-rep1` | `b1r1` | live-unreviewed | complete | 129.24/h | 0.25/0.29 | 0/6 | 0 | 0 | 0 | 0.405900900000000000 | yes |
| `wip2-b3r1-rep1` | `b3r1` | live-unreviewed | complete | 162.85/h | 0.50/0.55 | 4/8 | 1 | 1 | 2 | 0.524332700000000013 | yes |
| `wip2-b6r2-rep1` | `b6r2` | live-unreviewed | complete | 262.05/h | 0.58/0.62 | 2/7 | 1 | 1 | 1 | 0.459993900000000019 | yes |
| `wip2-b6r1-rep1` | `b6r1` | live-unreviewed | complete | 201.13/h | 0.97/1.07 | 2/7 | 1 | 1 | 1 | 0.461573199999999998 | yes |
| `wip2-b3r1-rep2` | `b3r1` | live-unreviewed | complete | 218.16/h | 0.56/0.60 | 0/6 | 0 | 0 | 0 | 0.399137200000000012 | yes |
| `wip2-b6r1-rep2` | `b6r1` | live-unreviewed | complete | 182.44/h | 1.07/1.10 | 2/7 | 1 | 1 | 1 | 0.461485200000000002 | yes |
| `wip2-b1r1-rep2` | `b1r1` | live-unreviewed | complete | 91.52/h | 0.23/1.22 | 2/7 | 0 | 0 | 1 | 0.456505100000000028 | yes |
| `wip2-b6r2-rep2` | `b6r2` | live-unreviewed | complete | 223.58/h | 0.80/0.87 | 2/7 | 1 | 1 | 1 | 0.461535900000000004 | yes |
| `wip2-b6r1-rep3` | `b6r1` | live-unreviewed | complete | 198.68/h | 0.99/1.06 | 2/7 | 1 | 1 | 1 | 0.451357600000000024 | yes |
| `wip2-b6r2-rep3` | `b6r2` | live-unreviewed | complete | 255.85/h | 0.60/0.65 | 2/7 | 1 | 1 | 1 | 0.463860500000000020 | yes |
| `wip2-b3r1-rep3` | `b3r1` | live-unreviewed | complete | 227.13/h | 0.53/0.56 | 0/6 | 0 | 0 | 0 | 0.400319800000000013 | yes |
| `wip2-b1r1-rep3` | `b1r1` | live-unreviewed | complete | 138.15/h | 0.23/0.25 | 0/6 | 0 | 0 | 0 | 0.406067800000000008 | yes |

## Per-wave WIP-curve rows (derived by events.py from each run's record)

### `wip2-b1r1-rep1`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=1 reviewers=1` | `throughput=134.85/h` | `latency_median=0.25m latency_max=0.25m` | `rework=0/1` | `freshness=0` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=133.05/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=3` | `builders=1 reviewers=1` | `throughput=125.48/h` | `latency_median=0.28m latency_max=0.28m` | `rework=0/1` | `freshness=0` |
| `wave=4` | `builders=1 reviewers=1` | `throughput=138.04/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=5` | `builders=1 reviewers=1` | `throughput=114.30/h` | `latency_median=0.29m latency_max=0.29m` | `rework=0/1` | `freshness=0` |
| `wave=6` | `builders=1 reviewers=1` | `throughput=132.78/h` | `latency_median=0.25m latency_max=0.25m` | `rework=0/1` | `freshness=0` |

### `wip2-b3r1-rep1`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=3 reviewers=1` | `throughput=153.62/h` | `latency_median=0.52m latency_max=0.55m` | `rework=1/3` | `freshness=0` |
| `wave=2` | `builders=3 reviewers=1` | `throughput=154.04/h` | `latency_median=0.54m latency_max=0.54m` | `rework=2/3` | `freshness=0` |
| `wave=3` | `builders=3 reviewers=1` | `throughput=184.47/h` | `latency_median=0.41m latency_max=0.45m` | `rework=1/2` | `freshness=1` |

### `wip2-b6r2-rep1`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=2` | `throughput=310.55/h` | `latency_median=0.58m latency_max=0.62m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=2` | `throughput=147.16/h` | `latency_median=0.23m latency_max=0.23m` | `rework=1/1` | `freshness=1` |

### `wip2-b6r1-rep1`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=1` | `throughput=214.62/h` | `latency_median=1.00m latency_max=1.07m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=1` | `throughput=153.04/h` | `latency_median=0.24m latency_max=0.24m` | `rework=1/1` | `freshness=1` |

### `wip2-b3r1-rep2`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=3 reviewers=1` | `throughput=213.49/h` | `latency_median=0.57m latency_max=0.60m` | `rework=0/3` | `freshness=0` |
| `wave=2` | `builders=3 reviewers=1` | `throughput=223.04/h` | `latency_median=0.55m latency_max=0.57m` | `rework=0/3` | `freshness=0` |

### `wip2-b6r1-rep2`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=1` | `throughput=204.33/h` | `latency_median=1.08m latency_max=1.10m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=1` | `throughput=118.81/h` | `latency_median=0.26m latency_max=0.26m` | `rework=1/1` | `freshness=1` |

### `wip2-b1r1-rep2`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=1 reviewers=1` | `throughput=132.81/h` | `latency_median=0.25m latency_max=0.25m` | `rework=0/1` | `freshness=0` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=136.64/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=3` | `builders=1 reviewers=1` | `throughput=0.00/h` | `latency_median=unavailable latency_max=unavailable` | `rework=1/1` | `freshness=0` |
| `wave=4` | `builders=1 reviewers=1` | `throughput=42.07/h` | `latency_median=1.22m latency_max=1.22m` | `rework=1/1` | `freshness=0` |
| `wave=5` | `builders=1 reviewers=1` | `throughput=139.20/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=6` | `builders=1 reviewers=1` | `throughput=163.98/h` | `latency_median=0.22m latency_max=0.22m` | `rework=0/1` | `freshness=0` |
| `wave=7` | `builders=1 reviewers=1` | `throughput=150.59/h` | `latency_median=0.21m latency_max=0.21m` | `rework=0/1` | `freshness=0` |

### `wip2-b6r2-rep2`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=2` | `throughput=248.06/h` | `latency_median=0.82m latency_max=0.87m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=2` | `throughput=149.70/h` | `latency_median=0.24m latency_max=0.24m` | `rework=1/1` | `freshness=1` |

### `wip2-b6r1-rep3`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=1` | `throughput=217.06/h` | `latency_median=1.00m latency_max=1.06m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=1` | `throughput=139.57/h` | `latency_median=0.22m latency_max=0.22m` | `rework=1/1` | `freshness=1` |

### `wip2-b6r2-rep3`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=6 reviewers=2` | `throughput=302.71/h` | `latency_median=0.61m latency_max=0.65m` | `rework=1/6` | `freshness=0` |
| `wave=2` | `builders=6 reviewers=2` | `throughput=144.21/h` | `latency_median=0.24m latency_max=0.24m` | `rework=1/1` | `freshness=1` |

### `wip2-b3r1-rep3`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=3 reviewers=1` | `throughput=233.04/h` | `latency_median=0.51m latency_max=0.53m` | `rework=0/3` | `freshness=0` |
| `wave=2` | `builders=3 reviewers=1` | `throughput=221.51/h` | `latency_median=0.56m latency_max=0.56m` | `rework=0/3` | `freshness=0` |

### `wip2-b1r1-rep3`

| Wave | WIP setting | Builder throughput | Verification latency | Rework rate | Freshness violations |
|---|---|---|---|---|---|
| `wave=1` | `builders=1 reviewers=1` | `throughput=140.42/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=2` | `builders=1 reviewers=1` | `throughput=139.65/h` | `latency_median=0.23m latency_max=0.23m` | `rework=0/1` | `freshness=0` |
| `wave=3` | `builders=1 reviewers=1` | `throughput=121.73/h` | `latency_median=0.25m latency_max=0.25m` | `rework=0/1` | `freshness=0` |
| `wave=4` | `builders=1 reviewers=1` | `throughput=154.46/h` | `latency_median=0.22m latency_max=0.22m` | `rework=0/1` | `freshness=0` |
| `wave=5` | `builders=1 reviewers=1` | `throughput=129.78/h` | `latency_median=0.24m latency_max=0.24m` | `rework=0/1` | `freshness=0` |
| `wave=6` | `builders=1 reviewers=1` | `throughput=148.07/h` | `latency_median=0.24m latency_max=0.24m` | `rework=0/1` | `freshness=0` |

## Non-compliance and binding


## Recommendation

Status: **keep** — no pre-registered criterion for a change is met (a null or negative result).

Computed from the 12 protocol-compliant run(s) alone, whatever the basis of the rows above.

Authority: the rule yields a recommendation only; changing a cap is its own human-reviewed policy change citing the report.

## Limits on generalizing

- one synthetic, six-task, stdlib-only Python package; larger tasks, other languages and real repositories may bend the curve differently
- one host, the posix provider, one harness and one model; Orca and other providers schedule and isolate differently
- agent reviewers only; human review capacity, the real serial bottleneck the attention budget names, is not measured
- three runs per condition: enough to see a large effect, not to rule out a small one
