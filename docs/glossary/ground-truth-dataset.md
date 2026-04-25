# Ground Truth Dataset

> **Tooltip:** SME-labeled data scoped to one governed entity. Three tables: dataset (metadata), record (input items), annotation (labels).

## Definition

A versioned, multi-annotator labeled dataset scoped to one Governed Entity. Three-table design: `ground_truth_dataset` (metadata, IAA metrics), `ground_truth_record` (input items), `ground_truth_annotation` (one annotator's answer per record, `is_authoritative` flag picks the canonical label).

## See also

- [Validation Run](validation-run.md)
- [Metric Threshold](metric-threshold.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
