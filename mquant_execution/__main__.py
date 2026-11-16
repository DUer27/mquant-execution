from __future__ import annotations
import argparse, json, sys
from .db import Database
from .service import ExecutionService
from .api import serve
from .reports import Reports
from .market_service import MarketService
from .strategy_sync import StrategySyncService
from .scenarios import ScenarioService
from .paper_report import PaperReport

def db_for(path): return Database(path)

def main(argv=None):
    p=argparse.ArgumentParser(prog='python -m mquant_execution',description='PAPER-only SQLite execution simulator')
    p.add_argument('--db',default='runtime/paper.db'); sub=p.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init'); init.add_argument('--account',default='paper'); init.add_argument('--cash',default='0')
    cash=sub.add_parser('cash'); cashsub=cash.add_subparsers(dest='cash_command',required=True)
    for n in ('deposit','withdraw'):
        x=cashsub.add_parser(n); x.add_argument('--account',default='paper'); x.add_argument('--amount',required=True); x.add_argument('--reference',default='manual')
    x=sub.add_parser('import-signal'); x.add_argument('path'); x.add_argument('--account',default='paper')
    x=sub.add_parser('import-quotes'); x.add_argument('path')
    x=sub.add_parser('import-bars'); x.add_argument('path', nargs='?'); x.add_argument('--csv-text'); x.add_argument('--account',default='paper')
    x=sub.add_parser('simulate'); x.add_argument('--account',default='paper'); x.add_argument('--signal',required=True); x.add_argument('--as-of',required=True)
    x=sub.add_parser('replay'); x.add_argument('--account',default='paper'); x.add_argument('--start',required=True); x.add_argument('--end',required=True)
    x=sub.add_parser('settle'); x.add_argument('--account',default='paper'); x.add_argument('--as-of',required=True)
    x=sub.add_parser('market-refresh'); x.add_argument('--symbols',required=True,help='comma-separated codes'); x.add_argument('--idempotency-key')
    x=sub.add_parser('market-status'); x.add_argument('--symbols')
    x=sub.add_parser('strategy-sync'); x.add_argument('--idempotency-key')
    x=sub.add_parser('strategy-activate'); x.add_argument('--account',default='paper'); x.add_argument('--strategy-id',required=True); x.add_argument('--strategy-version',default=''); x.add_argument('--parameters',default='{}'); x.add_argument('--idempotency-key')
    x=sub.add_parser('strategy-current'); x.add_argument('--account',default='paper')
    x=sub.add_parser('strategy-run-once'); x.add_argument('--account',default='paper'); x.add_argument('--parameters',default='{}')
    x=sub.add_parser('scenario-create'); x.add_argument('--account',default='paper'); x.add_argument('--scenario-id',required=True); x.add_argument('--name',default=''); x.add_argument('--initial-cash',default='0'); x.add_argument('--parameters',default='{}')
    x=sub.add_parser('scenario-cashflow'); x.add_argument('--scenario-id',required=True); x.add_argument('--date',required=True); x.add_argument('--amount',required=True); x.add_argument('--flow-type',default='DEPOSIT'); x.add_argument('--note',default=''); x.add_argument('--idempotency-key')
    x=sub.add_parser('scenario-run'); x.add_argument('--scenario-id',required=True); x.add_argument('--start',required=True); x.add_argument('--end',required=True); x.add_argument('--parameters',default='{}'); x.add_argument('--idempotency-key')
    x=sub.add_parser('scenario-compare'); x.add_argument('--scenario-ids',required=True); x.add_argument('--start',required=True); x.add_argument('--end',required=True)
    for n in ('status','orders','cashflow','fills'):
        x=sub.add_parser(n); x.add_argument('--account',default='paper')
    x=sub.add_parser('export'); x.add_argument('--account',default='paper'); x.add_argument('--format',choices=('json','csv'),default='json')
    x=sub.add_parser('report'); x.add_argument('--account',default='paper'); x.add_argument('--format',choices=('json','csv'),default='json')
    x=sub.add_parser('serve'); x.add_argument('--host',default='127.0.0.1'); x.add_argument('--port',type=int,default=8080)
    dbsub=sub.add_parser('db'); dbcmd=dbsub.add_subparsers(dest='db_command',required=True); dbcmd.add_parser('integrity-check'); dbcmd.add_parser('migrate')
    x=dbcmd.add_parser('backup'); x.add_argument('--output',required=True)
    x=dbcmd.add_parser('restore'); x.add_argument('--input',required=True)
    sub.add_parser('rebuild-balances').add_argument('--account',default='paper')
    args=p.parse_args(argv); db=db_for(args.db); service=ExecutionService(db)
    def obj(value): return json.loads(value or '{}')
    try:
        if args.command=='init': print(json.dumps({'created':db.create_account(args.account,args.cash),'account':args.account}))
        elif args.command=='cash': print(json.dumps({'ok':getattr(service,args.cash_command)(args.account,args.amount,args.reference)}))
        elif args.command=='import-signal': print(json.dumps(dict(zip(('signal','status'),service.import_signal(args.path,args.account))),default=str,ensure_ascii=False))
        elif args.command=='import-quotes': print(json.dumps({'count':service.import_quotes(args.path)}))
        elif args.command=='import-bars':
            count=service.import_bars_csv(args.csv_text) if args.csv_text is not None else service.import_bars_file(args.path); print(json.dumps({'count':count}))
        elif args.command=='simulate': print(json.dumps(service.simulate(args.account,args.signal,args.as_of),default=str,ensure_ascii=False,indent=2))
        elif args.command=='replay':
            from .replay import ReplayService
            print(json.dumps(ReplayService(db).replay(args.account,args.start,args.end),default=str,ensure_ascii=False,indent=2))
        elif args.command=='settle':
            from .settlement import SettlementService
            print(json.dumps({'released':SettlementService(db).settle(args.account,args.as_of)}))
        elif args.command=='market-refresh': print(json.dumps(MarketService(db).refresh(args.symbols.split(','),args.idempotency_key),default=str,ensure_ascii=False))
        elif args.command=='market-status': print(json.dumps(MarketService(db).status(args.symbols.split(',') if args.symbols else None),default=str,ensure_ascii=False))
        elif args.command=='strategy-sync': print(json.dumps(StrategySyncService(db).sync(args.idempotency_key),default=str,ensure_ascii=False))
        elif args.command=='strategy-activate': print(json.dumps(StrategySyncService(db).activate(args.account,args.strategy_id,args.strategy_version,obj(args.parameters),args.idempotency_key),default=str,ensure_ascii=False))
        elif args.command=='strategy-current': print(json.dumps(StrategySyncService(db).current(args.account),default=str,ensure_ascii=False))
        elif args.command=='strategy-run-once': print(json.dumps(StrategySyncService(db).run_once(args.account,obj(args.parameters)),default=str,ensure_ascii=False))
        elif args.command=='scenario-create': print(json.dumps(ScenarioService(db).create(args.account,args.scenario_id,args.name,args.initial_cash,obj(args.parameters)),default=str,ensure_ascii=False))
        elif args.command=='scenario-cashflow': print(json.dumps(ScenarioService(db).add_cashflow(args.scenario_id,args.date,args.amount,args.flow_type,args.note,idempotency_key=args.idempotency_key),default=str,ensure_ascii=False))
        elif args.command=='scenario-run': print(json.dumps(ScenarioService(db).run(args.scenario_id,args.start,args.end,obj(args.parameters),args.idempotency_key),default=str,ensure_ascii=False))
        elif args.command=='scenario-compare': print(json.dumps(ScenarioService(db).compare(args.scenario_ids.split(','),args.start,args.end),default=str,ensure_ascii=False))
        elif args.command=='status': print(json.dumps(Reports(db).dashboard(args.account),default=str,ensure_ascii=False,indent=2))
        elif args.command=='orders': print(json.dumps([dict(x) for x in db.all('SELECT * FROM orders WHERE account_id=? ORDER BY created_at',(args.account,))],default=str,ensure_ascii=False,indent=2))
        elif args.command=='fills': print(json.dumps([dict(x) for x in db.all('SELECT * FROM fills WHERE account_id=? ORDER BY executed_at',(args.account,))],default=str,ensure_ascii=False,indent=2))
        elif args.command=='cashflow': print(json.dumps([dict(x) for x in db.all('SELECT * FROM cash_ledger WHERE account_id=? ORDER BY entry_id',(args.account,))],default=str,ensure_ascii=False,indent=2))
        elif args.command=='export': print(Reports(db).export(args.account,args.format))
        elif args.command=='report': print(PaperReport(db).csv(args.account) if args.format=='csv' else json.dumps(PaperReport(db).build(args.account),default=str,ensure_ascii=False,indent=2))
        elif args.command=='serve': serve(args.db,args.host,args.port)
        elif args.command=='rebuild-balances': print(json.dumps(dict(db.rebuild_balances(args.account)),default=str))
        elif args.command=='db':
            if args.db_command=='integrity-check': print(db.integrity_check())
            elif args.db_command=='migrate': db.migrate(); print('migrated')
            elif args.db_command=='backup': db.backup(args.output); print(args.output)
            elif args.db_command=='restore': db.restore(args.input); print('restored')
    except Exception as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr); return 1
    finally:
        if args.command!='serve': db.close()
    return 0
if __name__=='__main__': raise SystemExit(main())
