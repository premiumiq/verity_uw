# Verity Build Plan — Final

## Context

PremiumIQ Verity is an AI governance platform for P&C insurance. The goal: "Application X powered by Verity" — clear separation between the governance platform (Verity) and the business application (UW Demo). Verity must be designed as a distributable Python package (pip-installable), usable as an SDK, an API service, or a web application.

---

## Part 1: Architecture Decisions

### Build Location
Build in the current project directory `/home/avenugopal/verity_uw`. No `premiumiq-verity/` subdirectory — the repo root IS the project root.

### Database Approach
Raw SQL with Pydantic. No ORM. SQL queries in `.sql` files, transparent and debuggable. Thin Python helper loads named queries and returns Pydantic models.

### Schema Completeness
Full 7-state lifecycle in the schema from day one: `draft → candidate → staging → shadow → challenger → champion → deprecated`. The demo may only exercise a subset, but the schema, enums, and promotion validation logic are complete. The 7-state model IS the SR 11-7 compliance story.

### pgvector
`CREATE EXTENSION vector;` in the initial schema. `description_embedding vector(1536)` columns on `agent`, `task`, `tool`, and `prompt_version` tables from the start. Columns may be NULL initially — populated when embedding compute is implemented. No schema alterations needed later.

### MinIO
Include MinIO in App 1 docker-compose. Seed with synthetic documents. The document ingestion story ("this ACORD 855 PDF was pulled from MinIO, classified, and extracted") is materially more impressive for CIO demos. Text fixtures remain as fallback for local development without MinIO.

### UI Tech Stack
Jinja2 + HTMX + DaisyUI (Tailwind component library via CDN). No npm, no build step, no JavaScript to write. Server-rendered HTML with dynamic updates via HTMX.

---

## Part 2: Repository Structure

