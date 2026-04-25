-- ============================================================
-- VERITY_DB: AI Trust & Compliance Metamodel
-- PremiumIQ Verity v3.0
--
-- Full schema with 7-state lifecycle, pgvector columns,
-- and all governance tables.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";  -- pgvector for description embeddings

-- ── ENUMERATIONS ─────────────────────────────────────────────

CREATE TYPE lifecycle_state AS ENUM (
    'draft',        -- being developed
    'candidate',    -- development complete; ready for staging tests
    'staging',      -- staging tests running
    'shadow',       -- running on production inputs; outputs not used
    'challenger',   -- running on defined % of production traffic
    'champion',     -- live production version
    'deprecated'    -- historical record only; not executable
);

CREATE TYPE deployment_channel AS ENUM (
    'development', 'staging', 'shadow', 'evaluation', 'production'
);

CREATE TYPE materiality_tier AS ENUM (
    'high',    -- influences underwriting decisions directly
    'medium',  -- supports decisions; no direct influence
    'low'      -- operational/process; no decision influence
);

CREATE TYPE capability_type AS ENUM (
    'classification',   -- doc type, risk category, appetite
    'extraction',       -- field extraction from documents
    'generation',       -- narrative, memo, letter generation
    'summarisation',    -- condensing information
    'matching',         -- entity resolution, MDM matching
    'validation'        -- checking completeness or correctness
);

CREATE TYPE trust_level AS ENUM (
    'trusted', 'conditional', 'sandboxed', 'blocked'
);

CREATE TYPE data_classification AS ENUM (
    'tier1_public', 'tier2_internal', 'tier3_confidential', 'tier4_pii_restricted'
);

CREATE TYPE entity_type AS ENUM (
    'agent', 'task', 'prompt', 'tool'
);

CREATE TYPE governance_tier AS ENUM (
    'behavioural',  -- defines reasoning/output behaviour; full lifecycle required
    'contextual',   -- structures runtime input; lightweight versioning
    'formatting'    -- technical output format; minimal governance
);

CREATE TYPE api_role AS ENUM (
    'system',             -- system prompt passed as system= parameter
    'user',               -- user message template
    'assistant_prefill'   -- pre-filled assistant turn (rare)
);

CREATE TYPE metric_type AS ENUM (
    'exact_match',          -- output must exactly equal expected
    'schema_valid',         -- output must conform to schema
    'field_accuracy',       -- per-field accuracy for extraction tasks
    'classification_f1',    -- precision/recall/F1 for classification tasks
    'semantic_similarity',  -- embedding cosine similarity vs expected
    'human_rubric'          -- requires SME qualitative review
);

-- Ground truth dataset lifecycle status
CREATE TYPE gt_dataset_status AS ENUM (
    'collecting',    -- records being gathered, not yet ready for labeling
    'labeling',      -- annotations in progress
    'adjudicating',  -- disagreements being resolved
    'ready',         -- all records have an authoritative annotation
    'deprecated'     -- superseded by a newer dataset version
);

-- Ground truth quality classification
CREATE TYPE gt_quality_tier AS ENUM (
    'silver',   -- single annotator, no independent review
    'gold'      -- multi-annotator with IAA check, adjudication where needed
);

-- Ground truth record source type
CREATE TYPE gt_source_type AS ENUM (
    'document',     -- a real insurance document (ACORD form, loss run, etc.)
    'submission',   -- a full submission context (for agent testing)
    'synthetic'     -- generated test case, no real source document
);

-- Ground truth annotator type
CREATE TYPE gt_annotator_type AS ENUM (
    'human_sme',      -- domain expert (underwriter, compliance analyst)
    'llm_judge',      -- LLM evaluating against a rubric
    'adjudicator'     -- senior SME resolving a disagreement
);

-- Why an execution happened (independent of channel and mock_mode)
CREATE TYPE run_purpose AS ENUM (
    'production',       -- normal business execution
    'test',             -- test suite run
    'validation',       -- ground truth validation
    'audit_rerun'       -- historical reproduction
);


-- ── INFERENCE CONFIGURATION ──────────────────────────────────
-- Named, reusable LLM API parameter sets.

CREATE TABLE inference_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT NOT NULL,
    intended_use    TEXT NOT NULL,

    -- LLM API parameters
    model_name      VARCHAR(100) NOT NULL DEFAULT 'claude-sonnet-4-20250514',
    temperature     NUMERIC(4,3),
    max_tokens      INTEGER,
    top_p           NUMERIC(4,3),
    top_k           INTEGER,
    stop_sequences  TEXT[],

    -- Extended parameters (thinking, caching, batch, etc.)
    extended_params JSONB DEFAULT '{}',

    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);


-- ── AGENTS ───────────────────────────────────────────────────
-- Goal-directed Claude invocations that autonomously decide tool
-- call sequences. Use for complex synthesis and multi-step reasoning.

