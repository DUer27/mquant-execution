from .calendar import available_on
from .money import dec,text
from .db import now
class SettlementService:
    def __init__(self,db): self.db=db
    def settle(self,account_id,as_of):
        moved=0
        with self.db.transaction():
            self.db.execute("UPDATE position_lots SET available_quantity=quantity WHERE account_id=? AND available_quantity=0 AND buy_date < ?",(account_id,str(as_of)[:10]))
            for symbol in {r['symbol'] for r in self.db.all("SELECT DISTINCT symbol FROM position_lots WHERE account_id=? AND buy_date < ?",(account_id,str(as_of)[:10]))}:
                rows_lot=self.db.all("SELECT quantity,available_quantity,unit_cost FROM position_lots WHERE account_id=? AND symbol=? AND quantity>0",(account_id,symbol))
                qty=sum(int(x['quantity']) for x in rows_lot); avail=sum(int(x['available_quantity']) for x in rows_lot)
                if qty:
                    cost=sum((int(x['quantity'])*dec(x['unit_cost']) for x in rows_lot),dec(0))/qty
                    self.db.execute("UPDATE positions SET quantity=?,available_quantity=?,average_price=?,updated_at=? WHERE account_id=? AND symbol=?",(qty,avail,text(cost),now(),account_id,symbol))
            rows=self.db.all("SELECT c.entry_id,c.pending_delta,c.reference_id,f.trade_date FROM cash_ledger c JOIN fills f ON f.fill_id=c.reference_id WHERE c.account_id=? AND c.entry_type IN ('SELL','FEE') AND c.pending_delta<>0",(account_id,))
            for row in rows:
                if not available_on(row['trade_date'],as_of): continue
                key=f"settle:{row['entry_id']}"
                if self.db.ledger(account_id,'SETTLEMENT_RELEASE',row['pending_delta'],0,row['pending_delta'],-dec(row['pending_delta']),'cash_ledger',str(row['entry_id']),key): moved+=1
            self.db.audit(account_id,'SETTLEMENT_RUN','account',account_id,{'as_of':str(as_of),'released':moved})
        return moved
