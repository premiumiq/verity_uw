# Inference Config

> **Tooltip:** Versioned LLM API parameter set: model, temperature, max_tokens, extended_params. Frozen on entity version promotion.

## Definition

A row in the `inference_config` table representing one named, reusable LLM API parameter set. Pinned to entity versions; frozen at the moment the entity version was promoted (composition immutability). Future per-call retry/backoff config will also live here.

## See also

- [Task](task.md)
- [Agent](agent.md)

## Source

[`verity/src/verity/db/schema.sql`](../../verity/src/verity/db/schema.sql)
