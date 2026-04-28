## Compliance Stack — Architecture

**Status:** approved 2026-04-28
**Replaces:** the implicit "evidence packages = N hardcoded reports" approach in [enhancements/regulatory-evidence-packages.md](../enhancements/regulatory-evidence-packages.md)
**Source matrix:** [Verity_Complete_Regulatory_Matrix_v2.md](../../Verity_Complete_Regulatory_Matrix_v2.md) — 47 requirements × 4 frameworks, becomes seed data.

This document is the architectural contract for everything regulatory in Verity. The phased build plan lives in [enhancements/regulatory-evidence-packages.md](../enhancements/regulatory-evidence-packages.md).

---

## Goals

1. **No customer data lock-in.** Verity Analytics data must be incrementally exportable to any customer-owned warehouse (Snowflake, BigQuery, Redshift) so customers blend governance data with their own claims/policy/financial data. Never a full re-load.
2. **Metadata-driven reports.** Adding a new state requirement, or revising one, must not require a new SQL file or a new mart table. The work is one or two INSERTs. A BYO-SQL escape hatch handles edge/custom requirements that don't fit the metadata model.
3. **Expandable regulatory metamodel.** A new framework (state bill, NAIC tool revision) plugs in alongside existing ones. Requirements common across frameworks rationalize to a single canonical requirement (decompose-as-needed; goal is no redundancy without compromising coverage); provision-to-canonical mapping is many-to-many with semantic match strength.
4. **Vector-aware from day one.** Provisions, canonical requirements, features, and mart fields all carry embeddings so future agents can recommend mappings between a new framework's provisions and existing canonical requirements with coverage % and gaps.
5. **Operational hot path untouched.** Layer 1 (the runtime trust DB) does not change. The compliance stack is additive.
6. **Open architecture.** Every artifact (schema DDL, mapping YAML, report definitions, Parquet exports) is documented and reproducible. Customers can rebuild the compliance stack on their own infrastructure with their own data blended in. Not "industry standard" — open and documented Verity formats.

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
    code, name, jurisdiction, version, effective_date, source_url,
    valid_from date, valid_to date          -- temporal validity
       │
       └── regulatory_provision  (uuid pk)
              framework_id (fk), citation, title, text,
              effective_date, sort_seq,
              valid_from date, valid_to date,   -- temporal validity
              embedding vector(384)
```

A framework groups provisions. A provision is the literal text from the regulation, citable. Both temporally-versioned at the entity level: when CO SB21-169 is reframed in 2027, old provisions get `valid_to = revision_date` and new provisions arrive with `valid_from = revision_date`. Sentinel pattern (`valid_to = '2099-12-31'` for currently in force) follows [AD-009](decisions.md#ad-009).

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

### Bridge — provision ↔ canonical (M:N)

```
provision_requirement_map  (uuid pk)
    provision_id (fk), canonical_requirement_id (fk),
    match_strength numeric(3,2),       -- semantic alignment only: 1.00 = full framing match; <1.00 = partial
    confidence numeric(3,2),           -- 1.00 = human-validated; <1.00 = auto-recommended
    mapping_source text,               -- 'manual' | 'semantic_recommended' | 'human_validated'
    validated_by text, validated_at timestamptz, notes text
