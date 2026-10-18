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

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.do_GET()

        do_PUT = do_POST

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


def test_capture_and_matrix(tmp_path: Path):
    seen = []

    def legacy(path):
        seen.append(path)
        return '<a href="x.do?currentFlowKey=FK123&x=1">n</a><span id="v">7</span>'

    ls, lurl = _server(legacy, "text/html")
    y = tmp_path / "s.yaml"
    y.write_text("""
name: m
matrix: {gan: ["A1", "B2"]}
steps:
  - id: first
    endpoint: e#get
    legacy: {method: GET, url: "/get?g={gan}", capture: {fk: "currentFlowKey=([^&\\"]+)"}, extract: {v: "#v"}}
    modern: {method: GET, url: /x}
  - id: second
    endpoint: e#next
    legacy: {method: GET, url: "/next?g={gan}&k={fk}"}
    modern: {method: GET, url: /y}
""")
    try:
        from harness.core import load_scenarios
        scs = load_scenarios(y)
        assert [s.name for s in scs] == ["m__A1", "m__B2"]
        for sc in scs:
            record(sc, lurl, tmp_path / "g")
        assert "/next?g=A1&k=FK123" in seen and "/next?g=B2&k=FK123" in seen
        assert seen[0] == "/dateTimeUpdate.ftl?dateTime=20110601T120000Z"  # clock pinned before login/steps
        assert (tmp_path / "g" / "raw" / "m__A1.first.html").exists()
    finally:
        ls.shutdown()


def test_compare_flags_missing_step():
    g = {"s1": {"endpoint": "e", "status": 200, "ms": 1, "values": {}, "sql": []}}
    assert compare(g, {})[0]["diffs"] == ["missing"]


def test_write_flow_ui_only_reset_fail_if(tmp_path: Path, capsys):
    from harness.core import load_scenarios, reset_db
    ls, lurl = _server(lambda p: '<span id="X.error.message">Bad date</span>' if "preview" in p
                       else '<input type="hidden" name="currentFlowKey" value="FK9">', "text/html")
    ms, murl = _server(lambda p: "{}", "application/json")
    y = tmp_path / "w.yaml"
    y.write_text("""
name: w
reset: true
steps:
  - id: load
    endpoint: a#load
    legacy: {method: GET, url: /load, capture: {fk: 'name="currentFlowKey" value="([^"]*)"'}}
    modern: null
  - id: preview
    endpoint: a#preview
    legacy: {method: POST, url: /preview, data: {k: "{fk}"}, fail_if: 'error\\.message">\\s*[^<\\s]'}
    modern: {method: POST, url: /api, json: {ids: ["{fk}"]}}
""")
    try:
        sc, = load_scenarios(y)
        marker = tmp_path / "reset.log"
        reset_db(sc, f"echo $HARNESS_SIDE >> {marker}", "legacy", None)
        assert marker.read_text().strip() == "legacy"
        record(sc, lurl, tmp_path / "g")
        assert "fail_if" in capsys.readouterr().err
        rows = replay(sc, murl, tmp_path / "g")
        assert rows[0] == {"step": "load", "endpoint": "a#load", "match": None, "ui_only": True, "diffs": []}
        assert rows[1]["match"] is False and "golden is invalid" in rows[1]["diffs"][0]
        with pytest.raises(SystemExit):
            reset_db(sc, None, "legacy", None)
    finally:
        ls.shutdown()
        ms.shutdown()
