from datetime import datetime, timezone
from .calendar import is_session, is_trading_day
from .money import dec

def _as_of_instant(value):
    if isinstance(value, datetime):
        return value
    raw = str(value).replace('Z', '+00:00')
    if len(raw) <= 10:
        return datetime.fromisoformat(raw[:10] + 'T15:00:00+08:00')
    return datetime.fromisoformat(raw)


def _is_valid_execution_time(value):
    if isinstance(value, datetime):
        return is_session(value)
    raw = str(value)
    if len(raw) <= 10:
        return is_trading_day(raw)
    return is_session(raw)


class RiskEngine:
    def __init__(self, db): self.db=db
    def reject(self, account_id, signal_id, order_id, reason, details=None):
        self.db.execute("INSERT INTO risk_events(account_id,signal_id,order_id,level,reason,details_json,created_at) VALUES (?,?,?,?,?,?,?)",(account_id,signal_id,order_id,'REJECT',reason,__import__('json').dumps(details or {},sort_keys=True),datetime.now(timezone.utc).isoformat()))
        self.db.audit(account_id,'RISK_REJECTED','order',order_id,{'reason':reason,**(details or {})})
    def check(self, account_id, signal, order, quote, equity, turnover, as_of):
        cfg=self.db.config(account_id); q=quote
        if signal['gate_status'] not in ('ready','ready_controlled_paper_watch','ready_for_controlled_paper_watch','ready_local_paper_watch','PAPER'): return 'gate_not_approved'
        if signal['action'] != 'TARGET_PORTFOLIO': return 'record_only'
        if signal['expires_at'] and _as_of_instant(signal['expires_at']) <= _as_of_instant(as_of): return 'signal_expired'
        if not _is_valid_execution_time(as_of): return 'outside_trading_session'
        if int(q['tradable']) != 1 or int(q['suspended']) != 0: return 'quote_not_tradable'
        if order['quantity'] <= 0: return 'invalid_quantity'
        lot=cfg.default_lot_size
        if order['quantity'] % lot: return 'invalid_lot_size'
        gross=dec(order['quantity'])*dec(q['price'])
        if gross > cfg.max_order_value: return 'max_order_value'
        if equity and gross/equity > cfg.max_symbol_weight and order['side']=='BUY': return 'max_symbol_weight'
        if equity and turnover+gross > equity*cfg.max_turnover: return 'max_turnover'
        if q['limit_up'] is not None and order['side']=='BUY' and dec(q['price']) >= dec(q['limit_up']): return 'limit_up'
        if q['limit_down'] is not None and order['side']=='SELL' and dec(q['price']) <= dec(q['limit_down']): return 'limit_down'
        return None
