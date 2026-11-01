from __future__ import annotations
from datetime import datetime, timezone
from .fees import calculate_fee
from .money import dec, money, text
from .risk import RiskEngine
from .calendar import available_on
from .money import floor_lot
from .db import now

class ExecutionSimulator:
    def __init__(self,db): self.db=db; self.risk=RiskEngine(db)
    def execute(self,account_id,signal_id,as_of):
        signal=self.db.one("SELECT * FROM signals WHERE signal_id=? AND account_id=?",(signal_id,account_id))
        if not signal: raise ValueError('unknown_signal')
        orders=self.db.all("SELECT * FROM orders WHERE account_id=? AND signal_id=? ORDER BY CASE side WHEN 'SELL' THEN 0 ELSE 1 END, order_id",(account_id,signal_id))
        if not orders:
            self.db.execute("UPDATE signals SET status='EXECUTED',executed_at=? WHERE signal_id=?",(now(),signal_id))
            return {'orders':0,'fills':0}
        cfg=self.db.config(account_id); fills=0; turnover=dec(0)
        balance=self.db.balance(account_id)
        equity=dec(balance['available_cash'])+dec(balance['pending_cash'])
        for held in self.db.all("SELECT symbol,quantity,average_price FROM positions WHERE account_id=?",(account_id,)):
            market=self.db.one("SELECT price FROM quotes WHERE symbol=? AND quote_date=?",(held['symbol'],str(as_of)[:10]))
            equity += dec(held['quantity'])*(dec(market['price']) if market else dec(held['average_price']))
        with self.db.transaction():
            for order in orders:
                if order['status'] in ('FILLED','REJECTED','RISK_REJECTED'): continue
                q=self.db.one("SELECT * FROM quotes WHERE symbol=? AND quote_date=?",(order['symbol'],order['quote_date'] or str(as_of)[:10]))
                if not q:
                    self._reject(account_id,signal,order,'quote_missing'); continue
                remaining=int(order['quantity'])-int(order['filled_quantity'])
                if remaining <= 0:
                    self.db.execute("UPDATE orders SET status='FILLED' WHERE order_id=?",(order['order_id'],)); continue
                executable=remaining
                if dec(q['volume']) > 0:
                    executable=min(executable, floor_lot(dec(q['volume'])*cfg.max_participation, cfg.default_lot_size))
                if executable <= 0:
                    self._reject(account_id,signal,order,'max_participation'); continue
                effective=dict(order); effective['quantity']=executable
                reason=self.risk.check(account_id,signal,effective,q,equity,turnover,as_of)
                if not reason and order['side']=='SELL':
                    p=self.db.one("SELECT available_quantity FROM positions WHERE account_id=? AND symbol=?",(account_id,order['symbol']))
                    if not p or int(p['available_quantity'])<executable: reason='insufficient_available_position'
                if not reason and order['side']=='BUY':
                    gross=dec(executable)*dec(q['price']); fee=calculate_fee(gross,q['asset_type'],'BUY',cfg)[0]
                    if dec(self.db.balance(account_id)['available_cash'])-gross-fee < dec(0): reason='insufficient_cash'
                    elif dec(self.db.balance(account_id)['available_cash'])-gross-fee < equity*cfg.minimum_cash_reserve: reason='cash_reserve'
                if reason: self._reject(account_id,signal,order,reason); continue
                base=dec(q['ask'] or q['price']) if order['side']=='BUY' else dec(q['bid'] or q['price'])
                price=money(base*(1+cfg.slippage_bps/dec(100000) if order['side']=='BUY' else 1-cfg.slippage_bps/dec(100000)))
                qty=int(executable); gross=money(price*qty); fee,commission,stamp=calculate_fee(gross,q['asset_type'],order['side'],cfg)
                fill_id=f"fill-{order['order_id']}-{int(order['filled_quantity'])+qty}"
                if order['side']=='BUY':
                    self.db.ledger(account_id,'BUY',gross,-gross,-gross,0,'fill',fill_id,f'fill:{fill_id}',{'commission':text(commission),'stamp_tax':text(stamp)})
                    self.db.ledger(account_id,'FEE',fee,-fee,-fee,0,'fill',fill_id,f'fee:{fill_id}',{'commission':text(commission),'stamp_tax':text(stamp),'side':order['side']})
                    self._buy_lot(account_id,order['symbol'],qty,price,fill_id,order['quote_date'])
                else:
                    self.db.ledger(account_id,'SELL',gross,gross,0,gross,'fill',fill_id,f'fill:{fill_id}',{'commission':text(commission),'stamp_tax':text(stamp)})
                    self.db.ledger(account_id,'FEE',fee,-fee,0,-fee,'fill',fill_id,f'fee:{fill_id}',{'commission':text(commission),'stamp_tax':text(stamp),'side':order['side']})
                    self._sell_lots(account_id,order['symbol'],qty)
                self.db.execute("INSERT INTO fills(fill_id,order_id,account_id,symbol,side,quantity,price,gross_amount,fee,commission,stamp_tax,slippage,trade_date,executed_at,idempotency_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (fill_id,order['order_id'],account_id,order['symbol'],order['side'],qty,text(price),text(gross),text(fee),text(commission),text(stamp),text(price-dec(q['price'])),order['quote_date'],now(),fill_id))
                total_filled=int(order['filled_quantity'])+qty
                status='FILLED' if total_filled >= int(order['quantity']) else 'PARTIALLY_FILLED'
                self.db.execute("UPDATE orders SET status=?,filled_quantity=?,updated_at=? WHERE order_id=?",(status,total_filled,now(),order['order_id']))
                self.db.audit(account_id,'FILL_CREATED','fill',fill_id,{'order_id':order['order_id'],'fee':text(fee)})
                turnover+=gross; fills+=1
            self.db.execute("UPDATE signals SET status='EXECUTED',executed_at=? WHERE signal_id=?",(now(),signal_id))
        return {'orders':len(orders),'fills':fills,'turnover':text(turnover)}
    def _reject(self,account,signal,order,reason):
        self.db.execute("UPDATE orders SET status='RISK_REJECTED',reason=?,updated_at=? WHERE order_id=?",(reason,now(),order['order_id']))
        self.risk.reject(account,signal['signal_id'],order['order_id'],reason)
    def _buy_lot(self,account,symbol,qty,price,fill,date):
        self.db.execute("INSERT INTO position_lots(account_id,symbol,buy_date,quantity,available_quantity,unit_cost,source_fill_id) VALUES (?,?,?,?,?,?,?)",(account,symbol,date,qty,0,text(price),fill))
        self._aggregate(account,symbol)
    def _sell_lots(self,account,symbol,qty):
        remain=qty
        for lot in self.db.all("SELECT * FROM position_lots WHERE account_id=? AND symbol=? AND available_quantity>0 ORDER BY buy_date,lot_id",(account,symbol)):
            take=min(remain,int(lot['available_quantity'])); self.db.execute("UPDATE position_lots SET quantity=quantity-?,available_quantity=available_quantity-? WHERE lot_id=?",(take,take,lot['lot_id'])); remain-=take
            if remain==0: break
        if remain: raise ValueError('insufficient_available_position')
        self._aggregate(account,symbol)
    def _aggregate(self,account,symbol):
        rows=self.db.all("SELECT quantity,available_quantity,unit_cost FROM position_lots WHERE account_id=? AND symbol=? AND quantity>0",(account,symbol))
        qty=sum(int(r['quantity']) for r in rows); avail=sum(int(r['available_quantity']) for r in rows); cost=sum((int(r['quantity'])*dec(r['unit_cost']) for r in rows),dec(0))/qty if qty else dec(0)
        if qty: self.db.execute("INSERT INTO positions(account_id,symbol,quantity,available_quantity,average_price,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET quantity=excluded.quantity,available_quantity=excluded.available_quantity,average_price=excluded.average_price,updated_at=excluded.updated_at",(account,symbol,qty,avail,text(cost),now()))
        else: self.db.execute("DELETE FROM positions WHERE account_id=? AND symbol=?",(account,symbol))
