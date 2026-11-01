# signal.v1 合同

必需字段：`schema_version`、`strategy_id`、`generated_at`、`signal_date`、`effective_at`、`action`、`gate_status`、`planned_weight`、`cash_target_weight`、`portfolio`、`provenance`。`action` 只能是 `TARGET_PORTFOLIO` 或 `RECORD_ONLY`；组合标的不可重复，目标权重和现金权重不得超过 1，资产类型为 `stock`/`etf`。

每个组合项包含 `symbol`、`asset_type`、`target_weight`，可选 `target_quantity` 和 `rank`。`provenance` 必须包含 `source` 与 `data_policy`。导入器保存原始 JSON、规范化 JSON、内容哈希；指定 `signal_id` 用作幂等主键，未指定时按确定性组合内容生成短 SHA-256 ID。`RECORD_ONLY` 只入库和审计，不生成订单。

ZIP 只允许一个 JSON 信号文件，拒绝绝对路径、`..` 路径和额外信号 JSON，避免路径穿越。
