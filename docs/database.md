# 数据库

SQLite 文件固定建议放在 `runtime/`。启动时启用 `foreign_keys=ON`、`journal_mode=WAL`、`synchronous=FULL` 和 30 秒 busy timeout；迁移版本记录在 `schema_migrations`。`migrations/001_initial.sql` 建立账户、物化余额、追加式资金账簿、信号/目标组合、行情、订单/成交、T+1 批次、持仓、运行、快照、风控和审计表。

金额和价格以四位小数的规范化文本保存，Python 运算统一使用 `Decimal`。`cash_ledger` 是余额的事实来源：入金同时增加可用/可提现，买入扣除可用/可提现，卖出增加可用和待结算但不增加可提现，下一交易日用唯一 `settle:<entry_id>` 键释放待结算现金。所有人工资金流、计划执行、成交和结算在事务内完成。

`position_lots` 按买入交易日保存数量；买入日可卖数量为 0，结算服务推进到下一个交易日后释放并重算 `positions`。`rebuild-balances` 从账簿和持仓批次重建物化现金，写入审计事件；`db integrity-check` 执行 SQLite 完整性检查。
