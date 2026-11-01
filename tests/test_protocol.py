import unittest
from datetime import datetime, timezone
from mquant_execution.protocol import validate_signal, SignalError, signal_id
class ProtocolTests(unittest.TestCase):
 def base(self): return {'schema_version':'signal.v1','strategy_id':'s','generated_at':'2026-09-19T00:00:00Z','signal_date':'2026-09-19','effective_at':'2026-09-20T09:30:00+08:00','expires_at':'2026-12-20T15:00:00+08:00','action':'TARGET_PORTFOLIO','gate_status':'ready','planned_weight':'0.5','cash_target_weight':'0.5','portfolio':[{'symbol':'510300','asset_type':'etf','target_weight':'0.5'}],'provenance':{'source':'test','data_policy':'synthetic'}}
 def test_valid_and_deterministic_id(self):
  a=self.base(); b=validate_signal(a); self.assertEqual(b['signal_id'],signal_id(a)); self.assertEqual(b['signal_id'],signal_id(dict(a)))
 def test_rejects_weight_duplicate_expiry(self):
  a=self.base(); a['portfolio'].append(a['portfolio'][0].copy()); self.assertRaises(SignalError,validate_signal,a)
  a=self.base(); a['cash_target_weight']='0.6'; self.assertRaises(SignalError,validate_signal,a)
  a=self.base(); a['expires_at']='2020-01-01T00:00:00Z'; self.assertRaises(SignalError,lambda:validate_signal(a,datetime.now(timezone.utc)))
