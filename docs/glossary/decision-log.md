# Decision Log

> **Tooltip:** One immutable row per AI invocation in agent_decision_log capturing prompts, config, I/O, tool calls, tokens, durations.

## Definition

The non-negotiable side-effect of every Verity-mediated AI invocation. One row in `agent_decision_log` per Task or Agent run, capturing pinned versions, frozen inference config, full I/O, tool calls, message history, token counts, durations, and contextual IDs (workflow_run_id, execution_context_id, parent_decision_id). Immutable after write.

## See also

- [Execution Run](execution-run.md)
- [Parent Decision](parent-decision.md)
- [Override Log](override-log.md)
- [Run Purpose](run-purpose.md)

## Source

[`verity/src/verity/runtime/decisions_writer.py`](../../verity/src/verity/runtime/decisions_writer.py)
