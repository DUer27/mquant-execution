# 运维

## 备份、恢复和检查

```bash
python -m mquant_execution --db runtime/paper.db db integrity-check
python -m mquant_execution --db runtime/paper.db db backup --output runtime/backup.db
python -m mquant_execution --db runtime/paper.db db restore --input runtime/backup.db
python -m mquant_execution --db runtime/paper.db rebuild-balances --account paper
```

备份使用 SQLite online backup API；恢复前停止服务并保留原文件。升级由启动时迁移完成，迁移文件按数字前缀递增，不修改已执行版本。失败操作可安全重试：现金流水、信号、订单、成交、结算均有唯一幂等键。

## API

默认绑定 `127.0.0.1`：`GET /api/v1/health`、`POST /api/v1/accounts`、`GET /api/v1/accounts/{id}/dashboard`、`POST /api/v1/accounts/{id}/cash/deposit`、`POST .../cash/withdraw`、`POST .../signals/import`、`POST .../quotes/import`、`POST .../simulate`、`GET .../signals`、`orders`、`fills`、`cash-ledger`、`risk-events`、`audit-events`、`snapshots`、`POST .../rebuild`。接口仅本机使用，HTTP API 不提供 LIVE 下单。
