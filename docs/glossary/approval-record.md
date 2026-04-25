# Approval Record

> **Tooltip:** Per-promotion-gate sign-off row: who approved, what evidence reviewed, rationale.

## Definition

A row in `approval_record` written on every entity-version state transition gate. Captures the approver name and role, the gate type, the rationale, and the evidence reviewed (similarity check passed, validation results, model card reviewed, etc.).

## See also

- [Lifecycle State](lifecycle-state.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
