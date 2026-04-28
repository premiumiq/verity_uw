## Compliance Stack — Architecture

**Status:** approved 2026-04-28
**Replaces:** the implicit "evidence packages = N hardcoded reports" approach in [enhancements/regulatory-evidence-packages.md](../enhancements/regulatory-evidence-packages.md)
**Source matrix:** [Verity_Complete_Regulatory_Matrix_v2.md](../../Verity_Complete_Regulatory_Matrix_v2.md) — 47 requirements × 4 frameworks, becomes seed data.

This document is the architectural contract for everything regulatory in Verity. The phased build plan lives in [enhancements/regulatory-evidence-packages.md](../enhancements/regulatory-evidence-packages.md).

---

## Goals

1. **No customer data lock-in.** Verity Analytics data must be incrementally exportable to any customer-owned warehouse (Snowflake, BigQuery, Redshift) so customers blend governance data with their own claims/policy/financial data. Never a full re-load.
2. **Metadata-driven reports.** Adding a new state requirement, or revising one, must not require a new SQL file or a new mart table. The work is one or two INSERTs.
3. **Expandable regulatory metamodel.** A new framework (state bill, NAIC tool revision) plugs in alongside existing ones. Requirements common across frameworks rationalize to a single canonical requirement; provision-to-canonical mapping is many-to-many with weights.
4. **Vector-aware from day one.** Provisions, canonical requirements, features, and mart fields all carry embeddings so future agents can recommend mappings between a new framework's provisions and existing canonical requirements with coverage % and gaps.
5. **Operational hot path untouched.** Layer 1 (the runtime trust DB) does not change. The compliance stack is additive.

---

## The Five Layers

```
┌─ L5  Reports (data, not code) ─────────────────────────────────┐
│  report_definition + report_requirement                        │
│  No hardcoded SQL. Reports = manifests resolved against L3+L2. │
├─ L4  Compliance Semantic Layer (metadata-driven) ──────────────┤
│  canonical_requirement → requirement_evidence_field            │
│  → mart_field. THIS is where adding a state's requirement is   │
│  one INSERT, not one new SQL file.                             │
├─ L3  Compliance Metamodel (expandable, vector-aware) ──────────┤
│  Frameworks/provisions ↔ canonical requirements (bridge, M:N)  │
│  Features (plane→capability→feature, surrogate keyed)          │
│  pgvector on provisions, canonical reqs, features, mart fields │
├─ L2  Compliance Mart (append-only, CDC-shaped) ────────────────┤
│  fact_*  +  dim_*  with (event_ts, ingest_ts, source_lsn)      │
│  Universal — serves all reports, never per-report tables.      │
├─ L1  Operational Trust DB (untouched) ─────────────────────────┘
```

Layers are unidirectional. L1 → L2 via ETL/CDC. L2 is the only thing reports and exports read. L3 and L4 are governance metadata; they reference L2 by name (not by FK to runtime tables). This is what makes the customer-warehouse story work: ship the L2 schema + L3 + L4 to the customer, point report SQL at their warehouse instead of our Postgres, identical results.

---

## L3 — Compliance Metamodel

The metamodel rejects two anti-patterns: (a) flat tables with framework-as-column, and (b) composite codes (`G1`, `G2`) as primary keys.

**All primary keys are surrogate UUIDs.** Identifiers like `G1`, `SR11-7.II.A`, `feature.code` are natural attributes — sortable, displayable, never structural.

### Frameworks side

```
regulatory_framework  (uuid pk)
    code, name, jurisdiction, version, effective_date, source_url
       │
       └── regulatory_provision  (uuid pk)
              framework_id (fk), citation, title, text,
              effective_date, sort_seq,
              embedding vector(384)
```

A framework groups provisions. A provision is the literal text from the regulation, citable. Both versioned.

### Canonical requirements side

```
canonical_requirement_theme  (uuid pk)
    code, name, sort_seq          -- governance, fairness, data_quality, etc.
       │
       └── canonical_requirement  (uuid pk)
              theme_id (fk), code, title, description,
              embedding vector(384)
```

The canonical requirement is the rationalized "thing being required" — for example, "Model inventory & registration" — independent of which framework expresses it. This is what reports and coverage rollups attach to.

### Bridge — provision ↔ canonical (M:N, weighted)

