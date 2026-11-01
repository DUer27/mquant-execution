import tempfile,unittest
from pathlib import Path
from mquant_execution.db import Database
class DatabaseTests(unittest.TestCase):
 def test_migrate_wal_idempotent_backup_rebuild(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'paper.db'; db=Database(p); db.migrate(); db.migrate(); self.assertEqual(db.integrity_check(),'ok'); self.assertEqual(db.one('pragma journal_mode')[0],'wal'); db.create_account('a','100'); self.assertTrue(db.ledger('a','DEPOSIT','10','10','10',key='x')); self.assertFalse(db.ledger('a','DEPOSIT','10','10','10',key='x')); self.assertEqual(db.balance('a')['available_cash'],'10.0000'); db.rebuild_balances('a'); backup=Path(d)/'b.db'; db.backup(backup); self.assertTrue(backup.exists())