```
verity_uw/                           # Project root (current directory)
│
├── verity/                          # THE VERITY PACKAGE (pip-installable)
│   ├── pyproject.toml               # Package metadata: name=verity, dependencies
│   ├── verity/
│   │   ├── __init__.py              # Exports: Verity class
│   │   │
│   │   ├── core/                    # Pure Python SDK — the heart of Verity
│   │   │   ├── __init__.py
│   │   │   ├── client.py            # Verity class — main entry point for all operations
│   │   │   ├── registry.py          # Register/retrieve agents, tasks, prompts, configs, tools, pipelines
│   │   │   ├── lifecycle.py         # Promote (7-state), rollback, deprecate, approval gates
│   │   │   ├── execution.py         # Execute agents (multi-turn) and tasks (single-turn) with governance
│   │   │   ├── decisions.py         # Log decisions, query audit trail, record overrides
│   │   │   ├── testing.py           # Run test suites, validate against ground truth
│   │   │   └── reporting.py         # Model inventory, audit trail, compliance reports
│   │   │
│   │   ├── models/                  # Pydantic data models (NOT ORM)
│   │   │   ├── __init__.py
│   │   │   ├── agent.py             # Agent, AgentVersion, AgentConfig
│   │   │   ├── task.py              # Task, TaskVersion, TaskConfig
│   │   │   ├── prompt.py            # Prompt, PromptVersion, PromptAssignment
│   │   │   ├── inference_config.py  # InferenceConfig
│   │   │   ├── tool.py              # Tool, ToolAuthorization
│   │   │   ├── pipeline.py          # Pipeline, PipelineVersion, PipelineStep
│   │   │   ├── decision.py          # DecisionLog, OverrideLog, AuditTrailEntry
│   │   │   ├── lifecycle.py         # ApprovalRecord, LifecycleState enum, PromotionCriteria
│   │   │   ├── testing.py           # TestSuite, TestCase, TestResult, ValidationRun
│   │   │   └── reporting.py         # ModelInventoryItem, ModelCard, ComplianceReport
│   │   │
│   │   ├── db/                      # Database layer — raw SQL, transparent
│   │   │   ├── __init__.py
│   │   │   ├── connection.py        # Async connection pool (psycopg 3), named query loader
│   │   │   ├── schema.sql           # Full DDL — 7-state lifecycle, pgvector columns, all tables
│   │   │   ├── migrate.py           # Simple migration: apply schema.sql, track applied version
│   │   │   └── queries/             # SQL queries as named .sql files
│   │   │       ├── registry.sql     # get_agent_champion, get_task_champion, list_agents, etc.
│   │   │       ├── lifecycle.sql    # promote_version, rollback_version, create_approval, etc.
│   │   │       ├── decisions.sql    # log_decision, get_audit_trail, record_override, etc.
│   │   │       ├── testing.sql      # create_test_suite, log_test_result, get_validation_run, etc.
│   │   │       └── reporting.sql    # model_inventory, override_analysis, etc.
│   │   │
│   │   ├── api/                     # FastAPI routers (API service mode)
│   │   │   ├── __init__.py
│   │   │   ├── app.py               # create_verity_api(verity) → FastAPI sub-application
│   │   │   ├── registry.py          # /v1/agents, /v1/tasks, /v1/prompts, /v1/configs, /v1/tools
│   │   │   ├── lifecycle.py         # /v1/lifecycle/{entity_type}/{id}/promote, /rollback
│   │   │   ├── decisions.py         # /v1/decisions/log, /v1/decisions/{id}/override
│   │   │   ├── testing.py           # /v1/testing/run-suite, /v1/testing/run-ground-truth
│   │   │   └── reporting.py         # /v1/reports/model-inventory, /v1/reports/audit-trail
│   │   │
│   │   ├── web/                     # Web UI (admin/governance interface)
│   │   │   ├── __init__.py
│   │   │   ├── app.py               # create_verity_web(verity) → FastAPI sub-application
│   │   │   ├── routes.py            # HTML page routes (server-side rendered)
│   │   │   ├── templates/
│   │   │   │   ├── base.html        # Layout: DaisyUI theme, sidebar nav, header
│   │   │   │   ├── dashboard.html   # Overview: entity counts, recent decisions, system health
│   │   │   │   ├── agents.html      # Agent registry list
│   │   │   │   ├── agent_detail.html # Version history, prompts, tools, config, model card
│   │   │   │   ├── tasks.html       # Task registry list
│   │   │   │   ├── task_detail.html  # Version history, prompts, capability type, metrics
│   │   │   │   ├── prompts.html     # Prompt registry with governance tier badges
│   │   │   │   ├── prompt_detail.html # Version content, diff view, approval status
│   │   │   │   ├── configs.html     # Inference config browser
│   │   │   │   ├── tools.html       # Tool registry
│   │   │   │   ├── pipelines.html   # Pipeline steps visualization
│   │   │   │   ├── decisions.html   # Decision log: searchable, filterable
│   │   │   │   ├── decision_detail.html # Full decision: I/O, prompts used, tokens, tool calls
│   │   │   │   ├── audit_trail.html # Per-submission full task→agent chain
│   │   │   │   ├── lifecycle.html   # Promote/rollback controls with approval form
│   │   │   │   ├── model_inventory.html # Regulatory report: all champions
│   │   │   │   └── test_results.html # Per-entity test suite results
│   │   │   └── static/
│   │   │       └── verity.css       # Minimal overrides if needed
│   │   │
│   │   ├── setup/                   # Infrastructure setup utilities
│   │   │   ├── __init__.py
│   │   │   ├── postgres.py          # Check/create database, apply schema, verify extensions
│   │   │   ├── docker.py            # Generate docker-compose.yml for Verity standalone
│   │   │   └── k8s.py              # Generate k8s manifests (Deployment, Service, ConfigMap)
│   │   │                            # — not implemented now, but interface defined
│   │   │
│   │   └── cli.py                   # CLI entry points:
│   │                                #   verity init     — create DB, apply schema
│   │                                #   verity serve    — run API server
│   │                                #   verity web      — run web UI
│   │                                #   verity setup    — generate infra configs
│   │
│   └── tests/
│       ├── test_registry.py
│       ├── test_lifecycle.py
│       ├── test_execution.py
│       └── test_decisions.py
│
├── uw_demo/                         # THE BUSINESS APPLICATION (powered by Verity)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app — mounts Verity API + Web + UW routes
│   │   ├── config.py                # Settings from env vars
│   │   │
│   │   ├── setup/                   # Registers UW-specific entities in Verity
│   │   │   ├── __init__.py
│   │   │   ├── register_all.py      # Master registration script (calls all below in order)
│   │   │   ├── inference_configs.py  # 5 named configs
│   │   │   ├── tools.py             # 8-10 tool registrations
│   │   │   ├── tasks.py             # document_classifier, field_extractor (+ prompts)
│   │   │   ├── agents.py            # triage_agent, appetite_agent (+ prompts)
│   │   │   ├── pipelines.py         # uw_submission_pipeline
│   │   │   ├── test_suites.py       # Test suites + cases per entity
│   │   │   ├── promotions.py        # Approval records promoting all to champion
│   │   │   └── demo_data.py         # Pre-seeded decisions, overrides, submissions
│   │   │
│   │   ├── agents/                  # Agent execution: tool implementations + context builders
│   │   │   ├── __init__.py
│   │   │   ├── triage.py            # Triage tool functions: get_submission_context, etc.
│   │   │   └── appetite.py          # Appetite tool functions: get_guidelines, etc.
│   │   │
│   │   ├── tasks/                   # Task execution: input preparation + output parsing
│   │   │   ├── __init__.py
│   │   │   ├── classifier.py        # Document classifier input/output handling
│   │   │   └── extractor.py         # Field extractor input/output handling
│   │   │
│   │   ├── tools/                   # Shared Python tool functions called by agents/tasks
│   │   │   ├── __init__.py
│   │   │   ├── submission_tools.py  # get_full_submission_context, get_submission_detail
│   │   │   ├── guidelines_tools.py  # get_underwriting_guidelines
│   │   │   ├── document_tools.py    # get_documents_for_submission (MinIO integration)
│   │   │   └── mock_enrichment.py   # Simulated LexisNexis, D&B, Pitchbook responses
│   │   │
│   │   ├── db/                      # Business database (pas_db)
│   │   │   ├── __init__.py
│   │   │   ├── connection.py
│   │   │   ├── schema.sql           # accounts, submissions, submission_do_detail, etc.
│   │   │   └── queries/
│   │   │       ├── accounts.sql
│   │   │       └── submissions.sql
│   │   │
│   │   └── ui/                      # Minimal business workflow UI
│   │       ├── __init__.py
│   │       ├── routes.py
│   │       └── templates/
│   │           ├── base.html        # Business app layout (distinct nav from Verity admin)
│   │           ├── submissions.html  # Submission list with status badges
│   │           ├── submission_detail.html  # One submission: data + AI results panel
│   │           ├── pipeline_runner.html    # Run pipeline, see live step-by-step progress
│   │           └── documents.html    # Document list for a submission (from MinIO)
│   │
│   └── seed_docs/                   # Synthetic ACORD forms, loss runs (PDFs + text)
│       ├── acord_855_sample.pdf
│       ├── acord_855_sample.txt     # Text fallback
│       ├── acord_125_sample.pdf
│       ├── acord_125_sample.txt
│       ├── loss_run_sample.pdf
│       ├── loss_run_sample.txt
│       └── supplemental_do_sample.txt
│
├── docker-compose.yml               # PostgreSQL (pgvector) + MinIO + App
├── .env
├── .gitignore
├── Dockerfile                       # Single app container
├── requirements.txt                 # Combined deps (or just: -e ./verity + uw deps)
└── scripts/
    ├── init-multiple-dbs.sh         # Creates verity_db + pas_db, enables pgvector
    └── seed.py                      # Master seed: schema → Verity entities → business data
```

