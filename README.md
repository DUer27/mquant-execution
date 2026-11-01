# mquant-execution

独立、仅 `PAPER`、Python 标准库模拟盘。M-quant 只需导出 `signal.v1` JSON/ZIP；本仓库负责导入、SQLite WAL 账本、目标持仓再平衡、A 股股票/ETF 整手、T+1、费用/滑点、风控、快照、报告、CLI、本地只读页面和 HTTP API。没有 LIVE 模式，也不保存券商密钥。

## 快速开始

```bash
cd ../mquant-execution
python -m mquant_execution --db runtime/paper.db init --account paper --cash 1000000
python -m mquant_execution --db runtime/paper.db cash deposit --account paper --amount 1000000 --reference initial
python -m mquant_execution --db runtime/paper.db import-signal examples/signals/target-portfolio.json --account paper
python -m mquant_execution --db runtime/paper.db import-quotes examples/quotes/2026-09-21.json
python -m mquant_execution --db runtime/paper.db simulate --account paper --signal demo-signal-20260920 --as-of 2026-09-21
python -m mquant_execution --db runtime/paper.db status --account paper
sh scripts/run_checks.sh
```

默认数据库位于 `runtime/paper.db`，运行时目录被 Git 忽略。执行一次模拟会优先卖出订单、使用卖一/买一和固定滑点、产生费用流水、写入成交批次和快照。重复导入信号、重复入金引用和重复模拟均使用幂等键。

## CLI / API / 页面

CLI 命令包括 `init`、`cash deposit/withdraw`、`import-signal`、`import-quotes`、`simulate`、`settle`、`status`、`orders`、`fills`、`cashflow`、`export`、`rebuild-balances` 和 `db migrate/backup/restore/integrity-check`。启动页面/API：

```bash
python -m mquant_execution --db runtime/paper.db serve --host 127.0.0.1 --port 8080
```

`GET /api/v1/health`、`GET /api/v1/accounts/{id}/dashboard` 等接口见 `docs/operations.md`。根页面是只读 HTML，不含网页下单按钮。

## 限制

这是确定性回放/教学用模拟，不是交易建议。默认交易日是周一至周五，未内置中国交易所节假日；没有真实撮合队列、涨跌停的完整撮合算法或券商费用同步。部分成交接口和更复杂的节假日日历需要后续扩展。所有价钱/金额在 SQLite 中按定标文本保存，Python 侧使用 `Decimal`。
