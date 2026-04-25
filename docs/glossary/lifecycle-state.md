# Lifecycle State

> **Tooltip:** Seven states an entity version moves through: draft → candidate → staging → shadow → challenger → champion → deprecated.

## Definition

An enum on every entity version row. The state machine: draft → candidate → staging → shadow → challenger → champion → deprecated. Promotion gates require evidence (similarity check, tests passed, validation results, model card review); each gate writes an `approval_record` capturing the approver and rationale.

## See also

- [Approval Record](approval-record.md)
- [Champion Resolution](champion-resolution.md)

## Source

[`verity/src/verity/governance/lifecycle.py`](../../verity/src/verity/governance/lifecycle.py)
