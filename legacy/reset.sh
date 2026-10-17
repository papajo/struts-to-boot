#!/usr/bin/env bash
# Restore DB to the post-seed snapshot (used by `harness --reset` before write scenarios).
# First run (after seed.sh) takes the snapshot from the legacy DB; later runs restore it.
# Same snapshot loads the modern DB (DSN=...:3307/...), so both sides start identical.
# Needs a mysql client on PATH (mac: brew install mysql-client). RESTART=1 also restarts Mifos.
set -euo pipefail
cd "$(dirname "$0")/.."
DSN=${DSN:-mysql://mifos:mifos@127.0.0.1:3306/mifos}
SNAP=legacy/snapshot.sql
re='^mysql://([^:]+):([^@]*)@([^:/]+):?([0-9]*)/(.+)$'
[[ $DSN =~ $re ]] || { echo "bad DSN $DSN" >&2; exit 2; }
U=${BASH_REMATCH[1]} P=${BASH_REMATCH[2]} H=${BASH_REMATCH[3]} PORT=${BASH_REMATCH[4]:-3306} DB=${BASH_REMATCH[5]}
args=(-h"$H" -P"$PORT" -u"$U" -p"$P" --protocol=TCP)
if [[ ! -f $SNAP || ${SNAPSHOT:-0} == 1 ]]; then
  # --no-tablespaces: app user lacks PROCESS; column-statistics off: MySQL 8 client vs 5.7 server
  # --lock-tables, not --single-transaction: a consistent-snapshot dump aborts with error 1412
  # ("Table definition has changed") when Mifos touched a table's metadata after startup.
  opts=(--lock-tables --routines --no-tablespaces)
  mysqldump --help 2>/dev/null | grep -q column-statistics && opts+=(--column-statistics=0)
  for try in 1 2 3; do   # tmp file: never leave a half snapshot behind
    mysqldump "${args[@]}" "${opts[@]}" "$DB" > "$SNAP.tmp" && break
    [[ $try == 3 ]] && { rm -f "$SNAP.tmp"; echo "snapshot failed" >&2; exit 1; }
    sleep 2
  done
  mv "$SNAP.tmp" "$SNAP"
  echo "snapshot -> $SNAP ($(grep -c '^INSERT' "$SNAP") insert statements)"
else
  mysql "${args[@]}" "$DB" < "$SNAP"
fi
if [[ ${RESTART:-0} == 1 && ${HARNESS_SIDE:-legacy} == legacy ]]; then
  docker compose -f legacy/docker-compose.yml restart mifos
  PORT=$(grep -s '^MIFOS_PORT=' legacy/.env | cut -d= -f2); PORT=${MIFOS_PORT:-${PORT:-18080}}
  until curl -sf -o /dev/null "http://localhost:$PORT/mifos/login.ftl"; do sleep 3; done
fi
