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

## PAPER 回放

`replay` 按导入 bars 的交易日读取数据，选择账户中已导入且生效的 `TARGET_PORTFOLIO` 信号，逐日执行已有纸面撮合逻辑并写入唯一日期 snapshots。它不会重复已成交信号/成交，明确不提供 LIVE 交易：

```bash
python -m mquant_execution --db runtime/paper.db replay --start 2026-01-01 --end 2026-12-31 --account paper
```

这是确定性回放/教学用模拟，不是交易建议。默认交易日是周一至周五，未内置中国交易所节假日；金额和价格在 SQLite 中按定标文本保存，Python 侧使用 `Decimal`。
