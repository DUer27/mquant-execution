"""Deterministic PAPER capital-valuation scenarios.

A scenario is intentionally not a strategy execution or backtest.  It values a
configured position map against imported ``market_bars`` and applies explicit
cash-flow, fee, turnover, and shock assumptions.  Real PAPER strategy
execution remains the responsibility of ``ReplayService`` and a temporary
account created through the normal execution services.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

from .db import now
from .money import dec, text


class ScenarioService:
    MODE = 'PAPER_CAPITAL_VALUATION'
    LIMITATIONS = [
        'scenario run does not create orders, fills, positions, or account snapshots',
        'scenario run does not execute signal.v1 or apply broker/T+1 constraints',
        'positions are configured quantities valued at market_bars close prices',
        'return_rate is a simple return on net contributed capital, not a time-weighted backtest return',
    ]

    def __init__(self, db):
        self.db = db
        self.db.migrate()

    def create(self, account_id, scenario_id, name='', initial_cash='0', parameters=None):
        self.db.account(account_id)
        if not scenario_id:
            raise ValueError('scenario_id_required')
        existing = self.db.one('SELECT * FROM scenarios WHERE scenario_id=?', (scenario_id,))
        if existing:
            return dict(existing)
        with self.db.transaction():
            self.db.execute(
                'INSERT INTO scenarios(scenario_id,account_id,name,initial_cash,parameters_json,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                (
                    scenario_id, account_id, name or scenario_id, text(initial_cash),
                    json.dumps(parameters or {}, sort_keys=True), 'READY', now(), now(),
                ),
            )
        return dict(self.db.one('SELECT * FROM scenarios WHERE scenario_id=?', (scenario_id,)))

    def list(self, account_id=None):
        if account_id is None:
            return [dict(x) for x in self.db.all('SELECT * FROM scenarios ORDER BY created_at DESC')]
        return [dict(x) for x in self.db.all('SELECT * FROM scenarios WHERE account_id=? ORDER BY created_at DESC', (account_id,))]

    def add_cashflow(self, scenario_id, event_date, amount, flow_type='DEPOSIT', note='', cashflow_id=None, idempotency_key=None):
        if not self.db.one('SELECT scenario_id FROM scenarios WHERE scenario_id=?', (scenario_id,)):
            raise ValueError('unknown_scenario')
        key = idempotency_key or f'cashflow:{scenario_id}:{event_date}:{flow_type}:{amount}'
        existing = self.db.one('SELECT * FROM scenario_cashflows WHERE idempotency_key=?', (key,))
        if existing:
            return dict(existing)
        cid = cashflow_id or 'cashflow-' + uuid.uuid4().hex
        with self.db.transaction():
            self.db.execute(
                'INSERT INTO scenario_cashflows(cashflow_id,scenario_id,event_date,flow_type,amount,note,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?)',
                (
                    cid, scenario_id, str(event_date)[:10], str(flow_type).upper(),
                    text(amount), note, key, now(),
                ),
            )
        return dict(self.db.one('SELECT * FROM scenario_cashflows WHERE cashflow_id=?', (cid,)))

    def cashflows(self, scenario_id):
        return [dict(x) for x in self.db.all(
            'SELECT * FROM scenario_cashflows WHERE scenario_id=? ORDER BY event_date,cashflow_id',
            (scenario_id,),
        )]

    @staticmethod
    def _shock_rate(parameters):
        return dec(parameters.get('shock_cost_bps', parameters.get('impact_bps', 0))) / dec(10000)

    @staticmethod
    def _fee_rate(parameters):
        return dec(parameters.get('fee_bps', parameters.get('fees_bps', parameters.get('commission_bps', 0)))) / dec(10000)

    @staticmethod
    def _flow_amount(row):
        amount = dec(row['amount'])
        return amount if row['flow_type'] in ('DEPOSIT', 'IN', 'ADD') else -amount

    @staticmethod
    def _flow_result(row):
        return {
            'cashflow_id': row['cashflow_id'],
            'date': row['event_date'],
            'flow_type': row['flow_type'],
            'amount': text(row['amount']),
            'signed_amount': text(ScenarioService._flow_amount(row)),
            'note': row['note'],
        }

    def _dates_and_bars(self, start, end):
        rows = self.db.all(
            'SELECT bar_date,symbol,close FROM market_bars WHERE bar_date>=? AND bar_date<=? ORDER BY bar_date,symbol',
            (start, end),
        )
        by_date = {}
        for row in rows:
            by_date.setdefault(row['bar_date'], {})[row['symbol']] = dec(row['close'])
        return by_date

    def run(self, scenario_id, start_date, end_date, parameters=None, idempotency_key=None):
        scenario = self.db.one('SELECT * FROM scenarios WHERE scenario_id=?', (scenario_id,))
        if not scenario:
            raise ValueError('unknown_scenario')
        start, end = str(start_date)[:10], str(end_date)[:10]
        if start > end:
            raise ValueError('scenario_start_after_end')

        configured = json.loads(scenario['parameters_json'] or '{}')
        configured.update(parameters or {})
        key = idempotency_key or f'scenario:{scenario_id}:{start}:{end}:{json.dumps(configured, sort_keys=True, default=str)}'
        previous = self.db.one('SELECT * FROM scenario_runs WHERE run_id=?', (key,))
        if previous and previous['status'] == 'SUCCEEDED':
            return json.loads(previous['result_json'])
        if previous and previous['status'] == 'RUNNING':
            raise RuntimeError('scenario_run_in_progress')
        if previous:
            self.db.execute('DELETE FROM scenario_runs WHERE run_id=?', (key,))

        self.db.execute(
            'INSERT INTO scenario_runs(run_id,scenario_id,account_id,start_date,end_date,status,parameters_json,idempotency_key,created_at) VALUES (?,?,?,?,?,?,?,?,?)',
            (
                key, scenario_id, scenario['account_id'], start, end, 'RUNNING',
                json.dumps(configured, sort_keys=True, default=str), key, now(),
            ),
        )
        try:
            initial_cash = dec(scenario['initial_cash'])
            all_flows = [row for row in self.cashflows(scenario_id) if start <= row['event_date'] <= end]
            flow_results = [self._flow_result(row) for row in all_flows]
            flows_by_date = {}
            for row in all_flows:
                flows_by_date.setdefault(row['event_date'], dec(0))
                flows_by_date[row['event_date']] += self._flow_amount(row)

            bars_by_date = self._dates_and_bars(start, end)
            dates = sorted(set(bars_by_date) | set(flows_by_date))
            if not dates:
                dates = [end]
            positions = configured.get('positions', {}) or {}
            # Quantities may arrive from JSON as numbers or strings; values are
            # deliberately kept as decimals so the report is deterministic.
            positions = {str(symbol): dec(quantity) for symbol, quantity in positions.items()}
            turnover = dec(configured.get('turnover', configured.get('turnover_amount', 0)))
            fee_rate = self._fee_rate(configured)
            shock_rate = self._shock_rate(configured)
            explicit_fees = dec(configured.get('fees', configured.get('fee_amount', 0)))
            explicit_shock = dec(configured.get('shock_cost', configured.get('impact_cost', 0)))
            fees = explicit_fees + turnover * fee_rate
            shock = explicit_shock + turnover * shock_rate
            total_cost = fees + shock
            cash = initial_cash
            curve = []
            peak = initial_cash
            cumulative_flow = dec(0)
            for date in dates:
                flow = flows_by_date.get(date, dec(0))
                cash += flow
                cumulative_flow += flow
                prices = bars_by_date.get(date, {})
                holdings = sum((quantity * prices.get(symbol, dec(0)) for symbol, quantity in positions.items()), dec(0))
                total_assets = cash + holdings - total_cost
                invested_capital = initial_cash + cumulative_flow
                pnl = total_assets - invested_capital
                peak = max(peak, total_assets)
                drawdown = total_assets - peak
                drawdown_rate = drawdown / peak if peak else dec(0)
                return_rate = pnl / invested_capital if invested_capital else dec(0)
                curve.append({
                    'date': date,
                    'cashflow': text(flow),
                    'cash': text(cash),
                    'holdings': text(holdings),
                    'turnover': text(turnover),
                    'fees': text(fees),
                    'shock_cost': text(shock),
                    'impact_cost': text(shock),
                    'total_cost': text(total_cost),
                    'total_assets': text(total_assets),
                    'pnl': text(pnl),
                    'return_rate': text(return_rate),
                    'drawdown': text(drawdown),
                    'drawdown_rate': text(drawdown_rate),
                })

            final = curve[-1]
            final_assets = dec(final['total_assets'])
            net_capital = initial_cash + cumulative_flow
            final_pnl = final_assets - net_capital
            max_drawdown = min((dec(row['drawdown']) for row in curve), default=dec(0))
            max_drawdown_rate = min((dec(row['drawdown_rate']) for row in curve), default=dec(0))
            result = {
                'schema_version': 'scenario-report.v1',
                'scenario_id': scenario_id,
                'run_id': key,
                'mode': self.MODE,
                'execution_status': 'NOT_EXECUTED',
                'data_policy': 'capital valuation from imported market_bars; no strategy or LIVE orders',
                'start': start,
                'end': end,
                'initial_cash': text(initial_cash),
                'net_contributed_capital': text(net_capital),
                'cashflows': flow_results,
                'curve': curve,
                'final': final,
                'pnl': text(final_pnl),
                'return_rate': text(final_pnl / net_capital if net_capital else dec(0)),
                'drawdown': final['drawdown'],
                'max_drawdown': text(max_drawdown),
                'max_drawdown_rate': text(max_drawdown_rate),
                'turnover': text(turnover),
                'fees': text(fees),
                'fee_bps': text(configured.get('fee_bps', configured.get('fees_bps', configured.get('commission_bps', 0)))),
                'shock': text(shock),
                'shock_cost': text(shock),
                'shock_cost_bps': text(configured.get('shock_cost_bps', configured.get('impact_bps', 0))),
                'limitations': list(self.LIMITATIONS),
                'statistics': {
                    'pnl': text(final_pnl),
                    'return_rate': text(final_pnl / net_capital if net_capital else dec(0)),
                    'drawdown': final['drawdown'],
                    'max_drawdown': text(max_drawdown),
                    'max_drawdown_rate': text(max_drawdown_rate),
                    'cashflows': flow_results,
                    'turnover': text(turnover),
                    'fees': text(fees),
                    'shock': text(shock),
                },
            }
            with self.db.transaction():
                self.db.execute(
                    "UPDATE scenario_runs SET status='SUCCEEDED',result_json=?,finished_at=? WHERE run_id=?",
                    (json.dumps(result, sort_keys=True), now(), key),
                )
            return result
        except Exception as exc:
            self.db.execute(
                "UPDATE scenario_runs SET status='FAILED',error=?,finished_at=? WHERE run_id=?",
                (str(exc), now(), key),
            )
            raise

    def compare(self, scenario_ids, start_date, end_date, parameters=None):
        return {
            'schema_version': 'scenario-report.v1',
            'mode': self.MODE,
            'execution_status': 'NOT_EXECUTED',
            'scenarios': [self.run(x, start_date, end_date, parameters) for x in scenario_ids],
        }

    def runs(self, scenario_id=None):
        sql = 'SELECT * FROM scenario_runs'
        args = ()
        if scenario_id:
            sql += ' WHERE scenario_id=?'
            args = (scenario_id,)
        return [dict(x) for x in self.db.all(sql + ' ORDER BY created_at DESC', args)]