```

This is where the matrix's many-to-one collapses correctly. "Model inventory & registration" appears in SR 11-7 §I, NAIC §3.1, NAIC Eval Tool Exhibit A — one canonical_requirement, three map rows.

`match_strength` is a property of the *relationship* between a provision and a canonical requirement — how strongly they semantically align. **It is not coverage.** Coverage (Verity's capability state for a canonical requirement) lives separately in `requirement_coverage.coverage_level`. Conflating them was rejected on review (2026-04-28).

A future agent ingests a new framework's provisions, embeds each, cosine-searches against `canonical_requirement.embedding`, proposes map rows with `mapping_source='semantic_recommended'` and the cosine similarity as `match_strength`. A reviewer flips them to `human_validated`. Coverage % rolls up independently from `requirement_coverage`.

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

### Fact tables (append-only)

Every fact carries:

| Column | Purpose | Populated |
|---|---|---|
| `surrogate_pk uuid` | mart-local identity | always |
| `event_ts timestamptz` | when the event happened in the source system | always |
| `ingest_ts timestamptz` | when the row landed in the mart (the watermark) | always |
| `source_pk text` | natural key from L1 (e.g. `decision_log.id`) | always |
| `source_lsn pg_lsn` | Postgres LSN of the originating WAL record (strict ordering) | **NULL at Rung 1** (polling ETL); populated only at Rung 2/3 by the CDC engine |

The schema is **CDC-ready** but at Rung 1 (polling) we cannot honestly fill `source_lsn` — `pg_current_wal_lsn()` at ETL time returns the LSN of the ETL transaction, not the source row's WAL position. The column is nullable from day one so customers who graduate to Rung 2/3 see it light up without a schema change. At Rung 1, ordering uses `(ingest_ts, source_pk)`.

Initial fact tables (Phase 2 slice):

- `fact_decision` — one row per `agent_decision_log`
- `fact_run` — one row per `execution_run` terminal state
- `fact_lifecycle_event` — one row per state transition
- `fact_validation_result` — one row per `test_execution_log`
- `fact_override` — one row per `hitl_override`

Future facts: `fact_approval`, `fact_tool_call`, `fact_source_resolution`, `fact_quota_event`, `fact_incident`.

**Append-only is non-negotiable.** No UPDATE, no DELETE. Corrections are new rows with a `correction_of_pk` reference. This is what makes incremental delivery tractable for any sink — watermark pull at Rung 1, CDC at Rung 2/3.

**Drilldown caveat.** A fact row's `source_pk` lets the Verity admin UI deep-link to the originating L1 row (e.g. `decision_log`). Customer warehouses receive only L2 — they have no L1 to drill into. This is a Verity-instance affordance, not a portable contract. Customer-facing reports show evidence rows but not their L1 origin.

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

A report is one of two shapes: **metadata-driven** (the default — the report inherits its fields from the canonical requirements it covers) or **template-driven** (BYO-SQL escape hatch — a parameterized SQL template stored in the metamodel and executed at run time).

```
report_definition  (uuid pk)
    code, name, description,
    report_kind text,            -- 'metadata_driven' | 'template_driven'
    render_template text,        -- 'standard_table' | 'naic_exhibit' | 'executive_summary' | ...
    output_formats text[],       -- {'html','pdf','csv','json'}
    scope_params jsonb           -- declares accepted params (date range, app, materiality)

-- For metadata-driven reports:
report_requirement  (uuid pk)
    report_id (fk),
    canonical_requirement_id (fk),
    section text,                -- where in the report this requirement's evidence lands
    sort_seq int

report_field_override  (uuid pk)        -- optional, per-report tweaks
    report_id, mart_field_id,
    role_override, aggregation_override, sort_seq_override

-- For template-driven (BYO-SQL) reports:
report_sql_template  (uuid pk)
    report_id (fk, UNIQUE),
    sql_text text,               -- parameterized SQL (named params: :since, :application_code, etc.)
    parameter_schema jsonb,      -- JSON Schema describing required + optional params
    referenced_mart_fields uuid[],   -- declared FK refs to mart_field for catalog completeness
    notes text
