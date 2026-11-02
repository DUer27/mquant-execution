"""SQLite storage, migrations and transactional accounting."""
from __future__ import annotations
import json, shutil, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .money import dec, text
from .config import AccountConfig
from .market import market_bar


def now(): return datetime.now(timezone.utc).isoformat()

class Database:
    def __init__(self, path="runtime/paper.db"):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn=sqlite3.connect(str(self.path), timeout=30, isolation_level=None, check_same_thread=False)
        self.conn.row_factory=sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.execute("PRAGMA busy_timeout=30000")
    def close(self): self.conn.close()
    def migrate(self):
        self.conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)")
        applied={r[0] for r in self.conn.execute("SELECT version FROM schema_migrations")}
        sql_dir=Path(__file__).resolve().parent.parent/'migrations'
        for path in sorted(sql_dir.glob('*.sql')):
            version=int(path.name.split('_',1)[0])
            if version in applied: continue
            with self.transaction():
                self.conn.executescript(path.read_text(encoding='utf-8'))
                self.conn.execute("INSERT INTO schema_migrations(version, applied_at) VALUES (?,?)",(version,now()))
    @contextmanager
    def transaction(self):
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            self.conn.rollback(); raise
        else: self.conn.commit()
    def execute(self, sql, args=()): return self.conn.execute(sql,args)
    def one(self, sql, args=()): return self.conn.execute(sql,args).fetchone()
    def all(self, sql, args=()): return self.conn.execute(sql,args).fetchall()
    def integrity_check(self):
        return self.one("PRAGMA integrity_check")[0]
    def backup(self, output):
        output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
        target=sqlite3.connect(str(output)); self.conn.backup(target); target.close()
    def restore(self, source):
        self.close(); shutil.copy2(source,self.path); self.__init__(self.path); self.migrate()
    def audit(self, account_id, event_type, reference_type=None, reference_id=None, details=None):
        self.execute("INSERT INTO audit_events(account_id,event_type,reference_type,reference_id,details_json,created_at) VALUES (?,?,?,?,?,?)",
                     (account_id,event_type,reference_type,reference_id,json.dumps(details or {},sort_keys=True),now()))
    def create_account(self, account_id, cash='0', config=None):
        cfg=config or AccountConfig()
        with self.transaction():
            if self.one("SELECT account_id FROM accounts WHERE account_id=?",(account_id,)): return False
            value=text(cash)
            self.execute("INSERT INTO accounts(account_id,initial_cash,config_json,created_at) VALUES (?,?,?,?)",(account_id,value,cfg.to_json(),now()))
            self.execute("INSERT INTO account_balances(account_id,updated_at) VALUES (?,?)",(account_id,now()))
            self.audit(account_id,'ACCOUNT_CREATED','account',account_id,{'initial_cash':value})
        return True
    def account(self, account_id):
        row=self.one("SELECT * FROM accounts WHERE account_id=?",(account_id,))
        if not row: raise ValueError(f"unknown account: {account_id}")
        return row
    def config(self, account_id): return AccountConfig.from_json(self.account(account_id)['config_json'])
    def balance(self, account_id): return self.one("SELECT * FROM account_balances WHERE account_id=?",(account_id,))
    def adjust_balance(self, account_id, available=0, withdrawable=0, pending=0, frozen=0, total_assets=None):
        b=self.balance(account_id)
        vals=[dec(b['available_cash'])+dec(available),dec(b['withdrawable_cash'])+dec(withdrawable),dec(b['pending_cash'])+dec(pending),dec(b['frozen_cash'])+dec(frozen)]
        if min(vals[:4]) < 0: raise ValueError('cash_balance_would_be_negative')
        total=text(total_assets if total_assets is not None else vals[0]+vals[2])
        self.execute("UPDATE account_balances SET available_cash=?,withdrawable_cash=?,pending_cash=?,frozen_cash=?,total_assets=?,updated_at=? WHERE account_id=?",
                     (*map(text,vals[:4]),total,now(),account_id))
    def ledger(self, account_id, entry_type, amount, available=0, withdrawable=0, pending=0, reference_type=None, reference_id=None, key=None, details=None):
        key=key or f'{entry_type}:{reference_id or now()}'
        try:
            self.execute("INSERT INTO cash_ledger(account_id,entry_type,amount,available_delta,withdrawable_delta,pending_delta,reference_type,reference_id,idempotency_key,details_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (account_id,entry_type,text(amount),text(available),text(withdrawable),text(pending),reference_type,reference_id,key,json.dumps(details or {},sort_keys=True),now()))
        except sqlite3.IntegrityError:
            return False
        self.adjust_balance(account_id,available,withdrawable,pending)
        return True
    def rebuild_balances(self, account_id):
        with self.transaction():
            rows=self.all("SELECT available_delta,withdrawable_delta,pending_delta FROM cash_ledger WHERE account_id=? ORDER BY entry_id",(account_id,))
            available=sum((dec(r[0]) for r in rows),dec(0)); withdrawable=sum((dec(r[1]) for r in rows),dec(0)); pending=sum((dec(r[2]) for r in rows),dec(0))
            symbols={r['symbol'] for r in self.all("SELECT DISTINCT symbol FROM position_lots WHERE account_id=?",(account_id,))}
            for symbol in symbols:
                lots=self.all("SELECT quantity,available_quantity,unit_cost FROM position_lots WHERE account_id=? AND symbol=? AND quantity>0",(account_id,symbol))
                quantity=sum(int(r['quantity']) for r in lots); available_quantity=sum(int(r['available_quantity']) for r in lots)
                if quantity:
                    average=sum((int(r['quantity'])*dec(r['unit_cost']) for r in lots),dec(0))/quantity
                    self.execute("INSERT INTO positions(account_id,symbol,quantity,available_quantity,average_price,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(account_id,symbol) DO UPDATE SET quantity=excluded.quantity,available_quantity=excluded.available_quantity,average_price=excluded.average_price,updated_at=excluded.updated_at",(account_id,symbol,quantity,available_quantity,text(average),now()))
                else: self.execute("DELETE FROM positions WHERE account_id=? AND symbol=?",(account_id,symbol))
            positions=self.all("SELECT p.symbol,p.quantity,p.average_price,COALESCE(q.price,m.close) AS market_price FROM positions p LEFT JOIN quotes q ON q.symbol=p.symbol AND q.quote_date=(SELECT MAX(quote_date) FROM quotes WHERE symbol=p.symbol) LEFT JOIN market_bars m ON m.symbol=p.symbol AND m.bar_date=(SELECT MAX(bar_date) FROM market_bars WHERE symbol=p.symbol) WHERE p.account_id=?",(account_id,))
            total=available+pending
            for position in positions:
                price=position['market_price']
                if price is None:
                    bar=market_bar(self,position['symbol'],None)
                    price=bar['close'] if bar else position['average_price']
                total += dec(position['quantity'])*dec(price)
            self.execute("UPDATE account_balances SET available_cash=?,withdrawable_cash=?,pending_cash=?,frozen_cash=0,total_assets=?,updated_at=? WHERE account_id=?",(text(available),text(withdrawable),text(pending),text(total),now(),account_id))
            self.audit(account_id,'BALANCES_REBUILT','account',account_id,{'available_cash':text(available),'pending_cash':text(pending)})
        return self.balance(account_id)
