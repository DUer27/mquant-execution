CREATE TABLE IF NOT EXISTS market_bars (
 symbol TEXT NOT NULL,
 date TEXT NOT NULL,
 bar_date TEXT NOT NULL,
 open TEXT NOT NULL,
 close TEXT NOT NULL,
 high TEXT NOT NULL,
 low TEXT NOT NULL,
 volume TEXT NOT NULL DEFAULT '0',
 amount TEXT NOT NULL DEFAULT '0',
 security TEXT,
 source TEXT,
 adjust TEXT,
 name TEXT,
 prev_close TEXT,
 tradable INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(symbol, date),
 UNIQUE(symbol, bar_date)
 );
CREATE INDEX IF NOT EXISTS idx_market_bars_date ON market_bars(date, symbol);
