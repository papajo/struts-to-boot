# Plan (3–4 weeks)

Target: Mifos loan module, 55 endpoints. Success = published numbers, not 100%.

## Week 1 — Legacy running + golden recordings
- [ ] Mifos builds and runs in Docker (`legacy/README.md` risks). Log every fix in `docs/build-log.md`.
- [ ] Seed data: 1 office, 1 loan officer, 3 clients, 1 group, 3 loan products, 5 loans in different states (pending, approved, disbursed, partially repaid, closed). Save as `legacy/seed.sql`.
- [ ] Scenarios for read endpoints first (`get`, `getLoanRepaymentSchedule`, `getAllActivity`, `viewStatusHistory`, `getInstallmentDetails`…). Record golden.
- [ ] Scenarios for write flows: disburse, repay, status change, reverse disbursal (multi-step: load → preview → update).
- [ ] Legacy Code Mapper (#2) v0: dependency map Action → service → DAO → tables for the slice. Feeds agent context.

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
