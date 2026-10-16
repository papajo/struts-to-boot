"""Export the map as an AnchorMesh anchor-tag manifest (papajo/AnchorMesh, schema v1).

Anchors are generated, not hand-placed: endpoints (EXTERNAL_API), business rules
(BUSINESS_LOGIC), and table writes (DATABASE_QUERY). Each carries `line` and `symbol`
extensions so AnchorMesh can resolve the zone without the `@anchor[...]` comment;
`annotate()` can also write the comments into a source tree.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from collections import defaultdict
from pathlib import Path

from .graph import Map

SCHEMA = "https://anchormesh.io/schemas/v1/anchor-tag-manifest.json"


def _id(prefix: str, *parts) -> str:
    return f"{prefix}-{hashlib.sha1('|'.join(map(str, parts)).encode()).hexdigest()[:6].upper()}"


def manifest(m: Map, endpoints: list[str] | None = None, depth: int = 6) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    eps = endpoints or [r[0] for r in m.con.execute("SELECT id FROM nodes WHERE kind='endpoint' ORDER BY id")]
    anchors: dict[str, dict] = {}

    def add(a: dict):
        a.update(createdBy="legacy-code-mapper", createdAt=now)
        anchors.setdefault(a["id"], a).setdefault("endpoints", [])

    for ep in eps:
        t = m.trace(ep, depth=depth)
        h = m.out(ep, "handles")
        hn = m.node(h[0]["dst"]) if h else None
        aid = _id("EP", ep)
        add({"id": aid, "name": ep, "type": "External API", "file": hn["file"] if hn else None,
             "line": hn["line"] if hn else None, "symbol": hn["id"] if hn else None,
             "purpose": f"Struts endpoint. Writes: {', '.join(k for k, v in t['tables'].items() if 'write' in v) or 'none'}. "
                        f"Views: {', '.join(t['views']) or 'none'}.",
             "severity": "high" if any("write" in v for v in t["tables"].values()) else "medium"})
        anchors[aid]["endpoints"].append(ep)
        for r in t["rules"]:
            rid = _id("RULE", r["file"], r["line"])
            add({"id": rid, "name": (r["message"] or r["key"] or r["outcome"])[:120], "type": "Business Logic",
                 "file": r["file"], "line": r["line"], "symbol": r["method"],
                 "purpose": f"{r['kind']}: if {r['condition']} -> {r['outcome']}",
                 "severity": "high" if r["kind"] == "guard" else "medium"})
            anchors[rid]["endpoints"].append(ep)
        for mm in t["methods"]:
            for w in m.out(mm["id"], "writes"):
                wid = _id("DB", mm["id"], w["line"])
                add({"id": wid, "name": f"write {w['dst'].removeprefix('table:')}", "type": "Database Query",
                     "file": mm["file"], "line": w["line"], "symbol": mm["id"],
                     "purpose": f"Persists to {w['dst'].removeprefix('table:')} (Hibernate save/update/delete).",
                     "severity": "high"})
                anchors[wid]["endpoints"].append(ep)
    for a in anchors.values():
        a["endpoints"] = sorted(set(a["endpoints"]))
    return {"$schema": SCHEMA, "version": "1.2.0", "generatedAt": now,
            "governance": {"enforceStrictCompliance": False, "permittedPrefixes": ["EP", "RULE", "DB"]},
            "anchors": sorted(anchors.values(), key=lambda a: (a["file"] or "", a["line"] or 0, a["id"])),
            "triggers": [], "variables": []}


def annotate(man: dict, root: Path) -> int:
    """Insert `// @anchor[ID]: name` above each anchored line (bottom-up so line numbers stay valid)."""
    by_file: dict[str, list[dict]] = defaultdict(list)
    for a in man["anchors"]:
        if a.get("file") and a.get("line"):
            by_file[a["file"]].append(a)
    n = 0
    for f, items in by_file.items():
        p = root / f
        lines = p.read_text(errors="replace").splitlines(keepends=True)
        for a in sorted(items, key=lambda a: -a["line"]):
            if any(f"@anchor[{a['id']}]" in l for l in lines):
                continue
            i = a["line"] - 1
            indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())] if i < len(lines) else ""
            lines.insert(i, f"{indent}// @anchor[{a['id']}]: {a['name'][:80]}\n")
            n += 1
        p.write_text("".join(lines))
    return n
