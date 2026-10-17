#!/usr/bin/env bash
# Prints OK/FAIL for a mifos/testmifos login against the running legacy app.
set -uo pipefail
cd "$(dirname "$0")/.."
PORT=$(grep -s '^MIFOS_PORT=' legacy/.env | cut -d= -f2); PORT=${MIFOS_PORT:-${PORT:-18080}}
B=http://localhost:$PORT/mifos; J=$(mktemp)
curl -s -c "$J" -b "$J" -o /dev/null "$B/login.ftl"
out=$(curl -s -c "$J" -b "$J" -o /dev/null -w '%{http_code} %{redirect_url}' \
      -d 'j_username=mifos&j_password=testmifos' "$B/j_spring_security_check")
rm -f "$J"
case "$out" in
  302*login*|302*error*|5*) echo "FAIL  $out" ; exit 1 ;;
  302*) echo "OK    $out" ;;
  *) echo "??    $out" ; exit 2 ;;
esac
