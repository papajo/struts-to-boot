#!/usr/bin/env bash
# Seed loan fixtures into the running legacy DB.
# Run AFTER Mifos has started once (Liquibase brings schema to HEAD on startup).
set -euo pipefail
cd "$(dirname "$0")/.."
DSN=${DSN:-mysql://mifos:mifos@127.0.0.1:3306/mifos}
DATASET=legacy-src/acceptanceTests/src/test/resources/dataSets/acceptance_dbunit.xml
PY=harness/.venv/bin/python
"$PY" tools/dbunit2sql.py "$DATASET" --dsn "$DSN" -o legacy/seed.sql --report docs/seed-report.md
docker compose -f legacy/docker-compose.yml exec -T mysql mysql -umifos -pmifos mifos < legacy/seed.sql
docker compose -f legacy/docker-compose.yml exec -T mysql mysql -umifos -pmifos mifos -e \
  "select account_state_id state, count(*) loans from account where account_type_id=1 group by 1"
echo "Restart Mifos so Hibernate caches drop: docker compose -f legacy/docker-compose.yml restart mifos"
