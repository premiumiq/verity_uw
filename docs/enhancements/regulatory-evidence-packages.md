# Regulatory Evidence Packages — Phased Plan

> **Status:** approved 2026-04-28 — supersedes the prior "N hardcoded generators" sketch.
> **Architecture:** [docs/architecture/compliance-stack.md](../architecture/compliance-stack.md)
> **Source matrix:** [Verity_Complete_Regulatory_Matrix_v2.md](../../Verity_Complete_Regulatory_Matrix_v2.md) — 47 requirements × 4 frameworks, used as seed data.
> **Priority:** high — directly supports CIO/CTO demo narrative; closes the largest "Substantial → Full" gap on the matrix.

---

## What changed from the prior plan

The earlier draft proposed one Python generator per framework with bespoke SQL and Jinja templates. Rejected on review (2026-04-28):

- N hardcoded structures → unmaintainable as regulations evolve.
- Adding a state's revised requirement → would require code changes.
- Reports tied to operational tables → blocks customer-warehouse portability.

The replacement is a five-layer stack with a metadata-driven semantic layer. See the architecture doc. This file is the build plan only.

---

## Phase 1 — L3 Compliance Metamodel + Seed

**Goal:** the 47-requirement matrix becomes queryable data. Coverage Matrix UI reads from DB.

