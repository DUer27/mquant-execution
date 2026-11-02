from __future__ import annotations
import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from .protocol import validate_signal, SignalError, canonical, content_hash
from .money import text
from .db import now
from .market import normalize_symbol


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

    @staticmethod
    def _bool(value, default=True):
        if value is None or value == '': return 1 if default else 0
        if isinstance(value, str): return 0 if value.strip().lower() in ('0','false','no','n','停牌','不可交易') else 1
        return 1 if value else 0

    @classmethod
    def _bar_row(cls, row):
        row = {str(k).strip().lower(): v for k, v in dict(row).items()}
        symbol = row.get('symbol') or row.get('code') or row.get('security')
        date = row.get('date') or row.get('bar_date') or row.get('trade_date')
        if not symbol or not date: raise ValueError('bar_requires_code_and_date')
        required = ('open', 'close', 'high', 'low')
        if any(row.get(key) in (None, '') for key in required):
            raise ValueError('bar_requires_ohlc')
        return {
            'symbol': normalize_symbol(symbol), 'bar_date': str(date)[:10],
            'open': text(row['open']), 'close': text(row['close']),
            'high': text(row['high']), 'low': text(row['low']),
            'volume': text(row.get('volume', 0) or 0), 'amount': text(row.get('amount', 0) or 0),
            'security': row.get('security'), 'source': row.get('source') or row.get('data_source'),
            'adjust': row.get('adjust') or row.get('adjust_type'), 'name': row.get('name'),
            'prev_close': None if row.get('prev_close') in (None, '') else text(row['prev_close']),
            'tradable': cls._bool(row.get('tradable'), True),
        }

    def import_bars(self, rows):
        if isinstance(rows, dict):
            rows = rows.get('bars', rows.get('data', rows))
            if isinstance(rows, dict) and any(key in rows for key in ('code', 'symbol')):
                rows = [rows]
            elif isinstance(rows, dict):
                flattened=[]
                for symbol, values in rows.items():
                    if isinstance(values, list):
                        flattened.extend(dict(item, symbol=symbol) for item in values)
                    elif isinstance(values, dict):
                        flattened.append(dict(values, symbol=symbol))
                rows=flattened
        if not isinstance(rows, list): raise ValueError('bars_must_be_list')
        parsed=[self._bar_row(row) for row in rows]
        timestamp=now()
        with self.db.transaction():
            for row in parsed:
                self.db.execute("INSERT INTO market_bars(symbol,date,bar_date,open,close,high,low,volume,amount,security,source,adjust,name,prev_close,tradable,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,bar_date) DO UPDATE SET date=excluded.date,open=excluded.open,close=excluded.close,high=excluded.high,low=excluded.low,volume=excluded.volume,amount=excluded.amount,security=excluded.security,source=excluded.source,adjust=excluded.adjust,name=excluded.name,prev_close=excluded.prev_close,tradable=excluded.tradable,updated_at=excluded.updated_at",
                    (row['symbol'],row['bar_date'],row['bar_date']) + tuple(row[key] for key in ('open','close','high','low','volume','amount','security','source','adjust','name','prev_close','tradable')) + (timestamp, timestamp))
        return len(parsed)

    def import_bars_csv(self, csv_text):
        return self.import_bars(list(csv.DictReader(io.StringIO(str(csv_text).lstrip('\ufeff')))))

    def import_bars_json(self, payload):
        if isinstance(payload, str): payload=json.loads(payload)
        return self.import_bars(payload)

    def import_bars_file(self, path):
        path=Path(path)
        if path.suffix.lower() == '.csv':
            return self.import_bars_csv(path.read_text(encoding='utf-8-sig'))
        return self.import_bars_json(path.read_text(encoding='utf-8'))
