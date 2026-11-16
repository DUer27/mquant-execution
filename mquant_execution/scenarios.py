"""Isolated PAPER scenario replay and capital valuation.

Scenario execution deliberately runs on a disposable SQLite backup and a
scenario-only account.  The source PAPER account is used as configuration and
as the source of signals/bars, but it never receives orders, fills, lots, or
snapshots from a scenario run.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
import uuid
from dataclasses import fields
from decimal import Decimal
from pathlib import Path

from .calendar import is_trading_day
from .config import AccountConfig
from .db import now, Database
from .execution import ExecutionSimulator
from .market import symbol_variants, market_bar
from .money import dec, text
from .planner import RebalancePlanner
from .settlement import SettlementService
from .snapshots import SnapshotService


class ScenarioService:
    VALUATION_MODE = 'PAPER_CAPITAL_VALUATION'
    EXECUTION_MODE = 'PAPER_REPLAY_EXECUTION'
    MODE = VALUATION_MODE
    LIMITATIONS = [
        'scenario execution is PAPER-only and uses a disposable SQLite account',
        'market data is limited to imported market_bars and existing PAPER execution constraints',
        'the source account is never mutated with scenario orders, fills, lots, or snapshots',
        'daily replay is deterministic but does not provide LIVE trading or broker connectivity',
    ]
    VALUATION_LIMITATIONS = [
        'no eligible TARGET_PORTFOLIO signal was selected; no orders or fills were created',
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
                    json.dumps(parameters or {}, sort_keys=True, default=str), 'READY', now(), now(),
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
    def _fee_rate(parameters):
        return dec(parameters.get('fee_bps', parameters.get('fees_bps', parameters.get('commission_bps', 0)))) / dec(10000)

    @staticmethod
    def _shock_rate(parameters):
        return dec(parameters.get('shock_cost_bps', parameters.get('impact_bps', 0))) / dec(10000)

    @staticmethod
    def _flow_amount(row):
        amount = dec(row['amount'])
        return amount if str(row.get('flow_type', 'DEPOSIT')).upper() in ('DEPOSIT', 'IN', 'ADD') else -amount

    @classmethod
    def _flow_result(cls, row):
        return {
            'cashflow_id': row['cashflow_id'],
            'date': str(row['event_date'])[:10],
            'flow_type': str(row.get('flow_type', 'DEPOSIT')).upper(),
            'amount': text(row['amount']),
            'signed_amount': text(cls._flow_amount(row)),
            'note': row.get('note', ''),
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

    @staticmethod
    def _price(prices, symbol):
        for variant in symbol_variants(symbol):
            if variant in prices:
                return prices[variant]
        return dec(0)

    @classmethod
    def _position_map(cls, value):
        if not value:
            return {}
        if isinstance(value, dict):
            return {str(symbol): dec(quantity) for symbol, quantity in value.items()}
        result = {}
        for row in value if isinstance(value, list) else []:
            if isinstance(row, dict) and row.get('symbol'):
                result[str(row['symbol'])] = dec(row.get('quantity', row.get('target_quantity', 0)))
        return result

    @classmethod
    def _inline_flows(cls, value, start, scenario_id):
        """Normalize the convenient run-time ``cashflow`` parameter."""
        if value in (None, '', 0, '0', False):
            return []
        rows = []
        if isinstance(value, (int, float, Decimal, str)):
            value = [{'event_date': start, 'amount': value, 'flow_type': 'DEPOSIT'}]
        elif isinstance(value, dict):
            if 'amount' in value:
                value = [value]
            else:
                value = [
                    {'event_date': event_date, 'amount': amount, 'flow_type': 'DEPOSIT'}
                    for event_date, amount in value.items()
                ]
        if not isinstance(value, list):
            return rows
        for index, item in enumerate(value):
            if not isinstance(item, dict) or item.get('amount') is None:
                continue
            event_date = str(item.get('event_date', item.get('date', start)))[:10]
            rows.append({
                'cashflow_id': str(item.get('cashflow_id', f'inline:{scenario_id}:{event_date}:{index}')),
                'event_date': event_date,
                'flow_type': str(item.get('flow_type', 'DEPOSIT')).upper(),
                'amount': text(item['amount']),
                'note': str(item.get('note', '')),
            })
        return rows

    def _run_flows(self, scenario_id, start, configured):
        rows = [dict(row) for row in self.cashflows(scenario_id)
                if start <= str(row['event_date'])[:10] <= configured['_end_date']]
        rows.extend(self._inline_flows(configured.get('cashflow'), start, scenario_id))
        rows.sort(key=lambda row: (str(row['event_date'])[:10], str(row['cashflow_id'])))
        return rows

    def _select_signal(self, scenario, configured, start, end):
        account_id = scenario['account_id']
        explicit_signal = configured.get('signal_id')
        explicit_strategy = configured.get('strategy_id')
        activation = self.db.one(
            "SELECT * FROM strategy_activations WHERE account_id=? AND status='ACTIVE' ORDER BY activated_at DESC LIMIT 1",
            (account_id,),
        )
        strategy_id = str(explicit_strategy) if explicit_strategy else (activation['strategy_id'] if activation else None)
        params = [account_id]
        clauses = ['account_id=?']
        if explicit_signal:
            clauses.append('signal_id=?')
            params.append(str(explicit_signal))
        elif strategy_id:
            clauses.append('strategy_id=?')
            params.append(strategy_id)
        clauses.append("action IN ('TARGET_PORTFOLIO','RECORD_ONLY')")
        rows = self.db.all(
            'SELECT * FROM signals WHERE ' + ' AND '.join(clauses) +
            " ORDER BY CASE WHEN action='TARGET_PORTFOLIO' THEN 0 ELSE 1 END, signal_date DESC, imported_at DESC, signal_id DESC", params,
        )
        # An explicitly requested signal is authoritative.  Otherwise only a
        # signal whose active window intersects the replay range is eligible.
        eligible = []
        for row in rows:
            effective = str(row['effective_at'])[:10]
            expiry = str(row['expires_at'])[:10] if row['expires_at'] else None
            if explicit_signal or (effective <= end and (not expiry or expiry >= start)):
                eligible.append(row)
        return eligible[0] if eligible else None

    @staticmethod
    def _scenario_config(source_config, parameters):
        cfg = source_config
        known = {field.name for field in fields(AccountConfig)}
        for key, value in parameters.items():
            if key in known:
                old = getattr(cfg, key)
                setattr(cfg, key, type(old)(value))
        if any(key in parameters for key in ('fee_bps', 'fees_bps', 'commission_bps')):
            cfg.commission_rate = ScenarioService._fee_rate(parameters)
            cfg.min_commission = dec(0)
        if any(key in parameters for key in ('shock_cost_bps', 'impact_bps')):
            cfg.slippage_bps = dec(parameters.get('shock_cost_bps', parameters.get('impact_bps')))
        return cfg
    @staticmethod
    def _clone_signal(db, signal, account_id, run_id):
        clone_id = 'scenario-signal-' + hashlib.sha256((run_id + ':' + signal['signal_id']).encode()).hexdigest()[:28]
        values = dict(signal)
        values.update({'signal_id': clone_id, 'account_id': account_id, 'status': 'IMPORTED', 'executed_at': None})
        columns = [
            'signal_id', 'account_id', 'schema_version', 'strategy_id', 'strategy_version', 'sleeve_id',
            'signal_date', 'effective_at', 'expires_at', 'action', 'gate_status', 'planned_weight',
            'cash_target_weight', 'raw_json', 'canonical_json', 'content_hash', 'status', 'imported_at', 'executed_at',
        ]
        db.execute(
            'INSERT INTO signals(' + ','.join(columns) + ') VALUES (' + ','.join('?' for _ in columns) + ')',
            tuple(values.get(column) for column in columns),
        )
        for position in db.all('SELECT * FROM signal_positions WHERE signal_id=?', (signal['signal_id'],)):
            db.execute(
                'INSERT INTO signal_positions(signal_id,symbol,asset_type,target_weight,target_quantity,rank) VALUES (?,?,?,?,?,?)',
                (clone_id, position['symbol'], position['asset_type'], position['target_weight'], position['target_quantity'], position['rank']),
            )
        return clone_id

    @staticmethod
    def _seed_positions(db, account_id, positions, as_of):
        for index, (symbol, quantity_value) in enumerate(positions.items()):
            quantity = int(quantity_value)
            if quantity <= 0:
                continue
            bar = market_bar(db, symbol, as_of)
            price = text(bar['close'] if bar else 0)
            source_fill = f'scenario-seed-{account_id}-{index}-{symbol}'
            db.execute(
                'INSERT INTO position_lots(account_id,symbol,buy_date,quantity,available_quantity,unit_cost,source_fill_id) VALUES (?,?,?,?,?,?,?)',
                (account_id, symbol, str(as_of)[:10], quantity, quantity, price, source_fill),
            )
            db.execute(
                'INSERT INTO positions(account_id,symbol,quantity,available_quantity,average_price,updated_at) VALUES (?,?,?,?,?,?)',
                (account_id, symbol, quantity, quantity, price, now()),
            )

    @staticmethod
    def _apply_flow(db, account_id, row, run_id):
        signed = ScenarioService._flow_amount(row)
        if not signed:
            return
        if signed > 0:
            entry_type, amount, available, withdrawable = 'DEPOSIT', signed, signed, signed
        else:
            entry_type, amount, available, withdrawable = 'WITHDRAWAL', -signed, signed, signed
        db.ledger(
            account_id, entry_type, amount, available, withdrawable, 0,
            'scenario_cashflow', str(row['cashflow_id']),
            f'{run_id}:cashflow:{row["cashflow_id"]}', {'scenario': run_id},
        )

    @staticmethod
    def _records(db, table, account_id):
        return [dict(row) for row in db.all(f'SELECT * FROM {table} WHERE account_id=? ORDER BY rowid', (account_id,))]

    def _execution_report(self, scenario, key, start, end, configured, initial_cash, flow_rows, signal, temp_db, temp_account, snapshots):
        orders = self._records(temp_db, 'orders', temp_account)
        fills = self._records(temp_db, 'fills', temp_account)
        lots = self._records(temp_db, 'position_lots', temp_account)
        turnover = sum((dec(row['gross_amount']) for row in fills), dec(0))
        fees = sum((dec(row['fee']) for row in fills), dec(0))
        shock = sum((abs(dec(row['slippage'])) * int(row['quantity']) for row in fills), dec(0))
        filled_orders = sum(1 for row in orders if int(row['filled_quantity']) > 0)
        rejected_orders = sum(1 for row in orders if row['status'] in ('REJECTED', 'RISK_REJECTED'))
        final = snapshots[-1] if snapshots else {
            'total_assets': text(initial_cash), 'pnl': text(0), 'drawdown': text(0),
        }
        net_capital = initial_cash + sum((self._flow_amount(row) for row in flow_rows), dec(0))
        final_assets = dec(final['total_assets'])
        pnl = final_assets - net_capital
        return_rate = pnl / net_capital if net_capital else dec(0)
        max_drawdown = min((dec(row['drawdown']) for row in snapshots), default=dec(0))
        max_drawdown_rate = min((dec(row.get('drawdown_rate', '0')) for row in snapshots), default=dec(0))
        statistics = {
            'pnl': text(pnl), 'return': text(return_rate), 'return_rate': text(return_rate),
            'drawdown': final.get('drawdown', text(0)), 'max_drawdown': text(max_drawdown),
            'max_drawdown_rate': text(max_drawdown_rate), 'turnover': text(turnover),
            'fees': text(fees), 'shock_cost': text(shock), 'filled_orders': filled_orders,
            'rejected_orders': rejected_orders, 'fills': len(fills), 'cashflows': [self._flow_result(row) for row in flow_rows],
        }
        return {
            'schema_version': 'scenario-report.v1', 'scenario_id': scenario['scenario_id'], 'run_id': key,
            'account_id': scenario['account_id'], 'mode': self.EXECUTION_MODE, 'execution_status': 'EXECUTED',
            'isolated_account': temp_account, 'signal_id': signal['signal_id'], 'strategy_id': signal['strategy_id'],
            'data_policy': 'isolated PAPER replay from imported market_bars using planner, execution, settlement, and snapshots',
            'start': start, 'end': end, 'initial_cash': text(initial_cash),
            'net_contributed_capital': text(net_capital), 'cashflows': [self._flow_result(row) for row in flow_rows],
            'curve': snapshots, 'snapshots': snapshots, 'orders': orders, 'fills': fills, 'position_lots': lots,
            'final': final, 'pnl': text(pnl), 'return': text(return_rate), 'return_rate': text(return_rate),
            'drawdown': final.get('drawdown', text(0)), 'max_drawdown': text(max_drawdown),
            'max_drawdown_rate': text(max_drawdown_rate), 'turnover': text(turnover), 'fees': text(fees),
            'fee_bps': text(configured.get('fee_bps', configured.get('fees_bps', configured.get('commission_bps', 0)))),
            'shock': text(shock), 'shock_cost': text(shock),
            'shock_cost_bps': text(configured.get('shock_cost_bps', configured.get('impact_bps', 0))),
            'filled_orders': filled_orders, 'rejected_orders': rejected_orders, 'fills_count': len(fills),
            'orders_count': len(orders), 'position_lots_count': len(lots), 'snapshots_count': len(snapshots),
            'blocked': False, 'limitations': list(self.LIMITATIONS), 'statistics': statistics,
        }

    def _valuation_report(self, scenario, key, start, end, configured):
        initial_cash = dec(configured.get('initial_cash', scenario['initial_cash']))
        flow_rows = self._run_flows(scenario['scenario_id'], start, configured)
        bars_by_date = self._dates_and_bars(start, end)
        flow_by_date = {}
        for row in flow_rows:
            flow_by_date.setdefault(str(row['event_date'])[:10], dec(0))
            flow_by_date[str(row['event_date'])[:10]] += self._flow_amount(row)
        dates = sorted(set(bars_by_date) | set(flow_by_date)) or [end]
        positions = self._position_map(configured.get('positions', {}))
        turnover = dec(configured.get('turnover', configured.get('turnover_amount', 0)))
        fee_rate = self._fee_rate(configured)
        shock_rate = self._shock_rate(configured)
        fees = dec(configured.get('fees', configured.get('fee_amount', 0))) + turnover * fee_rate
        shock = dec(configured.get('shock_cost', configured.get('impact_cost', 0))) + turnover * shock_rate
        total_cost = fees + shock
        cash = initial_cash
        cumulative_flow = dec(0)
        peak = initial_cash
        curve = []
        for date in dates:
            flow = flow_by_date.get(date, dec(0))
            cash += flow
            cumulative_flow += flow
            holdings = sum((quantity * self._price(bars_by_date.get(date, {}), symbol)
                            for symbol, quantity in positions.items()), dec(0))
            total_assets = cash + holdings - total_cost
            invested_capital = initial_cash + cumulative_flow
            pnl = total_assets - invested_capital
            peak = max(peak, total_assets)
            drawdown = total_assets - peak
            drawdown_rate = drawdown / peak if peak else dec(0)
            return_rate = pnl / invested_capital if invested_capital else dec(0)
            curve.append({
                'date': date, 'cashflow': text(flow), 'cash': text(cash), 'holdings': text(holdings),
                'turnover': text(turnover), 'fees': text(fees), 'shock_cost': text(shock),
                'impact_cost': text(shock), 'total_cost': text(total_cost), 'total_assets': text(total_assets),
                'pnl': text(pnl), 'return': text(return_rate), 'return_rate': text(return_rate),
                'drawdown': text(drawdown), 'drawdown_rate': text(drawdown_rate),
            })
        final = curve[-1]
        net_capital = initial_cash + cumulative_flow
        final_pnl = dec(final['total_assets']) - net_capital
        result = {
            'schema_version': 'scenario-report.v1', 'scenario_id': scenario['scenario_id'], 'run_id': key,
            'account_id': scenario['account_id'], 'mode': self.VALUATION_MODE, 'execution_status': 'NOT_EXECUTED',
            'data_policy': 'capital valuation from imported market_bars; no strategy or LIVE orders',
            'start': start, 'end': end, 'initial_cash': text(initial_cash),
            'net_contributed_capital': text(net_capital), 'cashflows': [self._flow_result(row) for row in flow_rows],
            'curve': curve, 'final': final, 'pnl': text(final_pnl), 'return': text(final_pnl / net_capital if net_capital else 0),
            'return_rate': text(final_pnl / net_capital if net_capital else 0), 'drawdown': final['drawdown'],
            'max_drawdown': text(min((dec(row['drawdown']) for row in curve), default=dec(0))),
            'max_drawdown_rate': text(min((dec(row['drawdown_rate']) for row in curve), default=dec(0))),
            'turnover': text(turnover), 'fees': text(fees),
            'fee_bps': text(configured.get('fee_bps', configured.get('fees_bps', configured.get('commission_bps', 0)))),
            'shock': text(shock), 'shock_cost': text(shock),
            'shock_cost_bps': text(configured.get('shock_cost_bps', configured.get('impact_bps', 0))),
            'filled_orders': 0, 'rejected_orders': 0, 'fills_count': 0, 'orders_count': 0,
            'position_lots_count': 0, 'snapshots_count': 0, 'blocked': False,
            'limitations': list(self.VALUATION_LIMITATIONS),
        }
        result['statistics'] = {
            'pnl': result['pnl'], 'return': result['return'], 'return_rate': result['return_rate'],
            'drawdown': result['drawdown'], 'max_drawdown': result['max_drawdown'],
            'max_drawdown_rate': result['max_drawdown_rate'], 'cashflows': result['cashflows'],
            'turnover': result['turnover'], 'fees': result['fees'], 'shock_cost': result['shock_cost'],
            'filled_orders': 0, 'rejected_orders': 0,
        }
        return result

    def _blocked_report(self, scenario, key, start, end, configured, signal):
        initial_cash = dec(configured.get('initial_cash', scenario['initial_cash']))
        flow_rows = self._run_flows(scenario['scenario_id'], start, configured)
        return {
            'schema_version': 'scenario-report.v1', 'scenario_id': scenario['scenario_id'], 'run_id': key,
            'account_id': scenario['account_id'], 'mode': 'PAPER_SIGNAL_BLOCKED', 'execution_status': 'BLOCKED',
            'signal_id': signal['signal_id'], 'strategy_id': signal['strategy_id'], 'blocked': True,
            'block_reason': 'RECORD_ONLY', 'data_policy': 'RECORD_ONLY signal recorded without PAPER execution',
            'start': start, 'end': end, 'initial_cash': text(initial_cash),
            'net_contributed_capital': text(initial_cash), 'cashflows': [self._flow_result(row) for row in flow_rows],
            'curve': [], 'snapshots': [], 'orders': [], 'fills': [], 'position_lots': [], 'final': {},
            'pnl': text(0), 'return': text(0), 'return_rate': text(0), 'drawdown': text(0),
            'max_drawdown': text(0), 'max_drawdown_rate': text(0), 'turnover': text(0), 'fees': text(0),
            'fee_bps': text(configured.get('fee_bps', 0)), 'shock': text(0), 'shock_cost': text(0),
            'shock_cost_bps': text(configured.get('shock_cost_bps', 0)), 'filled_orders': 0,
            'rejected_orders': 0, 'fills_count': 0, 'orders_count': 0, 'position_lots_count': 0,
            'snapshots_count': 0, 'limitations': list(self.LIMITATIONS),
            'statistics': {'filled_orders': 0, 'rejected_orders': 0, 'blocked': True},
        }

    def run(self, scenario_id, start_date, end_date, parameters=None, idempotency_key=None, strategy_id=None, signal_id=None):
        scenario = self.db.one('SELECT * FROM scenarios WHERE scenario_id=?', (scenario_id,))
        if not scenario:
            raise ValueError('unknown_scenario')
        start, end = str(start_date)[:10], str(end_date)[:10]
        if start > end:
            raise ValueError('scenario_start_after_end')
        configured = json.loads(scenario['parameters_json'] or '{}')
        configured.update(parameters or {})
        if strategy_id is not None:
            configured['strategy_id'] = strategy_id
        if signal_id is not None:
            configured['signal_id'] = signal_id
        configured['_end_date'] = end
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
            (key, scenario_id, scenario['account_id'], start, end, 'RUNNING', json.dumps(configured, sort_keys=True, default=str), key, now()),
        )
        try:
            signal = self._select_signal(scenario, configured, start, end)
            if signal and (str(signal['action']).upper() == 'RECORD_ONLY' or str(signal['gate_status']).upper() == 'RECORD_ONLY'):
                result = self._blocked_report(scenario, key, start, end, configured, signal)
            elif not signal:
                result = self._valuation_report(scenario, key, start, end, configured)
            else:
                result = self._run_isolated(scenario, key, start, end, configured, signal)
            with self.db.transaction():
                self.db.execute(
                    "UPDATE scenario_runs SET status='SUCCEEDED',result_json=?,finished_at=? WHERE run_id=?",
                    (json.dumps(result, sort_keys=True, default=str), now(), key),
                )
            return result
        except Exception as exc:
            self.db.execute(
                "UPDATE scenario_runs SET status='FAILED',error=?,finished_at=? WHERE run_id=?",
                (str(exc), now(), key),
            )
            raise

    def _run_isolated(self, scenario, key, start, end, configured, signal):
        bars_by_date = self._dates_and_bars(start, end)
        flow_rows = self._run_flows(scenario['scenario_id'], start, configured)
        dates = sorted(set(bars_by_date) | {str(row['event_date'])[:10] for row in flow_rows})
        dates = [date for date in dates if is_trading_day(date)] or [end]
        initial_cash = dec(configured.get('initial_cash', scenario['initial_cash']))
        source_config = self.db.config(scenario['account_id'])
        config = self._scenario_config(source_config, configured)
        isolated_id = 'scenario-account-' + hashlib.sha256(key.encode()).hexdigest()[:24]
        with tempfile.TemporaryDirectory(prefix='mquant-scenario-') as directory:
            path = Path(directory) / 'scenario.db'
            self.db.backup(path)
            temp_db = Database(path)
            try:
                temp_db.migrate()
                temp_db.create_account(isolated_id, initial_cash, config)
                with temp_db.transaction():
                    temp_db.ledger(isolated_id, 'DEPOSIT', initial_cash, initial_cash, initial_cash, 0,
                                   'scenario', key, f'{key}:initial_cash', {'scenario_id': scenario['scenario_id']})
                    self._seed_positions(temp_db, isolated_id, self._position_map(configured.get('positions')), dates[0])
                    clone_signal = self._clone_signal(temp_db, signal, isolated_id, key)
                snapshots = []
                executed_signal = False
                for as_of in dates:
                    for row in flow_rows:
                        if str(row['event_date'])[:10] == as_of:
                            self._apply_flow(temp_db, isolated_id, row, key)
                    SettlementService(temp_db).settle(isolated_id, as_of)
                    clone = temp_db.one('SELECT * FROM signals WHERE signal_id=?', (clone_signal,))
                    effective = str(clone['effective_at'])[:10]
                    expiry = str(clone['expires_at'])[:10] if clone['expires_at'] else None
                    if not executed_signal and effective <= as_of and (not expiry or expiry > as_of):
                        orders = RebalancePlanner(temp_db).plan(isolated_id, clone_signal, as_of)
                        execution = ExecutionSimulator(temp_db).execute(isolated_id, clone_signal, as_of)
                        execution['planned_orders'] = len(orders)
                        executed_signal = True
                    snapshots.append(SnapshotService(temp_db).create(isolated_id, as_of))
                result = self._execution_report(scenario, key, start, end, configured, initial_cash, flow_rows, signal, temp_db, isolated_id, snapshots)
            finally:
                temp_db.close()
        return result

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
