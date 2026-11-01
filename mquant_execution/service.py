from .db import Database
from .importer import SignalImporter
from .planner import RebalancePlanner
from .execution import ExecutionSimulator
from .settlement import SettlementService
from .snapshots import SnapshotService
from .db import now
import json, uuid

class ExecutionService:
    def __init__(self,db): self.db=db; self.db.migrate()
    def deposit(self,account,amount,reference='manual'):
        with self.db.transaction():
            ok=self.db.ledger(account,'DEPOSIT',amount,amount,amount,0,'cashflow',reference,'deposit:'+reference,{'reference':reference})
            if ok: self.db.audit(account,'CASH_DEPOSIT','cashflow',reference,{'amount':str(amount)})
        return ok
    def withdraw(self,account,amount,reference='manual'):
        with self.db.transaction():
            if __import__('decimal').Decimal(str(amount))>__import__('decimal').Decimal(str(self.db.balance(account)['withdrawable_cash'])): raise ValueError('insufficient_withdrawable_cash')
            ok=self.db.ledger(account,'WITHDRAWAL',amount,-__import__('decimal').Decimal(str(amount)),-__import__('decimal').Decimal(str(amount)),0,'cashflow',reference,'withdraw:'+reference,{'reference':reference})
            if ok: self.db.audit(account,'CASH_WITHDRAWAL','cashflow',reference,{'amount':str(amount)})
        return ok
    def import_signal(self,path,account): return SignalImporter(self.db).import_file(path,account)
    def import_signal_data(self,data,account): return SignalImporter(self.db).import_data(data,account)
    def import_quotes(self,path): return SignalImporter(self.db).import_quotes(path)
    def simulate(self,account,signal,as_of):
        run_id='run-'+uuid.uuid4().hex
        self.db.execute("INSERT INTO simulation_runs(run_id,account_id,signal_id,as_of,status,parameters_json,created_at) VALUES (?,?,?,?,?,?,?)",(run_id,account,signal,str(as_of),"RUNNING",json.dumps({'mode':'PAPER'},sort_keys=True),now()))
        try:
            SettlementService(self.db).settle(account,as_of)
            orders=RebalancePlanner(self.db).plan(account,signal,str(as_of)[:10])
            result=ExecutionSimulator(self.db).execute(account,signal,as_of)
            result['planned_orders']=len(orders); result['snapshot']=SnapshotService(self.db).create(account,str(as_of)[:10])
            self.db.execute("UPDATE simulation_runs SET status='SUCCEEDED',result_json=? WHERE run_id=?",(json.dumps(result,default=str,sort_keys=True),run_id))
            return result
        except Exception as exc:
            self.db.execute("UPDATE simulation_runs SET status='FAILED',error=? WHERE run_id=?",(str(exc),run_id)); raise
