# Materiality Tier

> **Tooltip:** Per-entity risk tier (low/medium/high) that drives lifecycle gate strictness and validation thresholds.

## Definition

An enum field on every Agent and Task entity row indicating the operational risk of decisions made by that entity. Low = cosmetic / advisory; medium = routing / scoring; high = customer-facing decisions or money. Drives the strictness of lifecycle gates and the default thresholds in metric_threshold rows.

## See also

- [Lifecycle State](lifecycle-state.md)
- [Metric Threshold](metric-threshold.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
