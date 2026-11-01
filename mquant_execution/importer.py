from __future__ import annotations
import json, zipfile
from datetime import datetime, timezone
from pathlib import Path
from .protocol import validate_signal, SignalError, canonical, content_hash
from .money import text
from .db import now

class SignalImporter:
    def __init__(self, db): self.db=db
    def import_file(self, path, account_id):
        path=Path(path)
        if path.suffix.lower()=='.zip':
            with zipfile.ZipFile(path) as z:
                names=z.namelist()
                if any(n.startswith('/') or '..' in Path(n).parts for n in names): raise SignalError('zip_path_traversal')
                allowed=[n for n in names if Path(n).suffix.lower()=='.json' and Path(n).name not in ('manifest.json',)]
                if len(allowed)!=1: raise SignalError('zip_must_contain_one_signal_json')
                data=json.loads(z.read(allowed[0]).decode('utf-8'))
        else: data=json.loads(path.read_text(encoding='utf-8'))
        return self.import_data(data,account_id)
    def import_data(self, data, account_id):
        signal=validate_signal(data,datetime.now(timezone.utc))
        self.db.account(account_id)
        existing=self.db.one("SELECT * FROM signals WHERE signal_id=?",(signal['signal_id'],))
        if existing: return dict(existing), 'DUPLICATE'
        raw=json.dumps(signal,ensure_ascii=False,sort_keys=True)
        with self.db.transaction():
            self.db.execute("INSERT INTO signals(signal_id,account_id,schema_version,strategy_id,strategy_version,sleeve_id,signal_date,effective_at,expires_at,action,gate_status,planned_weight,cash_target_weight,raw_json,canonical_json,content_hash,status,imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (signal['signal_id'],account_id,signal['schema_version'],signal['strategy_id'],signal.get('strategy_version',''),signal.get('sleeve_id',''),signal['signal_date'],signal['effective_at'],signal.get('expires_at'),signal['action'],signal['gate_status'],text(signal['planned_weight']),text(signal['cash_target_weight']),raw,canonical(signal),content_hash(signal), 'IMPORTED',now()))
            for rank,row in enumerate(signal['portfolio'],1):
                self.db.execute("INSERT INTO signal_positions(signal_id,symbol,asset_type,target_weight,target_quantity,rank) VALUES (?,?,?,?,?,?)",
                    (signal['signal_id'],str(row['symbol']),row.get('asset_type','stock'),text(row.get('target_weight','0')),row.get('target_quantity'),row.get('rank',rank)))
            self.db.audit(account_id,'SIGNAL_IMPORTED','signal',signal['signal_id'],{'action':signal['action'],'gate_status':signal['gate_status']})
        return dict(self.db.one("SELECT * FROM signals WHERE signal_id=?",(signal['signal_id'],))), 'IMPORTED'
    def import_quotes(self,path):
        data=json.loads(Path(path).read_text(encoding='utf-8'))
        quote_date=data.get('quote_date') or data.get('date')
        rows=data.get('quotes',data.get('data',data))
        if isinstance(rows,list): rows={str(x['symbol']):x for x in rows}
        if not quote_date: raise ValueError('quotes_require_date')
        with self.db.transaction():
            for symbol,q in rows.items():
                self.db.execute("INSERT INTO quotes(symbol,quote_date,price,bid,ask,volume,tradable,suspended,limit_up,limit_down,asset_type,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,quote_date) DO UPDATE SET price=excluded.price,bid=excluded.bid,ask=excluded.ask,volume=excluded.volume,tradable=excluded.tradable,suspended=excluded.suspended,limit_up=excluded.limit_up,limit_down=excluded.limit_down,asset_type=excluded.asset_type,updated_at=excluded.updated_at",
                    (str(symbol),str(quote_date),text(q['price']),None if q.get('bid') is None else text(q['bid']),None if q.get('ask') is None else text(q['ask']),text(q.get('volume',0)),1 if q.get('tradable',True) else 0,1 if q.get('suspended',False) else 0,q.get('limit_up'),q.get('limit_down'),q.get('asset_type','stock'),now()))
                self.db.audit(None,'QUOTE_IMPORTED','quote',f'{symbol}:{quote_date}',{'symbol':symbol,'quote_date':quote_date})
        return len(rows)
