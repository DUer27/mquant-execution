"""Deterministic PAPER-only market-bar replay."""
from __future__ import annotations
from .calendar import is_trading_day
from .settlement import SettlementService
from .snapshots import SnapshotService

class ReplayService:
    def __init__(self, db): self.db = db
    def replay(self, account_id, start, end):
        self.db.account(account_id); start,end=str(start)[:10],str(end)[:10]
        if start > end: raise ValueError('replay_start_after_end')
        dates=[row['bar_date'] for row in self.db.all('SELECT DISTINCT bar_date FROM market_bars WHERE bar_date>=? AND bar_date<=? ORDER BY bar_date',(start,end)) if is_trading_day(row['bar_date'])]
        snapshots=[]; executed=[]
        for as_of in dates:
            SettlementService(self.db).settle(account_id,as_of)
            candidates = self.db.all("SELECT * FROM signals WHERE account_id=? AND action='TARGET_PORTFOLIO' AND status!='EXECUTED' AND signal_date<=? ORDER BY signal_date DESC, imported_at DESC", (account_id, as_of))
            signal = next((candidate for candidate in candidates
                           if str(candidate['effective_at'])[:10] <= as_of
                           and (not candidate['expires_at'] or str(candidate['expires_at'])[:10] >= as_of)), None)
            if signal and self.db.one("SELECT 1 FROM orders WHERE signal_id=? AND status='FILLED'",(signal['signal_id'],)) is None:
                from .planner import RebalancePlanner
                from .execution import ExecutionSimulator
                orders=RebalancePlanner(self.db).plan(account_id,signal['signal_id'],as_of); result=ExecutionSimulator(self.db).execute(account_id,signal['signal_id'],as_of); result['planned_orders']=len(orders); executed.append({'signal_id':signal['signal_id'],'as_of':as_of,**result})
            snapshots.append(SnapshotService(self.db).create(account_id,as_of))
        return {'mode':'PAPER','account_id':account_id,'start':start,'end':end,'trading_days':dates,'executed':executed,'snapshots':snapshots}
