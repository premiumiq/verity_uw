# Sub-Agent Delegation

> **Tooltip:** Built-in delegate_to_agent meta-tool; parent → child relationships authorized via agent_version_delegation.

## Definition

A first-class capability where a parent Agent invokes a child Agent through the built-in `delegate_to_agent` meta-tool. Authorization is checked against `agent_version_delegation`. The child agent's `parent_decision_id` and `decision_depth` are set automatically by the runtime; the parent's audit row references the child decision.

## See also

- [Agent](agent.md)
- [Parent Decision](parent-decision.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
