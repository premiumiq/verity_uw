-- ============================================================
-- EDMS: Enterprise Document Management System
-- Lives in edms_db (separate from verity_db and pas_db)
--
-- Tables:
--   tag_definition              — governed tag keys and value control
--   tag_allowed_value           — allowed values for restricted tag keys
--   document_type_definition    — governed document type vocabulary (two-level)
--   context_type_definition     — governed context type vocabulary
--   collection                  — governed storage domains (map to MinIO buckets)
--   folder                      — virtual directory hierarchy within collections
--   document                    — registry of all files (originals + derived)
--   document_lineage            — parent-child transformation relationships
--   document_task               — tracks tasks performed on documents
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ── TAG GOVERNANCE ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tag_definition (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tag_key             VARCHAR(100) UNIQUE NOT NULL,
    display_name        VARCHAR(200) NOT NULL,
    description         TEXT,
    value_mode          VARCHAR(20) NOT NULL DEFAULT 'restricted',
    -- 'restricted' = only values from tag_allowed_value accepted
    -- 'freetext'   = any string value accepted
    is_required         BOOLEAN NOT NULL DEFAULT FALSE,
    sort_order          INTEGER DEFAULT 0,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tag_allowed_value (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tag_definition_id   UUID NOT NULL REFERENCES tag_definition(id) ON DELETE CASCADE,
    value               VARCHAR(200) NOT NULL,
    display_name        VARCHAR(200) NOT NULL,
    description         TEXT,
    sort_order          INTEGER DEFAULT 0,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tag_value UNIQUE (tag_definition_id, value)
);

CREATE INDEX IF NOT EXISTS idx_tav_tag ON tag_allowed_value(tag_definition_id);


-- ── DOCUMENT TYPE GOVERNANCE ─────────────────────────────────
-- Two-level hierarchy: type (top-level) and subtype (child).

CREATE TABLE IF NOT EXISTS document_type_definition (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_key            VARCHAR(100) UNIQUE NOT NULL,
    display_name        VARCHAR(200) NOT NULL,
    description         TEXT,
    parent_type_id      UUID REFERENCES document_type_definition(id),
    sort_order          INTEGER DEFAULT 0,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dtd_parent ON document_type_definition(parent_type_id);


-- ── CONTEXT TYPE GOVERNANCE ──────────────────────────────────
-- Controls what context_type values are allowed on documents.
-- Shown as a dropdown in the UI, not freetext.

CREATE TABLE IF NOT EXISTS context_type_definition (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type_key            VARCHAR(100) UNIQUE NOT NULL,
    -- Machine name (e.g., "submission", "policy", "claim")
    display_name        VARCHAR(200) NOT NULL,
    -- Human name (e.g., "Insurance Submission")
    description         TEXT,
    sort_order          INTEGER DEFAULT 0,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);


-- ── COLLECTION ───────────────────────────────────────────────
-- A collection is a governed storage domain. Maps 1:1 to a MinIO bucket.
-- Collections carry lifecycle status, default tags, and ownership.
-- Security (future) will be at the collection level.
--
-- Default tags cascade: collection -> folder -> document.
-- Each level's defaults are applied unless the level below overrides them.

CREATE TABLE IF NOT EXISTS collection (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(100) UNIQUE NOT NULL,
    -- Machine name (e.g., "submissions", "uw_guidelines")
    display_name        VARCHAR(200) NOT NULL,
    -- Human name (e.g., "Insurance Submissions")
    description         TEXT,

    -- Storage mapping (one MinIO bucket per collection)
    storage_provider    VARCHAR(50) NOT NULL DEFAULT 'minio',
    storage_container   VARCHAR(200) NOT NULL,
    -- MinIO bucket name (e.g., "submissions")

    -- Lifecycle
    status              VARCHAR(50) NOT NULL DEFAULT 'active',
    -- 'active'    = accepting new documents, full read/write
    -- 'readonly'  = no new uploads, existing docs accessible
    -- 'archived'  = no access without explicit unarchive
    -- 'locked'    = regulatory hold, no modifications allowed

    -- Default tags: cascade to all folders and documents in this collection.
    -- Folders can override. Documents can override.
    -- e.g., {"sensitivity": ["internal"], "lob": ["do"]}
    default_tags        JSONB DEFAULT '{}',

    -- Ownership
    owner_name          VARCHAR(200) NOT NULL,
    created_by          VARCHAR(200) NOT NULL,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW()
);


-- ── FOLDER ───────────────────────────────────────────────────
-- Virtual directory hierarchy within a collection.
-- Folders are metadata-only — they don't change MinIO storage structure.
-- Default tags cascade: folder overrides/extends collection defaults.

CREATE TABLE IF NOT EXISTS folder (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    collection_id       UUID NOT NULL REFERENCES collection(id) ON DELETE CASCADE,
    parent_folder_id    UUID REFERENCES folder(id),
    -- NULL = direct child of the collection root.

    name                VARCHAR(200) NOT NULL,
    description         TEXT,

    -- Folder-level tag defaults (merged with collection defaults, overrideable)
    default_tags        JSONB DEFAULT '{}',

    created_by          VARCHAR(200) NOT NULL DEFAULT 'system',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_folder_in_collection UNIQUE (collection_id, parent_folder_id, name)
);

CREATE INDEX IF NOT EXISTS idx_folder_collection ON folder(collection_id);
CREATE INDEX IF NOT EXISTS idx_folder_parent ON folder(parent_folder_id);


-- ── DOCUMENT ─────────────────────────────────────────────────
-- Every file in the system. Belongs to exactly one collection (mandatory).
-- Optionally in a folder within that collection.
-- storage_container is derived from collection.storage_container.

CREATE TABLE IF NOT EXISTS document (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Location: collection (mandatory) + folder (optional)
    collection_id       UUID NOT NULL REFERENCES collection(id),
    folder_id           UUID REFERENCES folder(id),

    -- Business context
    context_ref         VARCHAR(500) NOT NULL,
    context_type        VARCHAR(100),
    -- Validated against context_type_definition by service layer

    -- File identity
    filename            VARCHAR(500) NOT NULL,
    content_type        VARCHAR(100),
    file_size_bytes     INTEGER,

    -- Storage location
    storage_provider    VARCHAR(50) NOT NULL DEFAULT 'minio',
    storage_key         VARCHAR(500) NOT NULL,
    -- Key within the collection's bucket. Includes folder path for organization.

    -- Classification (validated against document_type_definition by service)
    document_type       VARCHAR(100),

    -- Tags: merge of collection defaults + folder defaults + document-specific.
    -- This stores the document's OWN tags (overrides/additions).
    -- Effective tags = collection.default_tags merged with folder chain defaults
    --                  merged with document.tags
    tags                JSONB DEFAULT '{}',

    -- Lineage
    uploaded_by         VARCHAR(200) NOT NULL,
    uploaded_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    notes               TEXT,

    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_collection ON document(collection_id);
CREATE INDEX IF NOT EXISTS idx_doc_folder ON document(folder_id);
CREATE INDEX IF NOT EXISTS idx_doc_context ON document(context_ref);
CREATE INDEX IF NOT EXISTS idx_doc_type ON document(document_type);
CREATE INDEX IF NOT EXISTS idx_doc_tags ON document USING GIN(tags);


-- ── DOCUMENT LINEAGE ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS document_lineage (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_document_id      UUID NOT NULL REFERENCES document(id),
    child_document_id       UUID NOT NULL REFERENCES document(id),
    transformation_type     VARCHAR(100) NOT NULL,
    transformation_method   VARCHAR(200),
    transformation_status   VARCHAR(50) NOT NULL DEFAULT 'complete',
    transformation_error    TEXT,
    transformation_metadata JSONB DEFAULT '{}',
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_lineage UNIQUE (parent_document_id, child_document_id, transformation_type)
);

CREATE INDEX IF NOT EXISTS idx_dl_parent ON document_lineage(parent_document_id);
CREATE INDEX IF NOT EXISTS idx_dl_child ON document_lineage(child_document_id);


-- ── DOCUMENT TASKS ───────────────────────────────────────────

CREATE TABLE IF NOT EXISTS document_task (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id         UUID NOT NULL REFERENCES document(id) ON DELETE CASCADE,
    task_type           VARCHAR(100) NOT NULL,
    task_method         VARCHAR(200),
    status              VARCHAR(50) NOT NULL DEFAULT 'pending',
    progress_pct        INTEGER DEFAULT 0,
    started_at          TIMESTAMP,
    completed_at        TIMESTAMP,
    duration_ms         INTEGER,
    result_document_id  UUID REFERENCES document(id),
    result_summary      TEXT,
    error_message       TEXT,
    initiated_by        VARCHAR(200) NOT NULL DEFAULT 'system',
    task_metadata       JSONB DEFAULT '{}',
    created_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dt_document ON document_task(document_id);
CREATE INDEX IF NOT EXISTS idx_dt_status ON document_task(status);
