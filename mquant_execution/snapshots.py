from .money import dec,text
from .db import now
from .market import market_bar
class SnapshotService:
    def __init__(self,db): self.db=db
    def create(self,account_id,as_of):
        b=self.db.balance(account_id); holdings=dec(0); rows=[]
        for p in self.db.all("SELECT * FROM positions WHERE account_id=?",(account_id,)):
            q=self.db.one("SELECT price FROM quotes WHERE symbol=? AND quote_date=?",(p['symbol'],str(as_of)[:10]))
            bar=market_bar(self.db,p['symbol'],as_of)
            price=dec(q['price']) if q else (dec(bar['close']) if bar else dec(p['average_price']))
            value=dec(p['quantity'])*price; holdings+=value
            rows.append({'symbol':p['symbol'],'quantity':p['quantity'],'available_quantity':p['available_quantity'],'average_price':p['average_price'],'price':text(price),'market_value':text(value),'pnl':text(value-dec(p['quantity'])*dec(p['average_price']))})
        total=dec(b['available_cash'])+dec(b['pending_cash'])+holdings
        account=self.db.account(account_id)
        deposits=sum((dec(row['available_delta']) for row in self.db.all("SELECT available_delta FROM cash_ledger WHERE account_id=? AND entry_type='DEPOSIT'", (account_id,))), dec('0'))
        withdrawals=sum((dec(row['available_delta']) for row in self.db.all("SELECT available_delta FROM cash_ledger WHERE account_id=? AND entry_type='WITHDRAWAL'", (account_id,))), dec('0'))
        capital_base=max(dec(account['initial_cash']), deposits + withdrawals)
        pnl=total-capital_base
        previous=self.db.one("SELECT MAX(total_assets) AS peak FROM account_snapshots WHERE account_id=?",(account_id,)); peak=max(total,dec(previous['peak']) if previous and previous['peak'] is not None else total)
        drawdown=(total-peak) if peak else dec(0)
        self.db.execute("UPDATE account_balances SET total_assets=?,updated_at=? WHERE account_id=?",(text(total),now(),account_id))
        self.db.execute("INSERT INTO account_snapshots(account_id,as_of,available_cash,pending_cash,withdrawable_cash,holdings_value,total_assets,pnl,drawdown,created_at) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account_id,as_of) DO UPDATE SET available_cash=excluded.available_cash,pending_cash=excluded.pending_cash,withdrawable_cash=excluded.withdrawable_cash,holdings_value=excluded.holdings_value,total_assets=excluded.total_assets,pnl=excluded.pnl,drawdown=excluded.drawdown,created_at=excluded.created_at",(account_id,str(as_of),b['available_cash'],b['pending_cash'],b['withdrawable_cash'],text(holdings),text(total),text(pnl),text(drawdown),now()))
        return {'account_id':account_id,'as_of':str(as_of),'available_cash':b['available_cash'],'pending_cash':b['pending_cash'],'withdrawable_cash':b['withdrawable_cash'],'holdings_value':text(holdings),'total_assets':text(total),'pnl':text(pnl),'drawdown':text(drawdown),'positions':rows}
