from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path
from .service import ExecutionService
from .reports import Reports
from .market_service import MarketService
from .strategy_sync import StrategySyncService
from .scenarios import ScenarioService
from .paper_report import PaperReport

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

    @property
    def db(self): return self.service.db

    def do_GET(self):
        parsed = urlparse(self.path); p = parsed.path; parts = p.strip('/').split('/'); params = parse_qs(parsed.query)
        try:
            if p in ('/', '/index.html'):
                return self._send(200, (Path(__file__).parent / 'web_static' / 'index.html').read_bytes(), 'text/html')
            if p == '/api/v1/health':
                return self._send(200, {'ok': True, 'mode': 'PAPER', 'market_source': 'eastmoney.push2'})
            if p in ('/api/v1/market/live', '/api/v1/market/quotes', '/api/v1/market/status'):
                symbols=params.get('symbol', params.get('symbols', [])); symbols=symbols[0].split(',') if symbols else None
                result=MarketService(self.db).status(symbols)
                if p.endswith('quotes'): return self._send(200, result['quotes'])
                return self._send(200, result)
            if p == '/api/v1/market/bars':
                symbol = params.get('symbol', [None])[0]; start = params.get('start', [None])[0]; end = params.get('end', [None])[0]
                where=[]; args=[]
                if symbol:
                    from .market import symbol_variants
                    variants=symbol_variants(symbol); where.append('symbol IN (%s)' % ','.join('?' for _ in variants)); args.extend(variants)
                if start: where.append('bar_date>=?'); args.append(start[:10])
                if end: where.append('bar_date<=?'); args.append(end[:10])
                sql='SELECT * FROM market_bars' + ((' WHERE ' + ' AND '.join(where)) if where else '') + ' ORDER BY bar_date,symbol'
                return self._send(200, [dict(row) for row in self.db.all(sql,args)])
            if p in ('/api/v1/strategies/catalog', '/api/v1/strategy/catalog'):
                return self._send(200, StrategySyncService(self.db).catalog())
            if p == '/api/v1/strategies/current':
                aid=params.get('account_id',['paper'])[0]; return self._send(200, StrategySyncService(self.db).current(aid))
            if p == '/api/v1/scenarios': return self._send(200, ScenarioService(self.db).list(params.get('account_id',[None])[0]))
            if p == '/api/v1/scenarios/compare':
                ids=params.get('scenario_id',[]); return self._send(200, ScenarioService(self.db).compare(ids,params.get('start',['1900-01-01'])[0],params.get('end',['2999-12-31'])[0]))
            if len(parts) >= 5 and parts[:3] == ['api', 'v1', 'scenarios']:
                scenario_id=parts[3]; name=parts[4]; svc=ScenarioService(self.db)
                if name == 'cashflows': return self._send(200,svc.cashflows(scenario_id))
                if name == 'runs': return self._send(200,svc.runs(scenario_id))
                if name in ('report','result'):
                    runs=svc.runs(scenario_id); return self._send(200,json.loads(runs[0]['result_json']) if runs and runs[0]['result_json']!='{}' else {})
            if len(parts) >= 5 and parts[:3] == ['api', 'v1', 'accounts']:
                aid, name = parts[3], parts[4]
                if name in ('report','report.v1') or (name == 'report.csv'):
                    report=PaperReport(self.db)
                    if name == 'report.csv': return self._send(200,report.csv(aid),'text/csv')
                    return self._send(200,report.build(aid))
                reports = Reports(self.db)
                if name == 'dashboard': return self._send(200, reports.dashboard(aid))
                if name == 'equity': return self._send(200, reports.equity(aid))
                if name in ('strategy','strategies'):
                    svc=StrategySyncService(self.db)
                    if len(parts)>5 and parts[5] in ('current','active'): return self._send(200,svc.current(aid))
                mapping = {'signals':'signals','orders':'orders','fills':'fills','transactions':'fills','cash-ledger':'cash_ledger','snapshots':'account_snapshots','risk-events':'risk_events','audit-events':'audit_events'}
                if name in mapping:
                    return self._send(200, [dict(row) for row in self.db.all(f"SELECT * FROM {mapping[name]} WHERE account_id=? ORDER BY rowid DESC", (aid,))])
        except Exception as exc:
            return self._send(400, {'error': str(exc)})
        return self._send(404, {'error': 'not_found'})

    def do_POST(self):
        p = urlparse(self.path).path; parts = p.strip('/').split('/'); data = self._json()
        try:
            if p == '/api/v1/accounts':
                aid = data['account_id']; self.db.create_account(aid, data.get('cash', '0')); return self._send(201, {'account_id': aid})
            if p in ('/api/v1/market/live/refresh','/api/v1/market/refresh','/api/v1/market/sync'):
                symbols=data.get('symbols',data.get('symbol',[])); symbols=[symbols] if isinstance(symbols,str) else symbols
                return self._send(200,MarketService(self.db).refresh(symbols,data.get('idempotency_key')))
            if p == '/api/v1/market/bars/import':
                if 'csv_text' in data: count = self.service.import_bars_csv(data['csv_text'])
                elif 'bars' in data: count = self.service.import_bars(data['bars'])
                elif 'file' in data or 'path' in data:
                    raw = data.get('file', data.get('path')); path = Path(raw).resolve(); cwd = Path.cwd().resolve()
                    if cwd != path and cwd not in path.parents: raise ValueError('file_path_outside_working_directory')
                    count = self.service.import_bars_file(path)
                else: raise ValueError('bars_import_requires_csv_text_or_bars')
                return self._send(200, {'count': count})
            if p in ('/api/v1/strategies/sync','/api/v1/strategy/sync'):
                return self._send(200,StrategySyncService(self.db).sync(data.get('idempotency_key'),data.get('catalog',data.get('strategies'))))
            if p in ('/api/v1/scenarios','/api/v1/scenarios/create'):
                return self._send(201,ScenarioService(self.db).create(data['account_id'],data['scenario_id'],data.get('name',''),data.get('initial_cash','0'),data.get('parameters')))
            if p == '/api/v1/scenarios/compare':
                return self._send(200,ScenarioService(self.db).compare(data.get('scenario_ids',[]),data['start'],data['end'],data.get('parameters')))
            if len(parts) >= 5 and parts[:3] == ['api', 'v1', 'scenarios']:
                sid, action=parts[3],parts[4]; svc=ScenarioService(self.db)
                if action in ('cashflows','cashflow'):
                    return self._send(201,svc.add_cashflow(sid,data['event_date'],data['amount'],data.get('flow_type','DEPOSIT'),data.get('note',''),data.get('cashflow_id'),data.get('idempotency_key')))
                if action in ('run','execute'):
                    return self._send(200,svc.run(sid,data['start'],data['end'],data.get('parameters'),data.get('idempotency_key')))
            if len(parts) >= 5 and parts[:3] == ['api', 'v1', 'accounts']:
                aid, action = parts[3], parts[4]; tail = parts[5] if len(parts) > 5 else ''
                if action in ('strategy','strategies') and tail in ('activate','active'):
                    return self._send(200,StrategySyncService(self.db).activate(aid,data['strategy_id'],data.get('strategy_version',''),data.get('parameters'),data.get('idempotency_key')))
                if action in ('strategy','strategies') and tail in ('run-once','run_once'):
                    return self._send(200,StrategySyncService(self.db).run_once(aid,data.get('parameters')))
                if action == 'cash' and tail in ('deposit', 'withdraw'):
                    result = (self.service.deposit if tail == 'deposit' else self.service.withdraw)(aid, data['amount'], data.get('reference', 'api')); return self._send(200, {'ok': result})
                if action == 'signals' and tail == 'import':
                    row, status = self.service.import_signal_data(data['signal'], aid); return self._send(200, {'status': status, 'signal': row})
                if action == 'signals' and tail == 'import-file':
                    raw = data.get('file_name', ''); content = data.get('content', '')
                    if not raw or not content: raise ValueError('signal_file_name_and_content_required')
                    import base64, tempfile
                    suffix = '.zip' if raw.lower().endswith('.zip') else '.json'; payload = base64.b64decode(content) if data.get('encoding') == 'base64' else content.encode()
                    with tempfile.NamedTemporaryFile('wb', suffix=suffix, delete=False) as handle: handle.write(payload); name = handle.name
                    try: row, status = self.service.import_signal(name, aid)
                    finally: Path(name).unlink(missing_ok=True)
                    return self._send(200, {'status': status, 'signal': row})
                if action == 'quotes' and tail == 'import': return self._send(200, {'count': self._quotes_data(data)})
                if action == 'replay':
                    from .replay import ReplayService
                    return self._send(200, ReplayService(self.db).replay(aid, data['start'], data['end']))
                if action == 'simulate' and tail in ('', 'run'): return self._send(200, self.service.simulate(aid, data['signal_id'], data['as_of']))
                if action == 'rebuild': return self._send(200, dict(self.db.rebuild_balances(aid)))
        except Exception as exc:
            return self._send(400, {'error': str(exc)})
        return self._send(404, {'error': 'not_found'})

    def _quotes_data(self, data):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
            json.dump(data, handle); name = handle.name
        try: return self.service.import_quotes(name)
        finally: Path(name).unlink(missing_ok=True)

    def log_message(self, *args): pass


def serve(db_path='runtime/paper.db', host='127.0.0.1', port=8080):
    from .db import Database
    db = Database(db_path); service = ExecutionService(db); APIHandler.service = service
    server = ThreadingHTTPServer((host, port), APIHandler); server.serve_forever()
