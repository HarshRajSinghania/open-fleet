from decimal import ROUND_HALF_UP, Decimal


def round_cents(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def split(total_cents: int, parts: int) -> list[int]:
    share, extra = divmod(total_cents, parts)
    return [share + (1 if i < extra else 0) for i in range(parts)]
