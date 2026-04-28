-- ============================================================
-- VERITY_DB: Compliance Metamodel (L3) + Analytics Schema (empty placeholder)
--
-- Architecture: docs/architecture/compliance-stack.md
-- Build plan:   docs/plans/compliance-build-plan.md
--
-- This file is applied AFTER schema.sql by migrate.py.
--
-- L3 metamodel: regulatory frameworks/provisions, canonical
-- requirements, features hierarchy, and the two M:N bridges that
-- connect them. This is the contract between regulators and Verity.
--
-- L2 (verity_analytics) schema is created empty here; populated in
-- Phase 2 with fact_* and dim_* tables.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS verity_compliance;
CREATE SCHEMA IF NOT EXISTS verity_analytics;

-- ── EMBEDDING MODEL IDENTITY ─────────────────────────────────
-- Single row marked is_current=true; history retained.
-- Each embedded row carries embedding_model_id pointing here so
-- the reembed CLI can identify stale vectors and re-embed only
-- those rows when the model is upgraded.

CREATE TABLE IF NOT EXISTS verity_compliance.embedding_config (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name      text NOT NULL,
    model_version   text NOT NULL,
    dim             int  NOT NULL,
    runtime         text NOT NULL DEFAULT 'fastembed',
    is_current      boolean NOT NULL DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

-- Only one row may have is_current=true at any time.
CREATE UNIQUE INDEX IF NOT EXISTS embedding_config_one_current
    ON verity_compliance.embedding_config (is_current)
    WHERE is_current = true;

-- ── LEFT AXIS: WHAT REGULATORS WROTE ─────────────────────────

CREATE TABLE IF NOT EXISTS verity_compliance.regulatory_framework (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,        -- 'SR_11_7', 'NAIC_AI_BULLETIN', ...
    name            text NOT NULL,
    jurisdiction    text NOT NULL,               -- 'US-FED', 'US-NAIC', 'US-CO', 'INDUSTRY'
    version         text,
    effective_date  date,
    valid_from      date NOT NULL DEFAULT current_date,
    valid_to        date NOT NULL DEFAULT DATE '2099-12-31',
    source_url      text,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT framework_valid_range CHECK (valid_from <= valid_to)
);

CREATE TABLE IF NOT EXISTS verity_compliance.regulatory_provision (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    framework_id       uuid NOT NULL
                            REFERENCES verity_compliance.regulatory_framework(id)
                            ON DELETE RESTRICT,
    citation           text NOT NULL,            -- '§II.A', '§3.1', etc.
    title              text NOT NULL,
    text               text,                     -- the actual regulation language where available
    effective_date     date,
    valid_from         date NOT NULL DEFAULT current_date,
    valid_to           date NOT NULL DEFAULT DATE '2099-12-31',
    sort_seq           int NOT NULL DEFAULT 0,
    embedding          vector(384),              -- populated by Phase 1.5 reembed CLI
    embedding_model_id uuid REFERENCES verity_compliance.embedding_config(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT provision_unique_citation UNIQUE (framework_id, citation),
    CONSTRAINT provision_valid_range CHECK (valid_from <= valid_to)
);

CREATE INDEX IF NOT EXISTS provision_framework_idx
    ON verity_compliance.regulatory_provision(framework_id);

-- IVFFlat / HNSW index on regulatory_provision.embedding deferred to
-- Phase 1.5 (need data first; building an empty IVFFlat is wasteful).

-- ── CENTER AXIS: RATIONALIZED REQUIREMENTS ───────────────────

CREATE TABLE IF NOT EXISTS verity_compliance.canonical_requirement_theme (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,        -- 'governance', 'fairness', ...
    name            text NOT NULL,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verity_compliance.canonical_requirement (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    theme_id           uuid NOT NULL
                            REFERENCES verity_compliance.canonical_requirement_theme(id)
                            ON DELETE RESTRICT,
    code               text NOT NULL UNIQUE,     -- 'model_inventory', 'fairness_pre_deployment', ...
    title              text NOT NULL,
    description        text,
    sort_seq           int NOT NULL DEFAULT 0,
    embedding          vector(384),
    embedding_model_id uuid REFERENCES verity_compliance.embedding_config(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS canonical_requirement_theme_idx
    ON verity_compliance.canonical_requirement(theme_id);

-- ── BRIDGE: PROVISION ↔ CANONICAL REQUIREMENT (M:N) ──────────
-- match_strength = semantic alignment of provision-to-canonical (0..1).
-- This is NOT coverage. Coverage lives in requirement_coverage.coverage_level.
-- Conflating the two was rejected on review (2026-04-28).

CREATE TABLE IF NOT EXISTS verity_compliance.provision_requirement_map (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provision_id             uuid NOT NULL
                                  REFERENCES verity_compliance.regulatory_provision(id)
                                  ON DELETE CASCADE,
    canonical_requirement_id uuid NOT NULL
                                  REFERENCES verity_compliance.canonical_requirement(id)
                                  ON DELETE CASCADE,
    match_strength           numeric(3,2) NOT NULL DEFAULT 1.00
                                  CHECK (match_strength > 0 AND match_strength <= 1),
    confidence               numeric(3,2) NOT NULL DEFAULT 1.00
                                  CHECK (confidence >= 0 AND confidence <= 1),
    mapping_source           text NOT NULL DEFAULT 'manual'
                                  CHECK (mapping_source IN ('manual',
                                                            'semantic_recommended',
                                                            'human_validated')),
    validated_by             text,
    validated_at             timestamptz,
    notes                    text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT provision_req_map_unique
        UNIQUE (provision_id, canonical_requirement_id)
);

CREATE INDEX IF NOT EXISTS provision_req_map_provision_idx
    ON verity_compliance.provision_requirement_map(provision_id);

CREATE INDEX IF NOT EXISTS provision_req_map_canonical_idx
    ON verity_compliance.provision_requirement_map(canonical_requirement_id);

-- ── RIGHT AXIS: WHAT VERITY OFFERS (FEATURES HIERARCHY) ──────
-- Three levels: plane → capability → feature.
-- Replaces the matrix's composite codes (G1, R5, A2, S1) with
-- surrogate UUIDs + sortable display labels.

CREATE TABLE IF NOT EXISTS verity_compliance.feature_plane (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code            text NOT NULL UNIQUE,        -- 'governance', 'runtime', 'agents', 'studio'
    name            text NOT NULL,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS verity_compliance.feature_capability (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plane_id        uuid NOT NULL
                         REFERENCES verity_compliance.feature_plane(id)
                         ON DELETE RESTRICT,
    code            text NOT NULL,
    name            text NOT NULL,
    description     text,
    sort_seq        int NOT NULL DEFAULT 0,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feature_capability_unique_per_plane UNIQUE (plane_id, code)
);

CREATE TABLE IF NOT EXISTS verity_compliance.feature (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_id      uuid NOT NULL
                            REFERENCES verity_compliance.feature_capability(id)
                            ON DELETE RESTRICT,
    code               text NOT NULL,
    name               text NOT NULL,
    description        text,
    status             text NOT NULL DEFAULT 'shipped'
                            CHECK (status IN ('shipped', 'planned', 'partial', 'deprecated')),
    sort_seq           int NOT NULL DEFAULT 0,
    embedding          vector(384),
    embedding_model_id uuid REFERENCES verity_compliance.embedding_config(id),
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT feature_unique_per_capability UNIQUE (capability_id, code)
);

CREATE INDEX IF NOT EXISTS feature_capability_idx
    ON verity_compliance.feature(capability_id);

-- ── BRIDGE: CANONICAL REQUIREMENT ↔ FEATURE (M:N) ────────────
-- "These Verity features satisfy this canonical requirement."
-- This is the structural proof of the v2 matrix's "Verity Features" column.

CREATE TABLE IF NOT EXISTS verity_compliance.requirement_feature_link (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_requirement_id uuid NOT NULL
                                  REFERENCES verity_compliance.canonical_requirement(id)
                                  ON DELETE CASCADE,
    feature_id               uuid NOT NULL
                                  REFERENCES verity_compliance.feature(id)
                                  ON DELETE CASCADE,
    role                     text NOT NULL DEFAULT 'primary'
                                  CHECK (role IN ('primary', 'supporting')),
    notes                    text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT requirement_feature_link_unique
        UNIQUE (canonical_requirement_id, feature_id)
);

-- ── COVERAGE: VERITY'S STANCE PER CANONICAL REQUIREMENT ──────
-- 1:1 with canonical_requirement. Separate table so coverage history
-- can become SCD2 in the future without restructuring.

CREATE TABLE IF NOT EXISTS verity_compliance.requirement_coverage (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_requirement_id uuid NOT NULL UNIQUE
                                  REFERENCES verity_compliance.canonical_requirement(id)
                                  ON DELETE CASCADE,
    coverage_level           text NOT NULL
                                  CHECK (coverage_level IN ('full',
                                                            'substantial',
                                                            'partial',
                                                            'gap')),
    rationale                text,
    customer_actions         text,
    last_reviewed_at         timestamptz NOT NULL DEFAULT now(),
    reviewed_by              text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);
