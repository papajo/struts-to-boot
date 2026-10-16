import asyncio
import json
from pathlib import Path

import pytest

from mapper.anchors import annotate, manifest
from mapper.graph import Map
from mapper.index import build

FIX = Path(__file__).parent / "fixture"
EP = "/loanAction.do#disburse"


@pytest.fixture(scope="module")
def m(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "map.db"
    stats = build(FIX, db)
    assert stats["endpoints"] == 2 and stats["java_files"] == 10
    return Map(db)


def test_trace_follows_interface_dispatch_to_domain(m):
    ids = [x["id"] for x in m.trace(EP)["methods"]]
    assert "com.acme.loan.LoanFacadeImpl#disburse/2" in ids      # interface -> impl
    assert "com.acme.loan.LoanBO#disburse/1" in ids              # field-typed receiver
    assert "com.acme.loan.PaymentEntity#post/0" in ids           # chained call via return type
    assert "com.acme.loan.LoanForm#validate/2" in ids            # struts form validation


def test_tables_views_queries(m):
    t = m.trace(EP)
    assert t["views"] == ["/pages/loan/details.jsp"]             # enum forward name resolved
    assert t["queries"] == ["loan.findByGlobalAccountNum"]        # constant -> named query
    assert "query" in t["tables"]["loan_account"] and "write" in t["tables"]["loan_account"]
    assert "create" in t["tables"]["account_payment"]            # new PaymentEntity(...)
    assert "update" in t["tables"]["loan_account"]               # setter on managed entity


def test_rules_resolve_messages_prefer_default_locale(m):
    rules = {r["kind"]: r for r in m.trace(EP)["rules"]}
    assert rules["guard"]["condition"] == "(state != 3)"
    assert rules["guard"]["message"] == "Loan must be approved before disbursal."
    assert rules["guard"]["file"].endswith("LoanBO.java") and rules["guard"]["line"] == 14
    assert rules["validation"]["message"] == "Please specify the amount."


def test_impact_reaches_endpoint_through_interface(m):
    assert m.impact("com.acme.loan.LoanBO#disburse/1")["endpoints"] == [EP]
    assert m.impact("table:account_payment")["endpoints"] == [EP]
    assert m.impact("LoanDao")["endpoints"] == [EP]


def test_context_respects_budget(m):
    c = m.context(EP, budget_tokens=400)
    assert c["tokens"] <= 400 and "LoanAction#disburse/4" in c["text"]


def test_anchormesh_manifest_and_annotate(m, tmp_path):
    man = manifest(m, [EP])
    types = {a["type"] for a in man["anchors"]}
    assert {"External API", "Business Logic", "Database Query"} <= types
    assert man["$schema"].startswith("https://anchormesh.io/schemas/v1/")
    import shutil
    root = tmp_path / "src"
    shutil.copytree(FIX, root)
    n = annotate(man, root)
    assert n == len(man["anchors"])
    rule = next(a for a in man["anchors"] if a["type"] == "Business Logic" and a["file"].endswith("LoanBO.java"))
    lines = (root / rule["file"]).read_text().splitlines()
    assert lines[rule["line"] - 1].strip().startswith(f"// @anchor[{rule['id']}]")
    assert annotate(man, root) == 0  # idempotent


def test_mcp_server_tools(m):
    from mcp.client import Client
    from mapper.server import create

    async def run():
        async with Client(create(m.db)) as c:
            tools = {t.name for t in (await c.list_tools()).tools}
            assert {"trace", "rules", "impact", "context", "source", "search", "anchors", "tables", "stats"} <= tools
            res = await c.call_tool("impact", {"symbol": "com.acme.loan.LoanBO#disburse/1"})
            body = res.structured_content or json.loads(res.content[0].text)
            assert EP in json.dumps(body)
    asyncio.run(run())
