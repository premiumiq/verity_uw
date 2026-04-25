# Application

> **Tooltip:** Consuming business app registered with Verity; every entity and decision is scoped/attributed to one or more applications.

## Definition

A row in the `application` table representing one consuming business app (e.g. `uw_demo`). Every governed entity is mapped to one or more applications via `application_entity` (many-to-many). Every decision_log row carries the `application` tag for spend attribution and per-tenant filtering.

## See also

- [Execution Context](execution-context.md)

## Source

_(no single canonical source — consult [architecture/](../architecture/))_
