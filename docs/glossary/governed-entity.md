# Governed Entity

> **Tooltip:** Supertype: anything Verity tracks as a versioned record (Agent, Task, Prompt, Tool, Pipeline).

## Definition

An EER supertype encompassing every kind of entity Verity governs. Each subtype has a name row (`agent`, `task`, …) and a versioned-record row (`agent_version`, `task_version`, …). Polymorphic FKs across the schema (entity_type + entity_version_id) point at the supertype rather than fanning out to each subtype.

## See also

- [Asset Registry](asset-registry.md)
- [Lifecycle State](lifecycle-state.md)
- [Champion Resolution](champion-resolution.md)

## Source

[`docs/diagrams/verity_db_conceptual_model.svg`](../../docs/diagrams/verity_db_conceptual_model.svg)
