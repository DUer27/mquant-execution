# mquant-execution

独立、仅 `PAPER`、Python 标准库模拟盘。M-quant 只需导出 `signal.v1` JSON/ZIP；本仓库负责导入、SQLite WAL 账本、目标持仓再平衡、A 股股票/ETF 整手、T+1、费用/滑点、风控、行情回放、快照、报告、CLI、本地只读页面和 HTTP API。没有 LIVE 模式，也不保存券商密钥。

## 快速开始

```bash
cd /Users/Admin/Documents/GitHub/mquant-execution
python -m mquant_execution --db runtime/paper.db init --account paper --cash 1000000
python -m mquant_execution --db runtime/paper.db cash deposit --account paper --amount 1000000 --reference initial
python -m mquant_execution --db runtime/paper.db import-bars data/510300.csv
python -m mquant_execution --db runtime/paper.db import-signal examples/signals/target-portfolio.json --account paper
python -m mquant_execution --db runtime/paper.db replay --account paper --start 2026-01-01 --end 2026-12-31
python -m mquant_execution --db runtime/paper.db status --account paper
sh scripts/run_checks.sh
```

## 行情 bars 导入

`market_bars` 是与账户无关的 `(symbol, bar_date)` 日线事实表；原有 `quotes` 快照表继续保留并优先用于撮合。支持压力测试 CSV 字段 `code,date,open,close,high,low,volume,amount,security,source,adjust,name,prev_close,tradable`、AkShare CSV 字段 `date,code,open,close,high,low,volume,amount`，以及 JSON 数组或 `{bars:[...]}`。代码自动规范：六位裸代码补 `.XSHE`（深市）或 `.XSHG`（沪市/ETF），已有后缀保持不变；价格、数量、金额以 Decimal 规范文本保存。

```bash
python -m mquant_execution --db runtime/paper.db import-bars pressure.csv
python -m mquant_execution --db runtime/paper.db import-bars akshare.csv
python -m mquant_execution --db runtime/paper.db import-bars bars.json
```

API 也接受 `POST /api/v1/market/bars/import` 的 `{"csv_text":"..."}` 或 `{"bars":[...]}`。可选 `file/path` 仅允许当前工作目录下的文件，避免任意路径读取。

## CLI / API / 页面

CLI 命令包括 `init`、`cash deposit/withdraw`、`import-signal`、`import-quotes`、`import-bars`、`simulate`、`replay`、`settle`、`status`、`orders`、`fills`、`cashflow`、`export`、`rebuild-balances` 和 `db migrate/backup/restore/integrity-check`。启动页面/API：

```bash
python -m mquant_execution --db runtime/paper.db serve --host 127.0.0.1 --port 8080
```

接口包括 `GET /api/v1/market/bars?symbol=&start=&end=`、`POST /api/v1/market/bars/import`、`GET /api/v1/accounts/{id}/equity`、dashboard、snapshots、transactions；dashboard 提供 bars 外的账户交易和 strategy markers。根页面是无外部 CDN、只读 HTML，含真实 bars OHLC/成交量 K 线、成交标记、持仓、订单、成交、资金流水和回放净值曲线，不含下单按钮。
### 实时行情边界

启动 `serve` 后会按 `MQUANT_MARKET_INTERVAL`（默认 30 秒）轮询 Eastmoney `push2`，标的优先取 `MQUANT_MARKET_SYMBOLS`，未配置时取已导入信号和当前持仓的标的。它是“轮询式近实时”，不是 WebSocket/交易所专线推送；不会连接券商，也不会提交 LIVE 订单。

手动刷新可调用 `POST /api/v1/market/live/refresh`，例如 `{"symbols":["510300","000001"]}`；状态通过 `GET /api/v1/market/status` 查看。成功的新报价为 `LIVE`，超过 `stale_seconds` 为 `STALE`，源请求失败或报价被判无效为 `SOURCE_ERROR`，系统不会把旧报价静默标为 LIVE。Eastmoney 网络断连、限流或接口不返回数据时，当前方式只能保留最近缓存并显式报告失败；历史 `market_bars` 仅用于回放/估值，不能当作实时行情。

## PAPER 回放

`replay` 按导入 bars 的交易日读取数据，选择账户中已导入且生效的 `TARGET_PORTFOLIO` 信号，逐日执行已有纸面撮合逻辑并写入唯一日期 snapshots。它不会重复已成交信号/成交，明确不提供 LIVE 交易：

```bash
python -m mquant_execution --db runtime/paper.db replay --start 2026-01-01 --end 2026-12-31 --account paper
```

这是确定性回放/教学用模拟，不是交易建议。默认交易日是周一至周五，未内置中国交易所节假日；金额和价格在 SQLite 中按定标文本保存，Python 侧使用 `Decimal`。

## 场景报告与执行模式

除正式 `paper` 账户的 replay 外，`ScenarioService.run` 提供隔离的 PAPER 场景回放：执行型 scenario 会复制数据到临时 SQLite、创建临时账户，逐日调用现有 signal_positions/planner/execution/settlement/market_bars 和 snapshots，完成后临时库自动删除，绝不污染正式 paper 账户。可通过 `strategy_id`/`signal_id` 选择信号；激活策略优先使用其 `TARGET_PORTFOLIO`，`RECORD_ONLY` 返回 blocked 且没有 fills；无信号保留纯资本估值并明确 `NOT_EXECUTED`。不实现 LLM 或 LIVE 下单。

所有场景结果采用 `scenario-report.v1`。报告包含 orders、fills、position lots、snapshots、逐日净值 curve，以及 turnover、fees、slippage/shock cost、filled/rejected orders、return、pnl、drawdown 和 cashflows。场景支持 `initial_cash`、`cashflow`、`fee_bps`、`shock_cost_bps`、`max_order_value`、`max_symbol_weight`、`minimum_cash_reserve`、`max_participation`、`positions`；默认继承源账户 `AccountConfig`。场景 run 按参数幂等，交易日、行情缺失、gate、整手、T+1 和风控限制仍可能导致拒单。
