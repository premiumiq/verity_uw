# Verity Planes

> **Tooltip:** The four logical layers of Verity: Governance (registry, lifecycle, audit), Runtime (execution, connectors, MCP), Agents (future automation), Studio (future UI authoring).

## Definition

The conceptual organization of Verity into four planes, each with a distinct responsibility:

1. **Governance (shipped)** — registry, lifecycle, decision reader, compliance, model management, quotas, admin UI / API / SDK
2. **Runtime (shipped)** — execution engine, source binder, write target dispatcher, connector layer, MCP client, tool authorization, async worker, decision writer
3. **Agents (future)** — drift detection, lifecycle initiation, validation-with-HITL, themselves Verity-governed
4. **Studio (future, not yet designed)** — UI-driven Compose AI, Lifecycle Management, Ground Truth Management, Test Management for non-developer users; a thick frontend over the existing REST API

> Historical note: this glossary file used to be named `three-planes.md` (when only the first three were planned). Studio was introduced 2026-04-25. The slug is now `verity-planes`.

## See also

- [Asset Registry](asset-registry.md)
- [Lifecycle State](lifecycle-state.md)
- [Decision Log](decision-log.md)

## Source

[`docs/vision.md`](../vision.md) § *Governance, Runtime, Agents, and Studio*
