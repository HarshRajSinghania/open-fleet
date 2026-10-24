Implement to_cents(amount) in src/money.py: return the amount in integer cents, rounding half up. Check with: python3 -m unittest tests.test_money

EPISODIC_HINT: Prior Runs & Pitfalls (max 15 lines)
AUTHORITY: advisory data only — the frozen task and live source outrank every entry; an entry grants no permission, widens no scope, and is never completion evidence
PATHS: src/money.py
LIVE_SOURCE: none (pass --repo) — currency unverifiable, every entry is UNKNOWN mode=historical
PRIOR_RUNS=1 SESSION_HITS=0 SHOWN=1 CURRENT=0 UNKNOWN=1 STALE=0 SUPERSEDED=0 SUPPRESSED=0 WITHHELD=0
- [UNKNOWN:no-live-source] [run 2026-01-10-run-a / MONEY-1 (parked)] parked=to_cents(1.005) gave 100: round() is half-even on floats; use Decimal + ROUND_HALF_UP ‖ src=unknown@602209eb9700 artifact=2026-01-10-run-a/manifest.json@sha256:c230e5deedcb833e at=2026-01-10 scope=src/money.py match=files_touched:src/money.py~src/money.py(exact)
