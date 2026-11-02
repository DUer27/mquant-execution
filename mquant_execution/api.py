from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from .service import ExecutionService
from .reports import Reports


class APIHandler(BaseHTTPRequestHandler):
    service = None

    def _send(self, status, data, content='application/json'):
        body = data if isinstance(data, bytes) else (data.encode() if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str).encode())
        self.send_response(status)
        self.send_header('Content-Type', content + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self):
        return json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0')) or 0) or '{}')

    def do_GET(self):
        parsed = urlparse(self.path)
        p = parsed.path
        parts = p.strip('/').split('/')
        params = parse_qs(parsed.query)
        try:
            if p in ('/', '/index.html'):
                return self._send(200, (Path(__file__).parent / 'web_static' / 'index.html').read_bytes(), 'text/html')
            if p == '/api/v1/health': return self._send(200, {'ok': True, 'mode': 'PAPER'})
            if p == '/api/v1/market/bars':
                symbol = params.get('symbol', [None])[0]; start = params.get('start', [None])[0]; end = params.get('end', [None])[0]
                where=[]; args=[]
                if symbol:
                    from .market import symbol_variants
                    variants=symbol_variants(symbol); where.append('symbol IN (%s)' % ','.join('?' for _ in variants)); args.extend(variants)
                if start: where.append('bar_date>=?'); args.append(start[:10])
                if end: where.append('bar_date<=?'); args.append(end[:10])
                sql='SELECT * FROM market_bars' + ((' WHERE ' + ' AND '.join(where)) if where else '') + ' ORDER BY bar_date,symbol'
                return self._send(200, [dict(row) for row in self.service.db.all(sql,args)])
            if len(parts) >= 5 and parts[:3] == ['api', 'v1', 'accounts']:
                aid, name = parts[3], parts[4]; reports = Reports(self.service.db)
                if name == 'dashboard': return self._send(200, reports.dashboard(aid))
                if name == 'equity': return self._send(200, reports.equity(aid))
                mapping = {'signals':'signals','orders':'orders','fills':'fills','transactions':'fills','cash-ledger':'cash_ledger','snapshots':'account_snapshots','risk-events':'risk_events','audit-events':'audit_events'}
                if name in mapping:
                    return self._send(200, [dict(row) for row in self.service.db.all(f"SELECT * FROM {mapping[name]} WHERE account_id=? ORDER BY rowid DESC", (aid,))])
        except Exception as exc:
            return self._send(400, {'error': str(exc)})
        return self._send(404, {'error': 'not_found'})

    def do_POST(self):
        p = urlparse(self.path).path
        parts = p.strip('/').split('/')
        data = self._json()
        try:
            if p == '/api/v1/accounts':
                aid = data['account_id']; self.service.db.create_account(aid, data.get('cash', '0')); return self._send(201, {'account_id': aid})
            if p == '/api/v1/market/bars/import':
                if 'csv_text' in data: count = self.service.import_bars_csv(data['csv_text'])
                elif 'bars' in data: count = self.service.import_bars(data['bars'])
                elif 'file' in data or 'path' in data:
                    raw = data.get('file', data.get('path')); path = Path(raw).resolve(); cwd = Path.cwd().resolve()
                    if cwd != path and cwd not in path.parents: raise ValueError('file_path_outside_working_directory')
                    count = self.service.import_bars_file(path)
                else: raise ValueError('bars_import_requires_csv_text_or_bars')
                return self._send(200, {'count': count})
            if len(parts) >= 5 and parts[:3] == ['api', 'v1', 'accounts']:
                aid, action = parts[3], parts[4]; tail = parts[5] if len(parts) > 5 else ''
                if action == 'cash' and tail in ('deposit', 'withdraw'):
                    result = (self.service.deposit if tail == 'deposit' else self.service.withdraw)(aid, data['amount'], data.get('reference', 'api')); return self._send(200, {'ok': result})
                if action == 'signals' and tail == 'import':
                    row, status = self.service.import_signal_data(data['signal'], aid); return self._send(200, {'status': status, 'signal': row})
                if action == 'quotes' and tail == 'import': return self._send(200, {'count': self._quotes_data(data)})
                if action == 'replay':
                    from .replay import ReplayService
                    return self._send(200, ReplayService(self.service.db).replay(aid, data['start'], data['end']))
                if action == 'simulate' and tail in ('', 'run'): return self._send(200, self.service.simulate(aid, data['signal_id'], data['as_of']))
                if action == 'rebuild': return self._send(200, dict(self.service.db.rebuild_balances(aid)))
        except Exception as exc:
            return self._send(400, {'error': str(exc)})
        return self._send(404, {'error': 'not_found'})

    def _quotes_data(self, data):
        import tempfile
        import pathlib
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump(data, handle); name = handle.name
        try: return self.service.import_quotes(name)
        finally: pathlib.Path(name).unlink(missing_ok=True)

    def log_message(self, *args): pass


def serve(db_path='runtime/paper.db', host='127.0.0.1', port=8080):
    from .db import Database
    db = Database(db_path); service = ExecutionService(db); APIHandler.service = service
    server = ThreadingHTTPServer((host, port), APIHandler); server.serve_forever()
