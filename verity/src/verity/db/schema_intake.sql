-- ============================================================
-- VERITY_DB: Governance Intake Schema
--
-- Architecture: docs/architecture/governance-intake.md
--
-- Adds the "process" layer that sits upstream of the registry:
--   - intake               -- the business-approved purpose (header)
--   - intake_impact_assessment  -- required for limited/high risk tier
--   - intake_requirement   -- BR/FR/NFR/compliance reqs (with embeddings)
--   - intake_entity_link   -- bridge to registry artifacts
--   - intake_artifact_plan -- proposed registry entities to build
--   - approval_request     -- per gating event (intake / promote / retire)
--   - approval_signoff     -- one row per role per request
--
-- This file is applied AFTER schema.sql AND schema_compliance.sql by
-- migrate.py. The dependency on schema_compliance.sql is the FK from
-- intake_requirement.embedding_model_id -> compliance.embedding_config.id.
-- ============================================================

-- Session search_path so the unqualified type/table references resolve.
SET search_path TO governance, runtime, compliance, analytics, public;


-- ── ENUMERATIONS ────────────────────────────────────────────

-- Reuse the existing governance.entity_type enum for polymorphic kinds.
-- Add the kinds the intake layer needs to link. ALTER TYPE ADD VALUE is
-- non-transactional and IF NOT EXISTS makes re-application a no-op.
ALTER TYPE governance.entity_type ADD VALUE IF NOT EXISTS 'test_suite';
ALTER TYPE governance.entity_type ADD VALUE IF NOT EXISTS 'ground_truth_dataset';


