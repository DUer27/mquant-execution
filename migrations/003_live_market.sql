-- PAPER live market, direct M-quant strategy sync and cash-flow scenarios.
CREATE TABLE IF NOT EXISTS live_quotes (
 symbol TEXT PRIMARY KEY, quote_time TEXT NOT NULL, price TEXT NOT NULL,
 bid TEXT, ask TEXT, volume TEXT NOT NULL DEFAULT '0', amount TEXT NOT NULL DEFAULT '0',
 prev_close TEXT, change_pct TEXT, asset_type TEXT NOT NULL DEFAULT 'stock', source TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'LIVE', source_error TEXT, received_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_live_quotes_status ON live_quotes(status, updated_at);
CREATE TABLE IF NOT EXISTS market_sync_runs (
 run_id TEXT PRIMARY KEY, source TEXT NOT NULL, symbols_json TEXT NOT NULL, status TEXT NOT NULL,
 quote_count INTEGER NOT NULL DEFAULT 0, started_at TEXT NOT NULL, finished_at TEXT, error TEXT,
 idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS strategy_catalog (
 strategy_id TEXT NOT NULL, strategy_version TEXT NOT NULL DEFAULT '', name TEXT NOT NULL DEFAULT '',
 description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'AVAILABLE', source TEXT NOT NULL DEFAULT 'M-quant',
 definition_json TEXT NOT NULL DEFAULT '{}', synced_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(strategy_id, strategy_version)
);
CREATE TABLE IF NOT EXISTS strategy_sync_runs (
 run_id TEXT PRIMARY KEY, status TEXT NOT NULL, source TEXT NOT NULL, strategies_count INTEGER NOT NULL DEFAULT 0,
 started_at TEXT NOT NULL, finished_at TEXT, error TEXT, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS strategy_activations (
 activation_id INTEGER PRIMARY KEY AUTOINCREMENT, account_id TEXT NOT NULL REFERENCES accounts(account_id),
 strategy_id TEXT NOT NULL, strategy_version TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ACTIVE',
 parameters_json TEXT NOT NULL DEFAULT '{}', activated_at TEXT NOT NULL, idempotency_key TEXT NOT NULL UNIQUE
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_strategy_active_account ON strategy_activations(account_id) WHERE status='ACTIVE';
CREATE TABLE IF NOT EXISTS scenarios (
 scenario_id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES accounts(account_id), name TEXT NOT NULL,
 initial_cash TEXT NOT NULL DEFAULT '0', parameters_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'READY',
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scenario_cashflows (
 cashflow_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id), event_date TEXT NOT NULL,
 flow_type TEXT NOT NULL DEFAULT 'DEPOSIT', amount TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 idempotency_key TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenario_cashflows_date ON scenario_cashflows(scenario_id, event_date);
CREATE TABLE IF NOT EXISTS scenario_runs (
 run_id TEXT PRIMARY KEY, scenario_id TEXT NOT NULL REFERENCES scenarios(scenario_id), account_id TEXT NOT NULL REFERENCES accounts(account_id),
 start_date TEXT NOT NULL, end_date TEXT NOT NULL, status TEXT NOT NULL, parameters_json TEXT NOT NULL DEFAULT '{}',
 idempotency_key TEXT NOT NULL UNIQUE, result_json TEXT NOT NULL DEFAULT '{}', error TEXT, created_at TEXT NOT NULL, finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_scenario_runs_scenario ON scenario_runs(scenario_id, created_at);
