import json, tempfile, unittest
from pathlib import Path
from decimal import Decimal
from mquant_execution.db import Database
from mquant_execution.market_sources import normalize_quote
from mquant_execution.mquant_client import MQuantClient
from mquant_execution.strategy_sync import StrategySyncService
from mquant_execution.scenarios import ScenarioService
from mquant_execution.paper_report import PaperReport

class UpgradeTests(unittest.TestCase):
 def test_quote_parser_and_source_fields(self):
  row=normalize_quote({'f43':1040,'f44':1044,'f45':1012,'f46':1019,'f47':100,'f48':200,'f57':'600000','f58':'浦发银行','f60':1021,'f169':185,'f170':19},'2026-01-01T00:00:00+00:00')
  self.assertEqual(row['price'],'10.4000'); self.assertEqual(row['symbol'],'600000'); self.assertEqual(row['status'],'LIVE')
 def test_client_catalog_signal_fake(self):
  class Resp:
   def __init__(self,data): self.data=data
   def read(self): return json.dumps(self.data).encode()
   def __enter__(self): return self
   def __exit__(self,*x): pass
  calls=[]
  def opener(req,timeout=0):
   calls.append(req.full_url)
   if 'execution-catalog' in req.full_url: return Resp({'strategies':[{'strategy_id':'s','strategy_version':'v'}]})
   return Resp({'action':'RECORD_ONLY','gate_status':'experimental_candidate'})
  c=MQuantClient('http://test',opener=opener); self.assertEqual(c.catalog()['strategies'][0]['strategy_id'],'s'); self.assertEqual(c.run_once('s')['action'],'RECORD_ONLY'); self.assertTrue(calls)
 def test_scenario_idempotency_and_report_contract(self):
  with tempfile.TemporaryDirectory() as d:
   db=Database(Path(d)/'a.db'); db.migrate(); db.create_account('paper','100')
   self.assertEqual(str(db.balance('paper')['available_cash']), '0')
   svc=ScenarioService(db); svc.create('paper','s1','test','100'); a=svc.add_cashflow('s1','2026-01-02','50'); b=svc.add_cashflow('s1','2026-01-02','50'); self.assertEqual(a['cashflow_id'],b['cashflow_id'])
   report=PaperReport(db).build('paper'); self.assertEqual(report['schema_version'],'paper-report.v1'); self.assertIn('market',report); self.assertIn('account',report); self.assertIn('evidence',report)