### How the Business App Uses Verity (Code Pattern)

```python
# uw_demo/app/main.py
from fastapi import FastAPI
from verity import Verity
from verity.api.app import create_verity_api
from verity.web.app import create_verity_web

app = FastAPI(title="UW Demo — Powered by PremiumIQ Verity")

# Initialize Verity (SDK mode — direct database access, no HTTP)
verity = Verity(database_url=settings.VERITY_DB_URL)

# Mount Verity governance API at /verity/v1/...
verity_api = create_verity_api(verity)
app.mount("/verity/api", verity_api)

# Mount Verity admin web UI at /verity/admin/...
verity_web = create_verity_web(verity)
app.mount("/verity/admin", verity_web)

# Business workflow routes at /uw/...
from uw_demo.app.ui.routes import router as uw_router
app.include_router(uw_router, prefix="/uw")
```

```python
# uw_demo/app/agents/triage.py — Business app invokes an agent through Verity
async def run_triage(verity: Verity, submission_id: str, context: dict):
    result = await verity.execute_agent(
        agent_name="triage_agent",
        context=context,
        submission_id=submission_id,
        channel="production"
    )
    # Verity has already:
    #  1. Resolved champion config (prompts, tools, inference params)
    #  2. Assembled prompts with condition_logic
    #  3. Checked tool authorizations
    #  4. Called Claude with governed parameters
    #  5. Logged the decision with full snapshot
    return result  # result.decision_log_id links to verity_db audit trail
```

