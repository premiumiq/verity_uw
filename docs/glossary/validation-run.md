# Validation Run

> **Tooltip:** Execution of an entity version against every record in a ground-truth dataset; computes aggregate metrics, gates staging→shadow.

## Definition

A scored execution of one entity version against every record in a ground-truth dataset. Stores per-record results in `validation_record_result` and aggregate metrics on the `validation_run` row. Used as a promotion gate (`staging → shadow` and again at `challenger → champion`).

## See also

- [Ground Truth Dataset](ground-truth-dataset.md)
- [Metric Threshold](metric-threshold.md)
- [Lifecycle State](lifecycle-state.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
