# Tool

> **Tooltip:** Callable action available to an Agent; has a transport (python_inprocess or mcp_*) and is authorized per agent version.

## Definition

A row in the `tool` table representing one callable action. The transport discriminator (`python_inprocess` or one of `mcp_*`) decides how the tool call is dispatched. Tools are authorized per agent version via `agent_version_tool` (or `task_version_tool` for tasks that use tools without LLM-in-the-loop reasoning).

## See also

- [Tool Authorization](tool-authorization.md)
- [MCP Server](mcp-server.md)
- [Agent](agent.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
