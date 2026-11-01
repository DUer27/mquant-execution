from __future__ import annotations
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
from .service import ExecutionService
from .reports import Reports
from pathlib import Path

class APIHandler(BaseHTTPRequestHandler):
    service=None
    def _send(self,status,data,content='application/json'):
        body=data if isinstance(data,bytes) else (data.encode() if isinstance(data,str) else json.dumps(data,ensure_ascii=False,default=str).encode())
        self.send_response(status); self.send_header('Content-Type',content+'; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def _json(self): return json.loads(self.rfile.read(int(self.headers.get('Content-Length','0')) or 0) or '{}')
    def do_GET(self):
        p=urlparse(self.path).path; parts=p.strip('/').split('/')
        if p in ('/','/index.html'):
            body=(Path(__file__).parent/'web_static'/'index.html').read_bytes(); return self._send(200,body,'text/html')
        if p=='/api/v1/health': return self._send(200,{'ok':True,'mode':'PAPER'})
        if len(parts)>=5 and parts[:3]==['api','v1','accounts']:
            aid=parts[3]; name=parts[4]; r=Reports(self.service.db)
            if name=='dashboard': return self._send(200,r.dashboard(aid))
            mapping={'signals':'signals','orders':'orders','fills':'fills','cash-ledger':'cash_ledger','snapshots':'account_snapshots'}
            if name in mapping: return self._send(200,[dict(x) for x in self.service.db.all(f"SELECT * FROM {mapping[name]} WHERE account_id=? ORDER BY rowid DESC",(aid,))])
        return self._send(404,{'error':'not_found'})
    def do_POST(self):
        p=urlparse(self.path).path; parts=p.strip('/').split('/'); data=self._json()
        try:
            if p=='/api/v1/accounts':
                aid=data['account_id']; self.service.db.create_account(aid,data.get('cash','0')); return self._send(201,{'account_id':aid})
            if len(parts)>=5 and parts[:3]==['api','v1','accounts']:
                aid=parts[3]; action=parts[4]; tail=parts[5] if len(parts)>5 else ''
                if action=='cash' and tail in ('deposit','withdraw'):
                    result=(self.service.deposit if tail=='deposit' else self.service.withdraw)(aid,data['amount'],data.get('reference','api')); return self._send(200,{'ok':result})
                if action=='signals' and tail=='import': row,status=self.service.import_signal_data(data['signal'],aid); return self._send(200,{'status':status,'signal':row})
                if action=='quotes' and tail=='import': return self._send(200,{'count':self._quotes_data(data)})
                if action=='simulate' and tail in ('','run'): return self._send(200,self.service.simulate(aid,data['signal_id'],data['as_of']))
                if action=='rebuild': return self._send(200,dict(self.service.db.rebuild_balances(aid)))
        except Exception as e: return self._send(400,{'error':str(e)})
        return self._send(404,{'error':'not_found'})
    def _quotes_data(self,data):
        import tempfile, pathlib
        with tempfile.NamedTemporaryFile('w',suffix='.json',delete=False) as f: json.dump(data,f); name=f.name
        try: return self.service.import_quotes(name)
        finally: pathlib.Path(name).unlink(missing_ok=True)
    def log_message(self,*args): pass

def serve(db_path='runtime/paper.db',host='127.0.0.1',port=8080):
    from .db import Database
    db=Database(db_path); service=ExecutionService(db); APIHandler.service=service
    server=ThreadingHTTPServer((host,port),APIHandler); server.serve_forever()
