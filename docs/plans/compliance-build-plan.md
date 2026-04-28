# Compliance Stack — Build Plan & Tracker

**Owner:** Anil
**Started:** 2026-04-28
**Architecture:** [docs/architecture/compliance-stack.md](../architecture/compliance-stack.md)
**Enhancement scope:** [docs/enhancements/regulatory-evidence-packages.md](../enhancements/regulatory-evidence-packages.md)
**Source matrix:** [Verity_Complete_Regulatory_Matrix_v2.md](../../Verity_Complete_Regulatory_Matrix_v2.md)

This doc is the working tracker. Each sub-step is a single reviewable commit. Architecture decisions live in the architecture doc; this is checklist + decisions-in-flight + the schema preview the user reviews **before** any DDL is committed.

---

## Phase status

- [ ] **Phase 1** — L3 compliance metamodel + seed
  - [x] 1.1 — Schema only (committed 9ae919b — 11 tables in `verity_compliance`, empty `verity_analytics` schema)
  - [x] 1.2 — Static seeds — 5 frameworks, 15 themes, 4 planes, 13 capabilities, 68 features. Reviewable via `verity compliance show` (tree print) or directly in `verity/src/verity/setup/compliance_seed_static.yaml`.
  - [ ] 1.2.5 — Author `docs/plans/compliance-seed-data.yaml` (review checkpoint)
  - [ ] 1.3 — Provisions, canonical requirements, bridge, coverage seed
  - [ ] 1.4 — Coverage Matrix UI page
  - [ ] 1.5 — Embedding pipeline (fastembed, reembed CLI)
- [ ] **Phase 2** — L2 compliance mart minimum slice
- [ ] **Phase 3** — L4 semantic layer + report engine + Model Inventory
- [ ] **Phase 4** — Three more reports as data
- [ ] **Phase 5** — Feed Rung 1 + export bundle

**Sequencing note:** 1.4 (UI) before 1.5 (embeddings) because the UI doesn't need vectors. Reembed runs as a separate workstream that completes when ready. The Coverage Matrix UI is functional from seeded coverage data alone; semantic-similarity recommendations arrive once 1.5 lands.

---

## Phase 1.1 — Schema design preview (REVIEW BEFORE COMMIT)

**Where this code will live:**

- Schema DDL: `verity/src/verity/db/schema_compliance.sql` (new file)
- Applied alongside existing `schema.sql` at startup; both run via the existing init path.
- Pydantic models: `verity/src/verity/models/compliance.py` (new file)
- Two Postgres schemas created in `verity_db`:
  - `verity_compliance` — L3 metamodel + L4 semantic layer + L5 report definitions (this phase: L3 only)
  - `verity_analytics` — created empty, populated in Phase 2

**Conventions:**

