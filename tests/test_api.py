import json,tempfile,threading,unittest,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from mquant_execution.db import Database
from mquant_execution.service import ExecutionService
from mquant_execution.api import APIHandler
class APITests(unittest.TestCase):
 def test_health_and_dashboard(self):
  with tempfile.TemporaryDirectory() as d:
   service=ExecutionService(Database(Path(d)/'a.db')); service.db.create_account('paper'); APIHandler.service=service; server=ThreadingHTTPServer(('127.0.0.1',0),APIHandler); t=threading.Thread(target=server.serve_forever,daemon=True); t.start(); base='http://127.0.0.1:%s'%server.server_port; self.assertEqual(json.load(urllib.request.urlopen(base+'/api/v1/health'))['mode'],'PAPER'); self.assertEqual(json.load(urllib.request.urlopen(base+'/api/v1/accounts/paper/dashboard'))['account_id'],'paper'); server.shutdown(); server.server_close()
