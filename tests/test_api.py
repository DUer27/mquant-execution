import json
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer

from mquant_execution.api import APIHandler
from mquant_execution.db import Database
from mquant_execution.service import ExecutionService


class APITests(unittest.TestCase):
    def _server(self, service):
        APIHandler.service = service
        server = ThreadingHTTPServer(('127.0.0.1', 0), APIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, 'http://127.0.0.1:%s' % server.server_port

    def _get(self, base, path):
        with urllib.request.urlopen(base + path) as response:
            return json.load(response)

    def _post(self, base, path, payload):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'},
        )
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def _signal(self, action='TARGET_PORTFOLIO', signal_id='sig'):
        return {
            'schema_version': 'signal.v1',
            'signal_id': signal_id,
            'strategy_id': 'api-test',
            'generated_at': '2026-09-20T00:00:00Z',
            'signal_date': '2026-09-20',
            'effective_at': '2026-09-21T09:30:00+08:00',
            'expires_at': '2030-01-01T00:00:00Z',
            'action': action,
            'gate_status': 'ready',
            'planned_weight': '0.3',
            'cash_target_weight': '0.7',
            'portfolio': [{'symbol': '510300', 'asset_type': 'etf', 'target_weight': '0.3'}],
            'provenance': {'source': 'api-test', 'data_policy': 'synthetic'},
        }

    def test_health_and_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ExecutionService(Database(Path(directory) / 'a.db'))
            service.db.create_account('paper')
            server, base = self._server(service)
            try:
                self.assertEqual(self._get(base, '/api/v1/health')['mode'], 'PAPER')
                dashboard = self._get(base, '/api/v1/accounts/paper/dashboard')
                self.assertEqual(dashboard['account_id'], 'paper')
                self.assertEqual(dashboard['account']['account_id'], 'paper')
                self.assertEqual(dashboard['cash'], dashboard['available_cash'])
            finally:
                server.shutdown()
                server.server_close()

    def test_monitoring_reads_and_dashboard_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            service = ExecutionService(Database(directory / 'a.db'))
            service.db.create_account('paper')
            service.deposit('paper', '100000', 'initial')
            quote_file = directory / 'quotes.json'
            quote_file.write_text(json.dumps({
                'quote_date': '2026-09-21',
                'quotes': {'510300': {'price': '4', 'bid': '3.99', 'ask': '4.01', 'volume': '100000', 'asset_type': 'etf'}},
            }))
            service.import_quotes(quote_file)
            service.import_signal_data(self._signal(), 'paper')
            service.simulate('paper', 'sig', '2026-09-21')
            service.db.execute(
                "INSERT INTO risk_events(account_id,signal_id,level,reason,details_json,created_at) VALUES (?,?,?,?,?,?)",
                ('paper', 'sig', 'WARN', 'test_read', '{}', '2026-09-21T00:00:00+00:00'),
            )
            service.db.audit('paper', 'TEST_READ', 'signal', 'sig', {'ok': True})

            server, base = self._server(service)
            try:
                for endpoint in ('risk-events', 'audit-events', 'cash-ledger', 'signals', 'fills'):
                    records = self._get(base, '/api/v1/accounts/paper/' + endpoint)
                    self.assertIsInstance(records, list)
                    self.assertTrue(records, endpoint)
                dashboard = self._get(base, '/api/v1/accounts/paper/dashboard')
                expected = {
                    'account', 'cash', 'pending', 'withdrawable', 'positions', 'orders', 'fills',
                    'cash_ledger', 'signals', 'risk_events', 'snapshots', 'audit_events',
                }
                self.assertTrue(expected.issubset(dashboard))
                self.assertEqual(len(dashboard['fills']), 1)
                self.assertTrue(dashboard['risk_events'])
                self.assertTrue(dashboard['audit_events'])
            finally:
                server.shutdown()
                server.server_close()

    def test_external_signal_file_import_is_disabled(self):
        import base64
        with tempfile.TemporaryDirectory() as directory:
            service = ExecutionService(Database(Path(directory) / 'file-import.db'))
            service.db.create_account('paper')
            server, base = self._server(service)
            try:
                payload = {
                    'file_name': 'signal.json',
                    'content': base64.b64encode(json.dumps(self._signal('RECORD_ONLY', 'file-signal')).encode()).decode(),
                    'encoding': 'base64',
                }
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self._post(base, '/api/v1/accounts/paper/signals/import-file', payload)
                self.assertEqual(ctx.exception.code, 410)
            finally:
                server.shutdown()
                server.server_close()

    def test_external_signal_import_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ExecutionService(Database(Path(directory) / 'a.db'))
            service.db.create_account('paper')
            server, base = self._server(service)
            try:
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    self._post(base, '/api/v1/accounts/paper/signals/import', {'signal': self._signal('RECORD_ONLY', 'record-only')})
                self.assertEqual(ctx.exception.code, 410)
            finally:
                server.shutdown()
                server.server_close()
