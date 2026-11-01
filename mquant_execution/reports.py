import csv,io,json
class Reports:
    def __init__(self,db): self.db=db
    def dashboard(self,account_id):
        b=dict(self.db.balance(account_id)); b['account_id']=account_id
        b['positions']=[dict(x) for x in self.db.all("SELECT p.*, q.price FROM positions p LEFT JOIN quotes q ON q.symbol=p.symbol AND q.quote_date=(SELECT MAX(quote_date) FROM quotes WHERE symbol=p.symbol) WHERE p.account_id=?",(account_id,))]
        b['orders']=[dict(x) for x in self.db.all("SELECT * FROM orders WHERE account_id=? ORDER BY created_at DESC",(account_id,))]
        b['fills']=[dict(x) for x in self.db.all("SELECT * FROM fills WHERE account_id=? ORDER BY executed_at DESC",(account_id,))]
        b['cash_ledger']=[dict(x) for x in self.db.all("SELECT * FROM cash_ledger WHERE account_id=? ORDER BY entry_id DESC",(account_id,))]
        b['risk_events']=[dict(x) for x in self.db.all("SELECT * FROM risk_events WHERE account_id=? ORDER BY event_id DESC",(account_id,))]
        b['signals']=[dict(x) for x in self.db.all("SELECT * FROM signals WHERE account_id=? ORDER BY imported_at DESC",(account_id,))]
        b['snapshots']=[dict(x) for x in self.db.all("SELECT * FROM account_snapshots WHERE account_id=? ORDER BY as_of DESC",(account_id,))]
        return b
    def export(self,account_id,fmt='json'):
        data=self.dashboard(account_id)
        if fmt=='json': return json.dumps(data,ensure_ascii=False,default=str,indent=2)
        out=io.StringIO(); w=csv.writer(out); w.writerow(['symbol','quantity','available_quantity','average_price','price'])
        for p in data['positions']: w.writerow([p.get(x,'') for x in ['symbol','quantity','available_quantity','average_price','price']])
        return out.getvalue()
