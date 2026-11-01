import csv
import io
import json


class Reports:
    def __init__(self, db):
        self.db = db

    def dashboard(self, account_id):
        account = dict(self.db.account(account_id))
        balance = dict(self.db.balance(account_id))
        report = dict(balance)
        report.update({
            'account_id': account_id,
            'account': account,
            # Keep concise aliases for dashboard consumers while retaining the
            # original balance column names for backwards compatibility.
            'cash': balance['available_cash'],
            'pending': balance['pending_cash'],
            'withdrawable': balance['withdrawable_cash'],
        })
        report['positions'] = [dict(row) for row in self.db.all(
            "SELECT p.*, q.price FROM positions p LEFT JOIN quotes q ON q.symbol=p.symbol "
            "AND q.quote_date=(SELECT MAX(quote_date) FROM quotes WHERE symbol=p.symbol) "
            "WHERE p.account_id=?", (account_id,)
        )]
        report['orders'] = [dict(row) for row in self.db.all(
            "SELECT * FROM orders WHERE account_id=? ORDER BY created_at DESC", (account_id,)
        )]
        report['fills'] = [dict(row) for row in self.db.all(
            "SELECT * FROM fills WHERE account_id=? ORDER BY executed_at DESC", (account_id,)
        )]
        report['cash_ledger'] = [dict(row) for row in self.db.all(
            "SELECT * FROM cash_ledger WHERE account_id=? ORDER BY entry_id DESC", (account_id,)
        )]
        report['signals'] = [dict(row) for row in self.db.all(
            "SELECT * FROM signals WHERE account_id=? ORDER BY imported_at DESC", (account_id,)
        )]
        report['risk_events'] = [dict(row) for row in self.db.all(
            "SELECT * FROM risk_events WHERE account_id=? ORDER BY event_id DESC", (account_id,)
        )]
        report['snapshots'] = [dict(row) for row in self.db.all(
            "SELECT * FROM account_snapshots WHERE account_id=? ORDER BY as_of DESC", (account_id,)
        )]
        report['audit_events'] = [dict(row) for row in self.db.all(
            "SELECT * FROM audit_events WHERE account_id=? ORDER BY event_id DESC", (account_id,)
        )]
        return report

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
