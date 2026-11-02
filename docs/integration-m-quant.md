# 与 M-quant 集成

M-quant 侧仍只生成并下载 `signal.v1` JSON 或 ZIP；它不 import 本仓库，也不读取本仓库的 SQLite。不要修改 M-quant。把导出文件和行情文件复制到本机后执行。网页端也可以在 8080 页面的“导入策略信号”文件选择器中直接选择 M-quant 导出的 `.json` 或 `.zip`；导入只保存信号并按 `action` 决定是否生成订单。


```bash
python -m mquant_execution --db runtime/paper.db import-bars /path/to/pressure-test.csv
python -m mquant_execution --db runtime/paper.db import-signal /path/to/target-portfolio.json --account paper
python -m mquant_execution --db runtime/paper.db replay --account paper --start 2026-01-01 --end 2026-12-31
python -m mquant_execution --db runtime/paper.db status --account paper
```

## API 文件导入

```text
POST /api/v1/accounts/{account_id}/signals/import-file
Content-Type: application/json
```

请求体使用 base64：

```json
{"file_name":"m-quant-paper-signal.zip","content":"<base64>","encoding":"base64"}
```

支持 M-quant 导出的 JSON 或 ZIP；重复 `signal_id` 返回 `DUPLICATE`。`RECORD_ONLY` 信号只入库审计，不创建订单。

## 压力测试 CSV 转换

支持字段：`code,date,open,close,high,low,volume,amount,security,source,adjust,name,prev_close,tradable`。AkShare 单标的 CSV 的 `date,code,open,close,high,low,volume,amount` 直接支持；JSON 为 bars 数组或 `{bars:[...]}`。导入映射如下：`code→symbol`、`date→bar_date`、OHLCV/amount 为 Decimal 文本，元数据写入同名字段。裸六位代码自动补 `.XSHE` 或 `.XSHG`，有后缀的代码保持不变。`market_bars` 以 symbol/date upsert，因此重复导入不会产生重复 bars。

```bash
python -m mquant_execution --db runtime/paper.db import-bars akshare.csv
python -m mquant_execution --db runtime/paper.db import-bars bars.json
```

也可以使用 `POST /api/v1/market/bars/import` 的 JSON `csv_text` 或 `bars` 字段。服务器只接受当前工作目录内的可选 `file/path`，不读取任意绝对路径。用 `GET /api/v1/market/bars?symbol=510300&start=...&end=...` 检查结果。

## PAPER 回放规则

`replay` 只处理 `market_bars` 中的工作日，按日期加载账户中有效的 `TARGET_PORTFOLIO` 信号，调用现有 PAPER planner/executor，逐日写 `account_snapshots`。旧的 `quotes` 快照仍优先用于成交，bars close 是行情与估值兜底。已成交信号不会再次产生订单/成交；重复运行只更新同一天 snapshot。该命令明确 PAPER-only，不连接券商，也没有下单按钮。