### Verity Deployment Modes (Architecture — Build Later)

```
Mode 1: Python SDK (pip install verity)
─────────────────────────────────────────
Business app imports verity, calls methods directly.
Database connection managed by the consuming app.
Used when: business app and Verity share the same process.

Mode 2: API Service (verity serve --port 8001)
─────────────────────────────────────────
Standalone FastAPI service exposing /v1/... endpoints.
Own database connection, own process, own container.
Used when: multiple apps consume Verity, or microservice architecture.
Docker:  verity serve --host 0.0.0.0 --port 8001
K8s:     Deployment + Service + ConfigMap (postgres connection)

Mode 3: Web Application (verity web --port 8001)
─────────────────────────────────────────
SDK + API + Admin UI in one process.
Used when: Verity is the primary interface (governance teams).
Docker:  verity web --host 0.0.0.0 --port 8001
K8s:     Same as Mode 2 with web UI enabled

Mode 4: Embedded (current demo)
─────────────────────────────────────────
Business app mounts Verity API + Web as sub-applications.
Single process, single container. Simplest deployment.
```

The `verity/setup/` directory provides:
- `postgres.py`: Check DB exists, apply schema, verify pgvector extension
- `docker.py`: Generate `docker-compose.yml` for standalone Verity deployment
- `k8s.py`: Generate Kubernetes manifests (Deployment, Service, ConfigMap, PersistentVolumeClaim) — interface defined now, implementation deferred

---

## Part 3: Schema (Full PRD Compliance)

### Lifecycle: Full 7-State Model

```sql
CREATE TYPE lifecycle_state AS ENUM (
    'draft', 'candidate', 'staging', 'shadow',
    'challenger', 'champion', 'deprecated'
);
```

The promotion engine validates transitions by entity type and materiality tier as specified in PRD Section 10.1. The demo exercises `draft → candidate → champion` (fast-track for seeded data), but the full 7-state path with HITL gates is implemented and demonstrable.

### pgvector: Columns Present from Day One

```sql
CREATE EXTENSION IF NOT EXISTS "vector";

-- On agent table:
description_embedding       vector(1536),
description_embedding_model VARCHAR(100),
last_similarity_check_at    TIMESTAMP,
similarity_flags            JSONB DEFAULT '[]',

-- On task table: same columns
-- On tool table: same columns
-- On prompt_version table: content_embedding vector(1536)
```

Columns are nullable. Populated when embedding compute is implemented (Phase 5 or App 1 upgrade).

### Tables: Full PRD Set Minus MCP

**Included (Phase 1 schema):**
All tables from PRD Section 6: `inference_config`, `agent`, `agent_version`, `task`, `task_version`, `prompt`, `prompt_version`, `entity_prompt_assignment`, `tool`, `agent_version_tool`, `task_version_tool`, `pipeline`, `pipeline_version`, `test_suite`, `test_case`, `test_execution_log`, `ground_truth_dataset`, `validation_run`, `evaluation_run`, `approval_record`, `agent_decision_log`, `override_log`, `model_card`, `metric_threshold`, `incident`, `description_similarity_log`

**Deferred (not in Phase 1 schema):**
`mcp_server`, `mcp_call_log` — No MCP servers in the demo. Add when MCP integration is needed.

---

## Part 4: Docker Compose (App 1)

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg16       # Includes pgvector pre-installed
    environment:
      POSTGRES_USER: verityuser
      POSTGRES_PASSWORD: veritypass123
      POSTGRES_MULTIPLE_DATABASES: verity_db,pas_db
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-multiple-dbs.sh:/docker-entrypoint-initdb.d/init.sh
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U verityuser"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:RELEASE.2024-11-07T00-52-20Z
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin123
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio-setup:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minioadmin minioadmin123;
      mc mb --ignore-existing local/submissions;
      mc mb --ignore-existing local/uw-guidelines;
      mc mb --ignore-existing local/ground-truth-datasets;
      echo 'MinIO buckets created';
      "

  app:
    build: .
    environment:
      VERITY_DB_URL: postgresql://verityuser:veritypass123@postgres:5432/verity_db
      PAS_DB_URL: postgresql://verityuser:veritypass123@postgres:5432/pas_db
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin123
      MINIO_SECURE: "false"
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      APP_ENV: demo
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy

