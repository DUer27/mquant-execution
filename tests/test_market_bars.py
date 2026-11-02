import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from mquant_execution.api import APIHandler
from mquant_execution.db import Database
from mquant_execution.replay import ReplayService
from mquant_execution.service import ExecutionService


class MarketBarTests(unittest.TestCase):
    def test_csv_json_import_and_snapshot_close_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ExecutionService(Database(Path(directory) / 'bars.db'))
            service.db.create_account('paper')
            csv_text = ('code,date,open,close,high,low,volume,amount,security,source,adjust,name,prev_close,tradable\n'
                        '510300,2026-01-02,4,4.2,4.3,3.9,100,420,ETF,ak,none,沪深300,4,1\n')
            self.assertEqual(service.import_bars_csv(csv_text), 1)
            self.assertEqual(service.import_bars([{
                'code': '000001.XSHE', 'date': '2026-01-02', 'open': '10',
                'close': '11', 'high': '12', 'low': '9', 'volume': '2', 'amount': '22'
            }]), 1)
            row = service.db.one('SELECT * FROM market_bars WHERE symbol=?', ('510300.XSHG',))
            self.assertEqual(row['close'], '4.2000')
            self.assertEqual(ReplayService(service.db).replay('paper', '2026-01-02', '2026-01-02')['trading_days'], ['2026-01-02'])

    def test_api_query_and_import(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ExecutionService(Database(Path(directory) / 'api.db'))
            service.db.create_account('paper')
            APIHandler.service = service
            server = ThreadingHTTPServer(('127.0.0.1', 0), APIHandler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:%d' % server.server_port
            try:
                payload = {'bars': [{'code': '510300', 'date': '2026-01-02', 'open': '4', 'close': '4.1', 'high': '4.2', 'low': '3.9'}]}
                request = urllib.request.Request(base + '/api/v1/market/bars/import', data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
                self.assertEqual(json.load(urllib.request.urlopen(request))['count'], 1)
                rows = json.load(urllib.request.urlopen(base + '/api/v1/market/bars?symbol=510300&start=2026-01-01&end=2026-01-03'))
                self.assertEqual(rows[0]['close'], '4.1000')
                self.assertEqual(json.load(urllib.request.urlopen(base + '/api/v1/accounts/paper/equity'))['mode'], 'PAPER')
            finally:
                server.shutdown()
                server.server_close()

    def test_replay_executes_target_signal_from_bars(self):
        with tempfile.TemporaryDirectory() as directory:
            service = ExecutionService(Database(Path(directory) / 'replay.db'))
            service.db.create_account('paper')
            service.deposit('paper', '1000000', 'initial')
            service.import_bars_csv(
                'code,date,open,close,high,low,volume,amount,tradable\n'
                '300136,2025-01-02,24.97,23.65,25.18,23.26,379228,920244780,1\n'
                '300136,2025-01-03,23.72,23.01,23.88,22.88,250575,587611825,1\n'
            )
            service.import_signal_data({
                'schema_version': 'signal.v1', 'signal_id': 'replay-signal',
                'strategy_id': 'replay-test', 'generated_at': '2025-01-01T00:00:00Z',
                'signal_date': '2025-01-01', 'effective_at': '2025-01-02T09:30:00+08:00',
                'expires_at': '2030-01-01T15:00:00+08:00', 'action': 'TARGET_PORTFOLIO',
                'gate_status': 'ready', 'planned_weight': '0.1', 'cash_target_weight': '0.9',
                'portfolio': [{'symbol': '300136', 'asset_type': 'stock', 'target_weight': '0.1'}],
                'provenance': {'source': 'test', 'data_policy': 'real_ohlcv'},
            }, 'paper')
            result = ReplayService(service.db).replay('paper', '2025-01-02', '2025-01-03')
            self.assertEqual(result['executed'][0]['fills'], 1)
            self.assertEqual(len(result['snapshots']), 2)
            self.assertEqual(service.db.one('SELECT COUNT(*) FROM fills')[0], 1)


if __name__ == '__main__':
    unittest.main()
