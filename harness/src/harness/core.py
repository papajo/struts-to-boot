"""Record legacy behavior, replay against the modern app, compare business values.

Legacy returns HTML (Struts/JSP); modern returns JSON (REST). Raw bodies can't be
diffed, so each step declares *extractors* that pull the same business facts from
both sides (CSS selectors for legacy, JSONPath for modern). Optional SQL checks
compare DB state after the step. A step "matches" when every extracted value and
every SQL result is equal after normalization.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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
    capture: dict[str, str] = field(default_factory=dict)  # var -> regex (group 1) over raw body
    fail_if: str | None = None  # regex over raw body that means the app rejected the request (e.g. validation error)


def _tmpl(v: Any, vars: dict) -> Any:
    """Fill {var} placeholders in strings/dicts; unknown vars are left as-is."""
    if isinstance(v, str):
        return re.sub(r"\{(\w+)\}", lambda m: str(vars.get(m[1], m[0])), v)
    if isinstance(v, dict):
        return {k: _tmpl(x, vars) for k, x in v.items()}
    if isinstance(v, list):
        return [_tmpl(x, vars) for x in v]
    return v


@dataclass
class Step:
    id: str
    endpoint: str  # inventory key, e.g. "/loanAccountAction.do#get"
    legacy: Side
    modern: Side | None  # None = UI-only step (form preview/navigation); recorded for chaining, not compared
    sql: list[str] = field(default_factory=list)


@dataclass
class Scenario:
    name: str
    steps: list[Step]
    login: dict | None = None  # {"legacy": Side-ish, "modern": Side-ish}
    vars: dict = field(default_factory=dict)
    reset: bool = False  # run the --reset command before this scenario (write flows)


def load_scenarios(path: Path) -> list[Scenario]:
    """One YAML may expand to several scenarios via `matrix: {var: [v1, v2]}`."""
    raw = yaml.safe_load(path.read_text())
    steps = [
        Step(id=s["id"], endpoint=s["endpoint"],
             legacy=Side(**s["legacy"]), modern=Side(**s["modern"]) if s.get("modern") else None,
             sql=s.get("sql", []))
        for s in raw["steps"]
    ]
    base_vars = raw.get("vars", {})
    reset = bool(raw.get("reset", False))
    matrix = raw.get("matrix") or {}
    if not matrix:
        return [Scenario(raw["name"], steps, raw.get("login"), dict(base_vars), reset)]
    (key, values), = matrix.items()  # single-axis matrix keeps names readable
    return [Scenario(f"{raw['name']}__{v}", steps, raw.get("login"), {**base_vars, key: v}, reset)
            for v in values]


def reset_db(sc: Scenario, cmd: str | None, which: str, dsn: str | None) -> None:
    """Restore fixtures before a write scenario so legacy and modern start from identical state."""
    if not sc.reset:
        return
    if not cmd:
        raise SystemExit(f"{sc.name} mutates data: pass --reset CMD (e.g. legacy/seed.sh)")
    env = {**os.environ, "HARNESS_SIDE": which, **({"DSN": dsn} if dsn else {})}
    subprocess.run(cmd, shell=True, check=True, env=env)


def load_scenario(path: Path) -> Scenario:
    return load_scenarios(path)[0]


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


def run_side(sc: Scenario, which: str, base: str, dsn: str | None = None,
             raw_dir: Path | None = None) -> dict:
    sess = requests.Session()
    if sc.login and which in sc.login:
        _send(sess, base, Side(**_tmpl(sc.login[which], sc.vars))).raise_for_status()
    vars = dict(sc.vars)
    results = {}
    for st in sc.steps:
        tpl = st.legacy if which == "legacy" else st.modern
        if tpl is None:  # UI-only step has no modern counterpart
            continue
        side = Side(tpl.method, _tmpl(tpl.url, vars), _tmpl(tpl.data, vars), _tmpl(tpl.json, vars),
                    tpl.extract, tpl.capture, tpl.fail_if)
        t0 = time.perf_counter()
        r = _send(sess, base, side)
        ms = round((time.perf_counter() - t0) * 1000, 1)
        for var, rx in side.capture.items():
            m = re.search(rx, r.text)
            if m:
                vars[var] = m.group(1)
            else:
                print(f"WARN {sc.name}/{st.id}: capture '{var}' matched nothing", file=sys.stderr)
        rejected = bool(side.fail_if and re.search(side.fail_if, r.text))
        if rejected:
            print(f"WARN {sc.name}/{st.id}: response matches fail_if (request rejected)", file=sys.stderr)
        if raw_dir is not None:
            raw_dir.mkdir(parents=True, exist_ok=True)
            ext = "html" if which == "legacy" else "json"
            (raw_dir / f"{sc.name}.{st.id}.{ext}").write_text(r.text)
        if which == "legacy":
            values = extract_html(r.text, side.extract)
            for k, v in values.items():
                if v in (None, []):
                    print(f"WARN {sc.name}/{st.id}: selector for '{k}' matched nothing", file=sys.stderr)
        else:
            values = extract_json(r.json() if r.content else None, side.extract)
        results[st.id] = {
            "endpoint": st.endpoint,
            "status": r.status_code,
            "rejected": rejected,
            "ui_only": st.modern is None,
            "ms": ms,
            "values": _jsonable(values),
            "sql": _jsonable(_run_sql(dsn, [_tmpl(q, vars) for q in st.sql])),
        }
    return results


def record(sc: Scenario, base: str, out: Path, dsn: str | None = None) -> Path:
    """Writes golden values to out/<name>.json and raw legacy HTML to out/raw/ (for writing selectors)."""
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{sc.name}.json"
    f.write_text(json.dumps(run_side(sc, "legacy", base, dsn, raw_dir=out / "raw"), indent=2))
    return f


def compare(golden: dict, actual: dict) -> list[dict]:
    rows = []
    for sid, g in golden.items():
        if g.get("ui_only"):
            rows.append({"step": sid, "endpoint": g["endpoint"], "match": None, "ui_only": True, "diffs": []})
            continue
        a = actual.get(sid)
        if a is None:
            rows.append({"step": sid, "endpoint": g["endpoint"], "match": False, "diffs": ["missing"]})
            continue
        diffs = []
        if g.get("rejected"):
            diffs.append("golden is invalid: legacy rejected this step (fix scenario, re-record)")
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