volumes:
  postgres_data:
  minio_data:
```

---

## Part 5: What Gets Demonstrated in App 1

### Verity Platform Features (the governance product)

| # | Feature | Demo Action | Verity UI Page |
|---|---|---|---|
| 1 | **Agent/Task Registry** | Browse all registered AI components | `/verity/admin/agents`, `/tasks` |
| 2 | **Version Management** | See version history, compare configs between versions | Agent/task detail pages |
| 3 | **Prompt Governance** | View prompts by governance tier; behavioural prompts show approval status | `/verity/admin/prompts` |
| 4 | **Inference Configs** | Named config sets with all LLM parameters | `/verity/admin/configs` |
| 5 | **Tool Authorization** | Which tools each agent version is authorized to call | Agent detail page |
| 6 | **7-State Lifecycle** | Promote a version through gates; show HITL approval requirements per tier | `/verity/admin/lifecycle` |
| 7 | **Execution Governance** | Run an agent/task; show Verity resolving config at runtime | Live demo + decision detail |
| 8 | **Decision Logging** | Every AI call logged: prompts, config snapshot, I/O, tokens, duration | `/verity/admin/decisions` |
| 9 | **Audit Trail** | Per-submission chain: every task and agent that ran, with exact versions | `/verity/admin/audit-trail` |
| 10 | **Override Tracking** | Human overrides AI decision with reason code | Decision detail page |
| 11 | **Model Inventory** | Regulatory report: all champions, materiality, validation, override rates | `/verity/admin/model-inventory` |
| 12 | **Model Cards** | SR 11-7 documentation per entity version | Agent/task detail page |
| 13 | **Testing Framework** | Test suites with results, metric types per capability | `/verity/admin/test-results` |
| 14 | **Pipeline Visualization** | Show pipeline steps with entity types and dependencies | `/verity/admin/pipelines` |

### Business Application Features (UW Demo powered by Verity)

| # | Feature | Demo Action | UW UI Page |
|---|---|---|---|
| 1 | **Submission List** | Browse 5 pre-seeded submissions with status badges | `/uw/submissions` |
| 2 | **Submission Detail** | View submission data + all AI results | `/uw/submissions/{id}` |
| 3 | **Document Upload** | Upload ACORD PDF to MinIO (or view pre-seeded docs) | Submission detail |
| 4 | **Document Classification** | Classifier task identifies document type + confidence | Submission detail AI panel |
| 5 | **Field Extraction** | Extractor task pulls structured fields from document | Submission detail AI panel |
| 6 | **Risk Triage** | Triage agent reasons across data → risk score + narrative | Submission detail AI panel |
| 7 | **Appetite Check** | Appetite agent evaluates against guidelines → determination | Submission detail AI panel |
| 8 | **Pipeline Execution** | Run full pipeline: classify → extract → triage → appetite | `/uw/pipeline/{submission_id}` |
| 9 | **Pipeline Progress** | Live step-by-step progress with entity type labels | Pipeline runner page |

### Agents and Tasks Registered in App 1

**Tasks (bounded, single-turn, fixed I/O):**

| Task | Capability | Materiality | Inference Config | What It Does |
|---|---|---|---|---|
| `document_classifier` | classification | medium | `classification_strict` (temp=0.0) | Classifies document text → type + confidence |
| `field_extractor` | extraction | medium | `extraction_deterministic` (temp=0.0) | Extracts structured fields from ACORD-like text |

**Agents (multi-turn, tool-using, autonomous):**

| Agent | Materiality | Inference Config | What It Does |
|---|---|---|---|
| `triage_agent` | high | `triage_balanced` (temp=0.2) | Calls tools to gather context → reasons about risk → Green/Amber/Red + narrative |
| `appetite_agent` | high | `triage_balanced` (temp=0.2) | Retrieves guidelines → compares against submission → appetite determination with citations |

**Why 2+2 is sufficient:** Every Verity feature (registry, versioning, 7-state lifecycle, prompt governance, tool auth, execution, logging, audit, override, reporting, testing, model cards) is demonstrable with this set. The remaining entities (quote_assistant, referral_memo, renewal_agent, loss_run_parser, acord_855_extractor, etc.) exercise the same Verity features with more business logic — added in App 2.

### Data Setup

**verity_db:**
```
inference_configs:       5 (classification_strict, extraction_deterministic,
                           triage_balanced, generation_narrative, renewal_analytical)