```

### Metadata-driven generation

1. Resolve `report_definition` → its `report_requirement`s.
2. Each requirement → its `requirement_evidence_field` rows → `mart_field` rows.
3. Plan SQL: union of fact tables touched, join their SCD2 dims, project the registered columns, apply the scope filter and any `report_field_override`s.
4. Render the resulting dataset through the template named by `render_template`.

### Template-driven generation (BYO-SQL escape hatch)

For edge or custom regulatory needs that don't fit the metadata-driven shape — bespoke disparity calculations, regulator-specific exhibit layouts, multi-stage CTE pipelines:

1. Resolve `report_definition` (`report_kind='template_driven'`) → `report_sql_template`.
2. Validate user-supplied params against `parameter_schema`.
3. Bind params into the stored `sql_text` (named-param substitution; never string concatenation — SQL injection is rejected at validation time).
4. Execute against `verity_analytics`. Render the dataset through `render_template`.

**Constraint:** `referenced_mart_fields` must be a non-empty subset of registered `mart_field` rows. The catalog still knows what fields the report touches, even though it doesn't generate the SQL. The integrity contract is preserved.

**When to use which:** start metadata-driven. Reach for template-driven only when the metadata model can't express the query (window functions over partition-by-decision, multi-CTE staging, vendor-specific exhibit shapes). Most reports stay metadata-driven; the escape hatch is for the long tail.

### Adding "Connecticut MC-25 §4(c)" workflow

1. INSERT `regulatory_provision` (CT MC-25 §4(c), text, embedding).
2. Either link to an existing `canonical_requirement` ("annual certification") via `provision_requirement_map`, or INSERT a new canonical_requirement and link.
3. If existing `mart_field`s already cover it → done. Coverage page shows it. Annual Cert Report auto-includes it.
4. If a new field is needed → ALTER TABLE fact_X ADD COLUMN; register in `mart_field`; INSERT `requirement_evidence_field`. One column, available to every report touching that requirement.

Zero new report SQL — unless the requirement is genuinely outside the metadata model, in which case author one `report_sql_template` row.

---

## Incremental Feed — three rungs, one schema

The schema contract on Layer 2 (`event_ts`, `ingest_ts`, `source_pk`, append-only; `source_lsn` nullable, populated only at Rung 2/3) is the same regardless of feed mechanism. Customers ingest the same shape on every rung; ordering primitive shifts from `(ingest_ts, source_pk)` at Rung 1 to `source_lsn` at Rung 2/3.

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

**Model:** `BAAI/bge-small-en-v1.5` (384 dimensions), run locally via **`fastembed`** (ONNX runtime). No API call, no per-token cost, no `torch` / `transformers` dependency in the runtime image.

**Why fastembed over sentence-transformers:**

- ~30 MB ONNX model + minimal Python dependencies, vs. ~700 MB+ for `sentence-transformers` (which transitively pulls `transformers` + `torch`). The runtime image stays lean — UW demo and runtime workers carry no embedding deps they don't use.
- Same BGE-small model, same 384-dim output. No quality difference.
- Pure-CPU inference is fine — embeddings are recomputed when source text changes, not at runtime, so there is no latency budget pressure.

**Embedded columns:** `regulatory_provision.embedding`, `canonical_requirement.embedding`, `feature.embedding`, `mart_field.embedding`. All `vector(384)`.

**Model identity recorded:** the `compliance_embedding_config` table holds one current model row (`is_current = true`) + history. Each embedded row carries `embedding_model_id` FK, so the system knows which model produced which vector.

**Staleness-aware reembed.** The `verity compliance reembed` CLI does not blindly re-embed everything. It selects rows where `embedding_model_id ≠ current_config.id` (or NULL), re-embeds those, and updates the FK. With thousands of rows, this is the difference between "30-minute job" and "30-second job" on routine runs.

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

### AD-CS-005: Append-only facts; `source_lsn` populated only at Rung 2/3
**Decision:** No UPDATE / DELETE on fact tables. Corrections are new rows with `correction_of_pk`. Every fact has `event_ts`, `ingest_ts`, `source_pk` always populated. `source_lsn pg_lsn` is nullable from day one and populated only by the Rung-2/3 CDC engine. At Rung 1 (polling ETL), `source_lsn` is NULL and ordering uses `(ingest_ts, source_pk)`.
**Rationale:** Polling cannot honestly fill LSN — `pg_current_wal_lsn()` returns the ETL transaction's LSN, not the source row's WAL position. Shipping a fake LSN at Rung 1 would silently break ordering when customers graduate to Rung 2. The schema stays CDC-ready (column exists, nullable); the fact stays honest (the column lights up only when the engine that can populate it is in use).

### AD-CS-006: Surrogate UUID PKs everywhere; codes are attributes
**Decision:** No composite or natural-string primary keys in compliance metamodel or mart. `G1`, `SR11-7.II.A`, `feature.code` are sortable display attributes only.
**Rationale:** Codes change. Sort orders change. Frameworks issue revisions. UUID surrogates absorb all that without cascading rewrites.

### AD-CS-007: Local small embedding via fastembed (BGE-small, 384 dim)
**Decision:** `BAAI/bge-small-en-v1.5` for all compliance embedding columns, served via `fastembed` (ONNX runtime). Not `sentence-transformers`. Model identity stored in `embedding_config`. Reembed CLI is staleness-aware (only re-embeds rows whose `embedding_model_id` ≠ current config).
**Rationale:** Cost-free, latency-free, customer-deployable air-gapped. fastembed's ~30 MB ONNX footprint keeps the runtime image lean — sentence-transformers would have added 700+ MB of `torch`/`transformers` deps for a once-per-model-upgrade job. Independent of runtime entities' 1536-dim vectors.

### AD-CS-008: Reports are data, not code (with BYO-SQL escape hatch)
**Decision:** Reports are rows in `report_definition` + `report_requirement` + (optional) `report_field_override`. Default generation is a planner that assembles SQL from `requirement_evidence_field` → `mart_field`. A `report_sql_template` table stores parameterized SQL for the long-tail of reports that don't fit the metadata model — bound at run time with named-param substitution, validated against `parameter_schema`, with `referenced_mart_fields` declared so the catalog still knows what's touched.
**Rationale:** New requirements and revisions become INSERTs. N reports do not become N hardcoded SQL files. Maintenance scales with regulation volume, not report count. The escape hatch handles edge/custom regulatory needs (bespoke disparity calculations, vendor-specific exhibit shapes) without breaking the integrity contract.

### AD-CS-009: Provision → canonical-requirement bridge is M:N with `match_strength`
**Decision:** `provision_requirement_map` carries `match_strength` (semantic alignment, 0.00–1.00), `confidence`, `mapping_source`. Many-to-many in both directions. Coverage of a canonical requirement (Verity's capability state) lives separately in `requirement_coverage.coverage_level`.
**Rationale:** A canonical requirement may map to many provisions across frameworks (correctly). A provision may map to multiple canonical requirements (some provisions span themes). `match_strength` is the semantic match strength — a property of the relationship — populated by the future similarity recommender. It is **not** coverage. Conflating the two attributes was rejected on review (2026-04-28).

### AD-CS-010: Temporal validity on frameworks and provisions
**Decision:** `regulatory_framework` and `regulatory_provision` carry `valid_from date` and `valid_to date`. Defaults: `valid_from = current_date`, `valid_to = '2099-12-31'` (sentinel for currently in force). Reuses [AD-009](decisions.md#ad-009) sentinel-date convention.
**Rationale:** Regulations get revised. CO SB21-169 may be reframed to "covered ADMT" in 2027 with reset enforcement date. Without temporal columns, revisions either silently overwrite history (loses audit trail) or proliferate near-duplicates (loses dedup). Temporal validity at the entity level lets the UI filter "as-of date" cleanly: old provisions retire, new provisions arrive, bridges and mappings adapt.

### AD-CS-011: Open architecture, not "open standards"
**Decision:** All export artifacts (DDL, mapping YAML, report definitions, Parquet) are documented and reproducible Verity formats. We do not claim conformance to any industry-standard schema (OpenLineage, RegTech-X, etc.).
**Rationale:** Honesty in marketing language. The contract is "you can rebuild this stack on your own infrastructure with full visibility into how it works" — that is open architecture. It is not "we comply with industry standard X." Avoid claims we cannot back.
