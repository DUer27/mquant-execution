import csv
import io
import json
from .market import latest_market_bar
from .money import dec, text


class Reports:
    def __init__(self, db):
        self.db = db

    def dashboard(self, account_id):
        account = dict(self.db.account(account_id))
        balance = dict(self.db.balance(account_id))
        report = dict(balance)
        report.update({'account_id': account_id, 'account': account,
                       'cash': balance['available_cash'], 'pending': balance['pending_cash'],
                       'withdrawable': balance['withdrawable_cash']})
        report['positions'] = []
        holdings = dec(0)
        for row in self.db.all("SELECT * FROM positions WHERE account_id=?", (account_id,)):
            position = dict(row)
            quote = self.db.one("SELECT price FROM quotes WHERE symbol=? ORDER BY quote_date DESC LIMIT 1", (row['symbol'],))
            bar = latest_market_bar(self.db, row['symbol'])
            position['price'] = quote['price'] if quote else (bar['close'] if bar else None)
            if position['price'] is not None:
                position['market_value'] = text(dec(position['quantity']) * dec(position['price']))
                holdings += dec(position['market_value'])
            report['positions'].append(position)
        report['holdings_value'] = text(holdings)
        report['orders'] = [dict(row) for row in self.db.all("SELECT * FROM orders WHERE account_id=? ORDER BY created_at DESC", (account_id,))]
        report['fills'] = [dict(row) for row in self.db.all("SELECT * FROM fills WHERE account_id=? ORDER BY executed_at DESC", (account_id,))]
        report['transactions'] = report['fills']
        report['cash_ledger'] = [dict(row) for row in self.db.all("SELECT * FROM cash_ledger WHERE account_id=? ORDER BY entry_id DESC", (account_id,))]
        total_assets = dec(balance['available_cash']) + dec(balance['pending_cash']) + holdings
        deposited = sum((dec(row['available_delta']) for row in report['cash_ledger'] if row['entry_type'] == 'DEPOSIT'), dec('0'))
        withdrawn = sum((dec(row['available_delta']) for row in report['cash_ledger'] if row['entry_type'] == 'WITHDRAWAL'), dec('0'))
        initial_cash = max(dec(account['initial_cash']), deposited + withdrawn)
        report['total_assets'] = text(total_assets)
        report['initial_cash'] = text(initial_cash)
        report['pnl'] = text(total_assets - initial_cash)
        report['drawdown'] = text(total_assets - initial_cash if total_assets < initial_cash else dec('0'))
        report['signals'] = [dict(row) for row in self.db.all("SELECT * FROM signals WHERE account_id=? ORDER BY imported_at DESC", (account_id,))]
        report['strategy_markers'] = [{'signal_id': row['signal_id'], 'strategy_id': row['strategy_id'], 'signal_date': row['signal_date'], 'action': row['action'], 'status': row['status']} for row in report['signals']]
        report['risk_events'] = [dict(row) for row in self.db.all("SELECT * FROM risk_events WHERE account_id=? ORDER BY event_id DESC", (account_id,))]
        report['snapshots'] = [dict(row) for row in self.db.all("SELECT * FROM account_snapshots WHERE account_id=? ORDER BY as_of DESC", (account_id,))]
        report['audit_events'] = [dict(row) for row in self.db.all("SELECT * FROM audit_events WHERE account_id=? ORDER BY event_id DESC", (account_id,))]
        return report

    def equity(self, account_id):
        account = self.db.account(account_id)
        snapshot = self.db.one("SELECT * FROM account_snapshots WHERE account_id=? ORDER BY as_of DESC LIMIT 1", (account_id,))
        balance = self.db.balance(account_id)
        result = dict(snapshot) if snapshot else dict(balance)
        result.update({'account_id': account_id, 'initial_cash': account['initial_cash'], 'mode': 'PAPER'})
        return result

    def export(self, account_id, fmt='json'):
        data = self.dashboard(account_id)
        if fmt == 'json':
            return json.dumps(data, ensure_ascii=False, default=str, indent=2)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(['symbol', 'quantity', 'available_quantity', 'average_price', 'price'])
        for position in data['positions']:
            writer.writerow([position.get(key, '') for key in ['symbol', 'quantity', 'available_quantity', 'average_price', 'price']])
        return out.getvalue()
