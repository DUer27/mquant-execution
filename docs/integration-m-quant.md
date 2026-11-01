# 与 M-quant 集成

M-quant 侧生成并下载 `signal.v1` JSON 或 ZIP；它不 import 本仓库，也不读取本仓库的 SQLite。把导出文件复制到本机后执行：

```bash
python -m mquant_execution --db runtime/paper.db import-signal /path/to/signal.json --account paper
python -m mquant_execution --db runtime/paper.db import-quotes examples/quotes/2026-09-21.json
python -m mquant_execution --db runtime/paper.db simulate --account paper --signal <signal_id> --as-of 2026-09-21
python -m mquant_execution --db runtime/paper.db status --account paper
```

相同 `signal_id` 重复导入返回 `DUPLICATE`；重复执行不会产生第二个订单/成交。行情快照必须包含日期和价格，可选买一、卖一、成交量、停牌/可交易状态及资产类型。平台先按目标权重和总权益计算整手目标数量，先卖后买，再以行情快照模拟成交。查看 `status`、`orders`、`fills`、`cashflow` 或 `export --format csv` 进行复核。

若准入状态为 `RECORD_ONLY` 或动作是 `RECORD_ONLY`，信号被保存并审计但不会产生订单。导入前检查来源、数据政策、信号有效期；示例行情是合成数据，不代表真实市场。
