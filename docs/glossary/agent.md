# Agent

> **Tooltip:** Multi-turn agentic loop with tool use and (optionally) sub-agent delegation. Authorized tools per version.

## Definition

One of two execution units in Verity. Multi-turn: assembles prompt, calls Claude in a loop until a terminal turn, dispatching tool calls (in-process Python or MCP-served) and optionally delegating to sub-agents. By default emits free-form text; with `enforce_output_schema=True` the runtime guarantees structured output via a synthetic `submit_output` tool.

## See also

- [Task](task.md)
- [Tool Authorization](tool-authorization.md)
- [Sub-Agent Delegation](sub-agent-delegation.md)
- [Enforce Output Schema](enforce-output-schema.md)

## Source

[`verity/src/verity/runtime/engine.py`](../../verity/src/verity/runtime/engine.py)