-- The lifecycle of an intake row, from "business idea" through
-- "approved" through "retired". See § 4 of governance-intake.md
-- for the legal transitions.
DO $$ BEGIN
    CREATE TYPE governance.intake_status AS ENUM (
        'proposed',
        'in_review',
        'impact_assessment',
        'approved',
        'in_build',
        'live',
        'rejected',
        'retired'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- AI risk tier under EU AI Act framing. Distinct from agent-level
-- materiality_tier, which is about a single agent's influence on
-- decisions; risk tier is about the intake's purpose.
DO $$ BEGIN
    CREATE TYPE governance.ai_risk_tier AS ENUM (
        'minimal', 'limited', 'high', 'unacceptable'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- NAIC Model Bulletin "material" classification.
DO $$ BEGIN
    CREATE TYPE governance.naic_materiality AS ENUM (
        'material', 'non_material'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- Kind of an intake_requirement.
DO $$ BEGIN
    CREATE TYPE governance.requirement_kind AS ENUM (
        'business', 'functional', 'non_functional', 'compliance'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- Lifecycle of an intake_requirement.
DO $$ BEGIN
    CREATE TYPE governance.requirement_status AS ENUM (
        'draft', 'approved', 'implemented', 'verified', 'deprecated'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- How an entity (agent/task/...) relates to a requirement.
-- 'implements' is the default; 'tests' for test suites, 'monitors' for
-- runtime monitors, 'informs' for entities that contribute context but
-- don't directly satisfy the requirement.
DO $$ BEGIN
    CREATE TYPE governance.requirement_relationship AS ENUM (
        'implements', 'tests', 'monitors', 'informs'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- A persona a Studio user can act as. Drives nav and authorization.
-- Not the same as approval_role — engineer/auditor/viewer can use
-- Studio but cannot sign off on approvals.
DO $$ BEGIN
    CREATE TYPE governance.studio_role AS ENUM (
        'business_owner', 'compliance', 'legal', 'model_risk',
        'ai_governance', 'security', 'privacy',
        'engineer', 'auditor', 'viewer'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- The subset of studio_role that can be required on an approval.
DO $$ BEGIN
    CREATE TYPE governance.approval_role AS ENUM (
        'business_owner', 'compliance', 'legal', 'model_risk',
        'ai_governance', 'security', 'privacy'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- A signoff decision on an approval_request.
DO $$ BEGIN
    CREATE TYPE governance.approval_decision AS ENUM (
        'approved', 'rejected', 'requested_changes', 'abstained'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- The kind of gating event an approval_request represents.
DO $$ BEGIN
    CREATE TYPE governance.approval_request_kind AS ENUM (
        'intake', 'risk_reclassification',
        'promote_candidate', 'promote_champion', 'retire'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- Lifecycle of an artifact_plan row (proposed -> realized, etc).
DO $$ BEGIN
    CREATE TYPE governance.artifact_plan_status AS ENUM (
        'proposed', 'in_progress', 'realized', 'cancelled'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ── INTAKE HEADER ────────────────────────────────────────────
-- One row per business-approved AI use case. The "code" is a
-- short slug (e.g. 'uw-bop-eligibility') that humans use in URLs
-- and YAML; the UUID is the structural key.

CREATE TABLE IF NOT EXISTS governance.intake (
    id                              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Every intake belongs to a registered application (the consuming
    -- product the AI use case is for — e.g. uw_demo). Only registered
    -- applications can intake use cases; the FK enforces this. Deletion
    -- of an application with active intakes is restricted to fail loud.
    application_id                  uuid NOT NULL
                                       REFERENCES governance.application(id)
                                       ON DELETE RESTRICT,
    -- Code is unique WITHIN an application — UNIQUE (application_id, code)
    -- below. Two applications can each have their own intake named
    -- "bop-eligibility" without colliding. The slug is auto-derived from
    -- title server-side; users never type it.
    code                            varchar(120) NOT NULL,
    title                           text NOT NULL,
    problem_statement               text NOT NULL,
    expected_benefit                text NOT NULL,
    in_scope_decisions              text,
    out_of_scope_decisions          text,
    -- JSONB array of population identifiers, e.g.
    --   ["applicants","brokers","underwriters"]
    -- Free-form for the demo; phase B introduces a controlled vocabulary.
    affected_populations            jsonb NOT NULL DEFAULT '[]'::jsonb,
    business_owner_name             varchar(200) NOT NULL,
    business_owner_email            varchar(200),
    requesting_team                 varchar(200),
    ai_risk_tier                    governance.ai_risk_tier NOT NULL,
    risk_classification_rationale   text NOT NULL,
    naic_materiality                governance.naic_materiality NOT NULL,
    status                          governance.intake_status NOT NULL DEFAULT 'proposed',
    intake_at                       timestamptz NOT NULL DEFAULT now(),
    approved_at                     timestamptz,
    retired_at                      timestamptz,
    effective_date                  date,
    next_recertification_due        date,
    created_by                      varchar(200) NOT NULL,
    -- Persona at write time, captured for audit. May be NULL on legacy
    -- writes (e.g. seed scripts before persona middleware is wired in).
    acting_as_role                  governance.studio_role,
    updated_at                      timestamptz NOT NULL DEFAULT now(),
    notes                           text,
    -- HITL (human-in-the-loop) strategy captured at intake.
    -- Free text describing how humans review or override AI output:
    -- e.g. "Underwriter reviews every classification before any
    -- bind/decline action; AI is decision-support only."
    hitl_strategy                   text,
    -- Trigger condition for HITL review (when applicable):
    -- e.g. "always", "confidence < 0.8", "weekly random 10% sample".
    hitl_review_threshold           text,

    -- Application-scoped uniqueness. Path-scoped URLs reflect this:
    -- /studio/intake/{application_code}/{intake_code}.
    CONSTRAINT intake_app_code_key UNIQUE (application_id, code)
);

CREATE INDEX IF NOT EXISTS idx_intake_status
    ON governance.intake(status);
CREATE INDEX IF NOT EXISTS idx_intake_risk_tier
    ON governance.intake(ai_risk_tier);
CREATE INDEX IF NOT EXISTS idx_intake_owner_email
    ON governance.intake(business_owner_email);
CREATE INDEX IF NOT EXISTS idx_intake_application
    ON governance.intake(application_id);


-- ── IMPACT ASSESSMENT ────────────────────────────────────────
-- Required when ai_risk_tier IN ('limited','high'). Phase A creates
-- exactly version=1 per intake; the UNIQUE permits future revisions.

CREATE TABLE IF NOT EXISTS governance.intake_impact_assessment (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                uuid NOT NULL
                                 REFERENCES governance.intake(id) ON DELETE CASCADE,
    version                  int NOT NULL DEFAULT 1,
    -- jsonb shapes (free-form for demo; phase B may formalise schemas):
    --   data_sources:    [{source,owner,classification},...]
    --   potential_harms: [{population,harm,severity,likelihood},...]
    --   mitigations:     [{mitigation,owner,evidence},...]
    data_sources             jsonb NOT NULL DEFAULT '[]'::jsonb,
    potential_harms          jsonb NOT NULL DEFAULT '[]'::jsonb,
    mitigations              jsonb NOT NULL DEFAULT '[]'::jsonb,
    fairness_considerations  text,
    privacy_considerations   text,
    -- Required (NOT NULL) only when tier >= limited; the application
    -- layer enforces this since the DB does not know the parent tier.
    human_oversight_plan     text,
    completed_at             timestamptz,
    completed_by             varchar(200),
    notes                    text,
    UNIQUE (intake_id, version)
);


-- ── INTAKE REQUIREMENTS ──────────────────────────────────────
-- Business / functional / non-functional / compliance requirements
-- raised under a specific intake. parent_requirement_id permits a
-- BR -> FR decomposition tree.
--
-- embedding columns (vector(384) BGE-small via fastembed) power
-- semantic search and redundancy detection. embedding_input_hash
-- is the staleness sentinel (SHA-256 of the embedded text).

CREATE TABLE IF NOT EXISTS governance.intake_requirement (
    id                         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                  uuid NOT NULL
                                   REFERENCES governance.intake(id) ON DELETE CASCADE,
    code                       varchar(40) NOT NULL,
    kind                       governance.requirement_kind NOT NULL,
    statement                  text NOT NULL,
    acceptance_criteria        text,
    source                     text,
    status                     governance.requirement_status NOT NULL DEFAULT 'draft',
    parent_requirement_id      uuid REFERENCES governance.intake_requirement(id) ON DELETE SET NULL,

    embedding                  vector(384),
    embedding_model_id         uuid REFERENCES compliance.embedding_config(id),
    embedding_input_hash       bytea,

    created_by                 varchar(200) NOT NULL,
    acting_as_role             governance.studio_role,
    updated_at                 timestamptz NOT NULL DEFAULT now(),
    UNIQUE (intake_id, code)
);

CREATE INDEX IF NOT EXISTS idx_req_intake
    ON governance.intake_requirement(intake_id);
CREATE INDEX IF NOT EXISTS idx_req_status
    ON governance.intake_requirement(status);

-- IVFFlat index on the embedding column. Wrapped in DO $$ ... $$ so
-- re-running the migration is safe; CREATE INDEX IF NOT EXISTS doesn't
-- play well with USING ivfflat across some pgvector versions.
DO $$ BEGIN
    CREATE INDEX idx_req_embedding
        ON governance.intake_requirement
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100);
EXCEPTION WHEN duplicate_table THEN NULL;
        WHEN undefined_object THEN NULL;  -- no rows yet; index built later
END $$;


-- ── ENTITY LINK (bridge to registry) ─────────────────────────
-- Polymorphic FK to registry artifacts. entity_type is the existing
-- governance.entity_type enum (extended above). entity_id is validated
-- in the application layer per kind, matching the convention used by
-- entity_prompt_assignment and application_entity.

CREATE TABLE IF NOT EXISTS governance.intake_entity_link (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id           uuid NOT NULL
                            REFERENCES governance.intake(id) ON DELETE CASCADE,
    requirement_id      uuid REFERENCES governance.intake_requirement(id) ON DELETE SET NULL,
    entity_type         governance.entity_type NOT NULL,
    entity_id           uuid NOT NULL,
    relationship        governance.requirement_relationship NOT NULL DEFAULT 'implements',
    created_by          varchar(200) NOT NULL,
    acting_as_role      governance.studio_role,
    created_at          timestamptz NOT NULL DEFAULT now(),
    -- (intake, requirement, entity, relationship) is a unique edge.
    -- requirement_id IS NULL for "intake-level" links; multiple NULLs
    -- with the same entity are handled via a partial unique index below.
    UNIQUE (intake_id, requirement_id, entity_type, entity_id, relationship)
);

CREATE INDEX IF NOT EXISTS idx_link_intake
    ON governance.intake_entity_link(intake_id);
CREATE INDEX IF NOT EXISTS idx_link_entity
    ON governance.intake_entity_link(entity_type, entity_id);


-- ── ARTIFACT PLAN ────────────────────────────────────────────
-- The "what we plan to build" list. Auto-generated on intake approval
-- by the rule-based plan generator (see plan_generator.py); engineers
-- add/edit/realize rows from Studio.

CREATE TABLE IF NOT EXISTS governance.intake_artifact_plan (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id                   uuid NOT NULL
                                    REFERENCES governance.intake(id) ON DELETE CASCADE,
    requirement_id              uuid REFERENCES governance.intake_requirement(id) ON DELETE SET NULL,
    proposed_kind               governance.entity_type NOT NULL,
    proposed_name               varchar(120) NOT NULL,
    proposed_display_name       text NOT NULL,
    proposed_description        text,
    proposed_purpose            text,
    proposed_inputs             jsonb DEFAULT '{}'::jsonb,
    proposed_outputs            jsonb DEFAULT '{}'::jsonb,
    -- Only populated when proposed_kind = 'task'. Agents have no
    -- capability_type column in the registry.
    proposed_capability_type    governance.capability_type,
    proposed_materiality_tier   governance.materiality_tier NOT NULL,
    -- Set when an engineer realizes this plan row by creating the
    -- corresponding registry entity. Once set, an intake_entity_link
    -- row connects the plan to the registry entity for traceability.
    realized_entity_id          uuid,
    status                      governance.artifact_plan_status NOT NULL DEFAULT 'proposed',
    auto_generated              boolean NOT NULL DEFAULT false,
    created_by                  varchar(200) NOT NULL,
    acting_as_role              governance.studio_role,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (intake_id, proposed_kind, proposed_name)
);

CREATE INDEX IF NOT EXISTS idx_plan_intake
    ON governance.intake_artifact_plan(intake_id);
CREATE INDEX IF NOT EXISTS idx_plan_status
    ON governance.intake_artifact_plan(status);


-- ── APPROVAL REQUEST ─────────────────────────────────────────
-- One row per gating event. required_roles is a JSONB array because
-- it's set per-request based on the intake's risk tier (see § 4.2 of
-- governance-intake.md).

CREATE TABLE IF NOT EXISTS governance.approval_request (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id               uuid NOT NULL
                                REFERENCES governance.intake(id) ON DELETE CASCADE,
    kind                    governance.approval_request_kind NOT NULL,
    -- Only populated for kind IN ('promote_candidate','promote_champion');
    -- NULL for intake / risk_reclassification / retire.
    target_entity_type      governance.entity_type,
    target_entity_id        uuid,
    -- e.g. ["business_owner","compliance","legal","model_risk","ai_governance"]
    required_roles          jsonb NOT NULL,
    status                  varchar(20) NOT NULL DEFAULT 'pending',
    opened_at               timestamptz NOT NULL DEFAULT now(),
    opened_by               varchar(200) NOT NULL,
    opened_by_role          governance.studio_role,
    decided_at              timestamptz,
    summary                 text NOT NULL,
    notes                   text
);

CREATE INDEX IF NOT EXISTS idx_approval_req_intake
    ON governance.approval_request(intake_id);
CREATE INDEX IF NOT EXISTS idx_approval_req_status
    ON governance.approval_request(status);


-- ── APPROVAL SIGNOFF ─────────────────────────────────────────
-- One row per approver per request. UNIQUE prevents a single email
-- from signing off twice in the same role on the same request.

CREATE TABLE IF NOT EXISTS governance.approval_signoff (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_request_id     uuid NOT NULL
                                REFERENCES governance.approval_request(id) ON DELETE CASCADE,
    role                    governance.approval_role NOT NULL,
    approver_name           varchar(200) NOT NULL,
    approver_email          varchar(200),
    decision                governance.approval_decision NOT NULL,
    comment                 text,
    evidence_url            text,
    signed_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (approval_request_id, role, approver_email)
);

CREATE INDEX IF NOT EXISTS idx_signoff_request
    ON governance.approval_signoff(approval_request_id);


-- ── COMPLIANCE BRIDGE — REMOVED ──────────────────────────────
-- An earlier draft of this file added a per-intake `intake_canonical_link`
-- bridge to compliance.canonical_requirement, plus an embedding-based
-- suggester. Both were wrong abstractions:
--   1. Compliance attaches to *capability* (Verity features), not to
--      individual intake instances. Mapping every intake to canonicals
--      is duplicate work and the wrong unit.
--   2. Embedding similarity on intake text → canonical text is mostly
--      noise — the two corpora describe different things (business
--      outcomes vs. regulatory obligations).
-- The corrected approach:
--   - Verity intake-module features go into compliance.feature
--   - They link to canonical_requirements via requirement_feature_link
--   - requirement_coverage carries the authored compliance prose
-- See docs/architecture/governance-intake.md § 9 (revised).
