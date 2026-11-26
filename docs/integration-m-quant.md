# M-quant 内部策略集成

M-quant 与本 PAPER 执行服务是一个共同体。用户统一从 M-quant 研究平台进入：

```text
http://127.0.0.1:5555/paper/
```

Paper 执行服务只作为后台运行模块，不作为独立用户入口。

## 内部策略链路

M-quant 内部策略目录通过同步、激活和运行接口进入 PAPER：

```text
POST /api/v1/strategies/sync
POST /api/v1/accounts/{account_id}/strategy/activate
POST /api/v1/accounts/{account_id}/strategy/run-once
```

或使用 CLI：

```bash
python -m mquant_execution --db runtime/paper.db strategy-sync
python -m mquant_execution --db runtime/paper.db strategy-activate --account paper --strategy-id <strategy-id>
python -m mquant_execution --db runtime/paper.db strategy-run-once --account paper
```

## 外部导入边界

为了保证内部闭环，以下外部导入方式已关闭：

- bars / OHLCV 文件导入
- quotes / 行情文件导入
- M-quant JSON/ZIP 策略信号文件导入
- 网页端文件导入

相关 HTTP 接口统一返回 `410 Gone`。不再通过复制文件、粘贴 JSON 或上传 ZIP 写入 PAPER 数据。

## PAPER 回放

回放使用系统内部已有行情和内部策略结果：

```bash
python -m mquant_execution --db runtime/paper.db replay --account paper --start 2026-01-01 --end 2026-12-31
```

回放只运行 PAPER 逻辑，不连接券商，不生成 LIVE 订单。
