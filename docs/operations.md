# PAPER 操作说明

## 备份、恢复和检查

```bash
python -m mquant_execution --db runtime/paper.db db integrity-check
python -m mquant_execution --db runtime/paper.db db backup --output runtime/backup.db
python -m mquant_execution --db runtime/paper.db db restore --input runtime/backup.db
python -m mquant_execution --db runtime/paper.db rebuild-balances --account paper
```

恢复前停止服务并保留原文件。升级由启动时迁移完成。

## 内部策略回放

```bash
python -m mquant_execution --db runtime/paper.db strategy-sync
python -m mquant_execution --db runtime/paper.db strategy-activate --account paper --strategy-id <strategy-id>
python -m mquant_execution --db runtime/paper.db strategy-run-once --account paper
python -m mquant_execution --db runtime/paper.db replay --start 2026-01-01 --end 2026-12-31 --account paper
```

策略只能来自 M-quant 内部策略目录，行情使用内部实时行情服务及已有 PAPER 数据。

## API 边界

默认绑定 `127.0.0.1`。支持健康检查、实时行情刷新、行情查询、账户报告、策略同步/激活/运行、回放和场景测试。

外部导入接口已关闭并返回 `410 Gone`：

- `POST /api/v1/market/bars/import`
- `POST /api/v1/accounts/{id}/signals/import`
- `POST /api/v1/accounts/{id}/signals/import-file`
- `POST /api/v1/accounts/{id}/quotes/import`

## PAPER 边界

服务不连接券商、不提供 LIVE 下单。回放和场景结果只代表内部 PAPER 测试结果；行情缺失、策略门禁、整手、T+1、风控和交易日限制都可能导致拒单。
