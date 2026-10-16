"""Record legacy behavior, replay against the modern app, compare business values.

Legacy returns HTML (Struts/JSP); modern returns JSON (REST). Raw bodies can't be
diffed, so each step declares *extractors* that pull the same business facts from
both sides (CSS selectors for legacy, JSONPath for modern). Optional SQL checks
compare DB state after the step. A step "matches" when every extracted value and
every SQL result is equal after normalization.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup
from jsonpath_ng.ext import parse as jsonpath

# ---------------------------------------------------------------- normalization

_NUM = re.compile(r"^-?[\d,]*\.?\d+$")


def normalize(v: Any) -> Any:
    """Make HTML-rendered and JSON values comparable."""
    if isinstance(v, list):
        return [normalize(x) for x in v]
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return Decimal(str(v)).normalize()
    s = " ".join(str(v).split())
    if _NUM.match(s):
        try:
            return Decimal(s.replace(",", "")).normalize()
        except InvalidOperation:
            pass
    return s


def _jsonable(v: Any) -> Any:
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return str(v)
    return v


# ---------------------------------------------------------------- extraction

def extract_html(html: str, spec: dict[str, str]) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for key, sel in spec.items():
        many = sel.endswith("[]")
        sel = sel[:-2] if many else sel
        nodes = soup.select(sel)
        texts = [n.get("value") if n.name == "input" else n.get_text(" ", strip=True) for n in nodes]
        out[key] = normalize(texts if many else (texts[0] if texts else None))
    return out


def extract_json(body: Any, spec: dict[str, str]) -> dict[str, Any]:
    out = {}
    for key, path in spec.items():
        many = path.endswith("[]") or path.endswith("[*]")
        path = path[:-2] if path.endswith("[]") else path
        vals = [m.value for m in jsonpath(path).find(body)]
        out[key] = normalize(vals if many else (vals[0] if vals else None))
    return out


# ---------------------------------------------------------------- scenario model

@dataclass
class Side:
    method: str
    url: str
    data: dict | None = None
    json: dict | None = None
    extract: dict[str, str] = field(default_factory=dict)


@dataclass
class Step:
    id: str
    endpoint: str  # inventory key, e.g. "/loanAccountAction.do#get"
    legacy: Side
    modern: Side
    sql: list[str] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    steps: list[Step]
    login: dict | None = None  # {"legacy": Side-ish, "modern": Side-ish}


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text())
    steps = [
        Step(id=s["id"], endpoint=s["endpoint"],
             legacy=Side(**s["legacy"]), modern=Side(**s["modern"]), sql=s.get("sql", []))
        for s in raw["steps"]
    ]
    return Scenario(name=raw["name"], steps=steps, login=raw.get("login"))


# ---------------------------------------------------------------- execution

def _send(sess: requests.Session, base: str, side: Side) -> requests.Response:
    return sess.request(side.method, base.rstrip("/") + side.url,
                        data=side.data, json=side.json, timeout=60, allow_redirects=True)


def _run_sql(dsn: str | None, queries: list[str]) -> list[Any]:
    if not dsn or not queries:
        return []
    import pymysql  # optional dependency

    m = re.match(r"mysql://(?P<u>[^:]+):(?P<p>[^@]*)@(?P<h>[^:/]+)(?::(?P<port>\d+))?/(?P<db>.+)", dsn)
    conn = pymysql.connect(host=m["h"], port=int(m["port"] or 3306), user=m["u"],
                           password=m["p"], database=m["db"])
    try:
        with conn.cursor() as cur:
            res = []
            for q in queries:
                cur.execute(q)
                res.append([[normalize(c) for c in row] for row in cur.fetchall()])
            return res
    finally:
        conn.close()


def run_side(sc: Scenario, which: str, base: str, dsn: str | None = None) -> dict:
    sess = requests.Session()
    if sc.login and which in sc.login:
        _send(sess, base, Side(**sc.login[which])).raise_for_status()
    results = {}
    for st in sc.steps:
        side = st.legacy if which == "legacy" else st.modern
        t0 = time.perf_counter()
        r = _send(sess, base, side)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        if which == "legacy":
            values = extract_html(r.text, side.extract)
        else:
            values = extract_json(r.json() if r.content else None, side.extract)
        results[st.id] = {
            "endpoint": st.endpoint,
            "status": r.status_code,
            "ms": ms,
            "values": _jsonable(values),
            "sql": _jsonable(_run_sql(dsn, st.sql)),
        }
    return results


def record(sc: Scenario, base: str, out: Path, dsn: str | None = None) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{sc.name}.json"
    f.write_text(json.dumps(run_side(sc, "legacy", base, dsn), indent=2))
    return f


def compare(golden: dict, actual: dict) -> list[dict]:
    rows = []
    for sid, g in golden.items():
        a = actual.get(sid)
        if a is None:
            rows.append({"step": sid, "endpoint": g["endpoint"], "match": False, "diffs": ["missing"]})
            continue
        diffs = []
        if (g["status"] < 400) != (a["status"] < 400):
            diffs.append(f"status legacy={g['status']} modern={a['status']}")
        for k, gv in g["values"].items():
            av = a["values"].get(k)
            if gv != av:
                diffs.append(f"{k}: legacy={gv!r} modern={av!r}")
        if g["sql"] != a["sql"]:
            diffs.append("db state differs")
        rows.append({"step": sid, "endpoint": g["endpoint"], "match": not diffs, "diffs": diffs,
                     "legacy_ms": g["ms"], "modern_ms": a["ms"]})
    return rows


def replay(sc: Scenario, base: str, golden_dir: Path, dsn: str | None = None) -> list[dict]:
    golden = json.loads((golden_dir / f"{sc.name}.json").read_text())
    return compare(golden, run_side(sc, "modern", base, dsn))
