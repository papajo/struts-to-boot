import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from harness.core import Scenario, Side, Step, compare, extract_html, extract_json, normalize, record, replay

LEGACY_HTML = """<html><body>
<span id="loanaccountdetail.text.interestRate">12.50</span>
<span id="loanaccountdetail.text.currency"> INR </span>
<table id="loanSummaryTable"><tr><td>1,000.00</td><td>250</td></tr></table>
</body></html>"""


def _server(body_fn, ctype):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            b = body_fn(self.path).encode()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def log_message(self, *a):
            pass

    s = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_port}"


def test_normalize_numbers_and_whitespace():
    assert normalize("1,000.00") == normalize(1000)
    assert normalize("  a \n b ") == "a b"
    assert normalize(12.5) == normalize("12.50")


def test_extractors_agree():
    h = extract_html(LEGACY_HTML, {"rate": '[id="loanaccountdetail.text.interestRate"]',
                                   "cells": "#loanSummaryTable td[]"})
    j = extract_json({"interestRate": 12.5, "summary": {"cells": [1000, 250]}},
                     {"rate": "$.interestRate", "cells": "$.summary.cells[*]"})
    assert h == j


def _scenario(rate_path="$.interestRate"):
    return Scenario(name="t", steps=[Step(
        id="s1", endpoint="/loanAccountAction.do#get",
        legacy=Side("GET", "/legacy", extract={"rate": '[id="loanaccountdetail.text.interestRate"]',
                                               "cur": '[id="loanaccountdetail.text.currency"]'}),
        modern=Side("GET", "/api", extract={"rate": rate_path, "cur": "$.currency"}))])


@pytest.mark.parametrize("modern_rate,expect", [(12.5, True), (12.0, False)])
def test_record_replay_end_to_end(tmp_path: Path, modern_rate, expect):
    ls, lurl = _server(lambda p: LEGACY_HTML, "text/html")
    ms, murl = _server(lambda p: json.dumps({"interestRate": modern_rate, "currency": "INR"}),
                       "application/json")
    try:
        sc = _scenario()
        record(sc, lurl, tmp_path)
        rows = replay(sc, murl, tmp_path)
        assert rows[0]["match"] is expect
        if not expect:
            assert any("rate" in d for d in rows[0]["diffs"])
    finally:
        ls.shutdown()
        ms.shutdown()


def test_compare_flags_missing_step():
    g = {"s1": {"endpoint": "e", "status": 200, "ms": 1, "values": {}, "sql": []}}
    assert compare(g, {})[0]["diffs"] == ["missing"]
