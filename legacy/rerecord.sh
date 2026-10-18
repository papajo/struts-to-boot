#!/usr/bin/env bash
# One-shot: rebuild legacy Mifos, smoke-test, record all golden scenarios, package for transfer.
#   legacy/rerecord.sh            # from repo root on oldbox; ~30 min; output in /tmp/rerecord.log
# Ends by writing /tmp/golden.tgz (stamped with the commit) and printing a summary.
set -uo pipefail
cd "$(dirname "$0")/.."
DC=(docker compose -f legacy/docker-compose.yml)
PORT=$(grep -s '^MIFOS_PORT=' legacy/.env | cut -d= -f2); PORT=${PORT:-18080}
B=http://localhost:$PORT/mifos
step() { printf '\n== %s  (%s)\n' "$*" "$(date +%H:%M:%S)"; }

pgrep -f 'harness record' >/dev/null && { echo "a recording is already running"; exit 1; }
step "commit"; git log --oneline -1
step "build"
"${DC[@]}" build mifos > /tmp/build.log 2>&1 || { tail -30 /tmp/build.log; exit 1; }
"${DC[@]}" up -d --force-recreate mifos >/dev/null 2>&1
step "wait for login"
for i in $(seq 1 60); do legacy/login-check.sh | grep -q OK && break; sleep 10; done
legacy/login-check.sh | grep -q OK || { echo "Mifos not up"; exit 1; }

step "smoke: loan 039 get + repayment schedule"
J=$(mktemp); curl -s -c "$J" -b "$J" -o /dev/null -d 'j_username=mifos&j_password=testmifos' "$B/j_spring_security_check"
curl -s -c "$J" -b "$J" -o /tmp/get.html "$B/loanAccountAction.do?method=get&globalAccountNum=000100000000039"
K=$(grep -o 'currentFlowKey=[0-9]*' /tmp/get.html | head -1 | cut -d= -f2)
R=$(grep -o 'randomNUm=[-0-9]*' /tmp/get.html | head -1 | cut -d= -f2)
code=$(curl -s -c "$J" -b "$J" -o /tmp/sched.html -w '%{http_code}' \
  "$B/loanAccountAction.do?method=getLoanRepaymentSchedule&accountId=39&globalAccountNum=000100000000039&randomNUm=$R&currentFlowKey=$K")
echo "schedule HTTP $code"
[[ $code == 200 ]] || "${DC[@]}" logs --since 2m mifos 2>&1 | grep -A3 'Caused by' | tail -12

step "record"
PYTHONUNBUFFERED=1 harness/.venv/bin/harness record --legacy "$B" \
  --legacy-db mysql://mifos:mifos@127.0.0.1:3306/mifos --reset legacy/reset.sh > /tmp/record.log 2>&1
echo "harness exit $?"

step "summary"
echo "recorded: $(grep -c '^recorded' /tmp/record.log)/13"
grep WARN /tmp/record.log | sort | uniq -c | head -20
echo "error pages: $(grep -lE 'Exception|Page expired' harness/out/golden/raw/* 2>/dev/null | wc -l)"
git log --oneline -1 > harness/out/golden/COMMIT
cp /tmp/record.log harness/out/golden/record.log
tar czf /tmp/golden.tgz harness/out/golden && ls -l /tmp/golden.tgz
