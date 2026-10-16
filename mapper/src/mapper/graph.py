"""Queries over the code map. Every answer cites file:line so an agent can verify it."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import deque
from pathlib import Path

ACCESSOR = re.compile(r"^(get|set|is|has)[A-Z]\w*$")
# Plumbing that every endpoint touches; expanding it drowns the business logic.
DEFAULT_SKIP = (
    "org.mifos.framework.util.helpers.SessionUtils", "org.mifos.framework.util.helpers.DateUtils",
    "org.mifos.framework.util.helpers.FlowManager", "org.mifos.framework.util.helpers.Flow",
    "org.mifos.framework.util.helpers.TransactionDemarcate", "org.mifos.framework.hibernate.helper.StaticHibernateUtil",
    "org.mifos.framework.util.LocalizationConverter", "org.mifos.config.", "org.mifos.security.",
    "org.mifos.framework.struts.tags.", "org.mifos.framework.exceptions.", "org.mifos.framework.business.util.helpers.MethodNameConstants",
)


class Map:
    def __init__(self, db: Path | str):
        self.db = Path(db)
        self.con = sqlite3.connect(self.db, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        root = self.meta().get("source_root")
        self.root = Path(root) if root else None

    # -------------------------------------------------------------- basics

    def meta(self) -> dict:
        return {r["k"]: json.loads(r["v"]) for r in self.con.execute("SELECT k, v FROM meta")}

    def node(self, nid: str) -> dict | None:
        r = self.con.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()
        return dict(r) if r else None

    def out(self, nid: str, kind: str) -> list[sqlite3.Row]:
        return self.con.execute("SELECT dst, line FROM edges WHERE src=? AND kind=?", (nid, kind)).fetchall()

    def inc(self, nid: str, kind: str) -> list[sqlite3.Row]:
        return self.con.execute("SELECT src, line FROM edges WHERE dst=? AND kind=?", (nid, kind)).fetchall()

    def search(self, q: str, kind: str | None = None, limit: int = 25) -> list[dict]:
        sql = "SELECT id, kind, file, line FROM nodes WHERE (id LIKE ? OR name LIKE ?)"
        args: list = [f"%{q}%", f"%{q}%"]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        sql += " ORDER BY length(id) LIMIT ?"
        return [dict(r) for r in self.con.execute(sql, (*args, limit))]

    def resolve(self, ref: str) -> str:
        """Accept exact ids, `Class#method` without arity, simple class names, or endpoint keys."""
        if self.node(ref):
            return ref
        if "#" in ref and "/" not in ref.split("#")[1]:
            r = self.con.execute("SELECT id FROM nodes WHERE id LIKE ? ORDER BY id LIMIT 1", (ref + "/%",)).fetchone()
            if r:
                return r[0]
        r = self.con.execute("SELECT id FROM nodes WHERE kind IN ('class','interface','enum') AND name=? LIMIT 1",
                             (ref,)).fetchone()
        if r:
            return r[0]
        raise KeyError(f"unknown symbol: {ref} (try search)")

    def source(self, ref: str, context: int = 0) -> dict:
        n = self.node(self.resolve(ref))
        if not n or not n["file"] or self.root is None:
            raise KeyError(f"no source for {ref}")
        lines = (self.root / n["file"]).read_text(errors="replace").splitlines()
        a, b = max(1, n["line"] - context), min(len(lines), n["end_line"] + context)
        return {"id": n["id"], "file": n["file"], "start": a, "end": b,
                "code": "\n".join(lines[a - 1:b])}

    # -------------------------------------------------------------- traversal

    def _overriders(self, mid: str) -> list[str]:
        out, todo = [], [mid]
        while todo:
            for r in self.inc(todo.pop(), "overrides"):
                if r["src"] not in out:
                    out.append(r["src"])
                    todo.append(r["src"])
        return out

    def _bases(self, mid: str) -> list[str]:
        out, todo = [], [mid]
        while todo:
            for r in self.out(todo.pop(), "overrides"):
                if r["dst"] not in out:
                    out.append(r["dst"])
                    todo.append(r["dst"])
        return out

    def _is_accessor(self, mid: str) -> bool:
        n = self.node(mid)
        name = mid.split("#")[1].split("/")[0]
        return bool(n and ACCESSOR.match(name) and (n["end_line"] or 0) - (n["line"] or 0) <= 4)

    def trace(self, ref: str, depth: int = 6, skip: tuple[str, ...] = DEFAULT_SKIP, max_methods: int = 6000,
              data_depth: int = 16) -> dict:
        """Endpoint or method -> reachable methods, tables, named queries, views, business rules.

        Methods, rules and LOC are listed to `depth` (what an agent reads). Tables and queries use
        the deeper `data_depth` closure: persistence side effects sit far below the action
        (e.g. GL postings at depth ~11 for a disbursal), and missing one breaks equivalence."""
        start = self.resolve(ref)
        n = self.node(start)
        roots: list[tuple[str, str]] = []
        views: list[str] = []
        if n["kind"] == "endpoint":
            roots = [(r["dst"], "handles") for r in self.out(start, "handles")]
            roots += [(r["dst"], "validates") for r in self.out(start, "validates")]
            views = [r["dst"].removeprefix("view:") for r in self.out(start, "forwards")]
        else:
            roots = [(start, "root")]
        seen: dict[str, int] = {}
        q = deque((m, 0) for m, _ in roots)
        accessors: set[str] = set()
        truncated = False
        while q:
            m, d = q.popleft()
            if m in seen:
                continue
            if len(seen) >= max_methods:
                truncated = True
                break
            seen[m] = d
            if d >= data_depth:
                continue
            for r in self.out(m, "calls"):
                callee = r["dst"]
                for c in [callee, *self._overriders(callee)]:
                    if c in seen or c.startswith(skip):
                        continue
                    if self._is_accessor(c):
                        accessors.add(c)
                        continue
                    q.append((c, d + 1))
        methods = sorted(((k, v) for k, v in seen.items() if v <= depth), key=lambda kv: (kv[1], kv[0]))
        tables: dict[str, set[str]] = {}
        queries: set[str] = set()

        def mark(cls: str | None, how: str):
            for t in (self.out(cls, "maps") if cls else []):
                tables.setdefault(t["dst"].removeprefix("table:"), set()).add(how)

        for m in list(seen) + list(accessors):
            for r in self.out(m, "writes"):
                tables.setdefault(r["dst"].removeprefix("table:"), set()).add("write")
            for r in self.out(m, "queries"):
                queries.add(r["dst"].removeprefix("query:"))
                for t in self.out(r["dst"], "reads"):
                    tables.setdefault(t["dst"].removeprefix("table:"), set()).add("query")
                for t in self.out(r["dst"], "writes"):
                    tables.setdefault(t["dst"].removeprefix("table:"), set()).add("write")
            for r in self.out(m, "instantiates"):  # new Entity(...) -> INSERT via cascade/save
                mark(r["dst"], "create")
            node = self.node(m)
            mark(node and node["ret"], "read")  # returns an entity / collection of entities
            name = m.split("#")[1]
            if m in accessors and name.startswith("set"):
                mark(m.split("#")[0], "update")  # setter on a managed entity = dirty-checked UPDATE
            elif m in seen:
                mark(m.split("#")[0], "entity")
        rules = self.rules_for([m for m, _ in methods])
        locs = [self.node(m) for m, _ in methods]
        return {
            "start": start, "kind": n["kind"],
            "methods": [{"id": m, "depth": d, "file": x["file"], "line": x["line"], "end_line": x["end_line"]}
                        for (m, d), x in zip(methods, locs)],
            "accessors_skipped": len(accessors), "truncated": truncated, "closure_methods": len(seen),
            "tables": {t: sorted(a) for t, a in sorted(tables.items())},
            "queries": sorted(queries), "views": sorted(views), "rules": rules,
            "loc": sum((x["end_line"] or 0) - (x["line"] or 0) + 1 for x in locs),
        }

    def rules_for(self, method_ids: list[str]) -> list[dict]:
        if not method_ids:
            return []
        out = []
        for i in range(0, len(method_ids), 500):
            chunk = method_ids[i:i + 500]
            out += [dict(r) for r in self.con.execute(
                f"SELECT method, file, line, kind, condition, outcome, key, message FROM rules "
                f"WHERE method IN ({','.join('?' * len(chunk))}) ORDER BY file, line", chunk)]
        return out

    def impact(self, ref: str, max_depth: int = 12) -> dict:
        """Who is affected if this symbol changes: callers up to endpoints (incl. interface dispatch)."""
        start = self.resolve(ref)
        n = self.node(start)
        if n["kind"] in ("class", "interface", "enum"):
            seeds = [r[0] for r in self.con.execute("SELECT id FROM nodes WHERE kind='method' AND id LIKE ?", (start + "#%",))]
        elif n["kind"] == "table":
            seeds = [r["src"] for r in self.inc(start, "writes")] + [r["src"] for r in self.inc(start, "reads")]
            seeds += [r["src"] for q in list(seeds) if q.startswith("query:") for r in self.inc(q, "queries")]
            seeds += [r["src"] for c in self.inc(start, "maps")
                      for r in self.con.execute("SELECT id AS src FROM nodes WHERE kind='method' AND id LIKE ?", (c["src"] + "#%",))]
            seeds = [s for s in seeds if not s.startswith("query:")]
        else:
            seeds = [start]
        seen: dict[str, int] = {}
        q = deque((s, 0) for s in seeds)
        while q:
            m, d = q.popleft()
            if m in seen or d > max_depth:
                continue
            seen[m] = d
            for target in [m, *self._bases(m)]:  # a call to the interface method reaches this impl
                for r in self.inc(target, "calls"):
                    q.append((r["src"], d + 1))
        eps = set()
        for m in seen:
            eps.update(r["src"] for r in self.inc(m, "handles"))
            eps.update(r["src"] for r in self.inc(m, "validates"))
        return {"symbol": start, "callers": len(seen) - len(seeds), "endpoints": sorted(eps)}

    def tables_for(self, ref: str) -> dict:
        return self.trace(ref)["tables"]

    def context(self, ref: str, budget_tokens: int = 12000, depth: int = 4) -> dict:
        """Source pack for an agent: handler first, then callees by depth, until the token budget."""
        t = self.trace(ref, depth=depth)
        parts, used, included = [], 0, []
        header = (f"# Context for {t['start']}\n"
                  f"tables: {json.dumps(t['tables'])}\nviews: {t['views']}\nqueries: {t['queries']}\n"
                  "## business rules\n" + "\n".join(
                      f"- [{r['kind']}] {r['file']}:{r['line']} if {r['condition']} -> {r['outcome']}"
                      + (f" ('{r['message']}')" if r['message'] else "") for r in t["rules"]))
        used += len(header) // 4
        for m in t["methods"]:
            try:
                s = self.source(m["id"])
            except KeyError:
                continue
            chunk = f"\n## {s['id']}  ({s['file']}:{s['start']}-{s['end']})\n{s['code']}\n"
            cost = len(chunk) // 4
            if used + cost > budget_tokens:
                continue
            parts.append(chunk)
            used += cost
            included.append(m["id"])
        return {"start": t["start"], "tokens": used, "methods_included": len(included),
                "methods_reachable": len(t["methods"]), "text": header + "".join(parts)}
