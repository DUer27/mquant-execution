from decimal import Decimal
import json,tempfile,unittest
from pathlib import Path
from mquant_execution.db import Database
from mquant_execution.service import ExecutionService
class ExecutionTests(unittest.TestCase):
 def test_target_buy_fee_slippage_idempotency(self):
  with tempfile.TemporaryDirectory() as d:
   d=Path(d); s=ExecutionService(Database(d/'a.db')); s.db.create_account('paper'); s.deposit('paper','100000','initial'); q=d/'q.json'; q.write_text(json.dumps({'quote_date':'2026-09-21','quotes':{'510300':{'price':'4','bid':'3.99','ask':'4.01','volume':'100000','asset_type':'etf'}}})); s.import_quotes(q); signal={'schema_version':'signal.v1','signal_id':'sig','strategy_id':'x','generated_at':'2026-09-20T00:00:00Z','signal_date':'2026-09-20','effective_at':'2026-09-21T09:30:00+08:00','expires_at':'2030-01-01T00:00:00Z','action':'TARGET_PORTFOLIO','gate_status':'ready','planned_weight':'0.3','cash_target_weight':'0.7','portfolio':[{'symbol':'510300','asset_type':'etf','target_weight':'0.3'}],'provenance':{'source':'t','data_policy':'synthetic'}}; row,status=s.import_signal_data(signal,'paper'); self.assertEqual(status,'IMPORTED'); out=s.simulate('paper','sig','2026-09-21'); self.assertEqual(out['fills'],1); self.assertEqual(s.db.one('select count(*) from fills')[0],1); self.assertEqual(s.db.one("select available_quantity from positions where symbol='510300'")[0],0); self.assertEqual(s.db.one('select count(*) from cash_ledger')[0],3)


class GateTests(unittest.TestCase):
 def test_controlled_paper_watch_gate_is_accepted(self):
  from mquant_execution.risk import RiskEngine
  from mquant_execution.db import Database
  import tempfile
  with tempfile.TemporaryDirectory() as d:
   db=Database(Path(d)/'gate.db'); db.migrate(); db.create_account('paper','100000')
   signal={'gate_status':'ready_for_controlled_paper_watch','action':'TARGET_PORTFOLIO','expires_at':None}
   order={'quantity':100,'side':'BUY'}
   quote={'price':'10','tradable':1,'suspended':0,'limit_up':None,'limit_down':None}
   self.assertIsNone(RiskEngine(db).check('paper',signal,order,quote,Decimal('100000'),Decimal('0'),'2026-09-21'))
