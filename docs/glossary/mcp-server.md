# MCP Server

> **Tooltip:** Registered MCP server endpoint used as a transport for tools whose transport='mcp_*'.

## Definition

A row in the `mcp_server` table registering one Model Context Protocol server (stdio subprocess or remote endpoint) that Verity can dispatch tool calls to. The `tool` table references it via `mcp_server_name` for tools whose transport is one of the `mcp_*` variants. MCP is a tool transport — distinct from data_connector, which carries declarative data I/O.

## See also

- [Tool](tool.md)
- [Data Connector](data-connector.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
