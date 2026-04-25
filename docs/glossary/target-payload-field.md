# Target Payload Field

> **Tooltip:** One row per output field per write_target; uses reference grammar to map LLM output fields to a connector payload.

## Definition

A row in the `target_payload_field` table, weakly owned by a write_target row, describing one field of the payload to be assembled. Each row pairs a target field path with a reference (typically `output.<field>`).

## See also

- [Write Target](write-target.md)
- [Reference Grammar](reference-grammar.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
