import tempfile,unittest
from pathlib import Path
from mquant_execution.db import Database
class RestartTests(unittest.TestCase):
 def test_reopen(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'a.db'; x=Database(p); x.migrate(); x.create_account('a','1'); x.close(); y=Database(p); y.migrate(); self.assertEqual(y.account('a')['account_id'],'a')