tools:                   8-10 (get_submission_context, get_guidelines, get_documents,
                                update_submission_event, mock enrichment tools, etc.)
agents:                  2 (triage_agent, appetite_agent)
agent_versions:          2 (v1.0.0 champion each) + 1 (v0.9.0 deprecated triage, for version history demo)
tasks:                   2 (document_classifier, field_extractor)
task_versions:           2 (v1.0.0 champion each) + 1 (v0.9.0 deprecated classifier)
prompts:                 8 (system + user template for each agent and task)
prompt_versions:         8+ (v1 current + v0 deprecated for diff demo)
entity_prompt_assign:    8 (linking active prompts to champion versions)
agent_version_tool:      ~10 (tool authorizations per agent version)
pipeline:                1 (uw_submission_pipeline)
pipeline_version:        1 (4-step: classify → extract → triage → appetite)
test_suites:             4 (one per entity: unit suite)
test_cases:              ~12 (3 per entity)
test_execution_log:      ~12 (pre-seeded passing results)
ground_truth_dataset:    2 (classifier + triage agent metadata)
validation_run:          2 (pre-seeded passing validation for classifier + triage)
approval_records:        6+ (promoting each entity through lifecycle gates)
model_cards:             2 (triage_agent, appetite_agent — high materiality)
metric_thresholds:       4 (per entity as specified in PRD)
agent_decision_log:      15-20 pre-seeded (showing past decisions for browsing)
override_log:            2-3 pre-seeded (showing human overrides)
```

**pas_db (simplified for App 1):**
```
accounts:                3 (Acme Dynamics LLC, TechFlow Industries Inc, Meridian Holdings Corp)
submissions:             5 with varying profiles:
  SUB-001: Acme Dynamics, D&O, clean profile         → Green (pre-computed)
  SUB-002: TechFlow Industries, D&O, some red flags   → Amber (pre-computed)
  SUB-003: Meridian Holdings, GL, high risk            → Red (pre-computed)
  SUB-004: Acme Dynamics, GL, borderline               → Amber (pre-computed)
  SUB-005: TechFlow Industries, D&O, fresh             → No AI results (for live demo)
