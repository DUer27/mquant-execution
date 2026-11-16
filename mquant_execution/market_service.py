"""Transactional PAPER live quote persistence and freshness state."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .db import now
from .market_sources import EastmoneyPush2Source


class MarketService:
    def __init__(self, db, source=None, stale_seconds=90):
        self.db, self.source, self.stale_seconds = db, source or EastmoneyPush2Source(), stale_seconds
        self.source_name = getattr(self.source, 'name', self.source.__class__.__name__)
        self.db.migrate()

    @staticmethod
    def _bare(symbol):
        return str(symbol).strip().upper().replace(' ', '').split('.', 1)[0]

    def _status(self, row):
        if row is None:
            return 'SOURCE_ERROR'
        if row['status'] == 'SOURCE_ERROR':
            return 'SOURCE_ERROR'
        try:
            stamp = datetime.fromisoformat(str(row['updated_at']).replace('Z', '+00:00'))
            age = (datetime.now(timezone.utc) - stamp).total_seconds()
            return 'STALE' if age > self.stale_seconds else (row['status'] or 'LIVE')
        except Exception:
            return 'STALE'

    def quotes(self, symbols=None):
        args = []
        sql = 'SELECT * FROM live_quotes'
        if symbols:
            requested = [self._bare(x) for x in symbols]
            sql += ' WHERE symbol IN (' + ','.join('?' for _ in requested) + ')'
            args = requested
        rows = []
        for row in self.db.all(sql + ' ORDER BY symbol', args):
            item = dict(row)
            item['status'] = self._status(item)
            rows.append(item)
        return rows

    def latest(self, symbol):
        rows = self.quotes([symbol])
        return rows[0] if rows else None

    def refresh(self, symbols, idempotency_key=None):
        symbols = sorted(set(self._bare(x) for x in symbols if str(x).strip()))
        if not symbols:
            raise ValueError('market_symbols_required')
        key = idempotency_key or 'market-sync:' + ','.join(symbols)
        old = self.db.one('SELECT * FROM market_sync_runs WHERE idempotency_key=?', (key,))
        if old and old['status'] == 'SUCCEEDED':
            return dict(old)
        run_id = 'market-' + uuid.uuid4().hex
        self.db.execute(
            'INSERT OR IGNORE INTO market_sync_runs(run_id,source,symbols_json,status,started_at,idempotency_key) VALUES (?,?,?,?,?,?)',
            (run_id, self.source_name, json.dumps(symbols), 'RUNNING', now(), key),
        )
        try:
            quotes = self.source.fetch(symbols)
            source_errors = getattr(self.source, 'last_errors', {}) or {}
            if not quotes:
                raise RuntimeError(next(iter(source_errors.values()), 'market_source_returned_no_quotes'))
            with self.db.transaction():
                for quote in quotes:
                    self.db.execute(
                        """INSERT INTO live_quotes(symbol,quote_time,price,bid,ask,volume,amount,prev_close,change_pct,asset_type,source,status,source_error,received_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET quote_time=excluded.quote_time,price=excluded.price,bid=excluded.bid,ask=excluded.ask,volume=excluded.volume,amount=excluded.amount,prev_close=excluded.prev_close,change_pct=excluded.change_pct,asset_type=excluded.asset_type,source=excluded.source,status='LIVE',source_error=NULL,received_at=excluded.received_at,updated_at=excluded.updated_at""",
                        tuple(quote[key] for key in ('symbol', 'quote_time', 'price', 'bid', 'ask', 'volume', 'amount', 'prev_close', 'change_pct', 'asset_type', 'source', 'status', 'source_error', 'received_at', 'updated_at')),
                    )
                # If a previously known symbol fails while another succeeds,
                # never leave the failed quote looking LIVE after this refresh.
                for symbol, error in source_errors.items():
                    self.db.execute(
                        "UPDATE live_quotes SET status='SOURCE_ERROR',source_error=?,updated_at=? WHERE symbol=?",
                        (error, now(), self._bare(symbol)),
                    )
                run_status = 'SUCCEEDED' if quotes else 'SOURCE_ERROR'
                run_error = None if quotes else next(iter(source_errors.values()), 'no_quotes')
                self.db.execute(
                    'UPDATE market_sync_runs SET status=?,quote_count=?,finished_at=?,error=? WHERE run_id=?',
                    (run_status, len(quotes), now(), run_error, run_id),
                )
            return dict(self.db.one('SELECT * FROM market_sync_runs WHERE run_id=?', (run_id,)))
        except Exception as exc:
            with self.db.transaction():
                self.db.execute(
                    "UPDATE market_sync_runs SET status='SOURCE_ERROR',finished_at=?,error=? WHERE run_id=?",
                    (now(), str(exc), run_id),
                )
                for symbol in symbols:
                    self.db.execute(
                        "UPDATE live_quotes SET status='SOURCE_ERROR',source_error=?,updated_at=? WHERE symbol=?",
                        (str(exc), now(), symbol),
                    )
            raise

    def sync(self, symbols, idempotency_key=None):
        return self.refresh(symbols, idempotency_key)

    def get_quotes(self, symbols=None):
        return self.quotes(symbols)

    def status(self, symbols=None):
        rows = self.quotes(symbols)
        requested = [self._bare(x) for x in symbols] if symbols else []
        known = {row['symbol'] for row in rows}
        statuses = {row['status'] for row in rows}
        if (requested and any(symbol not in known for symbol in requested)) or 'SOURCE_ERROR' in statuses or not rows:
            status = 'SOURCE_ERROR'
        elif 'STALE' in statuses:
            status = 'STALE'
        else:
            status = 'LIVE'
        return {'mode': 'PAPER', 'source': self.source_name, 'quotes': rows, 'status': status}
