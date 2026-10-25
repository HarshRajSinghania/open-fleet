# Audit findings

- F-1: src/money.py round_cents() rounds 2.675 down to 2.67; it should round half-up to 2.68.
- F-2: src/money.py split() drops the remainder: split(100, 3) sums to 99 cents.
