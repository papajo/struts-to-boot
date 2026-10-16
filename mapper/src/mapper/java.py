"""Java source -> declarations, resolved call edges, and business rules.

Two passes over tree-sitter ASTs:
  1. declare: packages, imports, types (incl. nested), fields, methods (params, return types),
     static final String constants.
  2. resolve: inside each method body, infer the static type of every call receiver
     (locals, params, fields up the class hierarchy, static class refs, chained calls via
     declared return types) and link `Class#method/arity`. Also extracts guard rules
     (`if (cond) throw new X(KEY)`) and validation rules (`errors.add(KEY, ...)` under an if).

No build or classpath needed - works on code that no longer compiles, which is the point.
Calls into types outside the indexed source (java.*, libraries) are counted as external,
not unresolved.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_java as tsj
from tree_sitter import Language, Node, Parser

PARSER = Parser(Language(tsj.language()))
JAVA_LANG = {"String", "Object", "Integer", "Long", "Short", "Boolean", "Double", "Float", "Byte",
             "Character", "Math", "System", "StringBuilder", "StringBuffer", "Exception",
             "RuntimeException", "Thread", "Class", "Number", "Enum", "Iterable", "Comparable"}
TYPE_DECLS = ("class_declaration", "interface_declaration", "enum_declaration", "annotation_type_declaration")
ERROR_CALLS = {"add", "addError", "addActionError", "rejectValue", "reject"}


def txt(n: Node | None) -> str:
    return n.text.decode("utf-8", "replace") if n is not None else ""


def base_type(t: str) -> str:
    """'List<Foo>[]' -> 'List';  'a.b.Foo' stays qualified."""
    t = re.sub(r"<.*>", "", t).replace("[]", "").replace("...", "").strip()
    return t


def type_args(t: str) -> list[str]:
    m = re.search(r"<(.*)>", t)
    return [base_type(x) for x in m[1].split(",")] if m else []


@dataclass
class Method:
    id: str               # pkg.Class#name/arity
    cls: str
    name: str
    arity: int
    ret: str              # raw return type text ("" for ctor)
    params: list[tuple[str, str]]  # (type, name)
    line: int
    end_line: int
    node: Node | None = None
    is_abstract: bool = False
    varargs: bool = False


@dataclass
class TypeDecl:
    fqn: str
    kind: str             # class|interface|enum
    file: str
    line: int
    end_line: int
    supers: list[str] = field(default_factory=list)       # raw names
    fields: dict[str, str] = field(default_factory=dict)  # name -> raw type
    methods: dict[str, list[Method]] = field(default_factory=dict)  # name -> overloads
    unit: "Unit | None" = None


@dataclass
class Unit:
    file: str
    pkg: str
    imports: dict[str, str]       # simple -> fqn
    wildcards: list[str]
    src: bytes
    static_imports: list[str] = field(default_factory=list)  # class fqns from `import static`
    types: list[TypeDecl] = field(default_factory=list)


@dataclass
class Rule:
    method: str
    file: str
    line: int
    kind: str       # guard | validation
    condition: str
    outcome: str    # e.g. "throw BusinessRuleException(LoanExceptionConstants.X)"
    key: str | None  # resolved message key, if any


@dataclass
class Index:
    units: list[Unit] = field(default_factory=list)
    types: dict[str, TypeDecl] = field(default_factory=dict)
    by_simple: dict[str, list[str]] = field(default_factory=dict)
    constants: dict[str, str] = field(default_factory=dict)  # Class.FIELD (fqn) -> literal
    calls: list[tuple[str, str, int]] = field(default_factory=list)  # (src method, dst method, line)
    news: list[tuple[str, str, int]] = field(default_factory=list)   # (src method, class fqn, line)
    uses_query: list[tuple[str, str, int]] = field(default_factory=list)  # (method, query name, line)
    saves: list[tuple[str, str, int]] = field(default_factory=list)  # (method, entity fqn, line)
    forwards: list[tuple[str, str]] = field(default_factory=list)   # (method, forward name)
    rules: list[Rule] = field(default_factory=list)
    stats: dict[str, int] = field(default_factory=lambda: {"resolved": 0, "external": 0, "unresolved": 0})


# ------------------------------------------------------------------ pass 1

def declare(ix: Index, path: Path, rel: str) -> None:
    src = path.read_bytes()
    root = PARSER.parse(src).root_node
    pkg, imports, wild, statics = "", {}, [], []
    for c in root.named_children:
        if c.type == "package_declaration":
            pkg = txt(c.named_children[-1]) if c.named_children else ""
            pkg = next((txt(x) for x in c.named_children if x.type in ("scoped_identifier", "identifier")), pkg)
        elif c.type == "import_declaration":
            name = next((txt(x) for x in c.named_children if x.type in ("scoped_identifier", "identifier")), "")
            star = any(x.type == "asterisk" for x in c.named_children)
            if "static" in txt(c).split()[1:2]:
                statics.append(name if star else name.rpartition(".")[0])
            elif star:
                wild.append(name)
            else:
                imports[name.rsplit(".", 1)[-1]] = name
    u = Unit(rel, pkg, imports, wild, src, statics)
    ix.units.append(u)
    for c in root.named_children:
        if c.type in TYPE_DECLS:
            _declare_type(ix, u, c, pkg)


def _declare_type(ix: Index, u: Unit, n: Node, outer: str) -> None:
    name = txt(n.child_by_field_name("name"))
    fqn = f"{outer}.{name}" if outer else name
    kind = n.type.split("_")[0]
    td = TypeDecl(fqn, kind, u.file, n.start_point[0] + 1, n.end_point[0] + 1, unit=u)
    sc = n.child_by_field_name("superclass")
    if sc is not None:
        td.supers += [txt(x) for x in sc.named_children]
    for f in ("interfaces",):
        s = n.child_by_field_name(f)
        if s is not None:
            td.supers += [txt(t) for tl in s.named_children for t in (tl.named_children if tl.type == "type_list" else [tl])]
    for c in n.named_children:  # interface `extends A, B`
        if c.type == "extends_interfaces":
            td.supers += [txt(t) for tl in c.named_children for t in tl.named_children]
    td.supers = [base_type(s) for s in td.supers]
    ix.types[fqn] = td
    ix.by_simple.setdefault(name, []).append(fqn)
    u.types.append(td)
    body = n.child_by_field_name("body")
    if body is None:
        return
    members = list(body.named_children)
    for c in list(members):
        if c.type == "enum_body_declarations":
            members += c.named_children
    for c in members:
        if c.type in TYPE_DECLS:
            _declare_type(ix, u, c, fqn)
        elif c.type in ("field_declaration", "constant_declaration"):
            ftype = txt(c.child_by_field_name("type"))
            mods = txt(next((x for x in c.children if x.type == "modifiers"), None))
            for d in c.children_by_field_name("declarator"):
                fname = txt(d.child_by_field_name("name"))
                td.fields[fname] = ftype
                val = d.child_by_field_name("value")
                is_const = ("static" in mods and "final" in mods) or kind == "interface"
                if is_const and val is not None and val.type == "string_literal":
                    ix.constants[f"{fqn}.{fname}"] = txt(val)[1:-1]
        elif c.type == "enum_constant":
            td.fields[txt(c.child_by_field_name("name"))] = name
        elif c.type in ("method_declaration", "constructor_declaration"):
            mname = txt(c.child_by_field_name("name")) if c.type == "method_declaration" else "<init>"
            params = []
            ps = c.child_by_field_name("parameters")
            for p in (ps.named_children if ps else []):
                if p.type in ("formal_parameter", "spread_parameter"):
                    pt = p.child_by_field_name("type") or next((x for x in p.named_children if "type" in x.type), None)
                    pn = p.child_by_field_name("name") or (p.named_children[-1] if p.named_children else None)
                    if p.type == "spread_parameter":
                        pn = next((x.child_by_field_name("name") for x in p.named_children if x.type == "variable_declarator"), pn)
                    params.append((txt(pt), txt(pn)))
            body_n = c.child_by_field_name("body")
            m = Method(f"{fqn}#{mname}/{len(params)}", fqn, mname, len(params),
                       txt(c.child_by_field_name("type")), params,
                       c.start_point[0] + 1, c.end_point[0] + 1, body_n,
                       is_abstract=body_n is None,
                       varargs=any(p.type == "spread_parameter" for p in (ps.named_children if ps else [])))
            td.methods.setdefault(mname, []).append(m)


# ------------------------------------------------------------------ type resolution

def resolve_type(ix: Index, u: Unit, raw: str, ctx: TypeDecl | None = None) -> str | None:
    t = base_type(raw)
    if not t or t[0].islower() and "." not in t:
        return None  # primitive / var
    if t in ix.types:
        return t
    head, _, rest = t.partition(".")
    if ctx is not None:  # nested types of current class and its outers
        c = ctx.fqn
        while c:
            if f"{c}.{head}" in ix.types:
                return f"{c}.{head}" + (f".{rest}" if rest else "")
            c = c.rpartition(".")[0] if c.rpartition(".")[0] in ix.types else ""
    if head in u.imports:
        q = u.imports[head] + (f".{rest}" if rest else "")
        return q if q in ix.types else f"ext:{q}"
    if f"{u.pkg}.{head}" in ix.types:
        return f"{u.pkg}.{head}" + (f".{rest}" if rest else "")
    for w in u.wildcards:
        if f"{w}.{head}" in ix.types:
            return f"{w}.{head}" + (f".{rest}" if rest else "")
    if head in JAVA_LANG:
        return f"ext:java.lang.{t}"
    return f"ext:{t}"


def supertypes(ix: Index, fqn: str) -> list[str]:
    """fqn plus all indexed ancestors, nearest first."""
    out, todo = [], [fqn]
    while todo:
        c = todo.pop(0)
        if c in out or c not in ix.types:
            continue
        out.append(c)
        td = ix.types[c]
        todo += [r for r in (resolve_type(ix, td.unit, s, td) for s in td.supers) if r and not r.startswith("ext:")]
    return out


def find_method(ix: Index, cls: str, name: str, arity: int) -> Method | None:
    for c in supertypes(ix, cls):
        ms = ix.types[c].methods.get(name, [])
        exact = [m for m in ms if m.arity == arity]
        if exact:
            return exact[0]
        varargs = [m for m in ms if m.varargs and arity >= m.arity - 1]
        if varargs:
            return varargs[0]
    return None


OBJECT_METHODS = {"getClass", "toString", "equals", "hashCode", "name", "ordinal", "compareTo", "values",
                  "valueOf", "clone", "finalize", "wait", "notify", "notifyAll", "getMessage", "getCause",
                  "printStackTrace", "getKey", "getLocalizedMessage", "getStackTrace", "initCause"}
ELEMENT_METHODS = {"get", "next", "remove", "poll", "peek", "pop", "first", "last", "getFirst", "getLast",
                   "previous", "elementAt", "firstElement", "lastElement", "nextElement"}


def has_external_ancestor(ix: Index, cls: str) -> bool:
    for c in supertypes(ix, cls):
        td = ix.types[c]
        if td.kind == "enum" or any((resolve_type(ix, td.unit, s, td) or "").startswith("ext:") for s in td.supers):
            return True
    return False


def find_field(ix: Index, cls: str, name: str) -> tuple[str, TypeDecl] | None:
    for c in supertypes(ix, cls):
        td = ix.types[c]
        if name in td.fields:
            return td.fields[name], td
    return None


# ------------------------------------------------------------------ pass 2

class _Scope:
    def __init__(self, ix: Index, td: TypeDecl, m: Method):
        self.ix, self.td, self.m, self.u = ix, td, m, td.unit
        self.locals: dict[str, str] = {n: t for t, n in m.params}
        if m.node is not None:
            self._collect(m.node)

    def _collect(self, n: Node):
        if n.type in ("local_variable_declaration",):
            t = txt(n.child_by_field_name("type"))
            for d in n.children_by_field_name("declarator"):
                self.locals[txt(d.child_by_field_name("name"))] = t
        elif n.type == "enhanced_for_statement":
            self.locals[txt(n.child_by_field_name("name"))] = txt(n.child_by_field_name("type"))
        elif n.type == "catch_formal_parameter":
            nm = n.child_by_field_name("name")
            ct = next((x for x in n.named_children if x.type == "catch_type"), None)
            if nm is not None and ct is not None:
                self.locals[txt(nm)] = txt(ct).split("|")[0].strip()
        for c in n.named_children:
            self._collect(c)

    def rt(self, raw: str, owner: TypeDecl | None = None) -> str | None:
        owner = owner or self.td
        return resolve_type(self.ix, owner.unit, raw, owner)

    def etype(self, n: Node | None) -> str | None:
        """Static type (fqn or 'ext:...') of an expression; 'static:' prefix for class refs."""
        if n is None:
            return None
        t = n.type
        if t == "this":
            return self.td.fqn
        if t == "super":
            sup = [r for r in (self.rt(s) for s in self.td.supers) if r]
            return sup[0] if sup else None
        if t == "string_literal":
            return "ext:java.lang.String"
        if t in ("parenthesized_expression",):
            return self.etype(n.named_children[0]) if n.named_children else None
        if t == "cast_expression":
            return self.rt(txt(n.child_by_field_name("type")))
        if t == "object_creation_expression":
            return self.rt(txt(n.child_by_field_name("type")))
        if t == "identifier":
            name = txt(n)
            if name in self.locals:
                return self.rt(self.locals[name])
            f = find_field(self.ix, self.td.fqn, name)
            if f:
                return self.rt(f[0], f[1])
            # outer class fields (inner classes)
            outer = self.td.fqn.rpartition(".")[0]
            while outer in self.ix.types:
                f = find_field(self.ix, outer, name)
                if f:
                    return self.rt(f[0], f[1])
                outer = outer.rpartition(".")[0]
            r = self.rt(name)
            if r and name[:1].isupper():
                return "static:" + r
            return None
        if t in ("scoped_identifier", "type_identifier", "scoped_type_identifier"):
            r = self.rt(txt(n))
            return "static:" + r if r else None
        if t == "field_access":
            obj = self.etype(n.child_by_field_name("object"))
            fname = txt(n.child_by_field_name("field"))
            if obj is None:
                r = self.rt(txt(n))  # maybe a qualified class name
                return "static:" + r if r and not r.startswith("ext:") else None
            cls = obj.removeprefix("static:")
            if cls.startswith("ext:"):
                return None
            f = find_field(self.ix, cls, fname)
            if f:
                return self.rt(f[0], f[1])
            if f"{cls}.{fname}" in self.ix.types:
                return "static:" + f"{cls}.{fname}"
            return None
        if t == "method_invocation":
            m = self.resolve_call(n, record=False)
            if m is not None and m.ret:
                owner = self.ix.types[m.cls]
                return self.rt(m.ret, owner)
            return self.element_type(n)
        if t == "array_access":
            return self.etype(n.child_by_field_name("array"))
        return None

    def raw_of(self, n: Node) -> tuple[str, TypeDecl] | None:
        """Declared (generic) type text of an identifier/field, for element-type inference."""
        if n.type == "identifier":
            if txt(n) in self.locals:
                return self.locals[txt(n)], self.td
            return find_field(self.ix, self.td.fqn, txt(n))
        if n.type == "field_access" and txt(n.child_by_field_name("object")) == "this":
            return find_field(self.ix, self.td.fqn, txt(n.child_by_field_name("field")))
        if n.type == "method_invocation":
            m = self.resolve_call(n, record=False)
            if m is not None and m.ret:
                return m.ret, self.ix.types[m.cls]
        return None

    def element_type(self, n: Node) -> str | None:
        """`list.get(i)`, `it.next()`, `map.get(k)` on a generic external container -> element type."""
        name = txt(n.child_by_field_name("name"))
        obj = n.child_by_field_name("object")
        if obj is None or name not in ELEMENT_METHODS:
            return None
        inner = obj
        if obj.type == "method_invocation" and txt(obj.child_by_field_name("name")) in ("iterator", "listIterator", "values", "keySet"):
            inner = obj.child_by_field_name("object")
            if inner is None:
                return None
        raw = self.raw_of(inner)
        if raw is None:
            return None
        targs = type_args(raw[0])
        if not targs:
            return None
        pick = targs[-1] if "Map" in base_type(raw[0]) else targs[0]
        return resolve_type(self.ix, raw[1].unit, pick, raw[1])

    def resolve_call(self, n: Node, record: bool = True) -> Method | None:
        name = txt(n.child_by_field_name("name"))
        args = n.child_by_field_name("arguments")
        arity = len(args.named_children) if args is not None else 0
        obj = n.child_by_field_name("object")
        if obj is None:
            target = self.td.fqn
            m = find_method(self.ix, target, name, arity)
            outer = target.rpartition(".")[0]
            while m is None and outer in self.ix.types:  # call to enclosing class method
                m = find_method(self.ix, outer, name, arity)
                outer = outer.rpartition(".")[0]
            for si in (self.u.static_imports if m is None else []):
                if si in self.ix.types:
                    m = find_method(self.ix, si, name, arity)
                    if m:
                        break
            if m is None and (self.u.static_imports or has_external_ancestor(self.ix, target)
                              or name in OBJECT_METHODS):
                if record:
                    self.ix.stats["external"] += 1
                return None
        else:
            et = self.etype(obj)
            if et is None:
                if record:
                    self.ix.stats["unresolved"] += 1
                return None
            target = et.removeprefix("static:")
            if target.startswith("ext:"):
                if record:
                    self.ix.stats["external"] += 1
                return None
            m = find_method(self.ix, target, name, arity)
            if m is None and (name in OBJECT_METHODS or has_external_ancestor(self.ix, target)):
                if record:
                    self.ix.stats["external"] += 1
                return None
        if record:
            self.ix.stats["resolved" if m else "unresolved"] += 1
        return m


def _resolve_const(sc: _Scope, n: Node) -> str | None:
    """String value of a literal / constant reference / enum-name-ish expression."""
    if n.type == "string_literal":
        return txt(n)[1:-1]
    if n.type == "identifier":
        for c in supertypes(sc.ix, sc.td.fqn):
            v = sc.ix.constants.get(f"{c}.{txt(n)}")
            if v is not None:
                return v
        return None
    if n.type == "field_access":
        obj = sc.etype(n.child_by_field_name("object"))
        fname = txt(n.child_by_field_name("field"))
        if obj and not obj.removeprefix("static:").startswith("ext:"):
            for c in supertypes(sc.ix, obj.removeprefix("static:")):
                v = sc.ix.constants.get(f"{c}.{fname}")
                if v is not None:
                    return v
        return None
    if n.type == "method_invocation":  # ActionForwards.load_success.toString()
        if txt(n.child_by_field_name("name")) in ("toString", "name"):
            o = n.child_by_field_name("object")
            if o is not None and o.type == "field_access":
                return txt(o.child_by_field_name("field"))
    return None


def _first_throw(n: Node | None) -> Node | None:
    if n is None:
        return None
    if n.type == "throw_statement":
        return n
    if n.type == "block":
        for c in n.named_children:
            if c.type == "throw_statement":
                return c
            if c.type not in ("expression_statement", "local_variable_declaration", "line_comment", "block_comment"):
                return None
    return None


def resolve_bodies(ix: Index) -> None:
    for td in list(ix.types.values()):
        for ms in td.methods.values():
            for m in ms:
                if m.node is not None:
                    _walk_body(ix, _Scope(ix, td, m), m.node, [])


SAVE_NAMES = {"save", "saveOrUpdate", "update", "delete", "createOrUpdate", "persist", "merge"}


def _walk_body(ix: Index, sc: _Scope, n: Node, conds: list[str]) -> None:
    t = n.type
    line = n.start_point[0] + 1
    if t == "method_invocation":
        m = sc.resolve_call(n)
        name = txt(n.child_by_field_name("name"))
        args = n.child_by_field_name("arguments")
        argl = list(args.named_children) if args is not None else []
        if m is not None:
            ix.calls.append((sc.m.id, m.id, line))
        # named queries: first string-ish arg of *NamedQuery* / getNamedQuery
        if "NamedQuery" in name and argl:
            q = _resolve_const(sc, argl[0])
            if q:
                ix.uses_query.append((sc.m.id, q, line))
        if name in SAVE_NAMES and len(argl) == 1:
            et = sc.etype(argl[0])
            if et and not et.startswith(("ext:", "static:")):
                ix.saves.append((sc.m.id, et, line))
        if name == "findForward" and argl:
            f = _resolve_const(sc, argl[0])
            if f:
                ix.forwards.append((sc.m.id, f))
        if name in ERROR_CALLS and conds and argl:
            keys = [k for k in (_resolve_const(sc, a) for a in argl) if k]
            inner = [a for a in argl if a.type == "object_creation_expression"]
            for a in inner:
                ia = a.child_by_field_name("arguments")
                if ia is not None and ia.named_children:
                    k = _resolve_const(sc, ia.named_children[0])
                    if k:
                        keys.insert(0, k)
            if keys and ("error" in txt(n.child_by_field_name("object")).lower() or name != "add"):
                ix.rules.append(Rule(sc.m.id, sc.td.file, line, "validation", " && ".join(conds),
                                     _short(txt(n)), keys[0]))
    elif t == "object_creation_expression":
        r = sc.rt(txt(n.child_by_field_name("type")))
        if r and not r.startswith("ext:"):
            ix.news.append((sc.m.id, r, line))
            args = n.child_by_field_name("arguments")
            ctor = find_method(ix, r, "<init>", len(args.named_children) if args else 0)
            if ctor:
                ix.calls.append((sc.m.id, ctor.id, line))
    elif t == "if_statement":
        cond = " ".join(txt(n.child_by_field_name("condition")).split())
        thr = _first_throw(n.child_by_field_name("consequence"))
        if thr is not None:
            ix.rules.append(_guard(sc, cond, thr))
        for c in n.named_children:
            if c == n.child_by_field_name("consequence"):
                _walk_body(ix, sc, c, conds + [cond])
            elif c == n.child_by_field_name("alternative"):
                _walk_body(ix, sc, c, conds + [f"!{cond}"])
            else:
                _walk_body(ix, sc, c, conds)
        return
    for c in n.named_children:
        _walk_body(ix, sc, c, conds)


def _short(s: str, n: int = 200) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _guard(sc: _Scope, cond: str, thr: Node) -> Rule:
    exc = next((c for c in thr.named_children), None)
    key = None
    outcome = _short(txt(thr).removeprefix("throw ").rstrip(";"))
    if exc is not None and exc.type == "object_creation_expression":
        args = exc.child_by_field_name("arguments")
        for a in (args.named_children if args is not None else []):
            key = _resolve_const(sc, a)
            if key:
                break
    return Rule(sc.m.id, sc.td.file, thr.start_point[0] + 1, "guard", _short(cond, 300), outcome, key)


def index_java(roots: list[Path], base: Path) -> Index:
    ix = Index()
    files = sorted(p for r in roots for p in r.rglob("*.java"))
    for p in files:
        declare(ix, p, str(p.relative_to(base)))
    resolve_bodies(ix)
    return ix
