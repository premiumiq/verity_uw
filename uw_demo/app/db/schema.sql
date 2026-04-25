-- UW Application Database Schema (uw_db)
--
-- Pre-bind underwriting data: submissions, extracted fields, assessments.
-- This is NOT PAS (Policy Administration System) — PAS is post-bind.
--
-- Conventions:
--   - gen_random_uuid() for primary keys (requires uuid-ossp extension)
--   - TIMESTAMPTZ for all timestamps (timezone-aware)
--   - JSONB for flexible structured data (risk factors, citations, etc.)
--   - Foreign keys with ON DELETE CASCADE where appropriate

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION: The core intake record from broker/insured
-- ══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS submission (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Business identifiers
    named_insured       TEXT NOT NULL,
    lob                 TEXT NOT NULL,           -- DO, GL
    fein                TEXT,                    -- Federal Employer ID
    entity_type         TEXT,                    -- LLC, Corporation, etc.
    state_of_incorporation TEXT,
    sic_code            TEXT,
    sic_description     TEXT,
    -- Financials
    annual_revenue      BIGINT,
    employee_count      INTEGER,
    -- D&O-specific
    board_size          INTEGER,
    independent_directors INTEGER,
    -- Policy details
    effective_date      DATE,
    expiration_date     DATE,
    limits_requested    BIGINT,
    retention_requested BIGINT,
    prior_carrier       TEXT,
    prior_premium       BIGINT,
    -- Workflow status
    -- intake: just received
    -- documents_processed: Pipeline 1 complete (classify + extract)
    -- review: HITL reviewing extracted fields
    -- approved: fields finalized, ready for risk assessment
    -- triaged: Pipeline 2 step 1 complete
    -- assessed: Pipeline 2 complete (triage + appetite)
    status              TEXT NOT NULL DEFAULT 'intake',
    -- Verity workflow-run correlation ids (caller-supplied UUIDs the
    -- UW workflows generate per invocation; Verity sees them as
    -- agent_decision_log.workflow_run_id values).
    last_doc_workflow_run_id  UUID,   -- most recent doc-processing run
    last_risk_workflow_run_id UUID,   -- most recent risk-assessment run
    execution_context_id      UUID,   -- Verity execution context
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION_EXTRACTION: Per-field extraction results from Pipeline 1
-- ══════════════════════════════════════════════════════════════
-- One row per extracted field per submission. The classifier identifies
-- the document type; the extractor pulls fields from the application.
-- Low-confidence or missing fields are flagged for HITL review.

CREATE TABLE IF NOT EXISTS submission_extraction (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id       UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    -- Extraction result
    field_name          TEXT NOT NULL,            -- e.g. 'named_insured', 'annual_revenue'
    extracted_value     TEXT,                     -- value as extracted by AI (null if not found)
    confidence          REAL,                     -- 0.0 to 1.0
    extraction_notes    TEXT,                     -- AI's note about where/how it found the field
    needs_review        BOOLEAN NOT NULL DEFAULT FALSE,  -- flagged for HITL
    review_reason       TEXT,                     -- why flagged: 'low_confidence', 'missing', 'ambiguous'
    -- HITL override tracking
    overridden          BOOLEAN NOT NULL DEFAULT FALSE,
    override_value      TEXT,                     -- human-corrected value
    overridden_by       TEXT,                     -- who overrode it
    override_reason     TEXT,                     -- why the override was needed
    override_at         TIMESTAMPTZ,
    -- Finalized value (either extracted or overridden)
    -- Computed by the app: if overridden, use override_value; else use extracted_value
    -- Audit
    workflow_run_id     UUID,                     -- workflow-run correlation id from the UW app
    source_document_id  UUID,                     -- EDMS document ID the field was extracted from
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One extraction per field per submission
    UNIQUE(submission_id, field_name)
);

-- Index for finding all extractions needing review
CREATE INDEX IF NOT EXISTS idx_extraction_needs_review
    ON submission_extraction(submission_id, needs_review)
    WHERE needs_review = TRUE;

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION_ASSESSMENT: Triage and appetite results from Pipeline 2
-- ══════════════════════════════════════════════════════════════
-- One row per assessment type per submission. Stores the full
-- structured output from the triage agent and appetite agent.

CREATE TABLE IF NOT EXISTS submission_assessment (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id       UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    assessment_type     TEXT NOT NULL,             -- 'triage' or 'appetite'
    -- Results
    result              JSONB NOT NULL,            -- full structured output from agent
    -- Key fields extracted for quick access / filtering
    risk_score          TEXT,                      -- Green, Amber, Red (triage only)
    routing             TEXT,                      -- assign_to_uw, refer_to_management, etc. (triage only)
    determination       TEXT,                      -- within_appetite, borderline, outside_appetite (appetite only)
    confidence          REAL,
    reasoning           TEXT,
    -- Audit
    workflow_run_id     UUID,                      -- workflow-run correlation id from the UW app
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One assessment per type per submission (latest wins)
    UNIQUE(submission_id, assessment_type)
);

-- ══════════════════════════════════════════════════════════════
-- LOSS HISTORY: Claims data per submission account
-- ══════════════════════════════════════════════════════════════
-- In production this would come from a loss run system or carrier API.
-- For the demo, seeded with realistic data.

-- ══════════════════════════════════════════════════════════════
-- WORKFLOW_STEP: Tracks progression through the underwriting workflow
-- ══════════════════════════════════════════════════════════════
-- Each submission has 5 workflow steps. Step 1 (intake) is auto-completed
-- on seed. Steps 2-5 are triggered by user actions in the UW app.
-- The stepper component in the UI reads from this table.

CREATE TABLE IF NOT EXISTS workflow_step (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id       UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    step_name           TEXT NOT NULL,             -- intake, document_processing, extraction_review, triage, appetite
    step_order          INTEGER NOT NULL,          -- 1-5, determines stepper display order
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending, running, complete, failed, skipped
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    completed_by        TEXT,                      -- who triggered or approved this step
    workflow_run_id     UUID,                      -- workflow-run correlation id from the UW app
    notes               TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(submission_id, step_name)
);

-- ══════════════════════════════════════════════════════════════
-- LOSS HISTORY: Claims data per submission account
-- ══════════════════════════════════════════════════════════════
-- In production this would come from a loss run system or carrier API.
-- For the demo, seeded with realistic data.

-- ══════════════════════════════════════════════════════════════
-- APP_SETTINGS: Key-value configuration (no restart needed)
-- ══════════════════════════════════════════════════════════════
-- Read on every request. Change a row in the DB and the next
-- request picks it up. No container restart required.

CREATE TABLE IF NOT EXISTS app_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    description         TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
-- LOSS HISTORY: Claims data per submission account
-- ══════════════════════════════════════════════════════════════
-- In production this would come from a loss run system or carrier API.
-- For the demo, seeded with realistic data.

CREATE TABLE IF NOT EXISTS loss_history (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id       UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    policy_year         INTEGER NOT NULL,
    claims_count        INTEGER NOT NULL DEFAULT 0,
    incurred            NUMERIC(15,2) NOT NULL DEFAULT 0,
    paid                NUMERIC(15,2) NOT NULL DEFAULT 0,
    reserves            NUMERIC(15,2) NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
