"""Build the code map: Java + Struts config + Hibernate mappings + message bundles -> SQLite.

    nodes(id, kind, name, file, line, end_line, ret)  kind: class|interface|enum|method|endpoint|view|table|query
                                                   ret: resolved return type (element type for collections)
    edges(src, dst, kind, line)                    kind: calls|overrides|extends|handles|validates|
                                                         forwards|maps|queries|reads|writes|instantiates
    rules(method, file, line, kind, condition, outcome, key, message)
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import java as J

SCHEMA = """
CREATE TABLE nodes(id TEXT PRIMARY KEY, kind TEXT, name TEXT, file TEXT, line INT, end_line INT, ret TEXT);
CREATE TABLE edges(src TEXT, dst TEXT, kind TEXT, line INT);
CREATE TABLE rules(id INTEGER PRIMARY KEY, method TEXT, file TEXT, line INT, kind TEXT,
                   condition TEXT, outcome TEXT, key TEXT, message TEXT);
CREATE TABLE meta(k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX e_src ON edges(src, kind);
CREATE INDEX e_dst ON edges(dst, kind);
CREATE INDEX r_m ON rules(method);
CREATE INDEX n_kind ON nodes(kind);
"""


# ------------------------------------------------------------------ xml helpers

def _parse_xml(p: Path) -> ET.Element | None:
    raw = p.read_text(errors="replace")
    raw = re.sub(r"<!DOCTYPE[^>[]*(\[[^\]]*\])?>", "", raw)  # DTDs are fetched remotely otherwise
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def struts_configs(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*struts-config*.xml")
                  if "/src/main/" in str(p.relative_to(base)) or str(p.relative_to(base)).startswith("src/main/"))


def hbm_files(base: Path) -> list[Path]:
    return sorted(p for p in base.rglob("*.hbm.xml") if "src/main/" in str(p.relative_to(base)))


# ------------------------------------------------------------------ hibernate

_HQL_ENTITY = re.compile(r"\b(?:from|join|update|delete\s+from)\s+([A-Za-z_][\w.]*)", re.I)
_SQL_TABLE = re.compile(r"\b(?:from|join|update|into)\s+([a-z_][\w]*)", re.I)


def index_hbm(base: Path):
    """-> (class_tables {fqn: [table]}, queries {name: (kind, text, file, line)})"""
    class_tables: dict[str, list[str]] = {}
    queries: dict[str, tuple[str, str, str, int]] = {}

    def walk(el: ET.Element, parent_tables: list[str], rel: str):
        for c in el:
            tag = c.tag
            if tag in ("class", "subclass", "joined-subclass", "union-subclass"):
                name = c.get("name") or c.get("entity-name") or ""
                tabs = class_tables.setdefault(name, [])
                if c.get("table") and c.get("table") not in tabs:
                    tabs.append(c.get("table"))
                if tag in ("subclass", "joined-subclass"):  # rows also live in the parent table(s)
                    tabs += [t for t in parent_tables if t not in tabs]
                for coll in c.iter():
                    if coll.tag in ("set", "bag", "list", "map", "idbag", "array") and coll.get("table"):
                        if coll.get("table") not in tabs:
                            tabs.append(coll.get("table"))
                walk(c, [t for t in tabs if t not in (coll.get("table") for coll in c.iter())] or parent_tables, rel)

    for p in hbm_files(base):
        rel = str(p.relative_to(base))
        root = _parse_xml(p)
        if root is None:
            continue
        walk(root, [], rel)
    # top-level <subclass extends="..."> / <joined-subclass extends="..."> in separate files
    for p in hbm_files(base):
        root = _parse_xml(p)
        for c in (root if root is not None else []):
            if c.tag in ("subclass", "joined-subclass") and c.get("extends") in class_tables:
                tabs = class_tables.setdefault(c.get("name"), [])
                tabs += [t for t in class_tables[c.get("extends")] if t not in tabs]
        text = p.read_text(errors="replace").splitlines()
        for q in root.iter():
            if q.tag in ("query", "sql-query") and q.get("name"):
                ln = next((i + 1 for i, l in enumerate(text) if f'name="{q.get("name")}"' in l), 0)
                queries[q.get("name")] = (q.tag, " ".join((q.text or "").split()), rel, ln)
    return class_tables, queries


def query_tables(kind: str, text: str, class_tables: dict[str, list[str]], simple: dict[str, str]) -> list[str]:
    out: list[str] = []
    if kind == "sql-query":
        out = [m.lower() for m in _SQL_TABLE.findall(text)]
    else:
        for ent in _HQL_ENTITY.findall(text):
            fqn = ent if ent in class_tables else simple.get(ent.rsplit(".", 1)[-1])
            if fqn and class_tables.get(fqn):
                out.append(class_tables[fqn][0])
    return sorted(set(out))


# ------------------------------------------------------------------ messages

def load_messages(base: Path) -> dict[str, str]:
    msgs: dict[str, str] = {}
    files = sorted((p for p in base.rglob("*.properties") if "src/main/" in str(p.relative_to(base))),
                   key=lambda p: (bool(re.search(r"_[a-z]{2}(_[A-Z]{2})?\.properties$", p.name)), str(p)))
    for p in files:
        localized = bool(re.search(r"_[a-z]{2}(_[A-Z]{2})?\.properties$", p.name))
        for line in p.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line[0] in "#!" or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k not in msgs or not localized and not msgs[k]:
                msgs.setdefault(k, v.strip())
    return msgs


# ------------------------------------------------------------------ build

def build(base: Path, db: Path) -> dict:
    t0 = time.time()
    base = base.resolve()
    roots = sorted(p for p in base.glob("*/src/main/java"))
    ix = J.index_java(roots, base)
    class_tables, queries = index_hbm(base)
    msgs = load_messages(base)

    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    nodes, edges = [], []

    for td in ix.types.values():
        nodes.append((td.fqn, td.kind, td.fqn.rsplit(".", 1)[-1], td.file, td.line, td.end_line, None))
        for s in td.supers:
            r = J.resolve_type(ix, td.unit, s, td)
            if r and not r.startswith("ext:"):
                edges.append((td.fqn, r, "extends", td.line))
        for t in class_tables.get(td.fqn, []):
            edges.append((td.fqn, f"table:{t}", "maps", 0))
        anc = J.supertypes(ix, td.fqn)[1:]
        for ms in td.methods.values():
            for m in ms:
                ret = None
                for cand in [m.ret, *J.type_args(m.ret)]:
                    rr = J.resolve_type(ix, td.unit, cand, td) if cand else None
                    if rr and not rr.startswith("ext:"):
                        ret = rr
                        break
                nodes.append((m.id, "method", m.name, td.file, m.line, m.end_line, ret))
                for a in anc:  # overrides / implements
                    base_m = next((x for x in ix.types[a].methods.get(m.name, []) if x.arity == m.arity), None)
                    if base_m:
                        edges.append((m.id, base_m.id, "overrides", m.line))
                        break

    edges += [(s, d, "calls", ln) for s, d, ln in ix.calls]
    edges += [(s, d, "instantiates", ln) for s, d, ln in ix.news]
    for m, ent, ln in ix.saves:
        for anc in J.supertypes(ix, ent):
            for t in class_tables.get(anc, []):
                edges.append((m, f"table:{t}", "writes", ln))

    simple = {}
    for fqn in class_tables:
        simple.setdefault(fqn.rsplit(".", 1)[-1], fqn)
    tables = {t for ts in class_tables.values() for t in ts}
    for name, (kind, text, rel, ln) in queries.items():
        nodes.append((f"query:{name}", "query", name, rel, ln, ln, None))
        for t in query_tables(kind, text, class_tables, simple):
            tables.add(t)
            edges.append((f"query:{name}", f"table:{t}", "writes" if re.match(r"\s*(update|delete|insert)", text, re.I) else "reads", 0))
    for m, q, ln in ix.uses_query:
        if q in queries:
            edges.append((m, f"query:{q}", "queries", ln))
    for t in sorted(tables):
        nodes.append((f"table:{t}", "table", t, None, None, None, None))

    # struts: endpoints -> handler methods, form validation, forwards -> views
    fwd_by_method: dict[str, set[str]] = {}
    for m, f in ix.forwards:
        fwd_by_method.setdefault(m, set()).add(f)
    views: set[str] = set()
    n_endpoints = 0
    for cfg in struts_configs(base):
        root = _parse_xml(cfg)
        if root is None:
            continue
        forms = {fb.get("name"): fb.get("type") for fb in root.iter("form-bean")}
        globals_ = {f.get("name"): f.get("path") for gf in root.iter("global-forwards") for f in gf.iter("forward")}
        rel = str(cfg.relative_to(base))
        lines = cfg.read_text(errors="replace").splitlines()
        for a in root.iter("action"):
            path, cls = a.get("path"), a.get("type")
            if not path or cls not in ix.types:
                continue
            fwd = {**globals_, **{f.get("name"): f.get("path") for f in a.iter("forward")}}
            ln = next((i + 1 for i, l in enumerate(lines) if f'path="{path}"' in l), 0)
            td = ix.types[cls]
            form_validate = None
            if a.get("name") in forms and forms[a.get("name")] in ix.types:
                form_validate = J.find_method(ix, forms[a.get("name")], "validate", 2)
            for ms in td.methods.values():
                for m in ms:
                    if m.arity != 4 or "ActionForward" not in m.ret:
                        continue
                    ep = f"{path}.do#{m.name}"
                    n_endpoints += 1
                    nodes.append((ep, "endpoint", ep, rel, ln, ln, None))
                    edges.append((ep, m.id, "handles", ln))
                    if form_validate:
                        edges.append((ep, form_validate.id, "validates", ln))
                    for fname in sorted(fwd_by_method.get(m.id, ())):
                        target = fwd.get(fname)
                        if target:
                            views.add(target)
                            edges.append((ep, f"view:{target}", "forwards", 0))
    for v in sorted(views):
        nodes.append((f"view:{v}", "view", v, None, None, None, None))

    rules = [(r.method, r.file, r.line, r.kind, r.condition, r.outcome, r.key,
              msgs.get(r.key) if r.key else None) for r in ix.rules]

    con.executemany("INSERT OR IGNORE INTO nodes VALUES (?,?,?,?,?,?,?)", nodes)
    con.executemany("INSERT INTO edges VALUES (?,?,?,?)", sorted(set(edges)))
    con.executemany("INSERT INTO rules(method,file,line,kind,condition,outcome,key,message) VALUES (?,?,?,?,?,?,?,?)", rules)
    s = ix.stats
    stats = {
        "source_root": str(base), "java_files": len(ix.units), "types": len(ix.types),
        "methods": sum(1 for n in nodes if n[1] == "method"), "endpoints": n_endpoints,
        "tables": len(tables), "named_queries": len(queries), "rules": len(rules),
        "rules_with_message": sum(1 for r in rules if r[7]),
        "calls_resolved": s["resolved"], "calls_external": s["external"], "calls_unresolved": s["unresolved"],
        "call_resolution_rate": round(s["resolved"] / max(1, s["resolved"] + s["unresolved"]), 3),
        "seconds": round(time.time() - t0, 1),
    }
    con.executemany("INSERT INTO meta VALUES (?,?)", [(k, json.dumps(v)) for k, v in stats.items()])
    con.commit()
    con.close()
    return stats
