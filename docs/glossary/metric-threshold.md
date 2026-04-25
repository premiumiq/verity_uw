# Metric Threshold

> **Tooltip:** Configured pass/fail thresholds for validation run metrics; per-entity, per-materiality-tier.

## Definition

A row in `metric_threshold` configuring the pass/fail bar for a validation run metric on a specific entity. Defaults derived from materiality_tier; can be overridden per entity. Failed thresholds block lifecycle promotion through validation gates.

## See also

- [Validation Run](validation-run.md)
- [Materiality Tier](materiality-tier.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
