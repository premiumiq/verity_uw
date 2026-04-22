"""DuckDuckGo web search MCP server.

Exposes one tool — `web_search(query, max_results)` — over MCP stdio.
Uses the `ddgs` Python package (successor to `duckduckgo-search`) which
hits DuckDuckGo's HTML search endpoint directly. No API key, no account.

Launch standalone:
    python -m mcp_servers.duckduckgo.server

Launch via Verity (the expected path):
    1. Register the server in verity_db.mcp_server with
         transport='stdio', command='python',
         args=['-m', 'mcp_servers.duckduckgo.server']
    2. Register one or more tool rows with transport='mcp_stdio' and
       mcp_server_name matching the mcp_server row.
    3. Authorize the tools for an agent.
    Verity's runtime lazy-spawns the server on first tool call and
    terminates it on Verity.close().
"""
