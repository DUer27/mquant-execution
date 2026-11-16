"""M-quant strategy catalog synchronization and PAPER activation."""
from __future__ import annotations

import json
import os
import uuid

from .db import now
from .mquant_client import MQuantClient, MQuantOffline


class StrategySyncService:
    def __init__(self, db, client=None):
        self.db = db
        self.client = client or MQuantClient()
        self.db.migrate()

    @staticmethod
    def _items(payload):
        """Accept current execution-catalog and older wrapped catalog shapes."""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ('strategies', 'catalog', 'items', 'data', 'results'):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
                if isinstance(value, dict):
                    nested = StrategySyncService._items(value)
                    if nested:
                        return nested
        return []

    @staticmethod
    def _signal(payload):
        """Unwrap signal/data/result envelopes without accepting a bad payload."""
        value = payload
        for _ in range(4):
            if not isinstance(value, dict):
                break
            if 'schema_version' in value and 'action' in value:
                return value
            nested = next((value[key] for key in ('signal', 'data', 'result') if key in value), None)
            if nested is None:
                break
            value = nested
        return value

    def catalog(self):
        return [dict(x) for x in self.db.all('SELECT * FROM strategy_catalog ORDER BY strategy_id,strategy_version')]

    def sync_catalog(self, idempotency_key=None, payload=None):
        return self.sync(idempotency_key, payload)

    def sync(self, idempotency_key=None, payload=None):
        key = idempotency_key or 'strategy-sync:' + str(os.getenv('MQUANT_URL', ''))
        old = self.db.one('SELECT * FROM strategy_sync_runs WHERE idempotency_key=?', (key,))
        if old and old['status'] == 'SUCCEEDED':
            return dict(old)
        run_id = 'strategy-sync-' + uuid.uuid4().hex
        self.db.execute(
            'INSERT OR IGNORE INTO strategy_sync_runs(run_id,status,source,started_at,idempotency_key) VALUES (?,?,?,?,?)',
            (run_id, 'RUNNING', 'M-quant', now(), key),
        )
        try:
            data = payload if payload is not None else self.client.catalog()
            items = self._items(data)
            stored = 0
            with self.db.transaction():
                for item in items:
                    strategy_id = str(item.get('strategy_id', item.get('id', ''))).strip()
                    if not strategy_id:
                        continue
                    version = str(item.get('strategy_version', item.get('version', '')))
                    name = item.get('name', item.get('strategy_name', strategy_id))
                    description = item.get('description', item.get('runnable_reason', ''))
                    definition = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                    timestamp = now()
                    self.db.execute(
                        '''INSERT INTO strategy_catalog(strategy_id,strategy_version,name,description,status,source,definition_json,synced_at,updated_at)
                        VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(strategy_id,strategy_version) DO UPDATE SET name=excluded.name,description=excluded.description,status=excluded.status,source=excluded.source,definition_json=excluded.definition_json,synced_at=excluded.synced_at,updated_at=excluded.updated_at''',
                        (
                            strategy_id, version, str(name), str(description),
                            str(item.get('status', 'AVAILABLE')), 'M-quant', definition,
                            timestamp, timestamp,
                        ),
                    )
                    stored += 1
                self.db.execute(
                    "UPDATE strategy_sync_runs SET status='SUCCEEDED',strategies_count=?,finished_at=?,error=NULL WHERE run_id=?",
                    (stored, now(), run_id),
                )
            return dict(self.db.one('SELECT * FROM strategy_sync_runs WHERE run_id=?', (run_id,)))
        except Exception as exc:
            self.db.execute(
                "UPDATE strategy_sync_runs SET status='SOURCE_ERROR',finished_at=?,error=? WHERE run_id=?",
                (now(), str(exc), run_id),
            )
            raise

    def activate_strategy(self, account_id, strategy_id, strategy_version='', parameters=None, idempotency_key=None):
        return self.activate(account_id, strategy_id, strategy_version, parameters, idempotency_key)

    def activate(self, account_id, strategy_id, strategy_version='', parameters=None, idempotency_key=None):
        self.db.account(account_id)
        if not strategy_id:
            raise ValueError('strategy_id_required')
        key = idempotency_key or f'activate:{account_id}:{strategy_id}:{strategy_version}'
        existing = self.db.one('SELECT * FROM strategy_activations WHERE idempotency_key=?', (key,))
        if existing:
            return dict(existing)
        with self.db.transaction():
            self.db.execute(
                "UPDATE strategy_activations SET status='INACTIVE' WHERE account_id=? AND status='ACTIVE'",
                (account_id,),
            )
            self.db.execute(
                'INSERT INTO strategy_activations(account_id,strategy_id,strategy_version,status,parameters_json,activated_at,idempotency_key) VALUES (?,?,?,?,?,?,?)',
                (
                    account_id, strategy_id, str(strategy_version), 'ACTIVE',
                    json.dumps(parameters or {}, sort_keys=True), now(), key,
                ),
            )
        return dict(self.db.one('SELECT * FROM strategy_activations WHERE idempotency_key=?', (key,)))

    def current(self, account_id):
        self.db.account(account_id)
        row = self.db.one(
            "SELECT * FROM strategy_activations WHERE account_id=? AND status='ACTIVE' ORDER BY activated_at DESC LIMIT 1",
            (account_id,),
        )
        return dict(row) if row else None

    def run_once(self, account_id, parameters=None):
        current = self.current(account_id)
        if not current:
            raise ValueError('no_active_strategy')
        configured = json.loads(current['parameters_json'] or '{}')
        configured.update(parameters or {})
        try:
            response = self.client.run_once(current['strategy_id'], current['strategy_version'], configured)
        except MQuantOffline:
            raise
        signal = self._signal(response)
        if not isinstance(signal, dict) or not signal.get('action'):
            raise ValueError('mquant_run_once_signal_required')

        action = str(signal.get('action', '')).upper()
        gate = str(signal.get('gate_status', '')).upper()
        if action == 'RECORD_ONLY' or gate == 'RECORD_ONLY':
            # Record an audit marker, but never pass this payload to SignalImporter:
            # that is the boundary which prevents planner/orders from seeing it.
            self.db.audit(
                account_id, 'STRATEGY_RECORD_ONLY', 'strategy', current['strategy_id'],
                {'strategy_version': current['strategy_version'], 'signal': signal},
            )
            return {'status': 'RECORD_ONLY', 'blocked': True, 'signal': signal}
        if action != 'TARGET_PORTFOLIO':
            raise ValueError('mquant_signal_action_unsupported:' + action)
        if signal.get('expires_at'):
            from .protocol import parse_time
            from datetime import datetime, timezone
            if parse_time(signal['expires_at']) <= datetime.now(timezone.utc):
                self.db.audit(account_id, 'STRATEGY_EXPIRED', 'strategy', current['strategy_id'], {'signal': signal})
                return {'status': 'EXPIRED', 'blocked': True, 'signal': signal}

        from .importer import SignalImporter
        row, status = SignalImporter(self.db).import_data(signal, account_id)
        return {'status': status, 'blocked': False, 'signal': row}
