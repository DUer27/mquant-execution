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
  row=normalize_quote({'f43':'10.40','f44':'10.44','f45':'10.12','f46':'10.19','f47':100,'f48':200,'f57':'600000','f58':'浦发银行','f60':'10.21','f169':'0.185','f170':'1.9'},'2026-01-01T00:00:00+00:00')
  self.assertEqual(row['price'],'10.4000'); self.assertEqual(row['change_pct'],'1.9000'); self.assertEqual(row['symbol'],'600000'); self.assertEqual(row['status'],'LIVE')
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
 def test_scenario_blocks_record_only_and_unapproved_gate(self):
  from mquant_execution.service import ExecutionService
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); service=ExecutionService(Database(d/'scenario.db')); service.db.create_account('paper')
   service.import_bars([{'code':'300136','date':'2026-01-02','open':'10','close':'10','high':'11','low':'9','volume':'1000000','amount':'10000000'}])
   base={'schema_version':'signal.v1','strategy_id':'scenario','generated_at':'2025-12-31T00:00:00Z','signal_date':'2026-01-01','effective_at':'2026-01-02T09:30:00+08:00','expires_at':'2030-01-01T00:00:00Z','planned_weight':'0.1','cash_target_weight':'0.9','portfolio':[{'symbol':'300136','asset_type':'stock','target_weight':'0.1'}],'provenance':{'source':'test','data_policy':'bars'}}
   record=dict(base, signal_id='record-only-scenario', action='RECORD_ONLY', gate_status='experimental_candidate')
   unapproved=dict(base, signal_id='unapproved-scenario', action='TARGET_PORTFOLIO', gate_status='experimental_candidate')
   service.import_signal_data(record,'paper'); service.import_signal_data(unapproved,'paper')
   svc=ScenarioService(service.db); svc.create('paper','record-scenario','record','1000000'); svc.create('paper','gate-scenario','gate','1000000')
   blocked=svc.run('record-scenario','2026-01-02','2026-01-02',{'signal_id':'record-only-scenario'})
   rejected=svc.run('gate-scenario','2026-01-02','2026-01-02',{'signal_id':'unapproved-scenario'})
   self.assertEqual(blocked['execution_status'],'BLOCKED'); self.assertEqual(blocked['block_reason'],'RECORD_ONLY')
   self.assertEqual(rejected['execution_status'],'BLOCKED'); self.assertEqual(rejected['block_reason'],'GATE_NOT_APPROVED')
   self.assertEqual(service.db.one('SELECT COUNT(*) FROM orders')[0],0); self.assertEqual(service.db.one('SELECT COUNT(*) FROM fills')[0],0)

 def test_scenario_run_idempotency_capital_and_official_isolation(self):
  from mquant_execution.service import ExecutionService
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); service=ExecutionService(Database(d/'scenario.db')); service.db.create_account('paper'); service.deposit('paper','1000000','initial')
   service.import_bars([{'code':'300136','date':'2026-01-02','open':'10','close':'10','high':'11','low':'9','volume':'1000000','amount':'10000000'}])
   signal={'schema_version':'signal.v1','signal_id':'capital-signal','strategy_id':'scenario','generated_at':'2025-12-31T00:00:00Z','signal_date':'2026-01-01','effective_at':'2026-01-02T09:30:00+08:00','expires_at':'2030-01-01T00:00:00Z','action':'TARGET_PORTFOLIO','gate_status':'ready','planned_weight':'0.1','cash_target_weight':'0.9','portfolio':[{'symbol':'300136','asset_type':'stock','target_weight':'0.1'}],'provenance':{'source':'test','data_policy':'bars'}}
   service.import_signal_data(signal,'paper'); svc=ScenarioService(service.db); svc.create('paper','small-capital','small','1000000'); svc.create('paper','large-capital','large','2000000')
   small=svc.run('small-capital','2026-01-02','2026-01-02',{'signal_id':'capital-signal'}); repeated=svc.run('small-capital','2026-01-02','2026-01-02',{'signal_id':'capital-signal'}); large=svc.run('large-capital','2026-01-02','2026-01-02',{'signal_id':'capital-signal'})
   self.assertEqual(small,repeated); self.assertNotEqual(small['isolated_account'],large['isolated_account']); self.assertNotEqual(small['final']['total_assets'],large['final']['total_assets']); self.assertGreater(small['fills_count'],0); self.assertGreater(large['fills_count'],0)
   self.assertEqual(service.db.one("SELECT COUNT(*) FROM orders WHERE account_id='paper'")[0],0); self.assertEqual(service.db.one("SELECT COUNT(*) FROM fills WHERE account_id='paper'")[0],0)

 def test_eastmoney_source_retries_transient_failure(self):
  from mquant_execution.market_sources import EastmoneyPush2Source
  class Resp:
   def read(self): return json.dumps({'rc':0,'data':{'f43':1040,'f44':1044,'f45':1012,'f46':1019,'f47':100,'f48':200,'f57':'600000','f58':'浦发银行','f60':1021,'f169':185,'f170':19}}).encode()
   def close(self): pass
  calls=[]
  def opener(req,timeout=0):
   calls.append(req.full_url)
   if len(calls)==1: raise OSError('transient')
   return Resp()
  rows=EastmoneyPush2Source(opener=opener,attempts=2,retry_backoff=0).fetch(['600000'])
  self.assertEqual(len(rows),1); self.assertEqual(len(calls),2); self.assertEqual(rows[0]['status'],'LIVE')