CREATE TABLE agent (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                        VARCHAR(100) UNIQUE NOT NULL,
    display_name                VARCHAR(200) NOT NULL,
    description                 TEXT NOT NULL,

    -- pgvector: description embedding for similarity checking
    description_embedding       vector(1536),
    description_embedding_model VARCHAR(100),
    last_similarity_check_at    TIMESTAMP,
    similarity_flags            JSONB DEFAULT '[]',

    purpose                     TEXT NOT NULL,
    domain                      VARCHAR(100) DEFAULT 'underwriting',
    materiality_tier            materiality_tier NOT NULL,

    -- Ownership
    owner_name                  VARCHAR(200) NOT NULL,
    owner_email                 VARCHAR(200),

    -- Regulatory documentation
    business_context            TEXT,
    known_limitations           TEXT,
    regulatory_notes            TEXT,

    -- Pointer to current champion version
    current_champion_version_id UUID,

    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_agent_name ON agent(name);
CREATE INDEX idx_agent_materiality ON agent(materiality_tier);


CREATE TABLE agent_version (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id                    UUID NOT NULL REFERENCES agent(id),

    -- Version numbering
    major_version               INTEGER NOT NULL DEFAULT 1,
    minor_version               INTEGER NOT NULL DEFAULT 0,
    patch_version               INTEGER NOT NULL DEFAULT 0,
    version_label               VARCHAR(20) GENERATED ALWAYS AS
                                (major_version::text || '.' ||
                                 minor_version::text || '.' ||
                                 patch_version::text) STORED,

    -- Lifecycle (full 7-state)
    lifecycle_state             lifecycle_state NOT NULL DEFAULT 'draft',
    channel                     deployment_channel NOT NULL DEFAULT 'development',

    -- Configuration — sourced from Verity at runtime, never hardcoded
    inference_config_id         UUID NOT NULL REFERENCES inference_config(id),
    -- Declared caller-facing contract. Required for agents that participate
    -- in multi-step workflows; existing agents get '{}' as a placeholder so
    -- seeding keeps working during migration. Admit-time validator rejects
    -- empty schemas when promoting an agent version out of draft.
    input_schema                JSONB NOT NULL DEFAULT '{}',
    output_schema               JSONB,
    authority_thresholds        JSONB DEFAULT '{}',
    mock_mode_enabled           BOOLEAN DEFAULT FALSE,
    decision_log_detail         VARCHAR(20) DEFAULT 'standard',  -- full, standard, summary, metadata, none
    shadow_traffic_pct          NUMERIC(5,4) DEFAULT 0,
    challenger_traffic_pct      NUMERIC(5,4) DEFAULT 0,

    -- Validation gates
    staging_tests_passed        BOOLEAN,
    ground_truth_passed         BOOLEAN,
    fairness_passed             BOOLEAN,
    shadow_period_complete      BOOLEAN DEFAULT FALSE,
    challenger_period_complete  BOOLEAN DEFAULT FALSE,

    -- Change tracking
    developer_name              VARCHAR(200),
    change_summary              TEXT,
    limitations_this_version    TEXT,
    change_type                 VARCHAR(20),

    -- Provenance: set when this version was created via the clone workflow.
    cloned_from_version_id      UUID REFERENCES agent_version(id),

    -- Timestamps
    valid_from                  TIMESTAMP,
    valid_to                    TIMESTAMP,
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_agent_version UNIQUE (agent_id, major_version, minor_version, patch_version)
);

CREATE INDEX idx_av_agent ON agent_version(agent_id);
CREATE INDEX idx_av_state ON agent_version(lifecycle_state);


-- ── TASKS ────────────────────────────────────────────────────
-- Bounded, single-purpose Claude invocations with defined I/O.

CREATE TABLE task (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                        VARCHAR(100) UNIQUE NOT NULL,
    display_name                VARCHAR(200) NOT NULL,
    description                 TEXT NOT NULL,

    -- pgvector: description embedding for similarity checking
    description_embedding       vector(1536),
    description_embedding_model VARCHAR(100),
    last_similarity_check_at    TIMESTAMP,
    similarity_flags            JSONB DEFAULT '[]',

    capability_type             capability_type NOT NULL,
    purpose                     TEXT NOT NULL,
    domain                      VARCHAR(100) DEFAULT 'underwriting',
    materiality_tier            materiality_tier NOT NULL,

    -- Input/output contract
    input_schema                JSONB NOT NULL,
    output_schema               JSONB NOT NULL,

    -- Ownership
    owner_name                  VARCHAR(200) NOT NULL,
    owner_email                 VARCHAR(200),

    -- Regulatory documentation
    business_context            TEXT,
    known_limitations           TEXT,
    regulatory_notes            TEXT,

    current_champion_version_id UUID,

    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_task_name ON task(name);
CREATE INDEX idx_task_capability ON task(capability_type);


CREATE TABLE task_version (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id                     UUID NOT NULL REFERENCES task(id),

    major_version               INTEGER NOT NULL DEFAULT 1,
    minor_version               INTEGER NOT NULL DEFAULT 0,
    patch_version               INTEGER NOT NULL DEFAULT 0,
    version_label               VARCHAR(20) GENERATED ALWAYS AS
                                (major_version::text || '.' ||
                                 minor_version::text || '.' ||
                                 patch_version::text) STORED,

    lifecycle_state             lifecycle_state NOT NULL DEFAULT 'draft',
    channel                     deployment_channel NOT NULL DEFAULT 'development',

    inference_config_id         UUID NOT NULL REFERENCES inference_config(id),
    output_schema               JSONB,
    mock_mode_enabled           BOOLEAN DEFAULT FALSE,
    decision_log_detail         VARCHAR(20) DEFAULT 'standard',  -- full, standard, summary, metadata, none
    shadow_traffic_pct          NUMERIC(5,4) DEFAULT 0,
    challenger_traffic_pct      NUMERIC(5,4) DEFAULT 0,

    staging_tests_passed        BOOLEAN,
    ground_truth_passed         BOOLEAN,
    fairness_passed             BOOLEAN,

    developer_name              VARCHAR(200),
    change_summary              TEXT,
    change_type                 VARCHAR(20),

    cloned_from_version_id      UUID REFERENCES task_version(id),

    valid_from                  TIMESTAMP,
    valid_to                    TIMESTAMP,
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_task_version UNIQUE (task_id, major_version, minor_version, patch_version)
);

CREATE INDEX idx_tv_task ON task_version(task_id);
CREATE INDEX idx_tv_state ON task_version(lifecycle_state);


-- ── PROMPTS ──────────────────────────────────────────────────
-- Reusable text artifacts managed with independent versioning.

CREATE TABLE prompt (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200) UNIQUE NOT NULL,
    display_name    VARCHAR(300) NOT NULL,
    description     TEXT NOT NULL,
    primary_entity_type  entity_type,
    primary_entity_id    UUID,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE prompt_version (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prompt_id           UUID NOT NULL REFERENCES prompt(id),

    -- 3-part versioning — consistent with agent_version and task_version
    major_version       INTEGER NOT NULL DEFAULT 1,
    minor_version       INTEGER NOT NULL DEFAULT 0,
    patch_version       INTEGER NOT NULL DEFAULT 0,
    version_label       VARCHAR(20) GENERATED ALWAYS AS
                        (major_version::text || '.' ||
                         minor_version::text || '.' ||
                         patch_version::text) STORED,

    content             TEXT NOT NULL,
    -- Declared template variables extracted from {{...}} placeholders in content.
    -- Auto-populated on registration. Validated at execution time to catch
    -- missing context values before sending prompts to Claude.
    template_variables  TEXT[] DEFAULT '{}',
    api_role            api_role NOT NULL DEFAULT 'system',
    governance_tier     governance_tier NOT NULL DEFAULT 'behavioural',

    -- pgvector: content embedding for similarity checking
    content_embedding   vector(1536),
    content_embedding_model VARCHAR(100),

    lifecycle_state     lifecycle_state NOT NULL DEFAULT 'draft',

    change_summary      TEXT NOT NULL,
    sensitivity_level   VARCHAR(20) DEFAULT 'high',
    author_name         VARCHAR(200),

    approved_by         VARCHAR(200),
    approved_at         TIMESTAMP,
    test_required       BOOLEAN GENERATED ALWAYS AS
                        (governance_tier = 'behavioural') STORED,
    staging_tests_passed BOOLEAN,

    cloned_from_version_id UUID REFERENCES prompt_version(id),

    -- Temporal validity (SCD Type 2) — set by lifecycle management
    valid_from          TIMESTAMP,
    valid_to            TIMESTAMP,

    created_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_prompt_version UNIQUE (prompt_id, major_version, minor_version, patch_version)
);

CREATE INDEX idx_pv_prompt ON prompt_version(prompt_id);
CREATE INDEX idx_pv_state ON prompt_version(lifecycle_state);
CREATE INDEX idx_pv_tier ON prompt_version(governance_tier);


-- ── ENTITY-PROMPT ASSIGNMENT ──────────────────────────────────
-- Many-to-many: which prompt versions are active for a given
-- agent_version or task_version.

CREATE TABLE entity_prompt_assignment (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type         entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id   UUID NOT NULL,

    prompt_version_id   UUID NOT NULL REFERENCES prompt_version(id),
    api_role            api_role NOT NULL,
    governance_tier     governance_tier NOT NULL,
    execution_order     INTEGER NOT NULL DEFAULT 1,
    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    condition_logic     JSONB,

    created_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_entity_prompt UNIQUE (entity_type, entity_version_id, prompt_version_id, api_role)
);

CREATE INDEX idx_epa_entity ON entity_prompt_assignment(entity_type, entity_version_id);


-- ── MCP SERVERS ──────────────────────────────────────────────
-- Registry of Model Context Protocol servers Verity can dispatch tools to.
-- Each row represents one MCP server (stdio subprocess or remote endpoint);
-- the tool table references this table via tool.mcp_server_name for tools
-- whose transport is one of the mcp_* variants.
--
-- Added in Phase 4a / FC-14 (MCP tool integration).

CREATE TABLE mcp_server (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,

    -- Transport type.
    --   'stdio' — spawn a subprocess (command + args); speak MCP over stdin/stdout
    --   'sse'   — connect to an SSE endpoint at `url`
    --   'http'  — call a JSON-RPC HTTP endpoint at `url`
    transport       VARCHAR(50) NOT NULL,

    -- stdio transport: how to launch the server. Ignored for sse/http.
    command         VARCHAR(500),
    args            TEXT[] DEFAULT '{}',

    -- sse/http transport: where to reach the server. Ignored for stdio.
    url             VARCHAR(500),

    -- Environment variables passed to the subprocess (stdio) or extra
    -- request headers (sse/http). JSONB because values may be structured.
    env             JSONB NOT NULL DEFAULT '{}',

    -- Auth config (API keys, bearer tokens, OAuth client IDs, etc).
    -- Kept as JSONB so we can evolve without schema changes.
    auth_config     JSONB NOT NULL DEFAULT '{}',

    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_mcp_server_name ON mcp_server(name);


-- ── TOOLS ────────────────────────────────────────────────────
-- Callable actions registered with governed descriptions. A tool is
-- either dispatched in-process as a registered Python callable
-- (transport='python_inprocess') or forwarded to an MCP server
-- (transport='mcp_*', mcp_server_name points at mcp_server.name).

CREATE TABLE tool (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                        VARCHAR(100) UNIQUE NOT NULL,
    display_name                VARCHAR(200) NOT NULL,
    description                 TEXT NOT NULL,

    -- pgvector: description embedding for similarity checking
    description_embedding       vector(1536),
    description_embedding_model VARCHAR(100),
    last_similarity_check_at    TIMESTAMP,
    similarity_flags            JSONB DEFAULT '[]',

    input_schema                JSONB NOT NULL,
    output_schema               JSONB NOT NULL,

    -- Dispatch transport. See mcp_server above for the MCP values.
    --   'python_inprocess' — implementation_path names a Python callable the
    --                        runtime dispatches directly (current default).
    --   'mcp_stdio' | 'mcp_sse' | 'mcp_http' — runtime forwards the call
    --                        through an MCP client to the server identified
    --                        by mcp_server_name, addressing the remote tool
    --                        as mcp_tool_name.
    transport                   VARCHAR(50) NOT NULL DEFAULT 'python_inprocess',

    -- Links this tool to an mcp_server row when transport is an mcp_* variant.
    -- NULL for python_inprocess tools.
    mcp_server_name             VARCHAR(100) REFERENCES mcp_server(name),

    -- The tool's name on the MCP server (may differ from Verity's `name`,
    -- which must be globally unique in the registry).
    mcp_tool_name               VARCHAR(200),

    -- For python_inprocess tools: dotted path of the registered callable
    -- (documentation / debugging only; runtime looks up by `name` in
    -- tool_implementations). For mcp_* tools: optional descriptor.
    implementation_path         VARCHAR(500) NOT NULL,

    mock_mode_enabled           BOOLEAN DEFAULT TRUE,
    mock_response_key           VARCHAR(200),
    -- Realistic mock responses keyed by scenario name.
    -- Example: {"default": {"account": "Acme", "revenue": 50000000},
    --           "high_risk": {"account": "DangerCo", "claims": 12}}
    mock_responses              JSONB DEFAULT '{}',

    data_classification_max     data_classification DEFAULT 'tier3_confidential',

    is_write_operation          BOOLEAN DEFAULT FALSE,
    requires_confirmation       BOOLEAN DEFAULT FALSE,

    tags                        TEXT[] DEFAULT '{}',
    active                      BOOLEAN DEFAULT TRUE,
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tool_name ON tool(name);


-- ── AGENT VERSION ↔ TOOL JUNCTION ────────────────────────────

CREATE TABLE agent_version_tool (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_version_id    UUID NOT NULL REFERENCES agent_version(id),
    tool_id             UUID NOT NULL REFERENCES tool(id),
    authorized          BOOLEAN NOT NULL DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_avt UNIQUE (agent_version_id, tool_id)
);

CREATE INDEX idx_avt_agent ON agent_version_tool(agent_version_id);


-- ── TASK VERSION ↔ TOOL JUNCTION ─────────────────────────────

CREATE TABLE task_version_tool (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_version_id     UUID NOT NULL REFERENCES task_version(id),
    tool_id             UUID NOT NULL REFERENCES tool(id),
    authorized          BOOLEAN NOT NULL DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tvt UNIQUE (task_version_id, tool_id)
);


-- ── DATA CONNECTORS ──────────────────────────────────────────
-- A registered integration that Tasks can read from (sources) or write to
-- (targets). One row per integration (e.g. "edms"). Verity stores the name
-- and non-secret tuning config; secrets (API keys, auth tokens) live in env
-- vars read by the provider at startup. Providers are registered in
-- verity.runtime.connectors by the consuming app — Verity itself does not
-- import EDMS or any specific integration.

CREATE TABLE data_connector (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) NOT NULL UNIQUE,    -- "edms"
    connector_type  VARCHAR(50)  NOT NULL,           -- "edms" (only type in v1)
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,
    config          JSONB NOT NULL DEFAULT '{}',     -- non-secret tuning only
    owner_name      VARCHAR(200),
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);


-- ── TASK VERSION DATA SOURCES ────────────────────────────────
-- Declarative inputs: "if the caller passes `input_field_name`, resolve it
-- via `connector_id.fetch_method(ref)` and bind the payload to the prompt
-- template variable `maps_to_template_var`." Resolution is eager — all
-- required sources fire before prompt build. A source failure is a hard
-- failure (SourceResolutionError). required=False only means the caller
-- may omit the ref; if a ref is provided, it must resolve.

CREATE TABLE task_version_source (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_version_id         UUID NOT NULL REFERENCES task_version(id) ON DELETE CASCADE,
    input_field_name        VARCHAR(100) NOT NULL,   -- key in caller's input_data dict
    connector_id            UUID NOT NULL REFERENCES data_connector(id),
    fetch_method            VARCHAR(100) NOT NULL,   -- e.g. "get_document_text"
    maps_to_template_var    VARCHAR(100) NOT NULL,   -- e.g. "document_text"
    required                BOOLEAN NOT NULL DEFAULT TRUE,
    execution_order         INTEGER NOT NULL DEFAULT 1,
    description             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tvs_field UNIQUE (task_version_id, input_field_name),
    CONSTRAINT uq_tvs_var   UNIQUE (task_version_id, maps_to_template_var)
);

CREATE INDEX idx_tvs_task_version ON task_version_source(task_version_id);


-- ── TASK VERSION DATA TARGETS ────────────────────────────────
-- Declarative outputs: "take `output_field_name` from the Task's structured
-- output and write it via `connector_id.write_method(container, payload)`."
-- Writes are channel-gated (champion only by default) AND runtime-gated via
-- the execution engine's write_mode parameter:
--   "auto"     — channel decides (champion=write, else log-only). Default.
--   "log_only" — forced dry run regardless of channel.
--   "write"    — forced write; caller must have authority.
-- Validation/test runs never write; the intended write is recorded in the
-- decision log instead.

CREATE TABLE task_version_target (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_version_id         UUID NOT NULL REFERENCES task_version(id) ON DELETE CASCADE,
    output_field_name       VARCHAR(100) NOT NULL,   -- key in Task's output dict
    connector_id            UUID NOT NULL REFERENCES data_connector(id),
    write_method            VARCHAR(100) NOT NULL,   -- e.g. "create_document"
    target_container        VARCHAR(200),            -- optional collection/folder
    required                BOOLEAN NOT NULL DEFAULT FALSE,
    execution_order         INTEGER NOT NULL DEFAULT 1,
    description             TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_tvt_out UNIQUE (task_version_id, output_field_name)
);

CREATE INDEX idx_tvtgt_task_version ON task_version_target(task_version_id);


-- ── WIRING: SOURCES AND TARGETS (UNIFIED FOR TASKS AND AGENTS) ──
-- Declarative I/O uses a single reference grammar across tasks and agents:
--   input.<path>              — value from the unit's own input_data
--   output.<path>             — value from the unit's own output (targets only)
--   const:<literal>           — a constant baked into the declaration
--   fetch:<connector>/<method>(input.<field>)
--                             — connector call at resolution time (sources only)
-- Path grammar: dotted keys + bracketed integer indices (`docs[0].kind`).
-- No JSONPath, no arithmetic, no conditionals.
--
-- Two purpose-named tables:
--   source_binding        — pre-prompt input resolution (task or agent)
--   write_target          — post-output write declaration (task or agent)
--   target_payload_field  — per-field payload assembly for a write_target
--
-- The older task_version_source / task_version_target tables remain during
-- the data-migration window; they will be dropped once existing rows are
-- translated into source_binding / write_target + target_payload_field.

CREATE TABLE source_binding (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_kind       VARCHAR(20) NOT NULL
                     CHECK (owner_kind IN ('task_version', 'agent_version')),
    owner_id         UUID NOT NULL,
    -- The key the prompt template expects ({{template_var}}), or more
    -- generally the key that gets overlaid into the template context before
    -- prompt assembly. Unique per owner so a single version can't
    -- double-declare the same variable.
    template_var     VARCHAR(100) NOT NULL,
    -- Reference string in the wiring DSL. See section comment above.
    reference        TEXT NOT NULL,
    required         BOOLEAN NOT NULL DEFAULT TRUE,
    execution_order  INTEGER NOT NULL DEFAULT 1,
    description      TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_source_binding UNIQUE (owner_kind, owner_id, template_var)
);

CREATE INDEX idx_source_binding_owner ON source_binding(owner_kind, owner_id);


CREATE TABLE write_target (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_kind       VARCHAR(20) NOT NULL
                     CHECK (owner_kind IN ('task_version', 'agent_version')),
    owner_id         UUID NOT NULL,
    -- Logical name for this target declaration, unique per owner. Surfaces
    -- in the target_writes audit JSONB on the decision log so operators can
    -- tell which declared target fired.
    name             VARCHAR(100) NOT NULL,
    connector_id     UUID NOT NULL REFERENCES data_connector(id),
    write_method     VARCHAR(100) NOT NULL,
    -- Optional static container hint (collection / folder / path). Dynamic
    -- routing per-call should be expressed in the payload instead, via
    -- target_payload_field rows.
    container        VARCHAR(200),
    required         BOOLEAN NOT NULL DEFAULT FALSE,
    execution_order  INTEGER NOT NULL DEFAULT 1,
    description      TEXT,
    created_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_write_target UNIQUE (owner_kind, owner_id, name)
);

CREATE INDEX idx_write_target_owner ON write_target(owner_kind, owner_id);


CREATE TABLE target_payload_field (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- CASCADE: if the write_target is dropped, its payload fields go with it.
    write_target_id   UUID NOT NULL REFERENCES write_target(id) ON DELETE CASCADE,
    -- The key that appears in the payload dict passed to the connector.
    payload_field     VARCHAR(200) NOT NULL,
    -- Reference string in the wiring DSL: input.<path>, output.<path>,
    -- or const:<literal>. fetch:* is not valid on target payloads.
    reference         TEXT NOT NULL,
    required          BOOLEAN NOT NULL DEFAULT TRUE,
    execution_order   INTEGER NOT NULL DEFAULT 1,
    description       TEXT,
    created_at        TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_target_payload_field UNIQUE (write_target_id, payload_field)
);

CREATE INDEX idx_target_payload_field_target ON target_payload_field(write_target_id);


-- ── AGENT VERSION ↔ AGENT DELEGATION JUNCTION ────────────────
-- First-class registry of "agent A can delegate to agent B" relationships.
-- Independent of agent_version_tool (which grants the capability to use
-- the delegate_to_agent meta-tool at all) — this table specifies WHICH
-- sub-agents a given parent version is authorized to delegate to.
--
-- Added in FC-1 (sub-agent delegation). The runtime enforces this
-- table during dispatch of the delegate_to_agent meta-tool: if no row
-- matches (parent_agent_version_id, target child agent), the tool call
-- comes back to Claude as an error listing the authorized targets, so
-- the agent can correct itself.
--
-- Exactly one of child_agent_name or child_agent_version_id must be set:
--   child_agent_name: champion-tracking — the delegation follows whichever
--     version of the named agent is currently promoted to champion.
--     Useful default; delegation stays current as sub-agents get promoted.
--   child_agent_version_id: version-pinned — locks the parent to a specific
--     child version. Use when you want the parent to keep calling a
--     previously-validated child version even after newer challengers arrive.

CREATE TABLE agent_version_delegation (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    parent_agent_version_id UUID NOT NULL REFERENCES agent_version(id),

    -- Exactly one must be set (see CHECK below).
    child_agent_name        VARCHAR(100),
    child_agent_version_id  UUID REFERENCES agent_version(id),

    -- Optional per-relationship constraints. JSONB so it can grow
    -- without schema churn. Examples:
    --   {"max_additional_depth": 2}
    --   {"allowed_lob": ["DO"]}
    --   {"reason_required": true}
    scope                   JSONB NOT NULL DEFAULT '{}',

    authorized              BOOLEAN NOT NULL DEFAULT TRUE,
    rationale               TEXT,   -- why this delegation is allowed (governance audit)
    notes                   TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_child_target CHECK (
        (child_agent_name IS NOT NULL AND child_agent_version_id IS NULL) OR
        (child_agent_name IS NULL AND child_agent_version_id IS NOT NULL)
    ),
    CONSTRAINT uq_avd_parent_child UNIQUE (
        parent_agent_version_id, child_agent_name, child_agent_version_id
    )
);

CREATE INDEX idx_avd_parent ON agent_version_delegation(parent_agent_version_id);
CREATE INDEX idx_avd_child_name ON agent_version_delegation(child_agent_name);
CREATE INDEX idx_avd_child_version ON agent_version_delegation(child_agent_version_id);


-- ── APPLICATIONS ─────────────────────────────────────────────
-- Each consuming business application registers itself with Verity.
-- Enables multi-tenant governance: filter decisions, inventory, and
-- entity mappings by application.

CREATE TABLE application (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- ── APPLICATION ↔ ENTITY MAPPING ─────────────────────────────
-- Many-to-many: which agents, tasks, prompts, tools belong to which
-- application. Entities can be shared across apps.

CREATE TABLE application_entity (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    entity_type     entity_type NOT NULL,
    entity_id       UUID NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_entity UNIQUE (application_id, entity_type, entity_id)
);

CREATE INDEX idx_ae_app ON application_entity(application_id);
CREATE INDEX idx_ae_entity ON application_entity(entity_type, entity_id);


-- ── EXECUTION CONTEXT ────────────────────────────────────────
-- Business-level grouping registered by the consuming application.
-- A context can span multiple workflow runs (e.g., initial run + re-run).
-- The context_ref is opaque to Verity — the business app defines it.
-- Uniqueness is per application: (application_id, context_ref).

CREATE TABLE execution_context (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    context_ref     VARCHAR(500) NOT NULL,
    context_type    VARCHAR(100),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_context UNIQUE (application_id, context_ref)
);

CREATE INDEX idx_ec_app ON execution_context(application_id);


-- ── TEST SUITES & CASES ───────────────────────────────────────

CREATE TABLE test_suite (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    entity_type         entity_type NOT NULL,
    entity_id           UUID NOT NULL,
    suite_type          VARCHAR(50) NOT NULL,
    created_by          VARCHAR(200),
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE test_case (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    suite_id            UUID NOT NULL REFERENCES test_suite(id),
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    input_data          JSONB NOT NULL,
    expected_output     JSONB NOT NULL,

    metric_type         metric_type NOT NULL,
    metric_config       JSONB,

    applies_to_versions UUID[] DEFAULT '{}',
    excludes_versions   UUID[] DEFAULT '{}',

    is_adversarial      BOOLEAN DEFAULT FALSE,
    tags                TEXT[] DEFAULT '{}',
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tc_suite ON test_case(suite_id);


-- Per-call mock data for test cases. Each row mocks one interaction.
-- mock_kind discriminates three shapes:
--   'tool'   — Agent tool mock (mock_key = tool_name). Claude is called
--              for real; the named tool returns mock_response instead of
--              making a real call.
--   'source' — Task data-source mock (mock_key = input_field_name on
--              task_version_source). The connector fetch is skipped and
--              mock_response is bound to the mapped template variable.
--   'target' — Task data-target expectation (mock_key = output_field_name
--              on task_version_target). The connector write is skipped;
--              the intended write is recorded in the decision log.
-- call_order supports multi-call scenarios for 'tool' (unused for source/target).
CREATE TABLE test_case_mock (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    test_case_id    UUID NOT NULL REFERENCES test_case(id) ON DELETE CASCADE,
    mock_kind       VARCHAR(20) NOT NULL DEFAULT 'tool'
                    CHECK (mock_kind IN ('tool', 'source', 'target')),
    mock_key        VARCHAR(200) NOT NULL,
    call_order      INTEGER DEFAULT 1,
    mock_response   JSONB NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tcm_case ON test_case_mock(test_case_id);
-- idx_tcm_kind created in the idempotent additions section below (after
-- mock_kind column is guaranteed to exist on previously-created tables).


CREATE TABLE test_execution_log (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    suite_id            UUID NOT NULL REFERENCES test_suite(id),
    entity_type         entity_type NOT NULL,
    entity_version_id   UUID NOT NULL,
    test_case_id        UUID NOT NULL REFERENCES test_case(id),
    run_at              TIMESTAMP DEFAULT NOW(),
    mock_mode           BOOLEAN NOT NULL,
    channel             deployment_channel,
    input_used          JSONB,
    actual_output       JSONB,
    expected_output     JSONB,
    metric_type         metric_type NOT NULL,
    metric_result       JSONB,
    passed              BOOLEAN NOT NULL,
    failure_reason      TEXT,
    duration_ms         INTEGER,
    inference_config_snapshot JSONB
);

CREATE INDEX idx_tel_entity ON test_execution_log(entity_type, entity_version_id);
CREATE INDEX idx_tel_suite ON test_execution_log(suite_id);


-- ── GROUND TRUTH — THREE-TABLE DESIGN ────────────────────────
-- Dataset → Record → Annotation
--
-- Dataset: metadata, quality tier, labeling status, IAA metrics.
-- Record:  one input item (document or submission context). No label.
-- Annotation: one annotator's answer per record. is_authoritative flag
--   selects the label used by the validation runner.
--
-- Storage abstraction: all document references use provider/container/key
-- instead of MinIO-specific fields. Works with MinIO, S3, Azure Blob, local.

CREATE TABLE ground_truth_dataset (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Which Verity entity this dataset validates
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_id               UUID NOT NULL,

    -- Optionally pin to a version this dataset was designed for
    -- (a dataset may outlive the version it was originally built for)
    designed_for_version_id UUID,

    -- Identity
    name                    VARCHAR(300) NOT NULL,
    version                 VARCHAR(50)  NOT NULL DEFAULT '1.0',
    description             TEXT,
    purpose                 TEXT NOT NULL,
    -- e.g. "Validate field extraction accuracy before v1.2 promotion"

    -- Quality classification
    quality_tier            gt_quality_tier NOT NULL DEFAULT 'silver',
    status                  gt_dataset_status NOT NULL DEFAULT 'collecting',

    -- Labeling guidance document (storage-abstracted)
    labeling_guide_provider  VARCHAR(50),
    labeling_guide_container VARCHAR(200),
    labeling_guide_key       VARCHAR(500),

    -- Ownership
    owner_name              VARCHAR(200) NOT NULL,
    created_by              VARCHAR(200) NOT NULL,

    -- Computed quality metrics — updated whenever annotations change
    record_count            INTEGER NOT NULL DEFAULT 0,
    annotated_count         INTEGER NOT NULL DEFAULT 0,
    authoritative_count     INTEGER NOT NULL DEFAULT 0,
    iaa_score               NUMERIC(5,4),
    iaa_computed_at         TIMESTAMP,
    iaa_method              VARCHAR(50),
    coverage_notes          TEXT,

    applies_to_versions     UUID[] DEFAULT '{}',
    superseded_by           UUID REFERENCES ground_truth_dataset(id),

    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_gt_dataset UNIQUE (entity_type, entity_id, name, version)
);

CREATE INDEX idx_gtd_entity ON ground_truth_dataset(entity_type, entity_id);
CREATE INDEX idx_gtd_status ON ground_truth_dataset(status);


-- One input item within a dataset. This is the "question" — the document
-- or context fed to the entity during validation. Carries NO label.
-- The label lives entirely in ground_truth_annotation.

CREATE TABLE ground_truth_record (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dataset_id              UUID NOT NULL REFERENCES ground_truth_dataset(id)
                            ON DELETE CASCADE,
    record_index            INTEGER NOT NULL,

    -- Source document reference (storage-abstracted)
    source_type             gt_source_type NOT NULL,
    source_provider         VARCHAR(50),
    source_container        VARCHAR(200),
    source_key              VARCHAR(500),
    source_description      VARCHAR(500),

    -- What gets fed to the entity during the validation run
    input_data              JSONB NOT NULL,

    -- Slice tags for analysis (edge_case, high_risk, amber_boundary, etc.)
    tags                    TEXT[] DEFAULT '{}',
    difficulty              VARCHAR(20),
    record_notes            TEXT,

    created_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_gt_record UNIQUE (dataset_id, record_index)
);

CREATE INDEX idx_gtr_dataset ON ground_truth_record(dataset_id);
CREATE INDEX idx_gtr_tags    ON ground_truth_record USING GIN(tags);


-- Per-call mock data for ground truth records. Same shape as test_case_mock;
-- see that comment for mock_kind semantics.
-- Provides the scenario data the annotation was labeled against — for agent
-- validation, this mocks get_submission_context / get_loss_history so Claude
-- reasons against the exact data the SME saw. For task validation with
-- declared sources, kind='source' mocks let a record override the connector
-- fetch (e.g. test the Task against a stored payload instead of EDMS).
CREATE TABLE ground_truth_record_mock (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    record_id       UUID NOT NULL REFERENCES ground_truth_record(id) ON DELETE CASCADE,
    mock_kind       VARCHAR(20) NOT NULL DEFAULT 'tool'
                    CHECK (mock_kind IN ('tool', 'source', 'target')),
    mock_key        VARCHAR(200) NOT NULL,
    call_order      INTEGER DEFAULT 1,
    mock_response   JSONB NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_gtrm_record ON ground_truth_record_mock(record_id);
-- idx_gtrm_kind created in the idempotent additions section below (after
-- mock_kind column is guaranteed to exist on previously-created tables).


-- One annotator's answer for one record. Multiple annotations per record
-- are allowed and expected for gold-tier datasets.
--
-- Exactly one annotation per record has is_authoritative = true at any time.
-- This is what the validation runner uses as the correct answer.
--
-- Adjudication: senior SME creates annotator_type = 'adjudicator' annotation
-- with is_authoritative = true. Prior authoritative annotation set to false
-- in the same transaction. Full lineage preserved.
--
-- LLM-as-judge: first-class annotator type. Tracked with model name and
-- prompt version for reproducibility.

CREATE TABLE ground_truth_annotation (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    record_id               UUID NOT NULL REFERENCES ground_truth_record(id)
                            ON DELETE CASCADE,
    dataset_id              UUID NOT NULL REFERENCES ground_truth_dataset(id),

    -- Who or what produced this annotation
    annotator_type          gt_annotator_type NOT NULL,

    -- Human SME / adjudicator fields
    labeled_by              VARCHAR(200),
    label_confidence        NUMERIC(5,4),
    label_notes             TEXT,

    -- LLM judge fields
    judge_model             VARCHAR(100),
    judge_prompt_version_id UUID REFERENCES prompt_version(id),
    judge_reasoning         TEXT,

    -- The label itself — what the correct output should be.
    -- Schema matches the entity's output_schema.
    expected_output         JSONB NOT NULL,

    -- Authoritative flag — exactly one per record should be true.
    -- Enforced by application logic (atomic swap in same transaction).
    is_authoritative        BOOLEAN NOT NULL DEFAULT FALSE,

    -- Correction tracking
    is_corrected            BOOLEAN DEFAULT FALSE,
    original_output         JSONB,
    corrected_at            TIMESTAMP,
    correction_reason       TEXT,

    labeled_at              TIMESTAMP NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_human_fields CHECK (
        annotator_type NOT IN ('human_sme', 'adjudicator')
        OR labeled_by IS NOT NULL
    ),
    CONSTRAINT chk_llm_fields CHECK (
        annotator_type != 'llm_judge'
        OR judge_model IS NOT NULL
    )
);

CREATE INDEX idx_gta_record     ON ground_truth_annotation(record_id);
CREATE INDEX idx_gta_dataset    ON ground_truth_annotation(dataset_id);
CREATE INDEX idx_gta_auth       ON ground_truth_annotation(record_id)
                                WHERE is_authoritative = TRUE;
CREATE INDEX idx_gta_type       ON ground_truth_annotation(annotator_type);


-- ── VALIDATION RUNS ───────────────────────────────────────────

CREATE TABLE validation_run (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id       UUID NOT NULL,
    dataset_id              UUID NOT NULL REFERENCES ground_truth_dataset(id),
    dataset_version         VARCHAR(50),
    -- Which dataset version was used, so results are unambiguous
    run_at                  TIMESTAMP DEFAULT NOW(),
    run_by                  VARCHAR(200) NOT NULL,

    precision_score         NUMERIC(7,6),
    recall_score            NUMERIC(7,6),
    f1_score                NUMERIC(7,6),
    cohens_kappa            NUMERIC(7,6),
    confusion_matrix        JSONB,
    -- Canonical format: {"labels": [...], "matrix": [[...]], "per_class": {...}}

    field_accuracy          JSONB,
    -- Canonical format: {"per_field": {"field_name": {"correct": N, "total": N, "accuracy": 0.96}}, "overall_accuracy": 0.91}
    overall_extraction_rate NUMERIC(7,6),
    low_confidence_rate     NUMERIC(7,6),

    fairness_metrics        JSONB,
    fairness_passed         BOOLEAN,
    fairness_notes          TEXT,

    thresholds_met          BOOLEAN,
    threshold_details       JSONB,

    sme_review_notes        TEXT,
    sme_reviewed_by         VARCHAR(200),
    sme_reviewed_at         TIMESTAMP,

    inference_config_snapshot JSONB,

    status                  VARCHAR(50) NOT NULL DEFAULT 'running',
    -- 'running' = in progress, 'complete' = finished successfully, 'failed' = errored
    passed                  BOOLEAN,
    notes                   TEXT
);

CREATE INDEX idx_vr_entity ON validation_run(entity_type, entity_version_id);


-- Per-record prediction results from a validation run.
-- Enables drill-down from aggregate metrics (F1=0.95) to individual
-- misclassifications, extraction errors, or incorrect triage outcomes.

CREATE TABLE validation_record_result (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    validation_run_id       UUID NOT NULL REFERENCES validation_run(id)
                            ON DELETE CASCADE,
    ground_truth_record_id  UUID NOT NULL REFERENCES ground_truth_record(id),
    record_index            INTEGER NOT NULL,

    -- Ground truth vs prediction
    expected_output         JSONB NOT NULL,
    actual_output           JSONB NOT NULL,
    confidence              NUMERIC(5,4),

    -- Outcome
    correct                 BOOLEAN NOT NULL,
    match_type              VARCHAR(50),   -- 'exact', 'partial', 'fuzzy'
    match_score             NUMERIC(7,6),  -- 0.0-1.0 for partial/fuzzy matches

    -- For extraction: per-field breakdown
    -- {"named_insured": {"correct": true, "expected": "X", "actual": "X"}, ...}
    field_results           JSONB,

    -- Links to agent_decision_log for full audit trail.
    -- No FK constraint: agent_decision_log is defined later in schema.
    -- Referential integrity maintained by application logic.
    decision_log_id         UUID,

    duration_ms             INTEGER,
    created_at              TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_vrr UNIQUE (validation_run_id, record_index)
);

CREATE INDEX idx_vrr_run     ON validation_record_result(validation_run_id);
CREATE INDEX idx_vrr_correct ON validation_record_result(validation_run_id, correct);


-- ── EVALUATION RUNS ───────────────────────────────────────────

CREATE TABLE evaluation_run (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL,
    entity_version_id       UUID NOT NULL,
    evaluation_type         VARCHAR(50) NOT NULL,
    run_period_start        TIMESTAMP NOT NULL,
    run_period_end          TIMESTAMP NOT NULL,

    champion_version_id     UUID,

    total_invocations       INTEGER NOT NULL DEFAULT 0,
    successful_invocations  INTEGER DEFAULT 0,
    failed_invocations      INTEGER DEFAULT 0,

    agreement_rate          NUMERIC(7,6),
    disagreement_examples   JSONB,

    avg_duration_ms         NUMERIC(10,2),
    avg_input_tokens        NUMERIC(10,2),
    avg_output_tokens       NUMERIC(10,2),

    override_count          INTEGER DEFAULT 0,
    override_rate           NUMERIC(7,6),
    override_pattern_flags  JSONB,

    metric_drift_detected   BOOLEAN DEFAULT FALSE,
    drift_details           JSONB,

    promotion_recommendation VARCHAR(50),

    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_er_entity ON evaluation_run(entity_type, entity_version_id);


-- ── APPROVAL RECORDS (HITL GATES) ────────────────────────────

CREATE TABLE approval_record (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL,
    entity_version_id       UUID NOT NULL,
    gate_type               VARCHAR(50) NOT NULL,
    from_state              lifecycle_state,
    to_state                lifecycle_state,

    approver_name           VARCHAR(200) NOT NULL,
    approver_role           VARCHAR(100),
    approved_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    rationale               TEXT NOT NULL,

    staging_results_reviewed        BOOLEAN DEFAULT FALSE,
    ground_truth_reviewed           BOOLEAN DEFAULT FALSE,
    fairness_analysis_reviewed      BOOLEAN DEFAULT FALSE,
    shadow_metrics_reviewed         BOOLEAN DEFAULT FALSE,
    challenger_metrics_reviewed     BOOLEAN DEFAULT FALSE,
    model_card_reviewed             BOOLEAN DEFAULT FALSE,
    similarity_flags_reviewed       BOOLEAN DEFAULT FALSE,

    decision_override       BOOLEAN DEFAULT FALSE,
    override_reason         TEXT
);

CREATE INDEX idx_ar_entity ON approval_record(entity_type, entity_version_id);
CREATE INDEX idx_ar_gate ON approval_record(gate_type);


-- ── RUN TRACKING (EVENT-SOURCED) ─────────────────────────────
-- Tracks the live state of an asynchronous task or agent run.
-- Four immutable, insert-only tables plus a view that surfaces current
-- state. Nothing about a run is ever updated; the run's story is the
-- append-only ledger. The decision log (agent_decision_log) already
-- commits to immutability for audit — this section applies the same
-- invariant to run-state tracking, which lets workers scale horizontally
-- (INSERT has no row contention) and gives operators a complete ledger
-- of every claim, heartbeat, and terminal outcome for post-hoc analysis.
--
--   execution_run            — the request (one row per submission)
--   execution_run_status     — ledger of submitted/claimed/heartbeat/released
--   execution_run_completion — terminal success row (at most one per run)
--   execution_run_error      — terminal failure row (at most one per run)
--   execution_run_current    — view combining all four into current state
--
-- API and UI reads go through the view; workers INSERT into the tables.

CREATE TABLE execution_run (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- What was requested. Immutable once inserted.
    entity_kind           VARCHAR(20) NOT NULL
                          CHECK (entity_kind IN ('task', 'agent')),
    entity_version_id     UUID NOT NULL,
    entity_name           VARCHAR(100) NOT NULL,
    channel               deployment_channel NOT NULL,
    input_json            JSONB,
    execution_context_id  UUID REFERENCES execution_context(id),
    -- Caller-supplied correlation id grouping multiple runs into one
    -- logical workflow invocation. Opaque to Verity.
    workflow_run_id       UUID,
    -- For sub-agent delegation: the parent decision's id. Lets the
    -- decision log for a spawned run be linked back to its parent
    -- before that parent's own audit row is written.
    parent_decision_id    UUID,
    application           VARCHAR(100) NOT NULL DEFAULT 'default',
    mock_mode             BOOLEAN NOT NULL DEFAULT FALSE,
    -- Overrides used by the runtime when the worker executes. Null means
    -- fall back to the runtime default.
    write_mode            VARCHAR(20),
    enforce_output_schema BOOLEAN,

    submitted_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    submitted_by          VARCHAR(100)
);

CREATE INDEX idx_execution_run_context  ON execution_run(execution_context_id);
CREATE INDEX idx_execution_run_workflow ON execution_run(workflow_run_id);
CREATE INDEX idx_execution_run_entity   ON execution_run(entity_kind, entity_version_id);
CREATE INDEX idx_execution_run_submitted ON execution_run(submitted_at DESC);


CREATE TABLE execution_run_status (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    execution_run_id  UUID NOT NULL REFERENCES execution_run(id),
    -- 'submitted' — inserted in the same txn as the execution_run row.
    -- 'claimed'   — a worker has taken ownership of the run.
    -- 'heartbeat' — periodic proof-of-life from the claiming worker.
    -- 'released'  — worker handed the run back (graceful shutdown) or a
    --               janitor re-queued a stuck claim. Next claim cycle
    --               re-picks the run.
    -- Terminal events live in execution_run_completion / _error, NOT here.
    status            VARCHAR(20) NOT NULL
                      CHECK (status IN ('submitted', 'claimed', 'heartbeat', 'released')),
    recorded_at       TIMESTAMP NOT NULL DEFAULT NOW(),
    worker_id         VARCHAR(100),
    notes             TEXT
);

CREATE INDEX idx_exec_run_status_run ON execution_run_status(execution_run_id, recorded_at DESC);


CREATE TABLE execution_run_completion (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Only one terminal-success row per run; enforced by UNIQUE.
    execution_run_id  UUID NOT NULL UNIQUE REFERENCES execution_run(id),
    -- 'complete'  — worker produced a successful envelope.
    -- 'cancelled' — run was terminated on request before/after claim.
    final_status      VARCHAR(20) NOT NULL
                      CHECK (final_status IN ('complete', 'cancelled')),
    completed_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    -- Points at the immutable audit row. Null on 'cancelled' if the run
    -- was terminated before any engine work produced a decision.
    decision_log_id   UUID,  -- FK added after agent_decision_log defined below
    duration_ms       INTEGER,
    worker_id         VARCHAR(100)
);


CREATE TABLE execution_run_error (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Only one terminal-failure row per run; enforced by UNIQUE.
    execution_run_id  UUID NOT NULL UNIQUE REFERENCES execution_run(id),
    failed_at         TIMESTAMP NOT NULL DEFAULT NOW(),
    -- Machine-readable code (e.g. 'connector_timeout', 'schema_violation').
    error_code        VARCHAR(100),
    error_message     TEXT NOT NULL,
    error_trace       TEXT,
    worker_id         VARCHAR(100),
    -- If a partial audit row was written before the failure surfaced,
    -- reference it here. FK added after agent_decision_log defined below.
    decision_log_id   UUID
);


-- ── AGENT DECISION LOG ───────────────────────────────────────
-- Every Claude invocation — agent or task — is logged here.

CREATE TABLE agent_decision_log (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id       UUID NOT NULL,

    prompt_version_ids      UUID[] DEFAULT '{}',
    inference_config_snapshot JSONB NOT NULL,

    channel                 deployment_channel NOT NULL,
    mock_mode               BOOLEAN DEFAULT FALSE,
    -- Caller-supplied correlation id grouping multiple related runs as one
    -- logical workflow invocation (e.g. classify + extract for a single
    -- document). App code sets it; Verity treats it as opaque. Renamed
    -- from pipeline_run_id now that Verity no longer owns pipelines.
    workflow_run_id         UUID,
    -- Immutable-state FK into the event-sourced run-tracking tables.
    -- Populated for any decision produced from a run submitted through
    -- the async submission API; null for legacy synchronous calls that
    -- predate the execution_run machinery.
    execution_run_id        UUID REFERENCES execution_run(id),

    -- Hierarchy: tracks parent-child relationships for sub-agent calls.
    parent_decision_id      UUID REFERENCES agent_decision_log(id),
    decision_depth          INTEGER DEFAULT 0,
    step_name               VARCHAR(100),

    input_summary           TEXT,
    input_json              JSONB,
    output_json             JSONB,
    output_summary          TEXT,

    reasoning_text          TEXT,
    risk_factors            JSONB,
    confidence_score        NUMERIC(5,4),
    low_confidence_flag     BOOLEAN DEFAULT FALSE,

    model_used              VARCHAR(100),
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    duration_ms             INTEGER,
    tool_calls_made         JSONB,

    -- Full conversation array for multi-turn replay.
    -- Stores all messages (system, user, assistant, tool results) in order.
    -- Used by MockContext.from_decision_log() to replay the exact sequence.
    message_history         JSONB,

    -- Source application that created this decision.
    application             VARCHAR(100) DEFAULT 'default',

    -- Why this execution happened. Independent of channel (deployment stage)
    -- and mock_mode (whether mocking was used). Separates production runs
    -- from test/validation/audit activities.
    run_purpose             run_purpose NOT NULL DEFAULT 'production',

    -- For audit reruns: direct FK to the original decision being reproduced.
    -- Preserves lineage without burying it in JSONB metadata.
    reproduced_from_decision_id UUID REFERENCES agent_decision_log(id),

    -- Execution context: business-level grouping registered by the app.
    -- Links this decision to a specific business operation (e.g., submission, policy).
    execution_context_id    UUID REFERENCES execution_context(id),

    hitl_required           BOOLEAN DEFAULT FALSE,
    hitl_completed          BOOLEAN DEFAULT FALSE,
    hitl_approval_id        UUID REFERENCES approval_record(id),

    status                  VARCHAR(30) DEFAULT 'complete',
    error_message           TEXT,

    -- Decision logging level used for this entry + what was redacted
    decision_log_detail     VARCHAR(20) DEFAULT 'standard',
    redaction_applied       JSONB,          -- null if nothing redacted

    -- Declarative I/O audit trail for Task sources and targets. One entry
    -- per declared source resolved (or intentionally skipped) during this
    -- execution; same shape for target writes. Null when the entity did
    -- not declare any sources/targets (common for agents and for tasks
    -- without declared I/O). Per-entry shape (source_resolutions):
    --   {
    --     "input_field":   "document_ref",
    --     "template_var":  "document_text",
    --     "connector":     "edms",
    --     "method":        "get_document_text",
    --     "ref_summary":   "doc-abc-123",   -- truncated ref for audit
    --     "status":        "resolved" | "skipped_no_ref" | "failed",
    --     "mocked":        true | false,
    --     "payload_size":  14523             -- bytes/chars; -1 = unmeasurable
    --   }
    source_resolutions      JSONB,
    target_writes           JSONB,

    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_adl_entity ON agent_decision_log(entity_type, entity_version_id);
CREATE INDEX idx_adl_created ON agent_decision_log(created_at);
CREATE INDEX idx_adl_workflow ON agent_decision_log(workflow_run_id);
CREATE INDEX idx_adl_run ON agent_decision_log(execution_run_id);
CREATE INDEX idx_adl_parent ON agent_decision_log(parent_decision_id);


-- ── RUN TRACKING BACK-FILL FKS ───────────────────────────────
-- The execution_run_completion and execution_run_error tables reference
-- agent_decision_log, but they were created earlier in the file (before
-- agent_decision_log existed). Add the FK constraints now that the
-- target table is defined. Kept separate so the forward-referenced
-- columns above don't block schema apply.

ALTER TABLE execution_run_completion
    ADD CONSTRAINT fk_exec_run_completion_decision
    FOREIGN KEY (decision_log_id) REFERENCES agent_decision_log(id);

ALTER TABLE execution_run_error
    ADD CONSTRAINT fk_exec_run_error_decision
    FOREIGN KEY (decision_log_id) REFERENCES agent_decision_log(id);


-- ── RUN TRACKING: CURRENT-STATE VIEW ─────────────────────────
-- Combines the four run-tracking tables into one queryable row per run.
-- The current_status column is resolved by precedence:
--   1. If a completion row exists: use its final_status ('complete'|'cancelled').
--   2. Else if an error row exists: 'failed'.
--   3. Else: the latest entry in execution_run_status.
-- API and UI reads go through this view so callers never have to join
-- the four tables themselves.

CREATE VIEW execution_run_current AS
SELECT
    r.id,
    r.entity_kind,
    r.entity_version_id,
    r.entity_name,
    r.channel,
    r.input_json,
    r.execution_context_id,
    r.workflow_run_id,
    r.parent_decision_id,
    r.application,
    r.mock_mode,
    r.write_mode,
    r.enforce_output_schema,
    r.submitted_at,
    r.submitted_by,

    -- Resolved current status. See precedence above.
    COALESCE(
        c.final_status,
        CASE WHEN e.id IS NOT NULL THEN 'failed' ELSE s.latest_status END,
        'submitted'
    )                                   AS current_status,

    -- Event-table details for drill-through.
    s.latest_status                     AS latest_status_event,
    s.latest_status_at                  AS current_status_as_of,
    s.latest_worker_id                  AS current_worker_id,

    -- Completion details (null if the run didn't complete successfully).
    c.completed_at                      AS completed_at,
    c.decision_log_id                   AS completion_decision_log_id,
    c.duration_ms                       AS duration_ms,

    -- Error details (null if the run didn't fail).
    e.failed_at                         AS failed_at,
    e.error_code                        AS error_code,
    e.error_message                     AS error_message,
    e.decision_log_id                   AS error_decision_log_id,

    -- When the worker first picked it up (for elapsed-time display while
    -- still running; null if never claimed).
    first_claim.first_claimed_at        AS first_started_at
FROM execution_run r
LEFT JOIN execution_run_completion c ON c.execution_run_id = r.id
LEFT JOIN execution_run_error      e ON e.execution_run_id = r.id
LEFT JOIN LATERAL (
    SELECT status AS latest_status,
           recorded_at AS latest_status_at,
           worker_id AS latest_worker_id
    FROM execution_run_status
    WHERE execution_run_id = r.id
    ORDER BY recorded_at DESC
    LIMIT 1
) s ON TRUE
LEFT JOIN LATERAL (
    SELECT MIN(recorded_at) AS first_claimed_at
    FROM execution_run_status
    WHERE execution_run_id = r.id AND status = 'claimed'
) first_claim ON TRUE;


-- ── OVERRIDE LOG ─────────────────────────────────────────────

CREATE TABLE override_log (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_log_id         UUID NOT NULL REFERENCES agent_decision_log(id),
    entity_type             entity_type NOT NULL,
    entity_version_id       UUID NOT NULL,

    overrider_name          VARCHAR(200) NOT NULL,
    overrider_role          VARCHAR(100),
    override_reason_code    VARCHAR(50) NOT NULL,
    override_notes          TEXT,
    ai_recommendation       JSONB,
    human_decision          JSONB,
    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ol_entity ON override_log(entity_type, entity_version_id);
CREATE INDEX idx_ol_created ON override_log(created_at);


-- ── MODEL CARDS ───────────────────────────────────────────────

CREATE TABLE model_card (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id       UUID NOT NULL,
    card_version            INTEGER NOT NULL DEFAULT 1,

    purpose                 TEXT NOT NULL,
    design_rationale        TEXT NOT NULL,
    inputs_description      TEXT NOT NULL,
    outputs_description     TEXT NOT NULL,
    known_limitations       TEXT NOT NULL,
    conditions_of_use       TEXT NOT NULL,

    lm_specific_limitations TEXT,
    prompt_sensitivity_notes TEXT,

    validated_by            VARCHAR(200),
    validation_run_id       UUID REFERENCES validation_run(id),
    validation_notes        TEXT,

    regulatory_notes        TEXT,
    materiality_classification TEXT,

    approved_by             VARCHAR(200),
    approved_at             TIMESTAMP,
    lifecycle_state         VARCHAR(30) DEFAULT 'draft',

    created_at              TIMESTAMP DEFAULT NOW(),
    updated_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_mc_entity ON model_card(entity_type, entity_version_id);


-- ── METRIC THRESHOLDS ─────────────────────────────────────────

CREATE TABLE metric_threshold (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type         entity_type NOT NULL,
    entity_id           UUID NOT NULL,
    materiality_tier    materiality_tier NOT NULL,
    metric_name         VARCHAR(100) NOT NULL,
    -- NULL = aggregate metric, set = per-field threshold (for extraction tasks)
    field_name          VARCHAR(100),
    minimum_acceptable  NUMERIC(7,6) NOT NULL,
    target_champion     NUMERIC(7,6) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_threshold UNIQUE (entity_id, entity_type, materiality_tier, metric_name, field_name)
);


-- Per-field tolerance configuration for extraction tasks.
-- Defines how each extracted field should be compared against ground truth.

CREATE TABLE field_extraction_config (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type         entity_type NOT NULL CHECK (entity_type IN ('task')),
    entity_id           UUID NOT NULL,
    field_name          VARCHAR(100) NOT NULL,
    field_type          VARCHAR(50)  NOT NULL,
    -- 'string', 'numeric', 'date', 'boolean', 'enum'
    match_type          VARCHAR(50)  NOT NULL,
    -- 'exact', 'numeric_tolerance', 'case_insensitive', 'contains'
    tolerance_value     NUMERIC(10,4),
    -- For numeric: 0.05 = 5% when tolerance_unit='percent'
    tolerance_unit      VARCHAR(20),
    -- 'percent' or 'absolute'
    is_required         BOOLEAN DEFAULT TRUE,
    -- Must this field be extracted for "pass"?
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_field_config UNIQUE (entity_id, entity_type, field_name)
);


-- ── INCIDENTS ────────────────────────────────────────────────

CREATE TABLE incident (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL,
    entity_id               UUID NOT NULL,
    entity_version_id       UUID,
    title                   VARCHAR(300) NOT NULL,
    description             TEXT NOT NULL,
    severity                VARCHAR(20) NOT NULL,
    detection_source        VARCHAR(100),
    detected_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    affected_context_ids    UUID[] DEFAULT '{}',
    affected_decision_count INTEGER DEFAULT 0,
    rollback_executed       BOOLEAN DEFAULT FALSE,
    rollback_to_version_id  UUID,
    rollback_at             TIMESTAMP,
    rollback_approved_by    VARCHAR(200),
    resolution_notes        TEXT,
    new_test_cases_added    INTEGER DEFAULT 0,
    resolved_at             TIMESTAMP,
    status                  VARCHAR(30) DEFAULT 'open',
    created_at              TIMESTAMP DEFAULT NOW()
);


-- ── DESCRIPTION SIMILARITY LOG ───────────────────────────────

CREATE TABLE description_similarity_log (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    checked_entity_type     entity_type NOT NULL,
    checked_entity_id       UUID NOT NULL,
    checked_entity_name     VARCHAR(200) NOT NULL,
    similar_entity_type     entity_type NOT NULL,
    similar_entity_id       UUID NOT NULL,
    similar_entity_name     VARCHAR(200) NOT NULL,
    similarity_score        NUMERIC(7,6) NOT NULL,
    flagged                 BOOLEAN GENERATED ALWAYS AS (similarity_score > 0.85) STORED,
    reviewed_at             TIMESTAMP,
    reviewed_by             VARCHAR(200),
    resolution              VARCHAR(50),
    resolution_notes        TEXT,
    checked_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_dsl_entity ON description_similarity_log(checked_entity_type, checked_entity_id);


-- ============================================================
-- PLATFORM SETTINGS — Verity governance platform configuration
-- ============================================================
-- Key-value settings that control Verity's behavior at the platform level.
-- Read at runtime — no restart needed to change.
-- These are GOVERNANCE settings (decision logging, redaction thresholds),
-- not business app settings.

CREATE TABLE IF NOT EXISTS platform_settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT 'general',
    display_name        TEXT,
    description         TEXT,
    input_type          TEXT DEFAULT 'text',     -- text, select, number
    options             TEXT,                    -- comma-separated for select type
    sort_order          INTEGER DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ============================================================
-- MODEL MANAGEMENT — registry, pricing history, invocation log
-- ============================================================
-- `model` is the per-(provider, model_id) catalog row. Inference configs
-- link to it via `inference_config.model_id` (added idempotently below).
--
-- `model_price` is SCD Type 2: each row covers a validity window.
-- To insert a new price, set valid_to on the previous currently-active
-- row and INSERT a new one with valid_from = NOW() and valid_to = NULL.
-- The unique index uq_mp_active enforces "at most one currently-active
-- price per model" at the DB level.
--
-- `model_invocation_log` is one row per agent/task decision (NOT per
-- API turn — tokens are summed across turns). decision_log_id is the
-- FK back to the audit trail. Cost is computed on the fly via the
-- v_model_invocation_cost view, which joins to the pricing row whose
-- window contains the invocation's started_at — so historical reports
-- stay stable when prices change.

CREATE TABLE IF NOT EXISTS model (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider        VARCHAR(50)  NOT NULL,
    model_id        VARCHAR(200) NOT NULL,
    display_name    VARCHAR(300) NOT NULL,
    modality        VARCHAR(50)  DEFAULT 'chat',     -- chat / embedding / vision / ...
    context_window  INTEGER,
    status          VARCHAR(20)  DEFAULT 'active',   -- active / deprecated / beta
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_model UNIQUE (provider, model_id)
);
CREATE INDEX IF NOT EXISTS idx_model_provider ON model(provider);
CREATE INDEX IF NOT EXISTS idx_model_status ON model(status);


CREATE TABLE IF NOT EXISTS model_price (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_id                    UUID NOT NULL REFERENCES model(id),
    input_price_per_1m          NUMERIC(14,6) NOT NULL,
    output_price_per_1m         NUMERIC(14,6) NOT NULL,
    cache_read_price_per_1m     NUMERIC(14,6),
    cache_write_price_per_1m    NUMERIC(14,6),
    currency                    VARCHAR(3) DEFAULT 'USD',
    valid_from                  TIMESTAMPTZ NOT NULL,
    valid_to                    TIMESTAMPTZ,            -- NULL = currently active
    notes                       TEXT,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mp_lookup ON model_price(model_id, valid_from DESC);
-- At most one currently-active price per model. Application code
-- closes the prior row (sets valid_to) before inserting a new one.
CREATE UNIQUE INDEX IF NOT EXISTS uq_mp_active ON model_price(model_id) WHERE valid_to IS NULL;


CREATE TABLE IF NOT EXISTS model_invocation_log (
    id                              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_log_id                 UUID NOT NULL REFERENCES agent_decision_log(id) ON DELETE CASCADE,
    model_id                        UUID NOT NULL REFERENCES model(id),
    -- Denormalized (for fast group-by without joins on the hot path):
    provider                        VARCHAR(50)  NOT NULL,
    model_name                      VARCHAR(200) NOT NULL,
    started_at                      TIMESTAMPTZ NOT NULL,
    completed_at                    TIMESTAMPTZ NOT NULL,
    input_tokens                    INTEGER NOT NULL DEFAULT 0,
    output_tokens                   INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens     INTEGER DEFAULT 0,
    cache_read_input_tokens         INTEGER DEFAULT 0,
    api_call_count                  INTEGER DEFAULT 1,  -- turns within this decision
    stop_reason                     VARCHAR(50),
    status                          VARCHAR(20) DEFAULT 'complete',  -- complete / failed
    error_message                   TEXT,
    -- Per-turn details when we want drill-through; null for single-turn calls.
    per_turn_metadata               JSONB,
    created_at                      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_mil_decision ON model_invocation_log(decision_log_id);
CREATE INDEX IF NOT EXISTS idx_mil_started  ON model_invocation_log(started_at);
CREATE INDEX IF NOT EXISTS idx_mil_model    ON model_invocation_log(model_id, started_at);


-- Cost-on-the-fly view. Joins each invocation to the price row whose
-- [valid_from, valid_to) window contains the invocation's started_at.
-- Historical reports stay stable across price changes.
CREATE OR REPLACE VIEW v_model_invocation_cost AS
SELECT
    mil.id,
    mil.decision_log_id,
    mil.model_id,
    mil.provider,
    mil.model_name,
    mil.started_at,
    mil.completed_at,
    mil.input_tokens,
    mil.output_tokens,
    mil.cache_creation_input_tokens,
    mil.cache_read_input_tokens,
    mil.api_call_count,
    mil.stop_reason,
    mil.status,
    mp.input_price_per_1m,
    mp.output_price_per_1m,
    mp.cache_read_price_per_1m,
    mp.cache_write_price_per_1m,
    (mil.input_tokens::numeric  / 1e6) * mp.input_price_per_1m  AS input_cost_usd,
    (mil.output_tokens::numeric / 1e6) * mp.output_price_per_1m AS output_cost_usd,
    (mil.cache_creation_input_tokens::numeric / 1e6)
        * COALESCE(mp.cache_write_price_per_1m, mp.input_price_per_1m) AS cache_write_cost_usd,
    (mil.cache_read_input_tokens::numeric / 1e6)
        * COALESCE(mp.cache_read_price_per_1m, mp.input_price_per_1m * 0.1) AS cache_read_cost_usd,
    (
        (mil.input_tokens::numeric  / 1e6) * mp.input_price_per_1m
      + (mil.output_tokens::numeric / 1e6) * mp.output_price_per_1m
      + (mil.cache_creation_input_tokens::numeric / 1e6)
            * COALESCE(mp.cache_write_price_per_1m, mp.input_price_per_1m)
      + (mil.cache_read_input_tokens::numeric / 1e6)
            * COALESCE(mp.cache_read_price_per_1m, mp.input_price_per_1m * 0.1)
    ) AS total_cost_usd
FROM model_invocation_log mil
JOIN model_price mp
  ON mp.model_id = mil.model_id
 AND mil.started_at >= mp.valid_from
 AND (mp.valid_to IS NULL OR mil.started_at < mp.valid_to);


-- ============================================================
-- POST-CREATE ADJUSTMENTS
-- ============================================================
-- Adjustments that must run after the primary CREATE TABLE statements
-- above. Kept here so the main table definitions stay compact.

-- Model management — link inference configs to the registered model
-- catalog. Kept alongside the existing `model_name` VARCHAR column for
-- transition; seed script backfills this FK from the text column.
ALTER TABLE inference_config ADD COLUMN IF NOT EXISTS model_id UUID REFERENCES model(id);

-- Secondary index on test_case_mock after the primary CREATE TABLE
-- above finalizes the mock_kind column.
CREATE INDEX IF NOT EXISTS idx_tcm_kind  ON test_case_mock(test_case_id, mock_kind);
CREATE INDEX IF NOT EXISTS idx_gtrm_kind ON ground_truth_record_mock(record_id, mock_kind);


-- ============================================================
-- QUOTAS — soft budget caps per scope
-- ============================================================
-- A quota pairs a scope (application / agent / task / model) with a
-- period (daily / weekly / monthly) and a budget in USD. When the
-- checker runs (manually via /admin/quotas or POST /api/v1/quotas/check,
-- or on a cron), it computes the spend in the current period for
-- that scope and records a quota_check row. If spend crosses the
-- alert threshold (default 80% of budget), alert_fired is set on
-- that check.
--
-- V1 is SOFT quotas only — the engine does NOT refuse calls at
-- budget. Enforcement (hard_stop) is a column here for later, but
-- no write-side code reads it yet. Intentionally self-contained:
-- quota breaches do NOT create rows in the `incident` table because
-- the entity_type enum (agent/task/prompt/tool) doesn't
-- fit application/model scopes; the admin UI reads quota_check
-- directly for active breach counts.

CREATE TABLE IF NOT EXISTS quota (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    scope_type           VARCHAR(20) NOT NULL CHECK (scope_type IN ('application','agent','task','model')),
    scope_id             UUID,                             -- polymorphic; not a hard FK because the target table varies
    scope_name           VARCHAR(200) NOT NULL,            -- denormalized for display
    period               VARCHAR(20) NOT NULL CHECK (period IN ('daily','weekly','monthly')),
    budget_usd           NUMERIC(14,4) NOT NULL,
    alert_threshold_pct  INTEGER NOT NULL DEFAULT 80 CHECK (alert_threshold_pct BETWEEN 1 AND 200),
    hard_stop            BOOLEAN NOT NULL DEFAULT FALSE,   -- reserved; V1 ignores it
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    notes                TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_quota_scope   ON quota(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_quota_enabled ON quota(enabled);


CREATE TABLE IF NOT EXISTS quota_check (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    quota_id        UUID NOT NULL REFERENCES quota(id) ON DELETE CASCADE,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    period_start    TIMESTAMPTZ NOT NULL,
    period_end      TIMESTAMPTZ NOT NULL,
    spend_usd       NUMERIC(14,4) NOT NULL,
    budget_usd      NUMERIC(14,4) NOT NULL,
    spend_pct       INTEGER NOT NULL,
    alert_fired     BOOLEAN NOT NULL DEFAULT FALSE,
    alert_level     VARCHAR(20),                           -- 'warning' (>= alert_threshold_pct) | 'breach' (>= 100%)
    resolved_at     TIMESTAMPTZ,                           -- set when a later check shows spend below threshold
    note            TEXT
);
CREATE INDEX IF NOT EXISTS idx_qc_quota_checked ON quota_check(quota_id, checked_at DESC);
CREATE INDEX IF NOT EXISTS idx_qc_active        ON quota_check(alert_fired, resolved_at);