- All PKs are `uuid PRIMARY KEY DEFAULT gen_random_uuid()`.
- Codes (`framework.code`, `feature.code`, etc.) are `text` natural attributes with `UNIQUE` constraints, never PKs.
- Timestamps: `created_at timestamptz DEFAULT now()`, `updated_at timestamptz DEFAULT now()` on all tables.
- Vector columns: `vector(384)` (BGE-small dim), nullable, populated by Phase 1.5.
- Temporal validity (frameworks + provisions): `valid_from date DEFAULT current_date`, `valid_to date DEFAULT '2099-12-31'`. Sentinel-date convention from [AD-009](../architecture/decisions.md#ad-009).
- All FKs explicit with `ON DELETE` policy stated per table.

### DDL preview

```sql
-- =========================================================================
-- verity_compliance schema — L3 metamodel
-- =========================================================================
CREATE SCHEMA IF NOT EXISTS verity_compliance;
CREATE SCHEMA IF NOT EXISTS verity_analytics;   -- empty, populated in Phase 2

-- ---- 1. Embedding model identity ----------------------------------------
CREATE TABLE verity_compliance.embedding_config (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name      text NOT NULL,             -- 'BAAI/bge-small-en-v1.5'
    model_version   text NOT NULL,             -- 'v1.5'
    dim             int  NOT NULL,             -- 384
    runtime         text NOT NULL DEFAULT 'fastembed',  -- 'fastembed' | 'sentence_transformers' | ...
    is_current      boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);
-- Only one row should be is_current=true at a time.
CREATE UNIQUE INDEX embedding_config_one_current
    ON verity_compliance.embedding_config (is_current)
    WHERE is_current = true;

-- ---- 2. Frameworks side --------------------------------------------------
CREATE TABLE verity_compliance.regulatory_framework (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,      -- 'SR_11_7', 'NAIC_AI_BULLETIN', ...
    name            text NOT NULL,
    jurisdiction    text NOT NULL,             -- 'US-FED', 'US-NAIC', 'US-CO', 'INDUSTRY'
    version         text,                      -- '2023-12', etc.
    effective_date  date,
    valid_from      date NOT NULL DEFAULT current_date,
    valid_to        date NOT NULL DEFAULT DATE '2099-12-31',
    source_url      text,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_from <= valid_to)
);

CREATE TABLE verity_compliance.regulatory_provision (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    framework_id       uuid NOT NULL REFERENCES verity_compliance.regulatory_framework(id)
                            ON DELETE RESTRICT,
    citation           text NOT NULL,           -- '§II.A', '§3.1', etc.
    title              text NOT NULL,
    text               text,                    -- the actual regulation language (where available)
    effective_date     date,
    valid_from         date NOT NULL DEFAULT current_date,
    valid_to           date NOT NULL DEFAULT DATE '2099-12-31',
    sort_seq           int NOT NULL DEFAULT 0,
    embedding          vector(384),             -- populated by Phase 1.5
    embedding_model_id uuid REFERENCES verity_compliance.embedding_config(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (framework_id, citation),
    CHECK (valid_from <= valid_to)
);
CREATE INDEX provision_framework_idx ON verity_compliance.regulatory_provision(framework_id);
-- IVFFlat / HNSW index on embedding deferred to Phase 1.5 (need data first).

-- ---- 3. Canonical requirements side --------------------------------------
CREATE TABLE verity_compliance.canonical_requirement_theme (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,      -- 'governance', 'fairness', 'data_quality', ...
    name            text NOT NULL,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE verity_compliance.canonical_requirement (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id           uuid NOT NULL REFERENCES verity_compliance.canonical_requirement_theme(id)
                            ON DELETE RESTRICT,
    code               text NOT NULL UNIQUE,   -- 'model_inventory', 'fairness_pre_deployment', ...
    title              text NOT NULL,
    description        text,
    sort_seq           int NOT NULL DEFAULT 0,
    embedding          vector(384),
    embedding_model_id uuid REFERENCES verity_compliance.embedding_config(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX canonical_requirement_theme_idx
    ON verity_compliance.canonical_requirement(theme_id);

-- ---- 4. Provision ↔ canonical bridge (M:N) -------------------------------
CREATE TABLE verity_compliance.provision_requirement_map (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provision_id             uuid NOT NULL REFERENCES verity_compliance.regulatory_provision(id)
                                  ON DELETE CASCADE,
    canonical_requirement_id uuid NOT NULL REFERENCES verity_compliance.canonical_requirement(id)
                                  ON DELETE CASCADE,
    -- match_strength: semantic alignment of this provision to this canonical requirement.
    -- NOT coverage. Coverage lives in requirement_coverage.coverage_level.
    match_strength           numeric(3,2) NOT NULL DEFAULT 1.00
                                  CHECK (match_strength > 0 AND match_strength <= 1),
    confidence               numeric(3,2) NOT NULL DEFAULT 1.00
                                  CHECK (confidence >= 0 AND confidence <= 1),
    mapping_source           text NOT NULL DEFAULT 'manual'
                                  CHECK (mapping_source IN ('manual','semantic_recommended','human_validated')),
    validated_by             text,
    validated_at             timestamptz,
    notes                    text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provision_id, canonical_requirement_id)
);
CREATE INDEX provision_req_map_provision_idx
    ON verity_compliance.provision_requirement_map(provision_id);
CREATE INDEX provision_req_map_canonical_idx
    ON verity_compliance.provision_requirement_map(canonical_requirement_id);

-- ---- 5. Features hierarchy (replaces G1/G2/R1 composite codes) -----------
CREATE TABLE verity_compliance.feature_plane (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,      -- 'governance', 'runtime', 'agents', 'studio'
    name            text NOT NULL,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE verity_compliance.feature_capability (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_id        uuid NOT NULL REFERENCES verity_compliance.feature_plane(id)
                         ON DELETE RESTRICT,
    code            text NOT NULL,             -- 'asset_registry', 'lifecycle_engine', ...
    name            text NOT NULL,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (plane_id, code)
);

CREATE TABLE verity_compliance.feature (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_id      uuid NOT NULL REFERENCES verity_compliance.feature_capability(id)
                            ON DELETE RESTRICT,
    code               text NOT NULL,          -- 'task_version_registration', 'agent_loop', ...
    name               text NOT NULL,
    description        text,
    status             text NOT NULL DEFAULT 'shipped'
                            CHECK (status IN ('shipped','planned','partial','deprecated')),
    sort_seq           int NOT NULL DEFAULT 0,
    embedding          vector(384),
    embedding_model_id uuid REFERENCES verity_compliance.embedding_config(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (capability_id, code)
);
CREATE INDEX feature_capability_idx ON verity_compliance.feature(capability_id);

-- ---- 6. Requirement ↔ feature link (M:N) ---------------------------------
CREATE TABLE verity_compliance.requirement_feature_link (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_requirement_id uuid NOT NULL REFERENCES verity_compliance.canonical_requirement(id)
                                  ON DELETE CASCADE,
    feature_id               uuid NOT NULL REFERENCES verity_compliance.feature(id)
                                  ON DELETE CASCADE,
    role                     text NOT NULL DEFAULT 'primary'
                                  CHECK (role IN ('primary','supporting')),
    notes                    text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (canonical_requirement_id, feature_id)
);

-- ---- 7. Coverage ---------------------------------------------------------
CREATE TABLE verity_compliance.requirement_coverage (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_requirement_id uuid NOT NULL UNIQUE
                                  REFERENCES verity_compliance.canonical_requirement(id)
                                  ON DELETE CASCADE,
    coverage_level           text NOT NULL
                                  CHECK (coverage_level IN ('full','substantial','partial','gap')),
    rationale                text,
    customer_actions         text,
    last_reviewed_at         timestamptz NOT NULL DEFAULT now(),
    reviewed_by              text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
```

**Notes on what is NOT in Phase 1.1:**

- `mart_field`, `requirement_evidence_field`, `report_definition`, `report_requirement`, `report_field_override`, `report_sql_template` — these are L2/L4/L5 and arrive in Phases 2 and 3.
- `source_lsn pg_lsn` on fact tables — Phase 2; nullable from day one, populated only at Rung 2/3 ([AD-CS-005](../architecture/compliance-stack.md#ad-cs-005-append-only-facts-source_lsn-populated-only-at-rung-23)).
- IVFFlat / HNSW indexes on the four embedding columns — deferred to Phase 1.5 after embeddings are populated; building an empty IVFFlat is wasteful.
- ETL tables for L2 (Phase 2) — the schema is created empty in this phase but no tables in it yet.

### Pydantic models preview (`verity/src/verity/models/compliance.py`)

One model per table, mirror of DDL. UUID fields typed `uuid.UUID`, vector fields typed `list[float] | None`, timestamps `datetime`, dates `date`. Enums for `mapping_source`, `coverage_level`, `status`, `role`, `jurisdiction`. SQL queries in `verity/src/verity/db/queries/compliance/*.sql` per existing convention.

### Open questions for review

1. **Schema name `verity_compliance` vs `compliance`** — went with the namespaced version for symmetry with `verity_analytics`. OK?
2. **`embedding_model_id` per row** — added so a row remembers which model embedded it (M8 from review). Adds a column; worth it for the staleness-aware reembed path.
3. **`text` column on `regulatory_provision`** — full regulation language is long. `text` is unbounded; fine in PG. Acceptable?
4. **`match_strength` and `confidence` as `numeric(3,2)`** — gives 0.00–1.00 with two decimals. Fine for cosine-similarity-derived weights.
5. **`requirement_coverage` as a separate 1:1 table** — keeps coverage history-ready (could become SCD2 in future); inlining into `canonical_requirement` was the simpler alternative. Went separate.

---

## Phase 1.2 — Static seeds

Pre-build (no provisions yet, no mappings):

- 4 frameworks (SR 11-7, NAIC AI Bulletin, CO SB21-169, ORSA/ASOP/CAS) + NAIC AI Systems Evaluation Tool as a 5th. The "Cross-Framework" matrix rows (44–47) are NOT a virtual framework — those provisions get duplicated onto each contributing framework and rationalize through canonical requirements.
- ~12–15 themes: governance, ownership_accountability, conceptual_soundness, data_quality, testing_validation, monitoring_drift, change_management, fairness, privacy_security, robustness, oversight_intervention, transparency_explainability, risk_proportionality, third_party_oversight, examination_readiness, lineage_provenance, model_documentation.
- 4 feature_planes (Governance, Runtime, Agents, Studio).
- ~12 feature_capabilities (Asset Registry, Lifecycle Engine, Testing & Validation, Decision Logging, Model Management, Compliance & Reporting, Quotas & Incidents under Governance; Task Executor, Agent Loop, Async Execution, Connectors under Runtime; Drift / Lifecycle / Validation under Agents; Compose / Lifecycle / GroundTruth / Test under Studio).
- 61 features (G1–G38, R1–R23, A1–A3, S1–S4) populated under their capabilities. `feature.code` = the human-typed semantic code (e.g. `task_version_registration`); `sort_seq` preserves the v2-matrix order; the legacy `G1` label is derived for display only.

Seeder: `verity/src/verity/setup/seed_compliance.py`. Idempotent (UPSERT by code).

---

## Phase 1.2.5 — Author seed-data YAML (REVIEW CHECKPOINT)

**This is the highest-risk Phase 1 work.** The canonical-requirement set is the design — if it's wrong, every bridge, coverage row, and report inherits the error.

Output: `docs/plans/compliance-seed-data.yaml`. Contains:

- All ~50 provisions parsed from the v2 matrix (one row per matrix citation, not per matrix row — some matrix rows produce multiple provisions when they cite multiple framework sections).
- The proposed canonical requirement set. Goal: **decompose-as-needed; rationalization is not minimization.** Two provisions describing the same requirement collapse to one canonical; two provisions describing related-but-distinct requirements stay separate. Coverage must not be compromised by aggressive collapsing.
- All `provision_requirement_map` rows (every matrix row maps to ≥1 canonical requirement; some map to multiple).
- `requirement_feature_link` rows derived from the matrix's "Verity Features" column (the G1/R1/etc. references resolve to feature.code).
- `requirement_coverage` rows, one per canonical requirement, with `coverage_level` taken from the matrix's "Coverage" column and `customer_actions` from "Gaps / Customer Actions."

**Review process:** I draft the YAML; you review the canonical-requirement set and any merges; I revise; we lock it before Phase 1.3 runs the seeder.

---

## Phase 1.3 — Seed provisions, canonical requirements, bridge, coverage

Seeder reads the locked `compliance-seed-data.yaml` and writes:

- `regulatory_provision` rows (~50)
- `canonical_requirement_theme` rows (~12–15, if not already in 1.2 — likely moved here)
- `canonical_requirement` rows (count determined by 1.2.5; goal is no redundancy without compromising coverage)
- `provision_requirement_map` rows (one per provision-canonical pair; some provisions map to multiple canonicals)
- `requirement_feature_link` rows (from matrix)
- `requirement_coverage` rows (one per canonical_requirement, from matrix coverage levels)

Idempotent (UPSERT by natural key). Re-running with an updated YAML produces the same result.

**Acceptance:** all 47 v2-matrix rows are reachable: every matrix row's Coverage, Verity Features, and Customer Actions can be retrieved from the seeded DB by walking framework → provision → bridge → canonical → coverage / features.

---

## Phase 1.4 — Coverage Matrix UI

- Route: `/admin/compliance/coverage`
- Renders: framework × canonical_requirement matrix, color by coverage_level (Full=green, Substantial=blue, Partial=amber, Gap=red).
- Drill-down within Verity instance: click a cell → provision text + linked features + coverage rationale + customer actions. **No drill-down to operational decision rows in this phase** (that arrives in Phase 3 with the report engine and L2 mart).
- Read-only.
- Filterable by framework, theme, coverage_level.
- "As-of date" filter using `valid_from` / `valid_to` on framework + provision (so you can view "the matrix as it was 2026-01-01" once revisions happen).

**Acceptance:** all 47 matrix rows visible. Filters work. Drilldown into provision text and feature links works. Coverage rollup per framework matches the v2 matrix Part 2 totals (17 Full / 18 Substantial / 10 Partial / 2 Gap).

---

## Phase 1.5 — Embedding pipeline

- Add `fastembed>=0.3,<1.0` to `verity/pyproject.toml`.
- Bake the BGE-small ONNX model (~30 MB) into the Docker image so first run isn't slow. No `torch` / `transformers` deps.
- CLI: `verity compliance reembed [--force]` — staleness-aware. Selects rows where `embedding_model_id IS NULL OR embedding_model_id ≠ (current embedding_config.id)`, generates vectors, updates the FK. With `--force` it re-embeds everything.
- IVFFlat indexes on the four embedding columns built once data is populated.
- One-shot CLI: `verity compliance similarity-search --provision-text "..."` returns top-k candidate canonical_requirements with cosine similarity. This is a debugging affordance and the seed of the future similarity recommender.

**Acceptance:** all four embedded tables have populated vectors for every row. `embedding_model_id` FK populated. Similarity search returns sensible top-k for at least 5 sample provisions. Re-running reembed without `--force` is a no-op.

---

## Decisions deferred (revisit before each phase)

| # | Question | Default if not raised |
|---|---|---|
| D-1 | Schema namespace name (`verity_compliance` vs `compliance`) | `verity_compliance` |
| D-2 | `embedding_model_id` per row | yes, include |
| D-3 | Cross-framework requirements (matrix rows 44–47) — virtual framework or duplicated provisions? | duplicated provisions on each contributing framework, single canonical_requirement |
| D-4 | Coverage as 1:1 table vs inlined | separate table |
| D-5 | UI: link drill-downs to actual decision_log rows in Phase 1.4? | no — that arrives in Phase 3 with the report engine |
| D-6 | RBAC on Coverage Matrix and reports | future enhancement; cross-link [enhancements/rest-api-auth.md](../enhancements/rest-api-auth.md). Applies to all of Verity. |
| D-7 | Drill-down portability to customer warehouses | no — `source_pk` deep links are Verity-instance only ([compliance-stack.md L2 § Drilldown caveat](../architecture/compliance-stack.md#fact-tables-append-only)) |
