import tempfile,unittest
from pathlib import Path
from mquant_execution.db import Database
from mquant_execution.service import ExecutionService
class CashTests(unittest.TestCase):
 def test_deposit_withdraw_idempotency(self):
  with tempfile.TemporaryDirectory() as d:
   s=ExecutionService(Database(Path(d)/'a.db')); s.db.create_account('a'); self.assertTrue(s.deposit('a','100','x')); self.assertFalse(s.deposit('a','100','x')); self.assertTrue(s.withdraw('a','40','y')); self.assertEqual(s.db.balance('a')['withdrawable_cash'],'60.0000'); self.assertRaises(ValueError,lambda:s.withdraw('a','61','z'))
