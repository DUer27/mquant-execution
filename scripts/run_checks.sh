#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
PYTHONPATH=. python3 -m unittest discover -s tests -v
PYTHONPATH=. python3 -m compileall -q mquant_execution
TMP_DB="${TMPDIR:-/tmp}/mquant-execution-check-$$.db"
trap 'rm -f "$TMP_DB" "$TMP_DB-wal" "$TMP_DB-shm"' EXIT
PYTHONPATH=. python3 -m mquant_execution --db "$TMP_DB" init --account paper --cash 0 >/dev/null
PYTHONPATH=. python3 -m mquant_execution --db "$TMP_DB" db integrity-check
