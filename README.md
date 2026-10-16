# struts-to-boot

AI agents migrate the loan module of [Mifos](https://github.com/mifos/head) — a real Struts 1.2 microfinance platform (470k LOC) — to Spring Boot 3 + REST/OpenAPI + Kafka. Equivalence is proven, not claimed: legacy responses and DB state are recorded, then replayed against the new service.

## Results
| Metric | Value |
|---|---|
| Endpoints matched | — / 55 |
| Cost per 1,000 legacy LOC | — |
| Human fix minutes per endpoint | — |
| AI failure cases documented | — |

_Filled from `docs/metrics.csv` and `harness/out/REPORT.md`._

**Legacy Code Mapper** (`mapper/`, MCP server agents query before editing): 94.7% of internal calls resolved across 2,210 files in ~5 s; 1,258 business rules extracted with `file:line`; per-endpoint context ≈ 9k tokens vs ≈ 166k to load every touched file. See `docs/mapper-eval.md`.

## How equivalence works
Legacy returns JSP-rendered HTML; modern returns JSON. Each scenario step extracts the same business facts from both (CSS selectors vs JSONPath), normalizes numbers/whitespace, and compares — plus SQL checks on DB state after write steps. See `harness/`.

## Layout
- `legacy/` — Docker build/run for Mifos (`legacy-src/` submodule)
- `modern/` — Spring Boot 3 service
- `harness/` — record/replay equivalence harness
- `mapper/` — Legacy Code Mapper: call graph, tables, business rules → MCP + AnchorMesh manifest
- `tools/inventory.py` — Struts endpoint inventory → `docs/loan-inventory.md`
- `docs/` — inventory, metrics, failures, build log
