# Data Connector

> **Tooltip:** Registered integration providing fetch/write methods used by source_bindings and write_targets. Vault is the canonical example.

## Definition

A row in the `data_connector` table representing one external integration (e.g. `vault`). The DB row stores the name and non-secret tuning config; the Python provider implementation is registered separately by the consuming app via `register_connector_provider`. Connectors are orthogonal to MCP servers — connectors carry data I/O around the LLM call, MCP servers carry tool calls during the loop.

## See also

- [Source Binding](source-binding.md)
- [Write Target](write-target.md)
- [Vault](vault.md)
- [MCP Server](mcp-server.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
