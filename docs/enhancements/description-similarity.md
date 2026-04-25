# Description Similarity Check (pgvector Embeddings)

> **Status:** partial — `description_similarity_log` table + `vector(1536)` columns exist; embedding population and gate enforcement not wired
> **Source:** [vision.md § Lifecycle Framework](../vision.md), schema `description_similarity_log` table
> **Priority:** medium (improves authoring UX; not blocking demo)

## What's missing today

The lifecycle gate `candidate → staging` is supposed to require a "description similarity check passed" — verifying that the new entity's description isn't a near-duplicate of an existing entity (which usually indicates the author should have created a new version of the existing entity instead of a new entity).

Today:

- `description_similarity_log` table exists but is empty
- `agent.description_embedding`, `task.description_embedding`, `prompt.description_embedding` are `vector(1536)` nullable columns — never populated
- The promotion gate in `lifecycle.py` accepts the candidate without checking
- No embedding service is wired

## Proposed approach

### Embedding population

On every entity create / description edit:

1. Call an embedding service (OpenAI text-embedding-3-small, or Anthropic if/when available)
2. Store the resulting vector in `description_embedding`
3. Background job back-fills existing rows once on first deploy

Embedding model choice belongs in `inference_config` so it's governed and changeable.

### Similarity check at gate

In `lifecycle.promote(candidate → staging)`:

1. Compute cosine similarity between this entity's `description_embedding` and every other same-type entity in the same application
2. Top-N results (default N=3) above a threshold (default 0.85) are surfaced to the approver
3. Approver either confirms "yes I know, this is genuinely new" (logged as override) or aborts and re-uses an existing entity
4. The check decision and top similar entities are recorded in `description_similarity_log`

Threshold is per-materiality-tier in the long run; one global threshold is fine for v1.

### Authoring UI

Show the top-3 similar entities as live suggestions in the create-entity form, before the user commits. Cheap UX win, prevents most duplicates upstream of the gate.

## Acceptance criteria

- Embedding service is a registered `data_connector` (so the choice is governed)
- All existing entities have populated `description_embedding`
- `lifecycle.promote` consults similarity and records a `description_similarity_log` row on every candidate→staging transition
- Authoring UI shows live suggestions with similarity scores

## Notes

The `vector(1536)` width was chosen to match OpenAI text-embedding-3-small. Anthropic's future embedding model may use a different width — schema migration will need to handle that, or we choose a model-agnostic width via padding/projection.
