# 数据库

SQLite 文件固定建议放在 `runtime/`。启动时启用 `foreign_keys=ON`、`journal_mode=WAL`、`synchronous=FULL` 和 30 秒 busy timeout；迁移版本记录在 `schema_migrations`。`migrations/001_initial.sql` 建立账户、物化余额、追加式资金账簿、信号/目标组合、兼容行情快照 `quotes`、订单/成交、T+1 批次、持仓、运行、快照、风控和审计表；`migrations/002_market_bars.sql` 增加账户无关的真实日线行情表。

`market_bars` 主键是 `(symbol, bar_date)`，保存 `open/close/high/low/volume/amount/security/source/adjust/name/prev_close/tradable` 及导入时间。压力测试 CSV 与 AkShare CSV 均转换到该表，六位代码自动补 `.XSHE`/`.XSHG`。重复导入按主键更新，`quotes` 不删除且仍优先用于既有模拟撮合。

金额和价格以四位小数的规范化文本保存，Python 运算统一使用 `Decimal`。`cash_ledger` 是余额的事实来源；快照、重建余额和报告在缺少指定日 `quotes` 时使用 `market_bars.close` 兜底。`account_snapshots` 保存按日净值、持仓市值、盈亏和回撤，`replay` 逐交易日更新它们。