```
provision_requirement_map  (uuid pk)
    provision_id (fk), canonical_requirement_id (fk),
    weight numeric(3,2),               -- 1.00 = full alignment; <1.00 = partial framing match
    confidence numeric(3,2),           -- 1.00 = human-validated; <1.00 = auto-recommended
    mapping_source text,               -- 'manual' | 'semantic_recommended' | 'human_validated'
    validated_by text, validated_at timestamptz, notes text
```

This is where the matrix's many-to-one collapses correctly. "Model inventory & registration" appears in SR 11-7 §I, NAIC §3.1, NAIC Eval Tool Exhibit A — one canonical_requirement, three map rows.

A future agent ingests a new framework's provisions, embeds each, cosine-searches against `canonical_requirement.embedding`, proposes map rows with `mapping_source='semantic_recommended'` and the cosine similarity as `weight`. A reviewer flips them to `human_validated`. Coverage % auto-derives.

### Features side (the G1/G2 fix)

Three levels, each surrogate-keyed:

```
feature_plane         (uuid pk)  code, name, sort_seq
                       │
   feature_capability  (uuid pk)  plane_id (fk), code, name, sort_seq
                       │
   feature             (uuid pk)  capability_id (fk), code, name,
                                  description, status, sort_seq,
                                  embedding vector(384)
```

`G1` becomes a *display label* derived as `capability.code_letter || feature.sort_seq` (or just `feature.code`, which is human-typed). The matrix's "G1–G11 are all Asset Registry under Governance" becomes natural hierarchy.

### Coverage and feature linkage

```
canonical_requirement
       │  M:N
       ├── requirement_feature_link  (canonical_requirement_id, feature_id, role)
       │      role ∈ {'primary', 'supporting'}
       │
       └── requirement_coverage      (one row per canonical_requirement)
              coverage_level enum ('full','substantial','partial','gap'),
              rationale text, customer_actions text,
              last_reviewed_at, reviewed_by
```

Coverage level for a canonical_requirement is editable directly. The `verity_features` array from the v2 matrix becomes rows in `requirement_feature_link`.

---

## L2 — Compliance Mart

Separate Postgres schema `verity_analytics` in the same database (AD-CS-002 below). Star schema. Append-only facts. SCD2 dims.

### Fact tables (append-only, CDC-shaped)

Every fact carries:

| Column | Purpose |
|---|---|
| `surrogate_pk uuid` | mart-local identity |
| `event_ts timestamptz` | when the event happened in the source system |
| `ingest_ts timestamptz` | when the row landed in the mart (the watermark) |
| `source_lsn pg_lsn` | Postgres LSN of the originating WAL record (ordering) |
| `source_pk text` | natural key from L1 (e.g. `decision_log.id`) |

Initial fact tables (Phase 2 slice):

- `fact_decision` — one row per `agent_decision_log`
- `fact_run` — one row per `execution_run` terminal state
- `fact_lifecycle_event` — one row per state transition
- `fact_validation_result` — one row per `test_execution_log`
- `fact_override` — one row per `hitl_override`

Future facts: `fact_approval`, `fact_tool_call`, `fact_source_resolution`, `fact_quota_event`, `fact_incident`.

**Append-only is non-negotiable.** No UPDATE, no DELETE. Corrections are new rows with a `correction_of_pk` reference. This is what makes incremental CDC tractable for any sink.

### Dimensions (SCD Type 2)

```
dim_<entity>  (uuid pk)
    natural_key text,
    <attributes...>,
    valid_from timestamptz,
    valid_to   timestamptz,           -- '2999-12-31 23:59:59' sentinel for current
    is_current boolean,
    scd_hash bytea                    -- hash of tracked attrs for change detection
```

