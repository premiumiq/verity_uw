# Architectural Decisions Log

## AD-001: Verity as pip-installable Python package (2026-04-04)
**Decision:** Structure Verity as a distributable package with `pyproject.toml`, supporting 4 deployment modes: SDK, API service, web app, embedded.
**Rationale:** Long-term goal is `pip install verity` for any consuming application. Package-first design forces clean separation.

## AD-002: No ORM — raw SQL with Pydantic (2026-04-04)
**Decision:** Use psycopg 3 with raw SQL queries in `.sql` files. Pydantic for data validation.
**Rationale:** User is a data/analytics expert. ORMs are opaque and hard to debug. SQL is transparent, copy-pasteable to psql, and universally understood.

## AD-003: Full 7-state lifecycle in schema from day one (2026-04-04)
**Decision:** Include all 7 lifecycle states (draft, candidate, staging, shadow, challenger, champion, deprecated) in the initial schema.
**Rationale:** The 7-state model is the SR 11-7 compliance story for CIO demos. Schema migrations under live demo conditions are risky. Build it right the first time.

## AD-004: pgvector columns present but nullable (2026-04-04)
**Decision:** `CREATE EXTENSION vector;` and `vector(1536)` columns on agent, task, tool, prompt_version tables in initial schema. NULLable — populated when embedding compute is implemented.
**Rationale:** Schema additions are cheap; schema alterations after seeding are painful.

## AD-005: MinIO in App 1 (2026-04-04)
**Decision:** Include MinIO in docker-compose from App 1. Seed with synthetic documents.
**Rationale:** The document ingestion story ("this ACORD 855 PDF was pulled from MinIO, classified, and extracted") is materially more impressive for CIO demos than text fixtures.

## AD-006: Built-in web UI, ServiceNow later (2026-04-04)
**Decision:** Jinja2 + HTMX + DaisyUI for both Verity admin and business workflow UI. ServiceNow integration deferred to App 2.
**Rationale:** User is not a web developer. Built-in UI has zero external dependencies. ServiceNow PDI available but requires in-browser development for widgets/flows.

## AD-007: 2+2 entities for App 1 demo (2026-04-04)
**Decision:** 2 tasks (document_classifier, field_extractor) + 2 agents (triage_agent, appetite_agent) for initial demo.
**Rationale:** Sufficient to demonstrate every Verity feature. Remaining entities added in App 2 with more business logic.

## AD-008: Project docs in repo, not user home (2026-04-04)
**Decision:** All architectural decisions, plans, and context stored in `docs/` and `CLAUDE.md` inside the project folder.
**Rationale:** User wants decisions version-controlled with the codebase.

## AD-009: Version temporal management — SCD Type 2 with sentinel date (2026-04-05)
**Decision:** Version validity uses `valid_from` and `valid_to` timestamps with SCD Type 2 semantics. Active champions get `valid_to = '2999-12-31 23:59:59'` (sentinel) instead of NULL.
**Rationale:** Eliminates NULL checks in all date-based queries. The comparison `valid_from <= effective_date AND valid_to > effective_date` is clean and simple. No ambiguity about what NULL means.

**Lifecycle behavior:**

| Event | valid_from | valid_to |
|---|---|---|
| Version created (draft) | NULL | NULL |
| Promoted through candidate/staging/shadow/challenger | NULL | NULL |
| **Promoted to champion** | **NOW()** | **2999-12-31 23:59:59** |
| **Deprecated (superseded by new champion)** | unchanged | **NOW()** |

**Entities covered:** agent_version, task_version, prompt_version, pipeline_version.

**Key rules:**
- Only champion (and formerly-champion, now deprecated) versions have valid_from/valid_to set
- Pre-champion versions (draft through challenger) have NULL dates — they were never in production, so they're not date-resolvable
- At any point in time, exactly ONE champion version satisfies `valid_from <= date AND valid_to > date`
- The lifecycle `promote()` function enforces this automatically

## AD-010: Version composition immutability (2026-04-05)
**Decision:** An agent/task version is a frozen snapshot of its composition: prompts, inference config, tool authorizations, thresholds. Once promoted beyond `draft`, these bindings are immutable. Any change requires a new version.
**Rationale:** Regulatory audit reproducibility (SR 11-7) requires that the validated model is the model that runs in production. If prompt assignments can change after validation, the audit trail breaks. See FC-12 in future_capabilities.md for enforcement design.
