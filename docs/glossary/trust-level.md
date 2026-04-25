# Trust Level

> **Tooltip:** Entity flag (experimental/supervised/autonomous) hinting at HITL expectations.

## Definition

An enum field on Agent and Task entities indicating the expected human-in-the-loop posture. `experimental` = no production use; `supervised` = HITL recommended on every decision; `autonomous` = HITL only on overrides or edge cases.

## See also

- [Override Log](override-log.md)
- [Approval Record](approval-record.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
