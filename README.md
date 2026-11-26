# mquant-execution

独立、仅 `PAPER` 的模拟盘执行服务。它与 M-quant 研究平台共同工作：策略由 M-quant 内部策略链路同步、激活和运行，行情由实时行情服务刷新；本服务负责 SQLite 账本、目标持仓再平衡、A 股股票/ETF 整手、T+1、费用/滑点、风控、回放、快照和报告。没有 LIVE 模式，也不保存券商密钥。

## 快速开始

```bash
cd /Users/Admin/Documents/GitHub/mquant-execution
python -m mquant_execution --db runtime/paper.db init --account paper --cash 1000000
python -m mquant_execution --db runtime/paper.db cash deposit --account paper --amount 1000000 --reference initial
python -m mquant_execution --db runtime/paper.db strategy-sync
python -m mquant_execution --db runtime/paper.db strategy-activate --account paper --strategy-id <strategy-id>
python -m mquant_execution --db runtime/paper.db strategy-run-once --account paper
python -m mquant_execution --db runtime/paper.db status --account paper
sh scripts/run_checks.sh
```

## 内部行情与策略边界

- 行情由实时行情服务刷新，支持 `market-refresh`、`market-status` 和 `/api/v1/market/live/refresh`。
- 策略由 M-quant 内部策略目录同步，使用 `strategy-sync`、`strategy-activate` 和 `strategy-run-once`。
- 外部 bars、quotes、signal 文件导入已关闭，不提供网页或 HTTP 导入入口。
- 外部导入接口返回 `410 Gone`，避免绕过内部策略闭环写入数据。
- `replay` 和场景回放只使用系统内已有数据和内部策略结果。

## CLI / API / 页面

CLI 命令包括 `init`、`cash deposit/withdraw`、`simulate`、`replay`、`settle`、`market-refresh`、`market-status`、`strategy-sync`、`strategy-activate`、`strategy-current`、`strategy-run-once`、`scenario-*`、`status`、`orders`、`fills`、`cashflow`、`export`、`report`、`rebuild-balances` 和 `db migrate/backup/restore/integrity-check`。

启动服务：

```bash
python -m mquant_execution --db runtime/paper.db serve --host 127.0.0.1 --port 8080
```

最终用户通过 M-quant 统一入口访问 Paper 页面：

```text
http://127.0.0.1:5555/paper/
```

8080 仅作为后台执行服务，不作为用户入口。

## 实时行情

服务按 `MQUANT_MARKET_INTERVAL`（默认 30 秒）轮询 Eastmoney `push2`。标的优先取 `MQUANT_MARKET_SYMBOLS`，未配置时取当前持仓和内部策略涉及的标的。它是轮询式近实时，不连接券商，也不会提交 LIVE 订单。

手动刷新使用 `POST /api/v1/market/live/refresh`，状态使用 `GET /api/v1/market/status`。历史行情只用于系统内部回放/估值。

## PAPER 回放

`replay` 按系统内已有数据的交易日执行纸面撮合逻辑并写入账户快照。场景回放使用隔离临时 SQLite，不污染正式 PAPER 账户。所有运行结果都明确标记为 PAPER，不代表实盘建议。
