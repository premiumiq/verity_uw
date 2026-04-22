"""DuckDuckGo web search MCP server — stdio transport.

Exposes a single tool:
    web_search(query: str, max_results: int = 5) -> text

Returns a numbered, plain-text list of results (title, URL, snippet).
Intentionally text-only output: keeps the MCP result shape simple and
makes the output easy to include in a Claude prompt without extra
parsing. If richer structure is needed later, return additional
TextContent blocks or add fields to the schema.

No API key required. DuckDuckGo's search endpoint may rate-limit
aggressive use; the server surfaces errors as error-flagged MCP results
rather than crashing so Claude sees the error and can decide whether
to retry with a narrower query.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ddgs import DDGS
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

logger = logging.getLogger("mcp.duckduckgo")


# ── SERVER INSTANCE ─────────────────────────────────────────────
# One Server per process. Tool handlers register via decorators.

server: Server = Server(
    name="duckduckgo",
    version="0.1.0",
    instructions=(
        "Web search via DuckDuckGo. Use for current events, public records, "
        "regulatory filings, news about companies or people, and anything "
        "not already in the agent's context."
    ),
)


# ── TOOL: web_search ────────────────────────────────────────────

WEB_SEARCH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search query. Natural-language phrases work.",
        },
        "max_results": {
            "type": "integer",
            "description": "How many results to return (1-20). Default 5.",
            "default": 5,
            "minimum": 1,
            "maximum": 20,
        },
    },
    "required": ["query"],
}


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise the single web_search tool this server exposes."""
    return [
        Tool(
            name="web_search",
            description=(
                "Search the web via DuckDuckGo and return up to max_results "
                "text results (title, URL, snippet). No authentication; "
                "uses DuckDuckGo's free search endpoint."
            ),
            inputSchema=WEB_SEARCH_INPUT_SCHEMA,
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a tool call. Only `web_search` is supported."""
    if name != "web_search":
        return [
            TextContent(
                type="text",
                text=f"Unknown tool: {name!r}. This server only exposes web_search.",
            )
        ]

    query = (arguments or {}).get("query", "").strip()
    if not query:
        return [TextContent(type="text", text="Error: query is required and must be non-empty.")]

    max_results = int((arguments or {}).get("max_results", 5))
    max_results = max(1, min(max_results, 20))

    try:
        # DDGS().text() is synchronous — run in a thread so we don't
        # block the MCP server's asyncio loop on network I/O.
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=max_results))
        )
    except Exception as e:
        logger.exception("DDG search failed for query=%r", query)
        return [TextContent(type="text", text=f"Search failed: {type(e).__name__}: {e}")]

    if not results:
        return [TextContent(type="text", text=f"No results for: {query}")]

    # Format as a numbered list — readable by both humans and Claude.
    lines: list[str] = [f"Results for {query!r} ({len(results)} found):"]
    for i, r in enumerate(results, start=1):
        title = r.get("title", "(no title)")
        href = r.get("href", "")
        body = r.get("body", "")
        lines.append(f"\n{i}. {title}\n   {href}\n   {body}")
    return [TextContent(type="text", text="\n".join(lines))]


# ── STDIO ENTRY POINT ───────────────────────────────────────────

async def _main() -> None:
    """Run the server over stdin/stdout for MCP stdio transport."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
