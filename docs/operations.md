# 运维

## 备份、恢复和检查

```bash
python -m mquant_execution --db runtime/paper.db db integrity-check
python -m mquant_execution --db runtime/paper.db db backup --output runtime/backup.db
python -m mquant_execution --db runtime/paper.db db restore --input runtime/backup.db
python -m mquant_execution --db runtime/paper.db rebuild-balances --account paper
```

备份使用 SQLite online backup API；恢复前停止服务并保留原文件。升级由启动时迁移完成，迁移文件按数字前缀递增，不修改已执行版本。

## bars 导入与回放

```bash
python -m mquant_execution --db runtime/paper.db import-bars pressure-test.csv
python -m mquant_execution --db runtime/paper.db import-bars akshare.csv
python -m mquant_execution --db runtime/paper.db import-bars bars.json
python -m mquant_execution --db runtime/paper.db replay --start 2026-01-01 --end 2026-12-31 --account paper
```

CSV 压力测试字段映射为 `code→symbol,date→bar_date`，OHLC、`volume`、`amount` 原样进入 Decimal 文本，其他字段映射 `security/source/adjust/name/prev_close/tradable`；AkShare 的 `date,code,open,close,high,low,volume,amount` 是其子集。六位代码按交易所规则补 `.XSHE` 或 `.XSHG`。JSON 可为数组或 `{bars:[...]}`。导入是幂等 upsert。

## API

默认绑定 `127.0.0.1`：`GET /api/v1/health`、`GET /api/v1/market/bars?symbol=&start=&end=`、`POST /api/v1/market/bars/import`、`POST /api/v1/accounts`、`GET /api/v1/accounts/{id}/dashboard`、`GET /api/v1/accounts/{id}/equity`、`POST .../cash/deposit`、`POST .../cash/withdraw`、`POST .../signals/import`、`POST .../signals/import-file`（JSON/ZIP 文件内容）、`POST .../quotes/import`、`POST .../simulate`、`GET .../signals`、`orders`、`fills`、`transactions`、`cash-ledger`、`risk-events`、`audit-events`、`snapshots`、`POST .../rebuild`。接口仅本机使用，HTTP API 不提供 LIVE 或网页下单。
## Scenario PAPER replay

场景接口 `POST /api/v1/scenarios/{id}/run` 接收 `start`、`end`，可选 `strategy_id`、`signal_id` 以及 `parameters`。服务优先选择场景指定或源账户当前激活策略的 `TARGET_PORTFOLIO` 信号；场景执行发生在独立临时 SQLite/临时账户中，逐交易日复用 planner、execution、settlement 和 snapshots，正式 `paper` 账户不被写入。相同参数的 run 通过 `scenario_runs` 幂等返回原报告。

`RECORD_ONLY` 信号会返回 `scenario-report.v1` 的 `execution_status=BLOCKED` 且不产生 fills；没有信号时返回 `PAPER_CAPITAL_VALUATION`、`NOT_EXECUTED`，仅做配置 positions 估值。可配置 `initial_cash`、`cashflow`、`fee_bps`、`shock_cost_bps`、`max_order_value`、`max_symbol_weight`、`minimum_cash_reserve`、`max_participation` 和 `positions`；这些参数仅适用于场景，默认从源 `AccountConfig` 继承。报告是确定性 PAPER 分析，不连接 LIVE 券商，bars 缺失、信号 gate、整手/T+1、风控和交易日限制都可能使订单被拒。
