"""Real-time market data source adapters.

The Eastmoney push2 adapter intentionally builds the request URL explicitly. In
particular, ``fields`` must retain its comma separators; Eastmoney accepts the
verified browser-style URL but some deployments reject ``fields=f43%2Cf44``.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from urllib.parse import quote
from urllib.request import Request, urlopen

from .money import text


EASTMONEY_URL = 'https://push2.eastmoney.com/api/qt/stock/get'
 # With fltt=2, f43/f44/f45/f46/f60 are actual prices. f47/f48 are
 # volume and amount. f169 is change amount and f170 is change percent.
FIELDS = (
    'f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,'
    'f19,f20,f21,f22,f23,f24,f25,f26,f27,f28,f29,f30,'
    'f31,f32,f33,f34,f35,f36,f37,f38,f39,f40'
)
HEADERS = {
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://quote.eastmoney.com/',
    'User-Agent': (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36'
    ),
}


def _secid(symbol):
    raw = str(symbol).upper().strip().replace(' ', '')
    bare = raw.split('.', 1)[0]
    if raw.endswith('.XSHG') or bare.startswith(('5', '6', '9')):
        return '1.' + bare
    return '0.' + bare


def _bare_symbol(symbol):
    return str(symbol).upper().strip().replace(' ', '').split('.', 1)[0]


def _field(item, key, default=None):
    value = item.get(key, default)
    return None if value in (None, '-', '') else value


def _price(item, key):
    value = _field(item, key)
    return None if value is None else text(Decimal(str(value)))


def normalize_quote(item, received_at, source='eastmoney.push2'):
    """Convert one Eastmoney ``data`` object to the live-quote contract.

    ``live_quotes`` persists the contract fields, while the additional OHLC,
    name, and change fields make the source result explainable to callers and
    deterministic fake-opener tests.
    """
    code = str(_field(item, 'f57', _field(item, 'symbol', '')))
    if not code:
        raise ValueError('source_quote_symbol_missing')
    price_value = _price(item, 'f43')
    if price_value is None:
        raise ValueError('source_quote_price_missing:' + code)

    # Eastmoney's order book uses f19/f20 for bid quantity/price and
    # f31/f32 for ask quantity/price. Keep compatibility with reduced fake
    # responses that used f19/f20 as bid/ask prices.
    if _field(item, 'f32') is not None:
        bid = _price(item, 'f20')
        ask = _price(item, 'f32')
    else:
        bid = _price(item, 'f19')
        ask = _price(item, 'f20')
    change_amount = _field(item, 'f169')
    change_pct = _field(item, 'f170')
    name = str(_field(item, 'f58', ''))
    previous = _price(item, 'f60')

    return {
        'symbol': code,
        'name': name,
        'quote_time': received_at,
        'price': price_value,
        'current': price_value,
        'open': _price(item, 'f46'),
        'high': _price(item, 'f44'),
        'low': _price(item, 'f45'),
        'bid': bid,
        'ask': ask,
        'bid_volume': text(_field(item, 'f19', 0)),
        'ask_volume': text(_field(item, 'f31', 0)),
        'volume': text(_field(item, 'f47', 0)),
        'amount': text(_field(item, 'f48', 0)),
        'prev_close': previous,
        'change_pct': None if change_pct is None else text(Decimal(str(change_pct))),
        'change': None if change_amount is None else text(Decimal(str(change_amount))),
        'asset_type': 'etf' if code.startswith(('1', '5')) else 'stock',
        'source': source,
        'status': 'LIVE',
        'source_error': None,
        'received_at': received_at,
        'updated_at': received_at,
    }


class EastmoneyPush2Source:
    name = 'eastmoney.push2'

    def __init__(self, url=EASTMONEY_URL, timeout=8, opener=None, attempts=2, retry_backoff=0.25):
        self.url, self.timeout, self.opener = url, timeout, opener or urlopen
        self.attempts = max(1, int(attempts))
        self.retry_backoff = max(0, float(retry_backoff))
        self.last_errors = {}

    def _request_url(self, symbol):
        # Do not use urlencode here: its normal behaviour changes the verified
        # ``fields=f43,f44,...`` into ``fields=f43%2Cf44,...``.
        separator = '&' if '?' in self.url else '?'
        return (
            f'{self.url}{separator}invt=2&fltt=2&fields={FIELDS}'
            f'&secid={quote(_secid(symbol), safe=".")}'
        )

    def _fetch_one(self, symbol, received):
        last_error = None
        for attempt in range(self.attempts):
            try:
                request = Request(self._request_url(symbol), headers=dict(HEADERS), method='GET')
                response = self.opener(request, timeout=self.timeout)
                try:
                    raw = response.read()
                finally:
                    close = getattr(response, 'close', None)
                    if close:
                        close()
                if isinstance(raw, bytes):
                    raw = raw.decode('utf-8')
                payload = json.loads(raw)
                if payload.get('rc') not in (None, 0):
                    raise ValueError('eastmoney_rc:' + str(payload.get('rc')))
                item = payload.get('data')
                if not item:
                    raise ValueError('eastmoney_quote_missing:' + _bare_symbol(symbol))
                return normalize_quote(item, received, self.name)
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.attempts and self.retry_backoff:
                    time.sleep(self.retry_backoff * (attempt + 1))
        raise last_error or RuntimeError('eastmoney_quote_failed:' + _bare_symbol(symbol))

    def fetch(self, symbols):
        symbols = [str(x) for x in (symbols or [])]
        self.last_errors = {}
        if not symbols:
            return []
        from datetime import datetime, timezone

        received = datetime.now(timezone.utc).isoformat()
        rows = []
        for symbol in symbols:
            try:
                rows.append(self._fetch_one(symbol, received))
            except Exception as exc:
                # A bad symbol must not discard good quotes from the same
                # refresh. MarketService records this as SOURCE_ERROR/STALE.
                self.last_errors[_bare_symbol(symbol)] = str(exc)
        return rows

    def healthcheck(self):
        try:
            rows = self.fetch(['000001'])
            if rows:
                return {'source': self.name, 'reachable': True, 'error': None}
            return {
                'source': self.name,
                'reachable': False,
                'error': self.last_errors.get('000001', 'no_quote'),
            }
        except Exception as exc:
            return {'source': self.name, 'reachable': False, 'error': str(exc)}


EastmoneySource = EastmoneyPush2Source
