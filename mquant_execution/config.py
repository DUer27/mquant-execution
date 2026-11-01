from dataclasses import dataclass, asdict
from decimal import Decimal
import json

@dataclass
class AccountConfig:
    commission_rate: Decimal = Decimal("0.0003")
    min_commission: Decimal = Decimal("5")
    stock_stamp_tax: Decimal = Decimal("0.001")
    etf_stamp_tax: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("5")
    max_order_value: Decimal = Decimal("200000")
    max_symbol_weight: Decimal = Decimal("0.35")
    max_turnover: Decimal = Decimal("2")
    minimum_cash_reserve: Decimal = Decimal("0.05")
    max_orders: int = 100
    max_participation: Decimal = Decimal("0.1")
    default_lot_size: int = 100
    allow_fractional_etf: bool = False
    def to_json(self):
        return json.dumps({k: str(v) if isinstance(v, Decimal) else v for k,v in asdict(self).items()}, sort_keys=True)
    @classmethod
    def from_json(cls, value):
        if not value: return cls()
        data = json.loads(value) if isinstance(value, str) else value
        obj = cls()
        for key in asdict(obj):
            if key in data:
                old = getattr(obj, key)
                setattr(obj, key, type(old)(data[key]))
        return obj