(SCD2 sentinel-date convention reuses [AD-009](decisions.md#ad-009).)

Phase 2 dimensions: `dim_application`, `dim_entity_version`, `dim_user`, `dim_materiality`, `dim_data_classification`, `dim_canonical_requirement`, `dim_regulatory_framework`, `dim_date`.

Facts join dims on `(natural_key, valid_from <= event_ts < valid_to)` for point-in-time correctness. Reports can pin to today's view by filtering `is_current = true`.

### `mart_field` — the registry

```
mart_field  (uuid pk)
    table_name text,            -- 'fact_decision' | 'dim_application' | ...
    column_name text,
    semantic_type text,         -- 'identifier' | 'measure' | 'date' | 'category' | 'text'
    description text,
    is_pii boolean,
    embedding vector(384),
    sort_seq int,
    UNIQUE (table_name, column_name)
```

**Every column reachable from a report must be registered here.** L4 has FKs into `mart_field`; reports referencing an unregistered column fail at validation time, not run time. This is the integrity contract that lets non-Verity datasets be added safely: register the table + columns in `mart_field`, link to canonical requirements, reports can use them.

---

## L4 — Semantic Layer (metadata-driven reports)

```
requirement_evidence_field   (uuid pk)
    canonical_requirement_id (fk),
    mart_field_id (fk),
    role text,                   -- 'key' | 'measure' | 'dimension' | 'filter' | 'context'
    aggregation text,            -- null | 'count' | 'sum' | 'avg' | 'distinct_count'
    sort_seq int
```

This is the metadata that makes reports composable. A canonical_requirement says "to evidence me, you need these mart fields in these roles." Reports inherit the field manifest from the requirements they cover; they do not name fields directly.

---

## L5 — Reports (data, not code)

```
report_definition  (uuid pk)
    code, name, description,
    render_template text,        -- 'standard_table' | 'naic_exhibit' | 'executive_summary' | ...
    output_formats text[],       -- {'html','pdf','csv','json'}
    scope_params jsonb           -- declares accepted params (date range, app, materiality)

report_requirement  (uuid pk)
    report_id (fk),
    canonical_requirement_id (fk),
    section text,                -- where in the report this requirement's evidence lands
    sort_seq int

report_field_override  (uuid pk)        -- optional, per-report tweaks
    report_id, mart_field_id,
    role_override, aggregation_override, sort_seq_override
```

Report generation is a planner, not a script:

1. Resolve `report_definition` → its `report_requirement`s.
2. Each requirement → its `requirement_evidence_field` rows → `mart_field` rows.
3. Plan SQL: union of fact tables touched, join their SCD2 dims, project the registered columns, apply the scope filter and any `report_field_override`s.
4. Render the resulting dataset through the template named by `render_template`.

**Adding "Connecticut MC-25 §4(c)" workflow:**

1. INSERT `regulatory_provision` (CT MC-25 §4(c), text, embedding).
2. Either link to an existing `canonical_requirement` ("annual certification") via `provision_requirement_map`, or INSERT a new canonical_requirement and link.
3. If existing `mart_field`s already cover it → done. Coverage page shows it. Annual Cert Report auto-includes it.
4. If a new field is needed → ALTER TABLE fact_X ADD COLUMN; INSERT mart_field; INSERT requirement_evidence_field. One column, available to every report touching that requirement.

Zero new report SQL.

---

## Incremental Feed — three rungs, one schema

The contract on Layer 2 (`event_ts`, `ingest_ts`, `source_lsn`, append-only) is the same regardless of feed mechanism. Customers ingest the same shape on every rung.

| Rung | Mechanism | When | Customer-side |
|---|---|---|---|
| **1** | `GET /api/v1/feed/{table}?since={ingest_ts}&format={parquet\|jsonl}` | Ship in initial scope. Zero infra. | Cron + COPY INTO (Snowflake) / external table |
| **2** | Postgres logical replication → Python consumer → Iceberg-laid-out Parquet on S3/MinIO | When a customer asks for streaming. | Snowflake reads Iceberg natively as external table — no ingestion job. |
| **3** | Debezium Server (Kafka-less) → Iceberg sink (REST catalog + S3) | When CDC throughput justifies it. | Same as Rung 2. |

Rung 1 is sufficient for the demo and for early customers. Rungs 2 and 3 are non-breaking promotions because the watermark columns and table shapes are identical.

The export bundle command (`verity export-compliance --since {ts}`) emits:

- `verity_analytics.ddl.sql` — table DDL targetable at Postgres or Snowflake
- `mart_field.json` — the field registry
- `regulatory_mapping.yaml` — frameworks, provisions, canonical requirements, bridges, coverage
- `report_definitions.yaml` — packaged report manifests
- `data/{table}/*.parquet` — incremental partition by `ingest_ts` date

A customer importing this into their warehouse rebuilds the entire compliance stack with their own data blended in.

---

## Vector / Embedding Model

**Model:** `BAAI/bge-small-en-v1.5` (384 dimensions), run locally via `sentence-transformers` or ONNX. No API call, no per-token cost.

**Why local + small:**

- 384 dims keeps `pgvector` indexes fast and storage modest across four embedded tables.
- BGE-small benchmarks competitively with API embedding models for short, semantically-rich text (provisions, requirement descriptions, feature descriptions, field descriptions).
- Embeddings are recomputed when the source text changes, not at runtime — there is no latency budget pressure.

**Embedded columns:** `regulatory_provision.embedding`, `canonical_requirement.embedding`, `feature.embedding`, `mart_field.embedding`. All `vector(384)`.

**Model identity recorded:** a single `compliance_embedding_config` row stores model name + version + dim. Re-embedding becomes a guarded operation that bumps the config row.

This differs from runtime entities (agent/task/prompt embeddings at `vector(1536)`, [AD-004](decisions.md#ad-004)) because those were sized for a cloud model that may still be used on the runtime side. Compliance entities use the local model exclusively. A future unification can re-embed runtime entities at 384, but it is out of scope.

---

## Architectural Decisions

### AD-CS-001: Five-layer compliance stack
**Decision:** L1 operational → L2 mart → L3 metamodel → L4 semantic layer → L5 reports.
**Rationale:** Reports never read L1. Customer warehouses receive L2+L3+L4+L5 and can rebuild the stack with their own data.

### AD-CS-002: L2 in same Postgres, separate schema
**Decision:** `verity_analytics` schema in `verity_db`. Not a separate database.
**Rationale:** Ships immediately. No new ops surface. Same backup, same connection, same auth. Future promotion to a dedicated DB or external warehouse is a `pg_dump --schema=verity_analytics` away. The schema namespace makes the export boundary explicit and enforceable.

### AD-CS-003: SCD Type 2 dimensions
**Decision:** All dims are SCD2 with sentinel `valid_to` and `is_current` boolean. No frozen-snapshot dim shortcut.
**Rationale:** Standard data-mart practice. Enables any-point-in-time queries — "show me the model inventory as of the day this decision was made" answers cleanly. Reuses the sentinel-date convention from [AD-009](decisions.md#ad-009).

### AD-CS-004: `mart_field` registry is enforced
**Decision:** L4 metadata has FK constraints into `mart_field`. Reports referencing an unregistered column are rejected at validation time, not at SQL execution.
**Rationale:** This is what makes "add a custom non-Verity dataset" safe. Register the table and its columns in `mart_field`, optionally link to canonical requirements, reports gain access. No silent drift.

### AD-CS-005: Append-only facts with `(event_ts, ingest_ts, source_lsn)`
**Decision:** No UPDATE / DELETE on fact tables. Corrections are new rows with `correction_of_pk`. Every fact has watermark and ordering columns.
**Rationale:** Makes every CDC mechanism (watermark pull, logical replication, Debezium → Iceberg) tractable on the same schema. Customers never re-load.

### AD-CS-006: Surrogate UUID PKs everywhere; codes are attributes
**Decision:** No composite or natural-string primary keys in compliance metamodel or mart. `G1`, `SR11-7.II.A`, `feature.code` are sortable display attributes only.
**Rationale:** Codes change. Sort orders change. Frameworks issue revisions. UUID surrogates absorb all that without cascading rewrites.

### AD-CS-007: Local small embedding model (BGE-small, 384 dim)
**Decision:** `BAAI/bge-small-en-v1.5` for all compliance embedding columns. No API embedding model. Model identity stored in a config row.
**Rationale:** Cost-free, latency-free, customer-deployable air-gapped. Sufficient quality for short regulatory and feature text. Independent of runtime entities' 1536-dim vectors.

### AD-CS-008: Reports are data, not code
**Decision:** A report is rows in `report_definition` + `report_requirement` + (optional) `report_field_override`. Generation is a planner that assembles SQL from `requirement_evidence_field` → `mart_field`. Templates are a small fixed library (`standard_table`, `naic_exhibit`, `executive_summary`, etc.).
**Rationale:** New requirements and revisions become INSERTs. N reports do not become N hardcoded SQL files. Maintenance scales with regulation volume, not report count.

### AD-CS-009: Provision → canonical-requirement bridge is M:N with weights
**Decision:** `provision_requirement_map` with `weight`, `confidence`, `mapping_source`. Many-to-many in both directions.
**Rationale:** A canonical requirement may map to many provisions across frameworks (correctly). A provision may map to multiple canonical requirements (some provisions span themes). Weights enable partial-coverage accounting and feed the future semantic-similarity recommender.