**Schema (in a new `compliance` schema or alongside Verity's existing schema — TBD with first commit):**

- `regulatory_framework`
- `regulatory_provision` (with `embedding vector(384)`)
- `canonical_requirement_theme`
- `canonical_requirement` (with `embedding vector(384)`)
- `provision_requirement_map` (M:N bridge, weighted)
- `feature_plane`, `feature_capability`, `feature` (with `embedding vector(384)`)
- `requirement_feature_link` (M:N)
- `requirement_coverage`
- `compliance_embedding_config` (one row: model name, version, dim)

**Seed:**

- 4 frameworks (SR 11-7, NAIC AI Bulletin, CO SB21-169, ORSA/ASOP/CAS) + NAIC Eval Tool as the 5th if treated as separate.
- ~50 provisions extracted from the v2 matrix (one per row × one or two citations).
- ~30–35 canonical requirements (rationalized — fewer than 47 because of cross-framework dedup).
- All 47 matrix rows become `provision_requirement_map` entries pointing into the canonical set.
- 61 features (38 G + 23 R) seeded under `feature_plane` (Governance, Runtime, Agents, Studio) → `feature_capability` → `feature`.
- `requirement_feature_link` rows derived from the v2 matrix's "Verity Features" column.
- `requirement_coverage` rows for all canonical requirements (Full / Substantial / Partial / Gap).

**Embedding generation:**

- `BAAI/bge-small-en-v1.5` via `sentence-transformers` (Docker image addition or extra dep).
- A one-shot CLI: `verity compliance reembed` that walks each table and populates `embedding` columns.
- Recorded in `compliance_embedding_config`.

**UI:**

- `/admin/compliance/coverage` — Coverage Matrix page. Live, queryable, drill-down into provisions, mapped features, evidence (in Phase 3).

**Acceptance:** all 47 matrix rows are reachable via the metamodel. Coverage page renders the matrix from data. Embeddings populated. No reports yet.

---

## Phase 2 — L2 Compliance Mart Minimum Slice

**Goal:** universal, append-only, CDC-shaped data layer that all reports query. Live in `analytics` schema, same Postgres (per [AD-CS-002](../architecture/compliance-stack.md#ad-cs-002-l2-in-same-postgres-separate-schema)).

**Fact tables (append-only, all carry `event_ts` / `ingest_ts` / `source_lsn` / `source_pk`):**

- `fact_decision`
- `fact_run`
- `fact_lifecycle_event`
- `fact_validation_result`
- `fact_override`

**Dimensions (SCD Type 2 with sentinel-date convention):**

- `dim_application`, `dim_entity_version`, `dim_user`, `dim_materiality`, `dim_data_classification`, `dim_canonical_requirement`, `dim_regulatory_framework`, `dim_date`

**Mart field registry:**

- `mart_field` table — every column reachable from a report registered here, with `embedding vector(384)`.
- Seed: every column in the Phase 2 fact + dim tables.

**ETL:**

- A scheduled Python job (and an on-demand CLI) reads the L1 source tables, applies SCD2 logic to dims, appends to facts. Watermarked on `ingest_ts`. Idempotent.
- No streaming yet. Cron cadence sufficient for demo.

**Acceptance:** facts and dims populate from existing seeded UW data. `mart_field` registry covers every reachable column. SCD2 dims show at least one historical version row for at least one entity. Same dataset reproducible by re-running ETL from scratch.

---

## Phase 3 — L4 Semantic Layer + Report Engine + First Report

**Goal:** prove the metadata-driven report contract end-to-end with one report.

**Schema:**

- `requirement_evidence_field` — canonical_requirement → mart_field, with role + aggregation
- `report_definition`, `report_requirement`, `report_field_override`

**Report planner:**

- Python module `verity.compliance.reports.planner`
- Input: `report_code` + scope params (date range, application, materiality)
- Output: rendered HTML + downloadable PDF + CSV
- Process: resolve report → requirements → evidence fields → mart_fields → plan SQL → execute → render template

**First report: `model_inventory`**

- Covers canonical requirements: model_inventory, ownership_accountability, change_management, materiality_classification.
- Sources from `dim_entity_version` + `fact_lifecycle_event`.
- Template: `standard_table` with section per theme.

**UI:**

- `/admin/compliance/reports` — list of report definitions, scope picker, "Generate" → background job → download.
- Report runs themselves logged in `report_run_log` (auditable, reuse pattern from earlier draft's `regulatory_evidence_export` idea).

**Acceptance:** Model Inventory report generates from data. Every value in the report traces back to a registered mart_field via a queryable join. Adding a new canonical_requirement to the report is one INSERT into `report_requirement` — no Python change.

---

## Phase 4 — Three More Reports as Data

**Goal:** prove the "no new SQL" claim by adding three reports without writing any new SQL files.

**Reports:**

- `decision_audit_trail` — covers explainability, decision logging, data lineage. Source: `fact_decision` + dims, scoped by `execution_context_id`.
- `fairness_validation_summary` — covers pre-deployment fairness, bias testing methodology. Source: `fact_validation_result` filtered to fairness suite type.
- `naic_exhibit_c` — High-Risk System Deep Dive. Covers ~12 canonical requirements. Source: union of all five facts scoped by entity_version.

Each report = INSERT report_definition + INSERT N report_requirement rows. New evidence fields registered in `requirement_evidence_field` if needed (matrix rows that weren't covered in Phase 3).

**Templates:**

- Add `naic_exhibit` template (formatted to match Eval Tool exhibit layout).
- Reuse `standard_table` for the other two.

**Acceptance:** all three reports render. Coverage Matrix page links each canonical requirement to the report(s) that evidence it. No new `.sql` files committed in this phase except DDL for any new mart fields needed.

---

## Phase 5 — Feed Rung 1 + Export Bundle

**Goal:** a customer can pull incremental data into Snowflake/BigQuery/Redshift today.

**Watermark API:**

- `GET /api/v1/feed/{table}?since={ingest_ts}&format=parquet|jsonl&limit={n}`
- Returns: rows with `ingest_ts > since`, ordered by `(ingest_ts, source_lsn)`, plus a `next_since` watermark.
- Auth: API key (reuses existing pattern; see [enhancements/rest-api-auth.md](rest-api-auth.md)).

**Export bundle CLI:**

- `verity export-compliance --since {ts} --out {dir}`
- Emits:
  - `analytics.ddl.sql` — Postgres + Snowflake-compatible DDL
  - `mart_field.json` — field registry
  - `regulatory_mapping.yaml` — frameworks/provisions/canonical reqs/bridges/coverage
  - `report_definitions.yaml` — packaged reports as data
  - `data/{table}/*.parquet` — incremental partition by `ingest_ts` date

**Customer ingest doc:**

- `docs/guides/compliance-warehouse-ingest.md` — Snowflake `COPY INTO` recipe, BigQuery external-table recipe, Redshift `COPY` recipe. All read the same Parquet shape.

**Acceptance:** running the export against the demo DB produces a bundle that can be re-imported into a clean Postgres and reproduces the Coverage Matrix page identically. Snowflake recipe documented and dry-run validated.

---

## Out of scope for this enhancement

- **Feed Rung 2/3** (Postgres logical replication → Iceberg, Debezium Server → Iceberg). Schema-compatible promotion path; defer until a customer requires throughput beyond cron pulls.
- **Semantic-similarity recommender for new provisions.** Vectors are populated in Phase 1; the recommender agent is a future Verity Agents Plane feature.
- **Production fairness monitoring (B1).** Tracked separately; that capability writes new facts, which Phase 4 fairness report will then surface.
- **Submit-ready filings.** Verity emits evidence packages, not auto-filed regulatory submissions. A human reviewer always inspects.

---

## Sequencing notes

Phases are sequential. Each one ships behind the prior one's acceptance criteria. Phase 1 is the largest and most metamodel-shaping; subsequent phases are progressively smaller as the contract solidifies.

A Phase-1-only milestone (Coverage Matrix UI driven by seeded data, no reports yet) is a defensible standalone shippable; the work after that is incremental.
