"""In-repo MCP (Model Context Protocol) servers.

Each subdirectory here is a standalone MCP server — its own stdio process
that Verity's runtime spawns when a tool registered with
transport='mcp_stdio' dispatches. Keeping them in-repo (rather than as
external pip packages) makes the demo self-contained: one `pip install -e
verity/[runtime]` pulls the server's dependencies alongside Verity's.

Servers here:
  - duckduckgo  — web search over the free ddgs Python package
"""
