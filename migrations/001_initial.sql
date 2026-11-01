CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS accounts (
 account_id TEXT PRIMARY KEY, currency TEXT NOT NULL DEFAULT 'CNY', initial_cash TEXT NOT NULL DEFAULT '0',
 status TEXT NOT NULL DEFAULT 'ACTIVE', config_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_balances (
 account_id TEXT PRIMARY KEY REFERENCES accounts(account_id), available_cash TEXT NOT NULL DEFAULT '0',
 frozen_cash TEXT NOT NULL DEFAULT '0', withdrawable_cash TEXT NOT NULL DEFAULT '0', pending_cash TEXT NOT NULL DEFAULT '0',
 total_assets TEXT NOT NULL DEFAULT '0', updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cash_ledger (
 entry_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES accounts(account_id),
 entry_type TEXT NOT NULL, amount TEXT NOT NULL, available_delta TEXT NOT NULL DEFAULT '0',
 withdrawable_delta TEXT NOT NULL DEFAULT '0', pending_delta TEXT NOT NULL DEFAULT '0',
 reference_type TEXT, reference_id TEXT, idempotency_key TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
 UNIQUE(account_id, idempotency_key)
);
CREATE TABLE IF NOT EXISTS signals (
 signal_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id), schema_version TEXT NOT NULL,
 strategy_id TEXT NOT NULL, strategy_version TEXT NOT NULL DEFAULT '', sleeve_id TEXT NOT NULL DEFAULT '',
 signal_date TEXT NOT NULL, effective_at TEXT NOT NULL, expires_at TEXT, action TEXT NOT NULL, gate_status TEXT NOT NULL,
 planned_weight TEXT NOT NULL, cash_target_weight TEXT NOT NULL, raw_json TEXT NOT NULL, canonical_json TEXT NOT NULL,
 content_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'IMPORTED', imported_at TEXT NOT NULL, executed_at TEXT
);
CREATE TABLE IF NOT EXISTS signal_positions (
 signal_id TEXT NOT NULL REFERENCES signals(signal_id), symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
 target_weight TEXT NOT NULL, target_quantity INTEGER, rank INTEGER NOT NULL, PRIMARY KEY(signal_id, symbol)
);
CREATE TABLE IF NOT EXISTS quotes (
 symbol TEXT NOT NULL, quote_date TEXT NOT NULL, price TEXT NOT NULL, bid TEXT, ask TEXT, volume TEXT NOT NULL DEFAULT '0',
 tradable INTEGER NOT NULL DEFAULT 1, suspended INTEGER NOT NULL DEFAULT 0, limit_up TEXT, limit_down TEXT,
 asset_type TEXT NOT NULL DEFAULT 'stock', updated_at TEXT NOT NULL, PRIMARY KEY(symbol, quote_date)
);
CREATE TABLE IF NOT EXISTS orders (
 order_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id), signal_id TEXT NOT NULL REFERENCES signals(signal_id),
 symbol TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL, requested_price TEXT NOT NULL, status TEXT NOT NULL,
 filled_quantity INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '', target_weight TEXT, calculated_equity TEXT,
 quote_date TEXT, idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS fills (
 fill_id TEXT PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(order_id), account_id TEXT NOT NULL REFERENCES accounts(account_id),
 symbol TEXT NOT NULL, side TEXT NOT NULL, quantity INTEGER NOT NULL, price TEXT NOT NULL, gross_amount TEXT NOT NULL,
 fee TEXT NOT NULL, commission TEXT NOT NULL, stamp_tax TEXT NOT NULL, slippage TEXT NOT NULL, trade_date TEXT NOT NULL,
 executed_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS position_lots (
 lot_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES accounts(account_id), symbol TEXT NOT NULL,
 buy_date TEXT NOT NULL, quantity INTEGER NOT NULL, available_quantity INTEGER NOT NULL, unit_cost TEXT NOT NULL,
 source_fill_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS positions (
 account_id TEXT NOT NULL REFERENCES accounts(account_id), symbol TEXT NOT NULL, quantity INTEGER NOT NULL,
 available_quantity INTEGER NOT NULL, average_price TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(account_id, symbol)
);
CREATE TABLE IF NOT EXISTS simulation_runs (
 run_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, signal_id TEXT NOT NULL, as_of TEXT NOT NULL,
 status TEXT NOT NULL, parameters_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', error TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_snapshots (
 snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, as_of TEXT NOT NULL,
 available_cash TEXT NOT NULL, pending_cash TEXT NOT NULL, withdrawable_cash TEXT NOT NULL, holdings_value TEXT NOT NULL,
 total_assets TEXT NOT NULL, pnl TEXT NOT NULL, drawdown TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(account_id, as_of)
);
CREATE TABLE IF NOT EXISTS risk_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL, signal_id TEXT, order_id TEXT,
 level TEXT NOT NULL, reason TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT, event_type TEXT NOT NULL, reference_type TEXT,
 reference_id TEXT, details_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cash_ledger_account ON cash_ledger(account_id, entry_id);
CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_fills_account ON fills(account_id, executed_at);
CREATE INDEX IF NOT EXISTS idx_audit_account ON audit_events(account_id, event_id);
