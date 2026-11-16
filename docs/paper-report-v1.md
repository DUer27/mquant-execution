# paper-report.v1

`paper-report.v1` is the stable, PAPER-only reporting document returned by the
report API. It contains `schema_version`, `mode`, `account_id`, UTC
`generated_at`, the existing dashboard contract, and a `market_status` object.
All monetary values are serialized fixed-point decimal strings; consumers must
not interpret this document as live trading or broker execution data.

## HTTP

* `GET /api/v1/accounts/{account_id}/report` returns JSON.
* `GET /api/v1/accounts/{account_id}/report.csv` returns a CSV position export.

The report includes account cash, positions, orders, fills, cash ledger,
snapshots, risk/audit events, strategy markers, and live quote status
(`LIVE`, `STALE`, or `SOURCE_ERROR`).
