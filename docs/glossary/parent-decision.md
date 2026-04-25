# Parent Decision

> **Tooltip:** FK on agent_decision_log linking a sub-agent's decision to its parent; decision_depth records the depth in the delegation tree.

## Definition

A nullable self-reference on `agent_decision_log` (`parent_decision_id`) plus an integer `decision_depth`. Set by the runtime when an Agent invokes a sub-Agent via the `delegate_to_agent` meta-tool. Audit-trail queries reconstruct the tree by following these references.

## See also

- [Sub-Agent Delegation](sub-agent-delegation.md)
- [Decision Log](decision-log.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
