# Tool Authorization

> **Tooltip:** Per-agent-version `agent_version_tool` row authorizing one tool. Unauthorized tool calls are rejected and Claude is informed.

## Definition

A row in `agent_version_tool` declaring that a specific agent version may call a specific tool. Unauthorized tool calls during the agent loop are rejected and surfaced back to Claude as an error so the agent can correct itself; the rejection is logged in `tool_calls_made` with status `rejected`.

## See also

- [Tool](tool.md)
- [Agent](agent.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
