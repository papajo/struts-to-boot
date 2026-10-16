"""MCP server: agents query the legacy code map before changing anything.

    mapper serve --db mapper/out/map.db           (stdio; register in your MCP client)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from .anchors import manifest
from .graph import Map

INSTRUCTIONS = """Legacy Code Mapper for a Java/Struts/Hibernate codebase.
Before editing or migrating anything: call `trace` (what an endpoint/method reaches),
`rules` (business rules on that path, with file:line), `impact` (what breaks if a symbol
changes), then `context` for the source pack. Endpoint ids look like `/loanAccountAction.do#get`.
Every result cites file:line; verify with `source` rather than guessing."""


def create(db: Path) -> MCPServer:
    m = Map(db)
    srv = MCPServer("legacy-code-mapper", instructions=INSTRUCTIONS, version="0.1.0")

    @srv.tool()
    def stats() -> dict:
        """Index statistics: files, methods, endpoints, call-resolution rate."""
        return m.meta()

    @srv.tool()
    def search(query: str, kind: str | None = None, limit: int = 25) -> list[dict]:
        """Find symbols by substring. kind: class|interface|enum|method|endpoint|table|query|view."""
        return m.search(query, kind, limit)

    @srv.tool()
    def trace(symbol: str, depth: int = 6) -> dict:
        """What an endpoint or method reaches: methods (file:line), tables (write/query/entity), named queries, views, rules."""
        t = m.trace(symbol, depth=depth)
        t["methods"] = [f"{x['id']}  {x['file']}:{x['line']}  d={x['depth']}" for x in t["methods"]]
        return t

    @srv.tool()
    def rules(symbol: str, depth: int = 6) -> list[dict]:
        """Business rules (guards that throw, validations that add errors) on the path of an endpoint or method."""
        return m.trace(symbol, depth=depth)["rules"]

    @srv.tool()
    def impact(symbol: str) -> dict:
        """Reverse dependencies of a method, class, or `table:<name>`: caller count and affected endpoints."""
        return m.impact(symbol)

    @srv.tool()
    def tables(symbol: str) -> dict:
        """Tables an endpoint or method touches, with access kind."""
        return m.tables_for(symbol)

    @srv.tool()
    def source(symbol: str, context_lines: int = 0) -> dict:
        """Exact source of a method/class with file and line range."""
        return m.source(symbol, context_lines)

    @srv.tool()
    def context(symbol: str, budget_tokens: int = 12000) -> str:
        """Migration source pack: tables, rules, then handler + callee source by depth within a token budget."""
        return m.context(symbol, budget_tokens)["text"]

    @srv.tool()
    def anchors(endpoints: list[str]) -> dict:
        """AnchorMesh anchor-tag manifest (v1) for the given endpoints."""
        return manifest(m, endpoints)

    return srv


def main() -> None:
    create(Path(os.environ.get("MAPPER_DB", "mapper/out/map.db"))).run("stdio")
