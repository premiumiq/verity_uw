# Override Log

> **Tooltip:** Separate immutable record of a human disagreeing with an AI decision; preserves both AI recommendation and human decision.

## Definition

A row in `override_log` capturing one human override of an AI decision: the original decision_id, the AI recommendation, the human decision, the reason code and rationale, and the overrider's name and role. The original decision row is never modified.

## See also

- [Decision Log](decision-log.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
