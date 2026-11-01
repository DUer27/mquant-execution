from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

ZERO = Decimal("0")
CENT = Decimal("0.0001")

def dec(value) -> Decimal:
    if isinstance(value, Decimal): return value
    return Decimal(str(value))

def money(value) -> Decimal:
    return dec(value).quantize(CENT, rounding=ROUND_HALF_UP)

def floor_lot(value, lot=100) -> int:
    value = dec(value)
    return max(0, int(value // int(lot)) * int(lot))

def text(value) -> str:
    return format(money(value), 'f')
