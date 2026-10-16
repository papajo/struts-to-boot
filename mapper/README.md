# Legacy Code Mapper (Capstone #2)

Static map of a legacy Java/Struts/Hibernate codebase, served over MCP so agents query it
before changing anything. Extends [AnchorMesh](https://github.com/papajo/AnchorMesh): exports
an AnchorMesh v1 anchor-tag manifest, generated from the code instead of hand-placed.

No build or classpath needed: parses source with tree-sitter, so it works on code that no longer compiles.

## What it extracts
- **Call graph**: receiver types from locals/params/fields/inheritance/static imports/chained return types/generic element types; interface → implementation dispatch.
- **Struts**: endpoint `/path.do#method` → handler, form `validate()`, forwards → JSP/FTL.
- **Hibernate**: class → table (incl. joined-subclass parents and collection tables), named queries → tables, `save/update/delete` → writes, `new Entity()` → create, setter on entity → update.
- **Business rules**: `if (cond) throw new X(KEY)` guards and `errors.add(KEY, …)` validations, with the condition, `file:line`, and the user-facing message resolved from `*.properties` (default locale preferred).

## Commands
```bash
cd mapper && python3 -m venv .venv && .venv/bin/pip install -e '.[test]' && .venv/bin/pytest -q && cd ..
mapper/.venv/bin/mapper index legacy-src                      # -> mapper/out/map.db (~5 s on Mifos)
mapper/.venv/bin/mapper trace   '/loanDisbursementAction.do#update'
mapper/.venv/bin/mapper rules   '/loanDisbursementAction.do#update'
mapper/.venv/bin/mapper impact  table:loan_schedule           # or a method / class
mapper/.venv/bin/mapper context '/loanDisbursementAction.do#update' --budget 12000
mapper/.venv/bin/mapper anchors --inventory docs/loan-inventory.json   # AnchorMesh manifest
mapper/.venv/bin/mapper eval                                   # -> docs/mapper-eval.md
```

## MCP
Tools: `stats`, `search`, `trace`, `rules`, `impact`, `tables`, `source`, `context`, `anchors`.
```json
{"mcpServers": {"legacy-code-mapper": {
  "command": "/abs/path/struts-to-boot/mapper/.venv/bin/mapper",
  "args": ["--db", "/abs/path/struts-to-boot/mapper/out/map.db", "serve"]}}}
```
Claude Code: `claude mcp add legacy-code-mapper -- /abs/path/mapper/.venv/bin/mapper --db /abs/path/mapper/out/map.db serve`

## Results on Mifos (see `docs/mapper-eval.md`)
- 2,210 files / 23,696 methods / 566 endpoints indexed in ~5 s; 94.7% of internal calls resolved.
- 1,258 rules extracted, 748 with resolved messages.
- Loan slice (55 endpoints): context pack ≈ 9.1k tokens vs ≈ 166k to load every touched file (18×).
- Recall vs harness DB checks: 29/29 tables (regression check — tuned on these).

## Blind spots (v0)
- Reflection, Spring XML wiring, and calls into code outside `*/src/main/java` are invisible.
- Interface dispatch fans out to *all* implementations (over-approximate).
- Struts forms that branch on `request.getParameter("method")` in `validate()` contribute every branch's rules to every endpoint.
- Table access is coarse (`entity` = a method of the mapped class ran); writes via cascade are inferred from `new`/setters, not from hbm cascade settings.
- PL/SQL and Informatica (in the capstone brief) are not covered: Mifos has neither. Next adapters, tested on a public PL/SQL codebase.
