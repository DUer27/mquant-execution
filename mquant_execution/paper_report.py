"""Stable paper-report.v1 JSON/CSV document generation."""
from __future__ import annotations
import csv, io
from .reports import Reports
class PaperReport:
    schema_version='paper-report.v1'
    def __init__(self, db): self.db=db
    def build(self, account_id):
        dashboard=Reports(self.db).dashboard(account_id)
        market = self._market_status()
        return {
            'schema_version': self.schema_version,
            'mode': 'PAPER',
            'account_id': account_id,
            'scenario_id': None,
            'generated_at': __import__('mquant_execution.db',fromlist=['now']).now(),
            'data_policy': 'PAPER execution from live quotes/history bars; no LIVE orders',
            'market': {
                'source': market.get('source', ''),
                'as_of': market.get('quotes', [{}])[0].get('updated_at') if market.get('quotes') else None,
                'status': market.get('status', 'SOURCE_ERROR'),
                'symbols': len(market.get('quotes', [])),
            },
            'account': {
                'cash': dashboard.get('cash'), 'pending_cash': dashboard.get('pending'),
                'withdrawable_cash': dashboard.get('withdrawable'), 'holdings_value': dashboard.get('holdings_value'),
                'total_assets': dashboard.get('total_assets'), 'pnl': dashboard.get('pnl'), 'drawdown': dashboard.get('drawdown'),
            },
            'strategy': (dashboard.get('strategy_markers') or [{}])[0],
            'positions': dashboard.get('positions', []), 'orders': dashboard.get('orders', []),
            'fills': dashboard.get('fills', []), 'cash_ledger': dashboard.get('cash_ledger', []),
            'risk_events': dashboard.get('risk_events', []), 'snapshots': dashboard.get('snapshots', []),
            'evidence': {'sources': [market.get('source', 'paper')], 'limitations': ['本次只读 PAPER 报告，不包含 LIVE 交易。'], 'warnings': []},
            'dashboard': dashboard,
            'market_status': market,
        }
    def _market_status(self):
        try:
            from .market_service import MarketService
            return MarketService(self.db).status()
        except Exception as exc: return {'status':'SOURCE_ERROR','error':str(exc)}
    def csv(self, account_id):
        report=self.build(account_id); out=io.StringIO(); writer=csv.writer(out)
        writer.writerow(['schema_version','mode','account_id','section','symbol','quantity','price','market_value','pnl'])
        for row in report['dashboard'].get('positions',[]): writer.writerow([report['schema_version'],report['mode'],account_id,'position',row.get('symbol',''),row.get('quantity',''),row.get('price',''),row.get('market_value',''),row.get('pnl','')])
        if not report['dashboard'].get('positions'): writer.writerow([report['schema_version'],report['mode'],account_id,'summary','','','','',report['dashboard'].get('pnl','')])
        return out.getvalue()
