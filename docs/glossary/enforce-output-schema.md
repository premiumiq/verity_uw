# Enforce Output Schema

> **Tooltip:** Per-call agent option that injects a synthetic submit_output tool to structurally guarantee output.

## Definition

An optional flag on `execute_agent` / `run_agent`. When set, the runtime injects a synthetic `submit_output` tool whose input schema is the agent's `output_schema`, and forces `tool_choice` on the terminal turn. Result: the final output is structurally guaranteed to match the schema, at the cost of an extra forced tool call. Off by default — agents emit free-form text and `output` is best-effort-parsed.

## See also

- [Agent](agent.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
