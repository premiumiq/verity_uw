# Run Purpose

> **Tooltip:** Reason for an execution: production / test / validation / audit_rerun. Independent of channel.

## Definition

A column on `agent_decision_log` recording why an execution happened. Independent of channel and mock_mode. Set by the calling surface: REST runtime endpoints set it from request context; the validation runner sets `validation`; audit replay sets `audit_rerun` plus `reproduced_from_decision_id`.

## See also

- [Channel](channel.md)
- [Decision Log](decision-log.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