```

**MinIO (seeded documents):**
```
submissions/SUB-001/acord_855_acme.pdf
submissions/SUB-001/loss_run_acme.pdf
submissions/SUB-002/acord_855_techflow.pdf
submissions/SUB-005/acord_855_techflow_new.pdf   ← for live demo
uw-guidelines/do_guidelines_v1.txt
uw-guidelines/gl_guidelines_v1.txt
```

---

## Part 6: Build Phases

### Phase 1: Verity Package Foundation (Days 1-3)
**Critical files:** `verity/verity/db/schema.sql`, `verity/verity/db/connection.py`, `verity/verity/models/*.py`, `verity/pyproject.toml`

- `pyproject.toml` with package metadata and dependencies (psycopg[binary], pydantic, fastapi, jinja2, anthropic, minio, httpx)
- Full `schema.sql` from PRD Section 6 (7-state lifecycle, pgvector columns, all tables except MCP)
- `connection.py`: async connection pool (psycopg 3), `.sql` file loader, `fetch_one`/`fetch_all`/`execute` helpers
- `migrate.py`: apply schema.sql to database, verify pgvector extension
- All Pydantic models in `models/`
- `cli.py` with `verity init` command

### Phase 2: Verity Core SDK (Days 4-7)
**Critical files:** `verity/verity/core/*.py`, `verity/verity/db/queries/*.sql`

- `registry.py` + `queries/registry.sql`: CRUD for all entity types, get_champion_config
- `lifecycle.py` + `queries/lifecycle.sql`: 7-state promotion with per-tier validation, HITL gate enforcement, rollback
- `decisions.py` + `queries/decisions.sql`: log_decision with inference_config_snapshot, audit_trail query, record_override
- `execution.py`: agent runner (multi-turn Claude tool loop) + task runner (single-turn structured output) — prompt assembly, tool auth checking
- `testing.py` + `queries/testing.sql`: run_test_suite, log results
- `reporting.py` + `queries/reporting.sql`: model_inventory, audit_trail_report
- `client.py`: Verity class wrapping all core modules

### Phase 3: Verity API + Web UI (Days 8-14)
**Critical files:** `verity/verity/api/*.py`, `verity/verity/web/*.py`, `verity/verity/web/templates/*.html`

- API routers wrapping every SDK method (auto-generates OpenAPI docs)
- Web UI: base template (DaisyUI sidebar layout), all 14+ pages listed above
- HTMX for: decision log filtering, lifecycle promotion, live agent execution

### Phase 4: Business App + Seed Data (Days 15-19)
**Critical files:** `uw_demo/app/main.py`, `uw_demo/app/setup/*.py`, `uw_demo/app/db/schema.sql`

- Business DB schema (accounts, submissions)
- Registration scripts: all 5 configs, 2 agents, 2 tasks, tools, prompts, pipeline
- Seed: demo data including pre-computed decisions, overrides, test results
- Synthetic documents (PDF generation for ACORD 855, loss run)
- MinIO seeding
- Agent tool implementations (triage context builder, guidelines retriever)
- Task implementations (classifier, extractor)
- Business UI: submissions list, submission detail, pipeline runner

### Phase 5: Integration + Demo Polish (Days 20-22)
- End-to-end pipeline execution: upload → classify → extract → triage → appetite
- Demo reset endpoint (truncate decision_log, reset fresh submission)
- Pre-seeded browsing data verification
- Embedding compute for description similarity (populate pgvector columns)
- Walkthrough script

---

## Part 7: App 1 Upgrade Path (Before App 2)

These can be added incrementally to App 1 to strengthen the demo:

1. **Description embedding similarity checks** — Populate pgvector columns, implement similarity check at registration, show "we caught ambiguous definitions" in demo
2. **Additional documents in MinIO** — More sample submissions with varied document sets
3. **Mock enrichment responses** — Simulated LexisNexis, D&B data in agent tool responses
4. **Fairness analysis placeholder** — Show the framework exists even if metrics are pre-computed

---

## Part 8: App 2 Additions (3-4 weeks after App 1)

- Remaining agents: quote_assistant, referral_memo_agent, renewal_agent
- Remaining tasks: acord_855_extractor, acord_125_extractor, loss_run_parser, mdm_matcher, enrichment_aggregator, clearance_checker, document_validator
- Full pipeline: all 13 steps with parallel groups and dependency resolution
- pas_db expansion: quotes, policies, renewals, loss_history, endorsements
- workflow_db: sync logs, SLAs, rating logs
- broker_db: agencies, brokers
- Rating engine: D&O + GL rule-based
- ServiceNow PDI integration (REST API sync)
- PDF generation: quote letters, referral memos
- Ground truth datasets with actual validation runs

---

## Part 9: Verification

### Infrastructure
1. `docker-compose up` → postgres (pgvector) + minio + app healthy
2. `SELECT * FROM pg_extension WHERE extname = 'vector';` returns row in verity_db
3. All Verity tables created including vector(1536) columns
4. MinIO buckets created with seed documents

### Verity SDK
5. `verity.get_agent_config("triage_agent")` returns: prompts, tools, inference_config with temperature 0.2
6. `verity.get_task_config("document_classifier")` returns: inference_config with temperature 0.0, capability_type=classification

### Verity API
7. `GET /verity/api/v1/agents/triage_agent/champion` returns same as SDK
8. `POST /verity/api/v1/decisions/log` creates record and returns decision_log_id

### Verity Web UI
9. Dashboard at `/verity/admin/` shows: 2 agents, 2 tasks, 5 configs, recent decisions
10. Agent detail: version history (v0.9.0 deprecated + v1.0.0 champion), prompts, tools, model card
11. Decision log: 15-20 pre-seeded entries, filterable by entity type
12. Lifecycle page: promote a new triage_agent v1.1.0 through draft → candidate → champion
13. Model inventory: all champions with materiality tier and validation status

### Business App
14. `/uw/submissions` shows 5 submissions with status badges
15. Click SUB-005 → see no AI results yet
16. Click "Run Pipeline" on SUB-005 → classifier runs → extractor runs → triage runs → appetite runs
17. Each step visible in pipeline progress with [TASK] / [AGENT] labels
18. After pipeline: submission detail shows all AI results
19. Switch to Verity admin → decision log shows new entries from the pipeline run
20. Audit trail for SUB-005 shows complete chain: classifier → extractor → triage → appetite
