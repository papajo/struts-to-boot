# struts-to-boot

AI-assisted migration of the Mifos **loan module** (Struts 1.2) to Spring Boot 3 + REST/OpenAPI + Kafka, with behavioral equivalence proven by record/replay.

## Stack
- Legacy: Mifos (`legacy-src/`, submodule of mifos/head), Struts 1.2.7, Hibernate 3, Spring 3, JSP, MySQL 5.7, Jetty, Java 6 → built at 1.8
- Modern: Spring Boot 3.x, Java 21, Spring Web + springdoc-openapi, Spring Data JPA, Spring Kafka, Flyway, Testcontainers. **Same MySQL schema** as legacy (no data migration in scope).
- Harness: Python 3.10+ (`harness/`): requests, BeautifulSoup, jsonpath-ng, PyMySQL, pytest
- Infra: Docker Compose (`legacy/docker-compose.yml`)

## Scope
- Slice = `org.mifos.accounts.loan` → 7 actions, 55 endpoints, 26 JSPs. Source of truth: `docs/loan-inventory.json` (regenerate, don't hand-edit).
- Out of scope: UI (modern is API-only), reporting, non-loan modules.

## Commands
```bash
# inventory
python3 tools/inventory.py legacy-src --json docs/loan-inventory.json --md docs/loan-inventory.md
# legacy app
cd legacy && docker compose up --build           # :8080/mifos (first start runs Liquibase)
legacy/seed.sh                                    # load loan fixtures, then restart mifos
# harness
cd harness && python3 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest -q
harness record --legacy http://localhost:8080/mifos --legacy-db mysql://mifos:mifos@localhost:3306/mifos
harness replay --modern http://localhost:8081   --modern-db mysql://mifos:mifos@localhost:3307/mifos
harness report
# modern (once scaffolded)
cd modern && ./mvnw verify && ./mvnw spring-boot:run   # :8081
```

## Conventions
- Endpoint key: `<action path>.do#<dispatch method>` (e.g. `/loanAccountAction.do#get`). Every scenario step, commit, and metrics row uses it.
- One endpoint per AI migration run. Log every run in `docs/metrics.csv` (tokens, $, LOC in/out, human-fix minutes, pass/fail).
- AI failures go in `docs/failures.md` with endpoint key, what broke, root cause, fix. Never delete entries — they are the deliverable.
- Business logic stays in the legacy service/domain layer semantics; port it, don't "improve" it. Equivalence beats elegance.
- Modern REST: `/api/loans/...`, JSON camelCase, money as string decimals, dates ISO-8601.
- Kafka: emit domain events on state changes only (`loan.disbursed`, `loan.repaid`, `loan.status-changed`, `loan.disbursal-reversed`).
- Commits: `<endpoint key or area>: <what>`.
