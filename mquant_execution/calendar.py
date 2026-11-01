from datetime import date, datetime, timedelta, time

def parse_date(value):
    if isinstance(value, datetime): return value.date()
    if isinstance(value, date): return value
    return date.fromisoformat(str(value)[:10])

def is_trading_day(value): return parse_date(value).weekday() < 5

def next_trading_day(value):
    d = parse_date(value) + timedelta(days=1)
    while not is_trading_day(d): d += timedelta(days=1)
    return d

def is_session(value):
    if value is None: return True
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
    t = dt.time()
    return is_trading_day(dt) and (time(9,30) <= t <= time(11,30) or time(13,0) <= t <= time(15,0))

def available_on(buy_date, as_of): return parse_date(as_of) >= next_trading_day(buy_date)
