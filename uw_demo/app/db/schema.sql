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
-- STAGE-AWARE STATE MACHINE
-- ══════════════════════════════════════════════════════════════
-- Two orthogonal dimensions of submission lifecycle live in two
-- enums: which *stage* of the workflow we're in, and what's
-- *happening within* that stage. A submission has one
-- `submission_stage` row per stage; the active stage is the
-- lowest-priority one whose status isn't `complete`. This model
-- supports re-entry (Information Review can pull Document
-- Processing back to running when a new doc is uploaded) and
-- distinguishes "stage running" from "stage blocked on input"
-- without overloading a flat enum.
--
-- Stages:
--   intake               — submission record exists; nothing else done
--   document_processing  — discovery + classify + extract
--   information_review   — HITL reviewing extracted fields
--   triage               — risk-triage agent
--   appetite             — appetite-assessment agent
--   declined             — terminal: outside appetite or rejected
--
-- Status within a stage:
--   pending           — not yet started
--   running           — in progress (Verity run live, or HITL engaged)
--   blocked_on_input  — waiting on human or external input
--   complete          — finished successfully (passed through)
--   failed            — terminal failure for this entry; retry creates a new run

DO $$ BEGIN
    CREATE TYPE submission_stage_enum AS ENUM (
        'intake',
        'document_processing',
        'information_review',
        'triage',
        'appetite',
        'declined'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE stage_status_enum AS ENUM (
        'pending',
        'running',
        'blocked_on_input',
        'complete',
        'failed'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

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
    -- NOTE: there is no `status` column. Stage info lives in the
    -- `submission_stage` table (one row per stage). The "current
    -- stage" of a submission is derived: the lowest-priority stage
    -- whose status is not `complete`. The state.py helper owns the
    -- derivation logic.
    -- Verity workflow-run correlation ids (caller-supplied UUIDs the
    -- UW workflows generate per invocation; Verity sees them as
    -- agent_decision_log.workflow_run_id values).
    last_doc_workflow_run_id  UUID,   -- most recent doc-processing run
    last_risk_workflow_run_id UUID,   -- most recent risk-assessment run
    execution_context_id      UUID,   -- Verity execution context
    -- Async pipeline tracking — set when a verity.submit_run() call
    -- has been made and the run hasn't reached a terminal state yet.
    -- The detail page polls /run-status every 2s while these are set.
    -- Cleared once the run completes (success or failure).
    pending_run_id      UUID,         -- Verity execution_run id of the in-flight run
    pending_run_kind    TEXT,         -- 'doc_processing' | 'risk_assessment'
    -- Timestamps
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION_STAGE: Per-submission, per-stage status
-- ══════════════════════════════════════════════════════════════
-- One row per (submission, stage). Tracks status, run history, and
-- re-entries. Replaces the old workflow_step table and the
-- submission.status column.
--
-- Re-entry semantics: a stage that previously completed can be
-- pulled back to running when a later stage detects new input
-- (e.g. Information Review uploads more docs → Document Processing
-- flips from complete to running). Re-entries flip status back to
-- 'running' and bump enter_count; we don't insert a second row
-- per stage.
--
-- last_run_id is the most recent Verity workflow_run_id for this
-- stage; used to deep-link the audit trail to that specific run.

CREATE TABLE IF NOT EXISTS submission_stage (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id   UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    stage           submission_stage_enum NOT NULL,
    status          stage_status_enum NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    blocked_reason  TEXT,
    last_run_id     UUID,
    enter_count     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(submission_id, stage)
);

CREATE INDEX IF NOT EXISTS idx_submission_stage_sub
    ON submission_stage(submission_id);

CREATE INDEX IF NOT EXISTS idx_submission_stage_status
    ON submission_stage(submission_id, status);

-- ══════════════════════════════════════════════════════════════
-- DOCUMENT: Per-submission document references
-- ══════════════════════════════════════════════════════════════
-- One row per document UW cares about for a submission. The actual
-- file content lives in EDMS (a separate database/service); we keep
-- only a reference plus the metadata UW needs to display, route, and
-- track per-document extraction status.
--
-- Why this table exists, given documents already live in EDMS:
--   1. # Docs column on the submissions list — single SQL join
--      instead of one HTTP round-trip per row.
--   2. Documents tab on the detail page — render from uw_db so the
--      page doesn't break if EDMS is briefly unreachable.
--   3. Per-document extraction tracking — UW knows which docs have
--      been classified vs extracted vs skipped (not_applicable).
--   4. Discovery → extraction split — discovery writes here once,
--      extraction reads from here, and re-runs are idempotent.
--
-- The edms_document_id is the EDMS-side UUID. It's a value, not a
-- foreign key, because the two databases are independent.
--
-- discovery_status: how this document arrived in the table.
--   'received'  — confirmed present in EDMS (the normal path)
--   'pending'   — UW expects it but EDMS hasn't seen it yet
--   'failed'    — EDMS lookup failed last attempt
--
-- extraction_status: where this document is in UW's pipeline.
--   'pending'        — has not been classified or extracted yet
--   'in_progress'    — a doc-processing run is currently working it
--   'complete'       — classifier + (any) extractor finished cleanly
--   'not_applicable' — classifier ran but no extractor is registered
--                      for this doc_type (e.g. loss_run, board_resolution).
--                      This is a normal terminal state, NOT a failure.

CREATE TABLE IF NOT EXISTS document (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id               UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    -- The reference into EDMS (cross-DB, so a value not an FK)
    edms_document_id            UUID NOT NULL,
    -- File-level metadata (mirrored from EDMS at discovery time)
    filename                    TEXT NOT NULL,
    content_type                TEXT,
    file_size_bytes             INTEGER,
    page_count                  INTEGER,
    -- Classification (filled by the classifier task at extraction time)
    document_type               TEXT,
    classification_confidence   REAL,
    -- Lifecycle flags (see comments above for value sets)
    discovery_status            TEXT NOT NULL DEFAULT 'received',
    extraction_status           TEXT NOT NULL DEFAULT 'pending',
    -- Timestamps
    received_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- One row per (submission, edms_document_id) pair — re-running
    -- discovery is a no-op (UPSERT) on the same EDMS document.
    UNIQUE(submission_id, edms_document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_submission
    ON document(submission_id);

CREATE INDEX IF NOT EXISTS idx_document_extraction_status
    ON document(extraction_status);

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION_EXTRACTION: Per-field extraction results from Pipeline 1
-- ══════════════════════════════════════════════════════════════
-- One row per (submission, field_name). Two distinct value channels
-- live on each row:
--
--   ai_*    — what the AI produced on the most recent extraction run.
--             Immutable for the life of that run. NULL on ai_value
--             does NOT imply "not yet extracted" — that's what
--             ai_found is for (FALSE = AI hasn't run; TRUE = AI ran
--             and either found a value or deliberately did not).
--
--   hitl_*  — human-corrected value, if any. NULL until a UW edits.
--             When non-NULL, the row is no longer "AI-authoritative"
--             and the sparkle UX hides for that field.
--
-- The current displayed value is hitl_value if present, else ai_value.
-- Provenance for the AI value lives on the row alongside (source doc,
-- page, snippet, Verity run id, JSONPath) so the override API has
-- everything it needs without lookups.

CREATE TABLE IF NOT EXISTS submission_extraction (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id            UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    field_name               TEXT NOT NULL,
    -- AI channel — what the model produced on the most recent run
    ai_value                 TEXT,
    ai_confidence            REAL,                     -- 0.0 to 1.0
    ai_found                 BOOLEAN NOT NULL DEFAULT FALSE,
    -- Provenance — where on what doc the AI extracted from
    source_document_id       UUID REFERENCES document(id) ON DELETE SET NULL,
    source_page              INTEGER,
    source_snippet           TEXT,                     -- verbatim quote, drives sparkle tooltip
    -- Verity traceability — needed by the HITL override API call
    verity_execution_run_id  UUID,
    output_path              TEXT,                     -- JSONPath inside the run output
    extractor_id             TEXT,                     -- agent/model identifier
    -- HITL channel — human-corrected value, if any
    hitl_value               TEXT,
    hitl_at                  TIMESTAMPTZ,
    hitl_by                  TEXT,
    -- Queue-population flags (separate from value channels)
    needs_review             BOOLEAN NOT NULL DEFAULT FALSE,
    review_reason            TEXT,                     -- 'low_confidence' | 'ai_not_found' | 'flagged_by_rule'
    -- UW-side workflow correlation
    workflow_run_id          UUID,
    -- Audit
    created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(submission_id, field_name)
);

-- Index for finding all extractions needing review
CREATE INDEX IF NOT EXISTS idx_extraction_needs_review
    ON submission_extraction(submission_id, needs_review)
    WHERE needs_review = TRUE;

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION_EXTRACTION_AUDIT: Append-only log of field changes
-- ══════════════════════════════════════════════════════════════
-- One row per change to a submission_extraction value (AI write,
-- HITL edit, HITL re-edit). Kept here rather than in the broader
-- submission_event because rows have field-specific shape (old/new
-- value diffs) that doesn't compress cleanly into JSONB.
--
-- was_ai_authoritative captures whether the value being overwritten
-- was the AI's (i.e. this change is an AI→HITL flip). When TRUE,
-- a hitl_override row is also written to verity_db via the override
-- API; that override id is stored here on hitl_override_id.

CREATE TABLE IF NOT EXISTS submission_extraction_audit (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id         UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    field_name            TEXT NOT NULL,
    old_value             TEXT,
    new_value             TEXT,
    -- TRUE when the prior value was the AI's; FALSE when HITL→HITL
    was_ai_authoritative  BOOLEAN,
    actor                 TEXT NOT NULL,
    changed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Cross-DB reference: id of the matching verity_db.hitl_override
    -- row when this change was an AI→HITL flip. NULL otherwise.
    hitl_override_id      UUID,
    -- Denormalized for filter speed on the audit-trail tab
    workflow_run_id       UUID
);

CREATE INDEX IF NOT EXISTS idx_extraction_audit_sub_time
    ON submission_extraction_audit(submission_id, changed_at DESC);

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

-- ══════════════════════════════════════════════════════════════
-- SUBMISSION_EVENT: UW-side audit log
-- ══════════════════════════════════════════════════════════════
-- Append-only feed of everything UW does to a submission: state
-- changes, user actions, pipeline lifecycle events, system events.
-- The Audit Trail tab merges these rows with submission_extraction_audit
-- and Verity's decision log into a single chronological timeline.
--
-- event_category buckets:
--   'state_change'  — submission.status transitioned
--                     payload: {"from": "intake", "to": "documents_received"}
--   'user_action'   — a UW clicked something / uploaded / approved
--                     payload: {"action": "upload_document", "filename": "..."}
--   'pipeline'      — submit / claim / complete / fail of a Verity run
--                     payload: {"kind": "doc_processing", "outcome": "complete"}
--   'system'        — anything UW-internal that isn't user-driven
--                     (auto-trigger after HITL approval, etc.)
--
-- payload is loose-shape JSONB on purpose: each event_type has its
-- own keys. Cross-refs (workflow_run_id, document_id, field_name)
-- are denormalized as columns so the audit-trail UI can filter
-- without unpacking JSON.

CREATE TABLE IF NOT EXISTS submission_event (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    submission_id   UUID NOT NULL REFERENCES submission(id) ON DELETE CASCADE,
    event_category  TEXT NOT NULL,    -- 'state_change' | 'user_action' | 'pipeline' | 'system'
    event_type      TEXT NOT NULL,    -- 'status_changed', 'document_uploaded', etc.
    actor           TEXT NOT NULL,    -- 'uw_user' | 'system' | username
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    payload         JSONB NOT NULL DEFAULT '{}',
    -- Optional cross-refs for drill-down and filtering
    workflow_run_id UUID,
    document_id     UUID,
    field_name      TEXT
);

CREATE INDEX IF NOT EXISTS idx_submission_event_sub_time
    ON submission_event(submission_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_submission_event_category
    ON submission_event(submission_id, event_category, occurred_at DESC);
