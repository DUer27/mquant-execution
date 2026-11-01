import tempfile,unittest
from pathlib import Path
from mquant_execution.db import Database
from mquant_execution.service import ExecutionService
class T1Tests(unittest.TestCase):
 def test_lot_not_available_same_day(self):
  with tempfile.TemporaryDirectory() as d:
   db=Database(Path(d)/'a.db'); db.migrate(); db.create_account('a','1000'); db.ledger('a','DEPOSIT','1000','1000','1000',key='d'); db.execute("insert into position_lots(account_id,symbol,buy_date,quantity,available_quantity,unit_cost,source_fill_id) values ('a','x','2026-09-21',100,0,'1','f')"); db.execute("insert into positions(account_id,symbol,quantity,available_quantity,average_price,updated_at) values ('a','x',100,0,'1','now')"); from mquant_execution.settlement import SettlementService; SettlementService(db).settle('a','2026-09-21'); self.assertEqual(db.one("select available_quantity from positions where symbol='x'")[0],0); SettlementService(db).settle('a','2026-09-22'); self.assertEqual(db.one("select available_quantity from positions where symbol='x'")[0],100)
