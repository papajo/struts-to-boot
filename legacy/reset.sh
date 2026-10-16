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
  mysqldump "${args[@]}" --single-transaction --routines "$DB" > "$SNAP"
  echo "snapshot -> $SNAP"
else
  mysql "${args[@]}" "$DB" < "$SNAP"
fi
if [[ ${RESTART:-0} == 1 && ${HARNESS_SIDE:-legacy} == legacy ]]; then
  docker compose -f legacy/docker-compose.yml restart mifos
  until curl -sf -o /dev/null http://localhost:8080/mifos/login.ftl; do sleep 3; done
fi
