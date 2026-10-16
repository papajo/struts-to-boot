"""mapper index|trace|rules|impact|context|anchors|eval|serve"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DB = Path("mapper/out/map.db")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mapper")
    ap.add_argument("--db", type=Path, default=DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("index", help="build the map from a source tree")
    i.add_argument("src", type=Path)
    for name in ("trace", "rules", "impact", "context", "source"):
        s = sub.add_parser(name)
        s.add_argument("symbol")
        if name == "context":
            s.add_argument("--budget", type=int, default=12000)
    a = sub.add_parser("anchors", help="AnchorMesh manifest")
    a.add_argument("--endpoints", nargs="*", help="default: all")
    a.add_argument("--inventory", type=Path, help="limit to endpoints in an inventory json")
    a.add_argument("-o", type=Path, default=Path("mapper/out/anchor-tag-manifest.json"))
    a.add_argument("--annotate", type=Path, help="also insert // @anchor[...] comments into this source root")
    e = sub.add_parser("eval", help="per-endpoint numbers for an inventory")
    e.add_argument("--inventory", type=Path, default=Path("docs/loan-inventory.json"))
    e.add_argument("-o", type=Path, default=Path("docs/mapper-eval.md"))
    sub.add_parser("serve", help="MCP server over stdio")
    args = ap.parse_args(argv)

    if args.cmd == "index":
        from .index import build
        print(json.dumps(build(args.src, args.db), indent=2))
        return
    if args.cmd == "serve":
        from .server import create
        create(args.db).run("stdio")
        return
    from .graph import Map
    m = Map(args.db)
    if args.cmd == "trace":
        t = m.trace(args.symbol)
        print(f"{t['start']}: {len(t['methods'])} methods, {t['loc']} LOC, {len(t['rules'])} rules")
        for x in t["methods"]:
            print(f"  {'  ' * x['depth']}{x['id']}  {x['file']}:{x['line']}")
        print("tables:", json.dumps(t["tables"]))
        print("views:", t["views"])
    elif args.cmd == "rules":
        for r in m.trace(args.symbol)["rules"]:
            print(f"{r['file']}:{r['line']} [{r['kind']}] if {r['condition']} -> {r['outcome']}"
                  + (f"\n    '{r['message']}'" if r["message"] else ""))
    elif args.cmd == "impact":
        print(json.dumps(m.impact(args.symbol), indent=2))
    elif args.cmd == "source":
        print(m.source(args.symbol)["code"])
    elif args.cmd == "context":
        c = m.context(args.symbol, args.budget)
        print(c["text"])
        print(f"\n-- {c['tokens']} tokens, {c['methods_included']}/{c['methods_reachable']} methods", file=sys.stderr)
    elif args.cmd == "anchors":
        from .anchors import annotate, manifest
        eps = args.endpoints
        if args.inventory:
            inv = json.loads(args.inventory.read_text())
            eps = [f"{x['path']}.do#{mm}" for x in inv for mm in x["methods"]]
        man = manifest(m, eps)
        args.o.parent.mkdir(parents=True, exist_ok=True)
        args.o.write_text(json.dumps(man, indent=2))
        print(f"{len(man['anchors'])} anchors -> {args.o}")
        if args.annotate:
            print(f"{annotate(man, args.annotate)} comments inserted under {args.annotate}")
    elif args.cmd == "eval":
        from .evaluate import evaluate
        print(evaluate(m, args.inventory, args.o))


if __name__ == "__main__":
    main()
