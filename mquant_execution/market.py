"""Market-bar symbol normalization and lookup helpers."""
from __future__ import annotations


def normalize_symbol(value):
    value = str(value or '').strip().upper()
    if not value:
        raise ValueError('bar_symbol_required')
    value = value.replace(' ', '')
    if value.endswith('.XSHE') or value.endswith('.XSHG'):
        return value
    # AkShare commonly emits bare six-digit A-share codes.  Keep other
    # identifiers unchanged so existing quote/signal contracts remain valid.
    if len(value) == 6 and value.isdigit():
        return value + ('.XSHG' if value[0] in '568' else '.XSHE')
    return value


def symbol_variants(value):
    raw = str(value or '').strip().upper().replace(' ', '')
    canonical = normalize_symbol(raw)
    variants = [canonical]
    if raw and raw not in variants:
        variants.append(raw)
    if canonical.endswith('.XSHE') or canonical.endswith('.XSHG'):
        bare = canonical.rsplit('.', 1)[0]
        if bare not in variants:
            variants.append(bare)
    return variants


def market_bar(db, symbol, bar_date=None):
    variants = symbol_variants(symbol)
    placeholders = ','.join('?' for _ in variants)
    args = list(variants)
    sql = f'SELECT * FROM market_bars WHERE symbol IN ({placeholders})'
    if bar_date is not None:
        sql += ' AND bar_date=?'
        args.append(str(bar_date)[:10])
    else:
        sql += ' ORDER BY bar_date DESC LIMIT 1'
    if bar_date is not None:
        sql += ' LIMIT 1'
    return db.one(sql, args)


def latest_market_bar(db, symbol, bar_date=None):
    variants = symbol_variants(symbol)
    placeholders = ','.join('?' for _ in variants)
    args = list(variants)
    sql = f'SELECT * FROM market_bars WHERE symbol IN ({placeholders})'
    if bar_date is not None:
        sql += ' AND bar_date<=?'
        args.append(str(bar_date)[:10])
    sql += ' ORDER BY bar_date DESC LIMIT 1'
    return db.one(sql, args)
