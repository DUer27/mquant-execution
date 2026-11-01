"""signal.v1 parsing, validation and deterministic canonical IDs."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone
from decimal import Decimal

class SignalError(ValueError): pass

def parse_time(value):
    if not isinstance(value,str): raise ValueError
    return datetime.fromisoformat(value.replace('Z','+00:00'))

def _canonical_payload(data):
    p={k:v for k,v in data.items() if k not in ('signal_id','generated_at','metadata')}
    if 'portfolio' in p:
        p['portfolio']=sorted(p['portfolio'],key=lambda x:str(x.get('symbol','')))
    return p

def signal_id(data):
    explicit=data.get('signal_id')
    digest=hashlib.sha256(json.dumps(_canonical_payload(data),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return explicit or digest[:32]

def canonical(data): return json.dumps(_canonical_payload(data),ensure_ascii=False,sort_keys=True,separators=(',',':'))

def content_hash(data): return hashlib.sha256(canonical(data).encode('utf-8')).hexdigest()

def validate_signal(data, now=None):
    if not isinstance(data,dict): raise SignalError('signal_must_be_object')
    required=('schema_version','strategy_id','generated_at','signal_date','effective_at','action','gate_status','planned_weight','cash_target_weight','portfolio','provenance')
    missing=[x for x in required if x not in data]
    if missing: raise SignalError('missing_fields:'+','.join(missing))
    if data['schema_version']!='signal.v1': raise SignalError('unsupported_schema_version')
    if data['action'] not in ('TARGET_PORTFOLIO','RECORD_ONLY'): raise SignalError('invalid_action')
    if not isinstance(data['portfolio'],list): raise SignalError('portfolio_must_be_array')
    try: planned=Decimal(str(data['planned_weight'])); cash=Decimal(str(data['cash_target_weight']))
    except Exception: raise SignalError('invalid_weight')
    if planned<0 or cash<0 or planned+cash>1: raise SignalError('weights_exceed_one')
    seen=set(); total=Decimal('0')
    for row in data['portfolio']:
        if not isinstance(row,dict) or not row.get('symbol'): raise SignalError('invalid_portfolio_row')
        sym=str(row['symbol']);
        if not sym.isdigit() or len(sym) not in (5,6): raise SignalError('invalid_symbol:'+sym)
        if sym in seen: raise SignalError('duplicate_symbol:'+sym)
        seen.add(sym)
        if row.get('asset_type','stock') not in ('stock','etf'): raise SignalError('invalid_asset_type:'+sym)
        try: w=Decimal(str(row.get('target_weight','0')))
        except Exception: raise SignalError('invalid_target_weight:'+sym)
        if w<0: raise SignalError('negative_target_weight:'+sym)
        if row.get('target_quantity') is not None and int(row['target_quantity'])<0: raise SignalError('negative_target_quantity:'+sym)
        total+=w
    if total+cash>1: raise SignalError('portfolio_weights_exceed_one')
    prov=data['provenance']
    if not isinstance(prov,dict) or not prov.get('source') or not prov.get('data_policy'): raise SignalError('invalid_provenance')
    try:
        effective=parse_time(data['effective_at']); expiry=parse_time(data['expires_at']) if data.get('expires_at') else None
        if expiry and expiry<=effective: raise SignalError('invalid_expiry')
        if now is not None:
            current=now if isinstance(now,datetime) else parse_time(str(now))
            if expiry and expiry<=current: raise SignalError('signal_expired')
    except SignalError: raise
    except Exception: raise SignalError('invalid_timestamp')
    return {**data,'signal_id':signal_id(data)}
