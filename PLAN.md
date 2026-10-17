# Plan (3–4 weeks)

Target: Mifos loan module, 55 endpoints. Success = published numbers, not 100%.

## Week 1 — Legacy running + golden recordings
- [x] Mifos builds and runs in Docker on oldbox (x86 Linux): 18/18 modules, Liquibase at HEAD, login mifos/testmifos verified. 14 build/runtime fixes in `docs/build-log.md`.
- [x] Seed data: `legacy/seed.sh` converts Mifos's own `acceptance_dbunit.xml` (27 loans, 5 states) to the live schema via `tools/dbunit2sql.py`. Verified on baseline schema; rerun against HEAD.
- [x] Read scenarios: `harness/scenarios/loan_read.yaml` — 6 endpoints × 5 fixture loans.
- [ ] Record golden; replace `# placeholder` selectors using `harness/out/golden/raw/*.html`.
- [x] Write-flow scenarios: `loan_disburse`, `loan_repay`, `loan_reverse_disbursal`, `loan_status_bulk` (reset via `legacy/reset.sh` snapshot; DB-state SQL checks). Unverified until first record — watch `fail_if` WARNs.
- [x] Legacy Code Mapper (#2) v0 (`mapper/`): call graph + Struts + Hibernate + rules → SQLite, MCP server, AnchorMesh manifest. 94.7% call resolution; 18× smaller context per endpoint; `docs/mapper-eval.md`.
- [ ] Mapper v1: PL/SQL + Informatica adapters on a public codebase; Spring XML bean wiring; hbm cascade.

## Week 2 — Modern skeleton + read endpoints
- [ ] `modern/` Spring Boot 3, JPA entities for loan tables (generated from schema, reviewed), OpenAPI spec.
- [ ] Agent loop per endpoint: context = mapper output + action source + JSP + golden → generate controller/service → `harness replay` → fix → log metrics.
- [ ] All read endpoints passing.

## Week 3 — Write endpoints + Kafka
- [ ] Disburse, repay, status change, reverse disbursal, multi-loan create. DB-state SQL checks must match.
- [ ] Kafka events on each state change; contract test.
- [ ] `failures.md` honest and complete.

## Week 4 — Publish
- [ ] README with headline numbers: endpoints matched / 55, $ per 1,000 LOC, human minutes per endpoint, failure taxonomy.
- [ ] 2-minute demo video (replay run going green).
- [ ] Show HN + one founder email (see sheet tab "Getting Noticed").
