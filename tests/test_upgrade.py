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

 def test_scenario_executes_isolated_target_signal(self):
  from mquant_execution.service import ExecutionService
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); service=ExecutionService(Database(d/'scenario.db')); service.db.create_account('paper'); service.deposit('paper','1000000','initial')
   service.import_bars([{'code':'300136','date':'2026-01-02','open':'10','close':'10','high':'11','low':'9','volume':'1000000','amount':'10000000'}])
   signal={'schema_version':'signal.v1','signal_id':'scenario-signal','strategy_id':'scenario','generated_at':'2025-12-31T00:00:00Z','signal_date':'2026-01-01','effective_at':'2026-01-02T09:30:00+08:00','expires_at':'2030-01-01T00:00:00Z','action':'TARGET_PORTFOLIO','gate_status':'ready','planned_weight':'0.1','cash_target_weight':'0.9','portfolio':[{'symbol':'300136','asset_type':'stock','target_weight':'0.1'}],'provenance':{'source':'test','data_policy':'bars'}}
   service.import_signal_data(signal,'paper'); svc=ScenarioService(service.db); svc.create('paper','exec','exec','1000000')
   result=svc.run('exec','2026-01-02','2026-01-02',{'signal_id':'scenario-signal'})
   self.assertEqual(result['execution_status'],'EXECUTED'); self.assertGreater(result['fills_count'],0); self.assertEqual(service.db.one('SELECT COUNT(*) FROM fills')[0],0)
