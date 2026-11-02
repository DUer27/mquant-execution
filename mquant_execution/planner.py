from __future__ import annotations
from .money import dec, floor_lot, text
from .db import now
from .market import market_bar

class RebalancePlanner:
    def __init__(self,db): self.db=db
    def _equity(self, account_id, quote_date):
        b=self.db.balance(account_id); total=dec(b['available_cash'])+dec(b['pending_cash'])
        for p in self.db.all("SELECT * FROM positions WHERE account_id=?",(account_id,)):
            q=self.db.one("SELECT price FROM quotes WHERE symbol=? AND quote_date=?",(p['symbol'],quote_date)); bar=market_bar(self.db,p['symbol'],quote_date)
            total += dec(p['quantity'])*(dec(q['price']) if q else (dec(bar['close']) if bar else dec(p['average_price'])))
        return total
    def plan(self,account_id,signal_id,quote_date):
        signal=self.db.one("SELECT * FROM signals WHERE signal_id=? AND account_id=?",(signal_id,account_id))
        if not signal: raise ValueError('unknown_signal')
        if signal['action']!='TARGET_PORTFOLIO' or signal['gate_status']=='RECORD_ONLY': return []
        equity=self._equity(account_id,quote_date); cfg=self.db.config(account_id)
        targets={r['symbol']:r for r in self.db.all("SELECT * FROM signal_positions WHERE signal_id=?",(signal_id,))}
        current={r['symbol']:r for r in self.db.all("SELECT * FROM positions WHERE account_id=?",(account_id,))}; orders=[]
        for symbol,p in current.items():
            if symbol not in targets:
                qty=int(p['available_quantity'])
                if qty: orders.append(self._make(account_id,signal,symbol,'SELL',qty,quote_date,None,equity,'removed_from_target'))
        for symbol,t in targets.items():
            q=self.db.one("SELECT * FROM quotes WHERE symbol=? AND quote_date=?",(symbol,quote_date)); bar=market_bar(self.db,symbol,quote_date)
            if not q and not bar: continue
            price=q['price'] if q else bar['close']; target=int(t['target_quantity']) if t['target_quantity'] is not None else floor_lot(equity*dec(t['target_weight'])/dec(price),cfg.default_lot_size)
            held=int(current.get(symbol,{}).get('quantity',0)); available=int(current.get(symbol,{}).get('available_quantity',0)); delta=target-held
            if delta<0: orders.append(self._make(account_id,signal,symbol,'SELL',min(-delta,available),quote_date,t['target_weight'],equity,'reduce_to_target'))
            elif delta>0: orders.append(self._make(account_id,signal,symbol,'BUY',delta,quote_date,t['target_weight'],equity,'increase_to_target'))
        return [o for o in orders if o['quantity']>0]
    def _make(self,account,signal,symbol,side,qty,date,weight,equity,reason):
        q=self.db.one("SELECT price FROM quotes WHERE symbol=? AND quote_date=?",(symbol,date)); bar=market_bar(self.db,symbol,date); price=q['price'] if q else (bar['close'] if bar else '0')
        oid=f"ord-{signal['signal_id']}-{symbol}-{side}"
        row={'order_id':oid,'account_id':account,'signal_id':signal['signal_id'],'symbol':symbol,'side':side,'quantity':int(qty),'requested_price':price,'status':'CREATED','filled_quantity':0,'reason':reason,'target_weight':weight,'calculated_equity':text(equity),'quote_date':date,'idempotency_key':oid,'created_at':now(),'updated_at':now()}
        cursor=self.db.execute("INSERT OR IGNORE INTO orders(order_id,account_id,signal_id,symbol,side,quantity,requested_price,status,filled_quantity,reason,target_weight,calculated_equity,quote_date,idempotency_key,created_at,updated_at) VALUES (:order_id,:account_id,:signal_id,:symbol,:side,:quantity,:requested_price,:status,:filled_quantity,:reason,:target_weight,:calculated_equity,:quote_date,:idempotency_key,:created_at,:updated_at)",row)
        if cursor.rowcount: self.db.audit(account, 'ORDER_CREATED', 'order', oid, {'symbol':symbol,'side':side,'quantity':int(qty),'reason':reason})
        return dict(self.db.one("SELECT * FROM orders WHERE order_id=?",(oid,)))
