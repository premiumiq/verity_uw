# Product Requirements Document
# PremiumIQ Verity — AI Trust & Compliance Framework
# with Integrated Commercial Underwriting Platform

**Product:** PremiumIQ Verity  
**Version:** 3.0 — Revised Metamodel  
**Date:** 2026-04-03  
**Status:** Ready for Development  
**Target Environment:** Claude Code  
**Company:** PremiumIQ  

---

## CRITICAL ARCHITECTURAL PRINCIPLE

> **Verity is not a separate product that the UW platform integrates with. Verity is the governance layer that the UW platform runs on. Every agent definition, every task definition, every prompt, every inference configuration, every tool registration, and every lifecycle state lives in Verity's metamodel database. The UW platform's execution engine has no AI definitions of its own — it calls Verity APIs at runtime to retrieve what to run, how to run it, and with what parameters. This is non-negotiable and must be preserved throughout development.**

---

## VOCABULARY REFERENCE

This document uses the following terms consistently. Read this before any implementation work.

| Term | Definition | Regulatory Equivalent |
|---|---|---|
| **Agent** | A goal-directed Claude invocation that autonomously decides which tools to call, in what order, across multiple reasoning steps. Produces structured output from complex synthesis. | Model System (SR 11-7) |
| **Task** | A bounded, single-purpose Claude invocation with defined inputs and outputs. Does not choose its own execution path — input in, structured output out. | Bounded Model (SR 11-7, ASOP 56) |
| **Prompt** | A reusable text artifact (system prompt or user message template) managed as a versioned, governed entity in the metamodel. | Model Parameter |
| **Tool** | A Python function callable by agents (and optionally tasks) to interact with external systems, databases, or APIs. | N/A |
| **Inference Config** | A named, versioned set of LLM API parameters (temperature, max_tokens, etc.) applied to a specific agent version or task version. | Model Configuration |
| **Pipeline** | An ordered, versioned sequence of agents and tasks with defined dependencies, parallelism, and error handling. | Model System (composite) |
| **entity_type** | A discriminator field indicating whether a governance record (test suite, model card, ground truth dataset, etc.) targets an `agent`, `task`, `prompt`, `pipeline`, or `tool`. | N/A (technical) |
| **capability_type** | The specific AI capability a task implements: `classification`, `extraction`, `generation`, `summarisation`, `matching`, `validation`. | Model Type (ASOP 56) |
| **governance_tier** | The regulatory weight of a prompt: `behavioural` (full lifecycle), `contextual` (lightweight versioning), `formatting` (minimal governance). | N/A (internal) |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Repository & Project Structure](#4-repository--project-structure)
5. [Infrastructure & Docker Compose](#5-infrastructure--docker-compose)
6. [Verity — Database Schema (verity_db)](#6-verity--database-schema-verity_db)
7. [UW Platform — Database Schemas](#7-uw-platform--database-schemas)
8. [MinIO Document Store](#8-minio-document-store)
9. [Verity — Core API Layer](#9-verity--core-api-layer)
10. [Verity — Lifecycle Management](#10-verity--lifecycle-management)
11. [Verity — Testing Framework](#11-verity--testing-framework)
12. [Verity — Compliance & Reporting](#12-verity--compliance--reporting)
13. [UW Platform — FastAPI Middleware](#13-uw-platform--fastapi-middleware)
14. [UW Platform — Execution Engine](#14-uw-platform--execution-engine)
15. [UW Platform — Agents and Tasks](#15-uw-platform--agents-and-tasks)
16. [UW Platform — Rating Engine](#16-uw-platform--rating-engine)
17. [ServiceNow Configuration](#17-servicenow-configuration)
18. [Seed Data](#18-seed-data)
19. [Demo Scenario Script](#19-demo-scenario-script)
20. [Development Phases](#20-development-phases)
21. [Non-Functional Requirements](#21-non-functional-requirements)
22. [Acceptance Criteria](#22-acceptance-criteria)
23. [Out of Scope](#23-out-of-scope)

---

## 1. Product Overview

### 1.1 What Is PremiumIQ Verity

PremiumIQ Verity is a metamodel-driven AI trust and compliance framework for P&C insurance. It governs the full lifecycle of agents and tasks — from initial definition through testing, validation, production deployment, monitoring, and deprecation — in a manner that satisfies US insurance regulatory requirements including SR 11-7, the NAIC AI Model Bulletin, Colorado SB21-169, and ORSA/ASOP 56 standards.

Verity is not an AI model. It is the governance infrastructure that AI systems run on. Every agent is a database record. Every task is a database record. Every prompt is versioned. Every inference configuration is named and governed. Every promotion requires human approval. Every decision is auditable.

### 1.2 The Agent vs. Task Distinction

This is the foundational design decision of the Verity metamodel. Getting this right determines whether the testing framework, the validation metrics, the compliance reporting, and the execution engine all work correctly.

**Agents** (5 in the UW platform) are appropriate where:
- The AI must *decide* what to do next based on intermediate results
- Multiple tools are called in a sequence the AI determines at runtime
- The reasoning path is not fully predictable in advance
- Complex synthesis across heterogeneous inputs is required

**Tasks** (4 in the UW platform) are appropriate where:
- Inputs and outputs are fully defined in advance
- The AI applies a specific capability (classify, extract, generate, match)
- The execution path is always the same: input → capability → output
- Metrics are well-defined and measurable against ground truth

**The UW Pipeline mapped correctly:**

| Step | Entity Type | Rationale |
|---|---|---|
| Document Validation | Task (validation) | Rule-based check, no reasoning required — could be non-AI |
| Document Classification | Task (classification) | Fixed I/O: doc text → doc type + confidence |
| Field Extraction (ACORD 855) | Task (extraction) | Fixed I/O: doc text + schema → structured fields |
| Field Extraction (ACORD 125) | Task (extraction) | Fixed I/O: doc text + schema → structured fields |
| Loss Run Parsing | Task (extraction) | Fixed I/O: doc text + schema → structured loss data |
| MDM Account Matching | Task (matching) | Fixed I/O: company name → matched entity + confidence |
| Account Enrichment Aggregation | Task (generation) | Fixed I/O: 5 source results → unified enrichment record |
| PAS Clearance Check | Task (validation) | Deterministic database lookups, no reasoning |
| Risk Triage | **Agent** | Must weigh competing factors, decide what matters, produce nuanced assessment |
| Appetite Assessment | **Agent** | Must reason across guidelines + submission, cite specific sections |
| Quote Assistance | **Agent** | Must synthesise rating + risk profile + market judgment |
| Referral Memo Generation | **Agent** | Must synthesise multiple sources into coherent narrative |
| Renewal Analysis | **Agent** | Must compare time periods, weigh changes, make judgment |

### 1.3 What Is the UW Platform

The Commercial Underwriting Platform is the first business application built on Verity. It demonstrates a reference architecture for specialty P&C insurance (D&O and GL) underwriting workflow, using:

- **ServiceNow PDI** as the underwriting workflow engine and UW-facing interface
- **PostgreSQL** (simulated PAS) as the system of record for all policy data
- **FastAPI** as the integration middleware and Verity execution host
- **MinIO** as the document repository
- **Claude (Anthropic API)** as the AI reasoning and task execution engine

### 1.4 Demo Audience & Positioning

**Primary audience:** CIOs and CTOs at P&C insurance carriers, specialty insurers, and brokerage firms.

**Demo narrative:** *"Every agent and task you see operating right now is running on Verity. The triage agent that just scored that submission Amber is version 2.1, promoted to Champion after ground truth validation with F1 of 0.93. The document classifier that identified those three documents as ACORD 855, loss runs, and supplemental application — also governed by Verity, version 1.2, validated against 200 labeled documents with precision 0.96. We can reconstruct every decision, every classification, every extraction. The entire reasoning chain is auditable."*

### 1.5 Lines of Business

- **Directors & Officers Liability (D&O)** — Private company D&O
- **General Liability (GL)** — Commercial GL

### 1.6 Scope Boundary

| In Scope | Out of Scope |
|---|---|
| Verity metamodel: agents, tasks, prompts, inference configs, tools, pipelines | Broker-facing portal |
| Verity lifecycle management with HITL gates | Claims management |
| Verity testing framework (mock mode, ground truth, metric validation) | Billing and premium collection |
| Verity compliance reporting (SR 11-7, NAIC, CO SB21-169) | Reinsurance workflows |
| Description embedding and ambiguity detection | Actuarial rating models |
| D&O + GL submission workflow end-to-end | Real LexisNexis/Pitchbook/D&B integration |
| Document classification, extraction, enrichment tasks | Broker-facing submission portal |
| Risk triage, appetite, quote, referral, renewal agents | Multi-carrier programs |
| ServiceNow UW workflow management | Production SSL/TLS |
| Rule-based D&O + GL rating engine | Cloud deployment or CI/CD |

---

## 2. System Architecture

### 2.1 Integrated Platform Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        SERVICENOW PDI                                   │
│                  "Underwriting Workflow Engine"                         │
│                                                                         │
│  Operator creates submission → UW assigned → reviews AI analysis →     │
│  requests info / quotes / refers / declines / binds                    │
│  Flow Designer manages SLAs, approvals, notifications                   │
│  Custom widget displays Verity AI analysis panel per submission         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ REST (ServiceNow Table API)
                             │ bidirectional — workflow state only
┌────────────────────────────▼────────────────────────────────────────────┐
│                     FASTAPI (Port 8000)                                 │
│              "Integration Middleware & Verity Execution Host"           │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    VERITY EXECUTION ENGINE                      │   │
│  │  get_agent() · get_task() · get_pipeline()                      │   │
│  │  → resolves champion version, prompts, inference_config, tools  │   │
│  │  log_decision() · record_override() · update_lifecycle_state()  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  UW Business Logic: submission sync, rating engine, doc management,    │
│  renewal triggers, admin UI, mock enrichment API                        │
└──────┬─────────────────────────────────────────┬───────────────────────┘
       │                                         │
┌──────▼──────────────────┐           ┌──────────▼──────────────────────┐
│     POSTGRESQL          │           │           MINIO                  │
│                         │           │    "Document Repository"         │
│  verity_db              │           │                                  │
│  ├ agent                │           │  /acord-forms                    │
│  ├ agent_version        │           │  /loss-runs                      │
│  ├ task                 │           │  /supplementals                  │
│  ├ task_version         │           │  /quote-letters                  │
│  ├ prompt               │           │  /binders                        │
│  ├ prompt_version       │           │  /uw-guidelines                  │
│  ├ entity_prompt_assign │           │  /referral-memos                 │
│  ├ inference_config     │           │  /renewal-notices                │
│  ├ tool                 │           │  /ground-truth-datasets          │
│  ├ agent_version_tool   │           └─────────────────────────────────┘
│  ├ task_version_tool    │
│  ├ pipeline             │
│  ├ pipeline_version     │
│  ├ mcp_server           │
│  ├ test_suite           │
│  ├ test_case            │
│  ├ test_execution_log   │
│  ├ ground_truth_dataset │
│  ├ validation_run       │
│  ├ evaluation_run       │
│  ├ approval_record      │
│  ├ agent_decision_log   │
│  ├ override_log         │
│  ├ incident             │
│  ├ model_card           │
│  ├ metric_threshold     │
│  ├ mcp_call_log         │
│  └ description_sim_log  │
│                         │
│  pas_db                 │
│  workflow_db            │
│  broker_db              │
└─────────────────────────┘
```

### 2.2 The Verity Execution Contract

The UW platform's execution engine never holds AI definitions locally. At runtime, for every agent or task invocation:

```python
# AGENT invocation
agent_config = verity.get_agent("triage_agent")
# Returns:
# {
#   agent_version_id, version_label, lifecycle_state,
#   prompts: [
#     {prompt_version_id, content, api_role: "system", governance_tier: "behavioural"},
#     {prompt_version_id, content, api_role: "user",   governance_tier: "contextual",
#      condition_logic: null}
#   ],
#   inference_config: {model_name, temperature, max_tokens, extended_params},
#   tools: [{tool_id, name, mock_mode_enabled, data_classification_max}],
#   authority_thresholds: {requires_hitl_above_premium: 500000, ...},
#   output_schema: {...},
#   materiality_tier: "high"
# }

result = execute_agent(agent_config, submission_context)

verity.log_decision(
    entity_type="agent",
    entity_version_id=agent_config.agent_version_id,
    submission_id=submission_id,
    prompt_version_ids=[p.prompt_version_id for p in agent_config.prompts],
    inference_config_snapshot=agent_config.inference_config,
    inputs=submission_context,
    outputs=result,
    duration_ms=elapsed,
    input_tokens=usage.input_tokens,
    output_tokens=usage.output_tokens
)

# TASK invocation — same contract, different entity type
task_config = verity.get_task("document_classifier")
result = execute_task(task_config, document_text)
verity.log_decision(entity_type="task", entity_version_id=task_config.task_version_id, ...)
```

### 2.3 System Boundaries

| System | Owns | Never Touches |
|---|---|---|
| ServiceNow PDI | Workflow state, task assignment, SLAs, UW-facing UI | PostgreSQL; agent/task definitions |
| Verity (verity_db) | All AI definitions: agents, tasks, prompts, inference configs, tools, pipelines, test results, decisions, approvals | Insurance business logic |
| pas_db | All insurance data: accounts, submissions, quotes, policies, renewals, losses | AI definitions |
| workflow_db | Sync state, event log, SLA tracking, rating log, document metadata | AI definitions |
| broker_db | Broker and agency reference data | AI definitions |
| MinIO | All documents: ACORD forms, loss runs, quote letters, ground truth datasets | Workflow state |
| FastAPI | Orchestration, execution engine, business logic, rating engine | None — it is the integration hub |
| Claude API | AI reasoning and task execution per invocation | Persistent state of any kind |

### 2.4 Data Flow Rules

1. ServiceNow never reads from or writes to PostgreSQL directly.
2. FastAPI is the only system that writes to PostgreSQL.
3. MinIO is accessed via FastAPI only — all access via presigned URLs.
4. Claude is invoked by the execution engine only, with all parameters sourced from Verity.
5. Agent and task definitions live exclusively in verity_db. No prompt text, inference parameter, tool list, or authority threshold is hardcoded in application code.
6. Every Claude invocation — agent or task — is logged to `verity_db.agent_decision_log` before the result is used downstream.
7. The inference_config snapshot is stored with each decision log, not just the config ID — this ensures historical decisions can be reconstructed even if the config changes.

---

## 3. Technology Stack

### 3.1 Pinned Versions

| Component | Technology | Version |
|---|---|---|
| Container orchestration | Docker Compose | 3.9 |
| API framework | FastAPI | 0.115.x |
| ASGI server | Uvicorn | 0.30.x |
| Python runtime | Python | 3.12 |
| Database | PostgreSQL | 16 with pgvector extension |
| Vector extension | pgvector | 0.7.x |
| ORM | SQLAlchemy | 2.0.x |
| Migrations | Alembic | 1.13.x |
| Object store | MinIO | RELEASE.2024-11-07 |
| MinIO SDK | minio (Python) | 7.2.x |
| Task scheduling | APScheduler | 3.10.x |
| AI SDK | anthropic | 0.40.x |
| Embeddings | anthropic (text-embedding-3-small via API) | same SDK |
| PDF extraction | PyMuPDF (fitz) | 1.24.x |
| PDF generation | ReportLab | 4.2.x |
| Fuzzy matching | rapidfuzz | 3.9.x |
| HTTP client | httpx | 0.27.x |
| Data validation | Pydantic | 2.x |
| Admin UI templating | Jinja2 | 3.1.x |
| Testing framework | pytest + pytest-asyncio | 8.x |
| Workflow engine | ServiceNow PDI | Xanadu release |

**Note on pgvector:** Required for description embedding similarity checks. Install via `CREATE EXTENSION vector;` in verity_db. Embedding dimension: 1536 (text-embedding-3-small).

---

## 4. Repository & Project Structure

```
premiumiq-verity/
│
├── docker-compose.yml
├── .env
├── .gitignore
├── README.md
│
├── scripts/
│   ├── init-multiple-dbs.sh
│   └── seed/
│       ├── seed_all.py
│       ├── seed_verity.py        # Registers all agents, tasks, prompts,
│       │                         # inference configs, tools in Verity
│       ├── seed_pas.py
│       ├── seed_brokers.py
│       └── seed_minio.py
│
├── verity/                       # Verity governance layer (port 8001)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   │
│   ├── db/
│   │   ├── engine.py
│   │   ├── models.py             # All Verity ORM models
│   │   ├── schema.sql            # Full verity_db DDL
│   │   └── migrations/
│   │
│   ├── api/
│   │   ├── registry.py           # GET agent, task, prompt, pipeline, tool
│   │   ├── lifecycle.py          # POST promote, rollback
│   │   ├── decisions.py          # POST log_decision, GET audit_trail
│   │   ├── overrides.py          # POST record_override
│   │   ├── testing.py            # POST run_test_suite, run_ground_truth
│   │   ├── validation.py         # POST run_fairness_analysis
│   │   ├── incidents.py          # POST create_incident, rollback
│   │   ├── reporting.py          # GET model_inventory, reg_report
│   │   ├── embeddings.py         # POST compute_embeddings, check_similarity
│   │   └── health.py
│   │
│   ├── lifecycle/
│   │   ├── promotion_engine.py
│   │   ├── approval_workflow.py
│   │   └── deprecation.py
│   │
│   ├── testing/
│   │   ├── mock_runner.py
│   │   ├── suite_runner.py
│   │   ├── ground_truth.py
│   │   └── fairness.py
│   │
│   ├── embeddings/
│   │   ├── compute.py            # Computes and stores description embeddings
│   │   └── similarity.py         # Cosine similarity checks, ambiguity detection
│   │
│   └── reporting/
│       ├── model_inventory.py
│       ├── audit_trail.py
│       └── documentation.py
│
├── uw/                           # UW Platform (port 8000)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   │
│   ├── execution/
│   │   ├── engine.py             # Core Verity execution contract
│   │   ├── agent_runner.py       # Agent-specific execution logic
│   │   ├── task_runner.py        # Task-specific execution logic
│   │   ├── verity_client.py      # HTTP client for Verity APIs
│   │   └── pipeline.py           # Pipeline orchestration
│   │
│   ├── db/  [pas, workflow, broker engines and models]
│   │
│   ├── tools/                    # Tool implementations (Python functions)
│   │   ├── pas_tools.py
│   │   ├── snow_tools.py
│   │   ├── minio_tools.py
│   │   ├── rating_tools.py
│   │   ├── enrichment_tools.py
│   │   └── pdf_tools.py
│   │
│   ├── mock_responses/           # Keyed mock responses per tool per scenario
│   │   └── {tool_name}.json
│   │
│   ├── routers/  [health, submissions, quotes, policies, renewals,
│   │              documents, rating, enrichment, snow, admin]
│   │
│   ├── services/  [snow_client, minio_client, rating_engine,
│   │               pdf_generator, fuzzy_match]
│   │
│   └── templates/admin/
│
└── seed_docs/                    # Sample PDFs for MinIO seeding
```

---

## 5. Infrastructure & Docker Compose

### 5.1 Docker Compose

Create file: `docker-compose.yml`

```yaml
version: '3.9'

services:

  postgres:
    image: pgvector/pgvector:pg16
    container_name: verity_postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: verityuser
      POSTGRES_PASSWORD: veritypass123
      POSTGRES_MULTIPLE_DATABASES: verity_db,pas_db,workflow_db,broker_db
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-multiple-dbs.sh:/docker-entrypoint-initdb.d/init-multiple-dbs.sh
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U verityuser"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:RELEASE.2024-11-07T00-52-20Z
    container_name: verity_minio
    restart: unless-stopped
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
    container_name: verity_minio_setup
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: >
      /bin/sh -c "
      mc alias set local http://minio:9000 minioadmin minioadmin123;
      mc mb --ignore-existing local/acord-forms;
      mc mb --ignore-existing local/loss-runs;
      mc mb --ignore-existing local/supplementals;
      mc mb --ignore-existing local/quote-letters;
      mc mb --ignore-existing local/binders;
      mc mb --ignore-existing local/endorsements;
      mc mb --ignore-existing local/uw-guidelines;
      mc mb --ignore-existing local/referral-memos;
      mc mb --ignore-existing local/renewal-notices;
      mc mb --ignore-existing local/ground-truth-datasets;
      echo 'MinIO buckets created';
      "

  verity:
    build:
      context: ./verity
      dockerfile: Dockerfile
    container_name: verity_api
    restart: unless-stopped
    environment:
      VERITY_DB_URL: postgresql://verityuser:veritypass123@postgres:5432/verity_db
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ADMIN_API_KEY: verity-admin-key-2024
      APP_ENV: demo
    volumes:
      - ./verity:/app
    ports:
      - "8001:8001"
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 15s
      timeout: 5s
      retries: 5

  uw:
    build:
      context: ./uw
      dockerfile: Dockerfile
    container_name: verity_uw
    restart: unless-stopped
    environment:
      PAS_DB_URL: postgresql://verityuser:veritypass123@postgres:5432/pas_db
      WORKFLOW_DB_URL: postgresql://verityuser:veritypass123@postgres:5432/workflow_db
      BROKER_DB_URL: postgresql://verityuser:veritypass123@postgres:5432/broker_db
      VERITY_API_URL: http://verity:8001
      MINIO_ENDPOINT: minio:9000
      MINIO_ACCESS_KEY: minioadmin
      MINIO_SECRET_KEY: minioadmin123
      MINIO_SECURE: "false"
      SNOW_INSTANCE: ${SNOW_INSTANCE}
      SNOW_USERNAME: ${SNOW_USERNAME}
      SNOW_PASSWORD: ${SNOW_PASSWORD}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      ADMIN_API_KEY: uw-admin-key-2024
      APP_ENV: demo
    volumes:
      - ./uw:/app
      - ./seed_docs:/app/seed_docs
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy
      verity:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 15s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
  minio_data:
```

**Note:** Use `pgvector/pgvector:pg16` image (not plain `postgres:16`) — this includes pgvector pre-installed.

### 5.2 Environment File

Create file: `.env`

```env
SNOW_INSTANCE=https://your-instance.service-now.com
SNOW_USERNAME=admin
SNOW_PASSWORD=your-snow-password
ANTHROPIC_API_KEY=your-anthropic-api-key
APP_ENV=demo
```

### 5.3 Init Script

Create file: `scripts/init-multiple-dbs.sh`

```bash
#!/bin/bash
set -e
for db in verity_db pas_db workflow_db broker_db; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE $db;
    GRANT ALL PRIVILEGES ON DATABASE $db TO $POSTGRES_USER;
EOSQL
done
```

---

## 6. Verity — Database Schema (verity_db)

Create file: `verity/db/schema.sql`

```sql
-- ============================================================
-- VERITY_DB: AI Trust & Compliance Metamodel
-- PremiumIQ Verity v3.0
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";  -- pgvector for description embeddings

-- ── ENUMERATIONS ─────────────────────────────────────────────

CREATE TYPE lifecycle_state AS ENUM (
    'draft',        -- being developed; local only
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
    'agent', 'task', 'prompt', 'pipeline', 'tool'
);

-- governance_tier: regulatory weight of a prompt version
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

-- ── INFERENCE CONFIGURATION ──────────────────────────────────
-- Named, reusable LLM API parameter sets. Versioned and governed.

CREATE TABLE inference_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    -- naming convention: {use_case}_{approach}
    -- e.g. 'extraction_deterministic', 'triage_balanced', 'generation_narrative'
    description     TEXT NOT NULL,
    intended_use    TEXT NOT NULL,   -- plain language: when to use this config

    -- LLM API parameters
    model_name      VARCHAR(100) NOT NULL DEFAULT 'claude-sonnet-4-20250514',
    temperature     NUMERIC(4,3),    -- NULL = model default; 0.0 for extraction/classification
    max_tokens      INTEGER,
    top_p           NUMERIC(4,3),
    top_k           INTEGER,
    stop_sequences  TEXT[],

    -- Extended parameters as JSONB for forward compatibility.
    -- Use for: extended thinking, prompt caching, batch config,
    -- model-specific features, future API additions.
    -- Example: {"thinking": {"type": "enabled", "budget_tokens": 8000}}
    -- Example: {"cache_control": {"type": "ephemeral"}}
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

    -- Description must be precise and unambiguous.
    -- Similarity check against all other agents and tasks runs at registration.
    description                 TEXT NOT NULL,
    description_embedding       vector(1536),
    description_embedding_model VARCHAR(100),
    last_similarity_check_at    TIMESTAMP,
    similarity_flags            JSONB DEFAULT '[]',
    -- [{similar_entity_type, similar_entity_id, similar_entity_name,
    --   similarity_score, flagged_at, resolved_at, resolution_notes}]

    purpose                     TEXT NOT NULL,
    domain                      VARCHAR(100) DEFAULT 'underwriting',
    materiality_tier            materiality_tier NOT NULL,

    -- Ownership
    owner_name                  VARCHAR(200) NOT NULL,
    owner_email                 VARCHAR(200),

    -- Regulatory documentation
    business_context            TEXT,   -- plain language for regulators
    known_limitations           TEXT,   -- ASOP 56 §3.8 required disclosure
    regulatory_notes            TEXT,

    -- Pointer to current champion version (set after first promotion)
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

    -- Lifecycle
    lifecycle_state             lifecycle_state NOT NULL DEFAULT 'draft',
    channel                     deployment_channel NOT NULL DEFAULT 'development',

    -- Configuration — all sourced from Verity at runtime, never hardcoded
    inference_config_id         UUID NOT NULL REFERENCES inference_config(id),
    output_schema               JSONB,
    authority_thresholds        JSONB DEFAULT '{}',
    -- {requires_hitl_above_premium: 500000, low_confidence_threshold: 0.70, ...}
    mock_mode_enabled           BOOLEAN DEFAULT FALSE,
    shadow_traffic_pct          NUMERIC(5,4) DEFAULT 0,
    challenger_traffic_pct      NUMERIC(5,4) DEFAULT 0,

    -- Prompts are assigned via entity_prompt_assignment junction (see below)
    -- Tools are assigned via agent_version_tool junction (see below)

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
    -- 'major_redesign' | 'new_capability' | 'prompt_tuning' |
    -- 'config_change' | 'tool_change' | 'bug_fix'

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
-- Use for classification, extraction, generation, matching, validation.
-- Does not autonomously choose its execution path.

CREATE TABLE task (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                        VARCHAR(100) UNIQUE NOT NULL,
    display_name                VARCHAR(200) NOT NULL,

    -- Description must be precise and unambiguous.
    -- Similarity checked against all agents and other tasks at registration.
    description                 TEXT NOT NULL,
    description_embedding       vector(1536),
    description_embedding_model VARCHAR(100),
    last_similarity_check_at    TIMESTAMP,
    similarity_flags            JSONB DEFAULT '[]',

    capability_type             capability_type NOT NULL,
    -- What kind of AI operation this task performs

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
    -- Tasks benefit from deterministic configs (temperature=0) for extraction/classification

    output_schema               JSONB,
    mock_mode_enabled           BOOLEAN DEFAULT FALSE,
    shadow_traffic_pct          NUMERIC(5,4) DEFAULT 0,
    challenger_traffic_pct      NUMERIC(5,4) DEFAULT 0,

    -- Prompts via entity_prompt_assignment
    -- Tools via task_version_tool (tasks may need tools, e.g. retrieval)

    staging_tests_passed        BOOLEAN,
    ground_truth_passed         BOOLEAN,
    fairness_passed             BOOLEAN,

    developer_name              VARCHAR(200),
    change_summary              TEXT,
    change_type                 VARCHAR(20),

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
-- Prompts are assigned to agent_versions and task_versions via junction.

CREATE TABLE prompt (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(200) UNIQUE NOT NULL,
    description     TEXT NOT NULL,
    -- Which entity this prompt was originally designed for (informational only)
    -- A prompt may be reused across multiple agents/tasks
    primary_entity_type  entity_type,
    primary_entity_id    UUID,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE prompt_version (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    prompt_id           UUID NOT NULL REFERENCES prompt(id),
    version_number      INTEGER NOT NULL,

    -- The actual prompt text
    content             TEXT NOT NULL,

    -- How this prompt is submitted to the Claude API
    api_role            api_role NOT NULL DEFAULT 'system',

    -- Governance weight determines lifecycle and approval requirements
    governance_tier     governance_tier NOT NULL DEFAULT 'behavioural',

    -- Description embedding for similarity checking
    -- (check at registration: does this prompt overlap with others assigned
    --  to the same agent/task in ways that could cause confusion?)
    content_embedding   vector(1536),
    content_embedding_model VARCHAR(100),

    -- Lifecycle
    lifecycle_state     lifecycle_state NOT NULL DEFAULT 'draft',

    -- Change tracking
    change_summary      TEXT NOT NULL,
    -- What changed from prior version and why — required field
    sensitivity_level   VARCHAR(20) DEFAULT 'high',
    -- 'high': changes agent behaviour significantly
    -- 'medium': changes output format or context structure
    -- 'low': minor wording, no behavioural impact
    author_name         VARCHAR(200),

    -- Approval (required for governance_tier = 'behavioural')
    approved_by         VARCHAR(200),
    approved_at         TIMESTAMP,
    test_required       BOOLEAN GENERATED ALWAYS AS
                        (governance_tier = 'behavioural') STORED,

    staging_tests_passed BOOLEAN,
    created_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_prompt_version UNIQUE (prompt_id, version_number)
);

CREATE INDEX idx_pv_prompt ON prompt_version(prompt_id);
CREATE INDEX idx_pv_state ON prompt_version(lifecycle_state);
CREATE INDEX idx_pv_tier ON prompt_version(governance_tier);

-- ── ENTITY-PROMPT ASSIGNMENT ──────────────────────────────────
-- Many-to-many junction: which prompt versions are active
-- for a given agent_version or task_version.

CREATE TABLE entity_prompt_assignment (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type         entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id   UUID NOT NULL,
    -- References agent_version.id or task_version.id depending on entity_type

    prompt_version_id   UUID NOT NULL REFERENCES prompt_version(id),

    api_role            api_role NOT NULL,
    -- How this prompt is submitted to the Claude API for this entity

    governance_tier     governance_tier NOT NULL,
    -- Must match the prompt_version.governance_tier

    execution_order     INTEGER NOT NULL DEFAULT 1,
    -- For multiple user messages assembled in sequence

    is_required         BOOLEAN NOT NULL DEFAULT TRUE,
    -- FALSE = conditionally included based on condition_logic

    condition_logic     JSONB,
    -- Null = always include
    -- e.g. {"if_lob": "DO", "include": true}
    -- e.g. {"if_confidence_below": 0.7, "include": true}

    created_at          TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_entity_prompt UNIQUE (entity_type, entity_version_id, prompt_version_id, api_role)
);

CREATE INDEX idx_epa_entity ON entity_prompt_assignment(entity_type, entity_version_id);

-- ── TOOLS ────────────────────────────────────────────────────
-- Callable Python functions. Registered with descriptions that
-- are embedded and checked for ambiguity at registration.

CREATE TABLE tool (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                        VARCHAR(100) UNIQUE NOT NULL,
    display_name                VARCHAR(200) NOT NULL,

    -- Description is what Claude reads to decide whether to call this tool.
    -- Must be unambiguous and clearly distinct from all other tool descriptions.
    description                 TEXT NOT NULL,
    description_embedding       vector(1536),
    description_embedding_model VARCHAR(100),
    last_similarity_check_at    TIMESTAMP,
    similarity_flags            JSONB DEFAULT '[]',

    input_schema                JSONB NOT NULL,
    output_schema               JSONB NOT NULL,

    -- Python implementation
    implementation_path         VARCHAR(500) NOT NULL,
    -- e.g. 'uw.tools.pas_tools.get_submission_from_pas'

    -- Mock mode configuration
    mock_mode_enabled           BOOLEAN DEFAULT TRUE,
    mock_response_key           VARCHAR(200),
    -- Key into uw/mock_responses/{tool_name}.json

    -- Data governance
    mcp_server_id               UUID,   -- FK to mcp_server if external
    data_classification_max     data_classification DEFAULT 'tier3_confidential',

    -- Operational flags
    is_write_operation          BOOLEAN DEFAULT FALSE,
    -- Write operations suppressed in mock mode and non-champion channels
    requires_confirmation       BOOLEAN DEFAULT FALSE,
    -- If true, execution engine must confirm before calling in production

    tags                        TEXT[] DEFAULT '{}',
    active                      BOOLEAN DEFAULT TRUE,
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tool_name ON tool(name);

-- ── AGENT VERSION ↔ TOOL JUNCTION ────────────────────────────
-- Explicit authorisation: which tools an agent version may call.
-- Enforced by execution engine before any tool invocation.

CREATE TABLE agent_version_tool (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_version_id    UUID NOT NULL REFERENCES agent_version(id),
    tool_id             UUID NOT NULL REFERENCES tool(id),
    authorized          BOOLEAN NOT NULL DEFAULT TRUE,
    -- FALSE = tool is registered but this version is explicitly blocked from it
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_avt UNIQUE (agent_version_id, tool_id)
);

CREATE INDEX idx_avt_agent ON agent_version_tool(agent_version_id);

-- ── TASK VERSION ↔ TOOL JUNCTION ─────────────────────────────
-- Tasks may also need tool access (e.g. retrieval for guidelines check)

CREATE TABLE task_version_tool (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_version_id     UUID NOT NULL REFERENCES task_version(id),
    tool_id             UUID NOT NULL REFERENCES tool(id),
    authorized          BOOLEAN NOT NULL DEFAULT TRUE,
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tvt UNIQUE (task_version_id, tool_id)
);

-- ── PIPELINES ────────────────────────────────────────────────
-- Ordered, versioned sequences of agents and tasks.

CREATE TABLE pipeline (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,
    current_champion_version_id UUID,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE pipeline_version (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pipeline_id     UUID NOT NULL REFERENCES pipeline(id),
    version_number  INTEGER NOT NULL,
    lifecycle_state lifecycle_state NOT NULL DEFAULT 'draft',

    -- Steps define the ordered sequence of agents and tasks
    steps           JSONB NOT NULL,
    -- [
    --   {
    --     "step_order": 1,
    --     "step_name": "validate_documents",
    --     "entity_type": "task",
    --     "entity_name": "document_validator",
    --     "entity_version_id": "uuid-or-null-to-use-champion",
    --     "depends_on": [],
    --     "parallel_group": null,
    --     "error_policy": "fail_pipeline",
    --     "output_key": "validation_result"
    --   },
    --   {
    --     "step_order": 2,
    --     "step_name": "classify_documents",
    --     "entity_type": "task",
    --     "entity_name": "document_classifier",
    --     "depends_on": ["validate_documents"],
    --     "parallel_group": null,
    --     "error_policy": "skip",
    --     "output_key": "classification_result"
    --   },
    --   {
    --     "step_order": 3,
    --     "step_name": "enrich_account",
    --     "entity_type": "task",
    --     "depends_on": ["classify_documents"],
    --     "parallel_group": "enrichment_group",
    --     "error_policy": "continue_with_flag"
    --   },
    --   {
    --     "step_order": 4,
    --     "step_name": "triage_submission",
    --     "entity_type": "agent",
    --     "entity_name": "triage_agent",
    --     "depends_on": ["enrich_account", "clearance_check"],
    --     "parallel_group": null,
    --     "error_policy": "fail_pipeline"
    --   }
    -- ]

    change_summary  TEXT,
    developer_name  VARCHAR(200),
    valid_from      TIMESTAMP,
    valid_to        TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),

    CONSTRAINT uq_pipeline_version UNIQUE (pipeline_id, version_number)
);

-- ── MCP SERVERS ──────────────────────────────────────────────

CREATE TABLE mcp_server (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                        VARCHAR(100) UNIQUE NOT NULL,
    display_name                VARCHAR(200) NOT NULL,
    server_url                  VARCHAR(500) NOT NULL,
    trust_level                 trust_level NOT NULL DEFAULT 'sandboxed',
    allowed_tool_names          TEXT[] DEFAULT '{}',
    data_classification_max     data_classification DEFAULT 'tier2_internal',
    vendor_name                 VARCHAR(200),
    vendor_risk_assessed_at     DATE,
    vendor_risk_assessment_notes TEXT,
    data_processing_agreement   BOOLEAN DEFAULT FALSE,
    soc2_type2_verified         BOOLEAN DEFAULT FALSE,
    audit_all_calls             BOOLEAN DEFAULT TRUE,
    active                      BOOLEAN DEFAULT TRUE,
    created_at                  TIMESTAMP DEFAULT NOW(),
    updated_at                  TIMESTAMP DEFAULT NOW()
);

-- ── TEST SUITES & CASES ───────────────────────────────────────
-- Tests target any entity type: agent, task, prompt, pipeline, or tool.
-- Metric type must match the entity's capability.

CREATE TABLE test_suite (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    entity_type         entity_type NOT NULL,
    -- 'agent' | 'task' | 'prompt' | 'pipeline' | 'tool'
    entity_id           UUID NOT NULL,
    -- References agent.id, task.id, prompt.id, pipeline.id, or tool.id
    suite_type          VARCHAR(50) NOT NULL,
    -- 'unit'        — tests a single entity in isolation with mock dependencies
    -- 'integration' — tests an entity with real dependencies
    -- 'regression'  — tests that prior-working behaviour still works
    -- 'adversarial' — edge cases, missing data, conflicting inputs
    -- 'ground_truth'— runs entity against SME-labeled dataset
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
    -- Must be consistent with the entity's capability_type:
    -- classification tasks → 'classification_f1'
    -- extraction tasks     → 'field_accuracy'
    -- generation tasks     → 'semantic_similarity' or 'human_rubric'
    -- agents               → 'classification_f1' (for routing/scoring decisions)
    --                        or 'human_rubric' (for narrative quality)
    -- prompts              → 'semantic_similarity' or 'human_rubric'
    -- tools                → 'exact_match' or 'schema_valid'

    metric_config       JSONB,
    -- For 'field_accuracy':       {"required_fields": ["named_insured", "revenue"], "tolerance": 0.95}
    -- For 'classification_f1':    {"classes": ["acord_855", "acord_125", "loss_runs"]}
    -- For 'semantic_similarity':  {"threshold": 0.85, "embedding_model": "text-embedding-3-small"}
    -- For 'exact_match':          {"strict": true}

    -- Version targeting
    applies_to_versions UUID[] DEFAULT '{}',   -- empty = all versions
    excludes_versions   UUID[] DEFAULT '{}',

    is_adversarial      BOOLEAN DEFAULT FALSE,
    tags                TEXT[] DEFAULT '{}',
    active              BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_tc_suite ON test_case(suite_id);

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
    -- {"passed": true, "precision": 0.94, "recall": 0.92, "f1": 0.93}
    -- {"passed": true, "field_accuracy": {"named_insured": 1.0, "revenue": 0.95}}
    passed              BOOLEAN NOT NULL,
    failure_reason      TEXT,
    duration_ms         INTEGER,
    inference_config_snapshot JSONB
    -- snapshot of inference_config used — for forensic analysis of failures
);

CREATE INDEX idx_tel_entity ON test_execution_log(entity_type, entity_version_id);
CREATE INDEX idx_tel_suite ON test_execution_log(suite_id);

-- ── GROUND TRUTH DATASETS ─────────────────────────────────────
-- SME-labeled evaluation data. Targets agents or tasks.
-- Tasks (especially classifiers and extractors) need their own datasets.

CREATE TABLE ground_truth_dataset (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_id               UUID NOT NULL,
    name                    VARCHAR(200) NOT NULL,
    version                 INTEGER NOT NULL DEFAULT 1,
    description             TEXT,
    lob                     VARCHAR(20),
    record_count            INTEGER NOT NULL,

    -- Location in MinIO
    minio_bucket            VARCHAR(100) DEFAULT 'ground-truth-datasets',
    minio_key               VARCHAR(500),
    -- e.g. 'document_classifier/v1/dataset.json'

    -- Labeling provenance
    labeled_by_sme          VARCHAR(200) NOT NULL,
    reviewed_by             VARCHAR(200),
    -- Second reviewer required for High-materiality entities

    -- Dataset evolution tracking
    superseded_by_version   INTEGER,
    -- If a newer version corrects this one
    records_corrected_since INTEGER DEFAULT 0,
    -- Number of records found incorrect after labeling

    -- Version applicability
    applies_to_versions     UUID[] DEFAULT '{}',
    -- Empty = applies to all versions of this entity

    created_at              TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_gt_dataset UNIQUE (entity_id, entity_type, version)
);

CREATE INDEX idx_gtd_entity ON ground_truth_dataset(entity_type, entity_id);

-- ── VALIDATION RUNS ───────────────────────────────────────────
-- Formal pre-promotion validation. One per entity version per promotion attempt.
-- Distinct from evaluation_run (ongoing production monitoring).

CREATE TABLE validation_run (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id       UUID NOT NULL,
    dataset_id              UUID NOT NULL REFERENCES ground_truth_dataset(id),
    run_at                  TIMESTAMP DEFAULT NOW(),
    run_by                  VARCHAR(200) NOT NULL,

    -- Classification metrics (for capability_type = 'classification'
    -- and for agents producing categorical outputs like risk_score, routing)
    precision_score         NUMERIC(7,6),
    recall_score            NUMERIC(7,6),
    f1_score                NUMERIC(7,6),
    cohens_kappa            NUMERIC(7,6),
    confusion_matrix        JSONB,

    -- Extraction metrics (for capability_type = 'extraction')
    field_accuracy          JSONB,
    -- {"named_insured": 0.98, "revenue": 0.94, "effective_date": 0.99}
    overall_extraction_rate NUMERIC(7,6),
    low_confidence_rate     NUMERIC(7,6),

    -- Fairness metrics (for decision-influencing entities)
    fairness_metrics        JSONB,
    -- {"sic_parity": 0.02, "geo_parity": 0.01, "revenue_band_parity": 0.03}
    fairness_passed         BOOLEAN,
    fairness_notes          TEXT,

    -- Threshold evaluation
    thresholds_met          BOOLEAN,
    threshold_details       JSONB,
    -- {"precision": {"required": 0.85, "achieved": 0.94, "passed": true}, ...}

    -- SME disagreement review
    sme_review_notes        TEXT,
    sme_reviewed_by         VARCHAR(200),
    sme_reviewed_at         TIMESTAMP,

    -- Inference config used
    inference_config_snapshot JSONB,

    passed                  BOOLEAN,
    notes                   TEXT
);

CREATE INDEX idx_vr_entity ON validation_run(entity_type, entity_version_id);

-- ── EVALUATION RUNS ───────────────────────────────────────────
-- Ongoing production evaluation: shadow comparison, challenger monitoring.
-- Many runs per time period. Distinct from one-time validation_run.

CREATE TABLE evaluation_run (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL,
    entity_version_id       UUID NOT NULL,
    evaluation_type         VARCHAR(50) NOT NULL,
    -- 'shadow_comparison'   — shadow vs champion agreement analysis
    -- 'challenger_ab'       — challenger vs champion on live traffic
    -- 'production_monitor'  — ongoing champion performance tracking
    run_period_start        TIMESTAMP NOT NULL,
    run_period_end          TIMESTAMP NOT NULL,

    -- Champion reference
    champion_version_id     UUID,

    -- Volume
    total_invocations       INTEGER NOT NULL DEFAULT 0,
    successful_invocations  INTEGER DEFAULT 0,
    failed_invocations      INTEGER DEFAULT 0,

    -- Agreement (for shadow/challenger)
    agreement_rate          NUMERIC(7,6),
    -- % of cases where shadow/challenger matched champion output
    disagreement_examples   JSONB,
    -- Sample of cases where outputs differed (for human review)

    -- Performance
    avg_duration_ms         NUMERIC(10,2),
    avg_input_tokens        NUMERIC(10,2),
    avg_output_tokens       NUMERIC(10,2),

    -- Override rate (for production champion monitoring)
    override_count          INTEGER DEFAULT 0,
    override_rate           NUMERIC(7,6),
    override_pattern_flags  JSONB,
    -- Auto-detected patterns: [{"pattern": "healthcare_sic_codes", "rate": 0.45}]

    -- Drift detection
    metric_drift_detected   BOOLEAN DEFAULT FALSE,
    drift_details           JSONB,

    promotion_recommendation VARCHAR(50),
    -- 'promote' | 'continue_evaluation' | 'reject' | 'investigate'

    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_er_entity ON evaluation_run(entity_type, entity_version_id);

-- ── APPROVAL RECORDS (HITL GATES) ────────────────────────────

CREATE TABLE approval_record (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL,
    entity_version_id       UUID NOT NULL,
    gate_type               VARCHAR(50) NOT NULL,
    -- 'shadow_promotion', 'challenger_promotion', 'champion_promotion',
    -- 'high_value_decision', 'incident_response', 'rollback',
    -- 'prompt_promotion' (for behavioural prompts)
    from_state              lifecycle_state,
    to_state                lifecycle_state,

    approver_name           VARCHAR(200) NOT NULL,
    approver_role           VARCHAR(100),
    approved_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    rationale               TEXT NOT NULL,

    -- Evidence reviewed checkboxes
    staging_results_reviewed        BOOLEAN DEFAULT FALSE,
    ground_truth_reviewed           BOOLEAN DEFAULT FALSE,
    fairness_analysis_reviewed      BOOLEAN DEFAULT FALSE,
    shadow_metrics_reviewed         BOOLEAN DEFAULT FALSE,
    challenger_metrics_reviewed     BOOLEAN DEFAULT FALSE,
    model_card_reviewed             BOOLEAN DEFAULT FALSE,
    similarity_flags_reviewed       BOOLEAN DEFAULT FALSE,

    -- For decision-level HITL
    submission_id           UUID,
    decision_override       BOOLEAN DEFAULT FALSE,
    override_reason         TEXT
);

CREATE INDEX idx_ar_entity ON approval_record(entity_type, entity_version_id);
CREATE INDEX idx_ar_gate ON approval_record(gate_type);

-- ── AGENT DECISION LOG ───────────────────────────────────────
-- Every Claude invocation — agent or task — is logged here.
-- This is the audit trail that answers regulatory questions.

CREATE TABLE agent_decision_log (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Entity that ran
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id       UUID NOT NULL,
    -- References agent_version.id or task_version.id

    -- Prompt versions active at time of execution
    prompt_version_ids      UUID[] DEFAULT '{}',
    -- Snapshot of which prompt versions were assembled for this invocation

    -- Inference config snapshot — stored here, not just by reference.
    -- This ensures we can reconstruct the exact parameters even if config changes.
    inference_config_snapshot JSONB NOT NULL,
    -- {"model_name": "claude-sonnet-4-20250514", "temperature": 0.0,
    --  "max_tokens": 2048, "extended_params": {}}

    -- Business context
    submission_id           UUID,
    policy_id               UUID,
    renewal_id              UUID,
    business_entity         VARCHAR(100),

    -- Execution context
    channel                 deployment_channel NOT NULL,
    mock_mode               BOOLEAN DEFAULT FALSE,
    pipeline_run_id         UUID,   -- groups decisions from same pipeline run

    -- Inputs and outputs
    input_summary           TEXT,
    input_json              JSONB,
    output_json             JSONB,
    output_summary          TEXT,

    -- Explainability (populated for decision-influencing entities)
    reasoning_text          TEXT,
    -- Plain-language reasoning — used for adverse action notices
    risk_factors            JSONB,
    -- Structured risk flags for regulatory reporting
    confidence_score        NUMERIC(5,4),
    low_confidence_flag     BOOLEAN DEFAULT FALSE,
    -- Auto-set when confidence_score < agent authority_threshold.low_confidence_threshold

    -- LLM execution metadata
    model_used              VARCHAR(100),
    input_tokens            INTEGER,
    output_tokens           INTEGER,
    duration_ms             INTEGER,
    tool_calls_made         JSONB,
    -- [{tool_name, tool_id, call_order, input_summary, output_summary, duration_ms}]

    -- HITL tracking
    hitl_required           BOOLEAN DEFAULT FALSE,
    hitl_completed          BOOLEAN DEFAULT FALSE,
    hitl_approval_id        UUID REFERENCES approval_record(id),

    -- Status
    status                  VARCHAR(30) DEFAULT 'complete',
    -- 'complete' | 'failed' | 'overridden' | 'pending_hitl' | 'low_confidence_escalated'
    error_message           TEXT,

    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_adl_entity ON agent_decision_log(entity_type, entity_version_id);
CREATE INDEX idx_adl_submission ON agent_decision_log(submission_id);
CREATE INDEX idx_adl_created ON agent_decision_log(created_at);
CREATE INDEX idx_adl_pipeline ON agent_decision_log(pipeline_run_id);

-- ── OVERRIDE LOG ─────────────────────────────────────────────

CREATE TABLE override_log (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    decision_log_id         UUID NOT NULL REFERENCES agent_decision_log(id),
    entity_type             entity_type NOT NULL,
    entity_version_id       UUID NOT NULL,

    overrider_name          VARCHAR(200) NOT NULL,
    overrider_role          VARCHAR(100),
    override_reason_code    VARCHAR(50) NOT NULL,
    -- 'risk_assessment_disagree' | 'missing_context' | 'client_relationship'
    -- 'market_conditions' | 'appetite_exception' | 'data_quality' | 'other'
    override_notes          TEXT,
    ai_recommendation       JSONB,
    human_decision          JSONB,
    submission_id           UUID,
    created_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ol_entity ON override_log(entity_type, entity_version_id);
CREATE INDEX idx_ol_created ON override_log(created_at);

-- ── MODEL CARDS ───────────────────────────────────────────────
-- Formal documentation per entity version. Required for SR 11-7
-- conceptual soundness and ASOP 56 §3.4 documentation requirements.

CREATE TABLE model_card (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL CHECK (entity_type IN ('agent', 'task')),
    entity_version_id       UUID NOT NULL,
    card_version            INTEGER NOT NULL DEFAULT 1,

    -- ASOP 56 §3.4 required fields
    purpose                 TEXT NOT NULL,
    design_rationale        TEXT NOT NULL,
    -- Why this approach vs alternatives; LLM selection rationale
    inputs_description      TEXT NOT NULL,
    outputs_description     TEXT NOT NULL,
    known_limitations       TEXT NOT NULL,
    -- ASOP 56 §3.8: must be disclosed to management at time of use
    conditions_of_use       TEXT NOT NULL,

    -- SR 11-7 §II.A: conceptual soundness
    -- For LLM-based entities: document sensitivity to prompt phrasing,
    -- out-of-distribution input behaviour, hallucination risk
    lm_specific_limitations TEXT,
    prompt_sensitivity_notes TEXT,

    -- Validation reference
    validated_by            VARCHAR(200),
    -- Must be independent of developer for High-materiality entities
    validation_run_id       UUID REFERENCES validation_run(id),
    validation_notes        TEXT,

    -- Regulatory
    regulatory_notes        TEXT,
    materiality_classification TEXT,
    -- Written justification for the materiality_tier assigned

    -- Approval
    approved_by             VARCHAR(200),
    approved_at             TIMESTAMP,
    lifecycle_state         VARCHAR(30) DEFAULT 'draft',
    -- 'draft' | 'approved' | 'superseded'

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
    minimum_acceptable  NUMERIC(7,6) NOT NULL,
    target_champion     NUMERIC(7,6) NOT NULL,
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_threshold UNIQUE (entity_id, entity_type, materiality_tier, metric_name)
);

-- ── MCP CALL LOG ─────────────────────────────────────────────

CREATE TABLE mcp_call_log (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    mcp_server_id       UUID NOT NULL REFERENCES mcp_server(id),
    tool_name           VARCHAR(100) NOT NULL,
    entity_type         entity_type,
    entity_version_id   UUID,
    decision_log_id     UUID REFERENCES agent_decision_log(id),
    input_data          JSONB,
    output_data         JSONB,
    data_classification data_classification,
    blocked             BOOLEAN DEFAULT FALSE,
    block_reason        TEXT,
    duration_ms         INTEGER,
    called_at           TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_mcl_server ON mcp_call_log(mcp_server_id);

-- ── INCIDENTS ────────────────────────────────────────────────

CREATE TABLE incident (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type             entity_type NOT NULL,
    entity_id               UUID NOT NULL,
    entity_version_id       UUID,
    title                   VARCHAR(300) NOT NULL,
    description             TEXT NOT NULL,
    severity                VARCHAR(20) NOT NULL,
    -- 'critical' | 'high' | 'medium' | 'low'
    detection_source        VARCHAR(100),
    detected_at             TIMESTAMP NOT NULL DEFAULT NOW(),
    affected_submission_ids UUID[] DEFAULT '{}',
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
-- Records results of embedding-based ambiguity checks.
-- Run at registration of any agent, task, or tool.

CREATE TABLE description_similarity_log (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    checked_entity_type     entity_type NOT NULL,
    checked_entity_id       UUID NOT NULL,
    checked_entity_name     VARCHAR(200) NOT NULL,
    similar_entity_type     entity_type NOT NULL,
    similar_entity_id       UUID NOT NULL,
    similar_entity_name     VARCHAR(200) NOT NULL,
    similarity_score        NUMERIC(7,6) NOT NULL,
    -- cosine similarity; > 0.85 triggers a flag
    flagged                 BOOLEAN GENERATED ALWAYS AS (similarity_score > 0.85) STORED,
    reviewed_at             TIMESTAMP,
    reviewed_by             VARCHAR(200),
    resolution              VARCHAR(50),
    -- 'accepted_as_distinct' | 'description_updated' | 'entity_merged'
    resolution_notes        TEXT,
    checked_at              TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_dsl_entity ON description_similarity_log(checked_entity_type, checked_entity_id);
```

---

## 7. UW Platform — Database Schemas

### 7.1 pas_db — Policy Admin System

*(Schema unchanged from v2.0 — see full DDL in `uw/db/schema_pas.sql`)*

Key tables: `account`, `submission`, `submission_do_detail`, `submission_gl_detail`, `loss_history`, `quote`, `policy`, `renewal`, `endorsement`.

The `quote` table adds one field vs. v2.0:

```sql
verity_decision_log_id UUID,   -- FK to verity_db.agent_decision_log
-- Links the quote back to the exact quote_assistant agent invocation
```

### 7.2 workflow_db — Integration Metadata Layer

*(Schema unchanged from v2.0)*

Key tables: `snow_sync_log`, `submission_event`, `sla_record`, `rating_log`, `document_metadata`, `renewal_queue`.

### 7.3 broker_db — Broker Registry

*(Schema unchanged from v2.0)*

Key tables: `agency`, `broker`, `broker_submission_log`.

---

## 8. MinIO Document Store

*(Unchanged from v2.0)*

Buckets: `acord-forms`, `loss-runs`, `supplementals`, `quote-letters`, `binders`, `endorsements`, `uw-guidelines`, `referral-memos`, `renewal-notices`, `ground-truth-datasets`.

Ground truth datasets stored as JSON in `ground-truth-datasets/{entity_name}/v{version}/dataset.json`.

---

## 9. Verity — Core API Layer

### 9.1 Registry Endpoints (Runtime — called by execution engine)

```
GET  /v1/agents/{name}/champion
     → Returns full champion config:
       {agent_version_id, version_label, inference_config,
        prompts: [{prompt_version_id, content, api_role, governance_tier,
                   execution_order, is_required, condition_logic}],
        tools: [{tool_id, name, description, input_schema, mock_mode_enabled,
                 data_classification_max, is_write_operation}],
        authority_thresholds, output_schema, materiality_tier}

GET  /v1/tasks/{name}/champion
     → Same structure as agent, includes capability_type

GET  /v1/pipelines/{name}/champion
     → Returns pipeline_version steps with resolved entity names and versions

GET  /v1/agents/{name}/versions
GET  /v1/tasks/{name}/versions
```

### 9.2 Decision Logging (Runtime — called after every invocation)

```
POST /v1/decisions/log
     Body: {entity_type, entity_version_id, prompt_version_ids,
            inference_config_snapshot, submission_id,
            channel, mock_mode, pipeline_run_id,
            input_json, output_json, reasoning_text, risk_factors,
            confidence_score, model_used, input_tokens, output_tokens,
            duration_ms, tool_calls_made, hitl_required}
     → Creates agent_decision_log record
     → Auto-sets low_confidence_flag if confidence below threshold
     → Returns: {decision_log_id}

POST /v1/decisions/{decision_log_id}/override
POST /v1/decisions/{submission_id}/audit-trail
     → Full decision history: every agent + task that ran,
       exact prompt versions, inference config, inputs, outputs,
       HITL records, overrides — suitable for regulatory examination
```

### 9.3 Lifecycle Management

```
POST /v1/lifecycle/{entity_type}/{entity_version_id}/promote
     Body: {target_state, approver_name, approver_role, rationale,
            evidence_reviewed: {staging, ground_truth, fairness,
                                shadow_metrics, challenger_metrics,
                                model_card, similarity_flags}}
     → Validates promotion criteria per materiality tier
     → Creates approval_record
     → Updates lifecycle_state
     → If promoting to champion: sets valid_from, deprecates prior champion

POST /v1/lifecycle/{entity_type}/{entity_version_id}/rollback
     Body: {approver_name, rationale, incident_id}
     → Restores prior champion immediately
     → Creates approval_record with gate_type='rollback'
```

### 9.4 Testing

```
POST /v1/testing/run-suite
     Body: {entity_type, entity_version_id, suite_id, mock_mode}
     → Executes test cases appropriate for entity type
     → Computes metric per test_case.metric_type
     → Logs to test_execution_log with inference_config_snapshot
     → Returns: {passed, failed, results[]}

POST /v1/testing/run-ground-truth
     Body: {entity_type, entity_version_id, dataset_id}
     → Runs entity against ground truth dataset
     → Computes metrics appropriate for entity's capability_type:
       classification → precision, recall, F1, kappa, confusion matrix
       extraction     → per-field accuracy, overall extraction rate
       agent          → outcome accuracy, kappa, fairness metrics
     → Creates validation_run record
     → Returns: {passed, metrics, threshold_details}

POST /v1/testing/check-descriptions
     Body: {entity_type, entity_id}
     → Computes embedding for entity description
     → Runs cosine similarity against ALL agents, tasks, and tools
     → Flags any pair with similarity > 0.85
     → Logs to description_similarity_log
     → Returns: {flags[], safe: bool}

POST /v1/testing/validate-prompt-assignment
     Body: {entity_type, entity_version_id}
     → Validates that prompt governance tiers are consistent:
       entity_version must have exactly one 'system'/'behavioural' prompt
       user-role prompts must be 'contextual' or 'formatting'
     → Returns: {valid, issues[]}
```

### 9.5 Reporting

```
GET  /v1/reports/model-inventory
     → All champion agents and tasks with: version, materiality_tier,
       validation status, last review date, override rate 30d,
       active_incidents, model_card status

GET  /v1/reports/audit-trail/{submission_id}
GET  /v1/reports/override-analysis?entity_type=&entity_id=&days=90
GET  /v1/reports/fairness/{entity_type}/{entity_version_id}
GET  /v1/reports/mcp-usage?days=30
GET  /v1/reports/regulatory/{framework}
     → framework: 'sr117' | 'naic' | 'co_sb21169' | 'orsa_asop'
     → Returns compliance evidence package

POST /v1/documentation/generate/{entity_type}/{entity_id}
     → Auto-generates model card content from metamodel fields
     → Returns markdown text suitable for regulatory disclosure
```

---

## 10. Verity — Lifecycle Management

### 10.1 Promotion Criteria by Entity Type and Materiality

**For Agents (Tier 1 — High):**

| Gate | Criteria |
|---|---|
| Draft → Candidate | Developer marks complete; change_summary populated |
| Candidate → Staging | Description similarity check passes (no unresolved flags) |
| Staging → Shadow | All staging tests pass; behavioural prompt(s) approved; HITL Gate 1 |
| Shadow → Challenger | Shadow period ≥ 2 weeks + 50 submissions; metrics at parity; HITL Gate 2 |
| Challenger → Champion | Agreement rate ≥ 90%; all metric thresholds met; fairness passed; model card approved; HITL Gate 3 |

**For Agents (Tier 2 — Medium) and Tasks (Tier 1 — High):**

Same path but fairness analysis optional unless task influences decisions.

**For Tasks (Tier 2 — Medium and Tier 3 — Low):**

| Gate | Criteria |
|---|---|
| Staging → Shadow | Staging tests pass; HITL Gate 1 (lightweight) |
| Shadow → Champion | Shadow period complete; metrics acceptable; no human review required for Tier 3 |

**For Prompts (governance_tier = behavioural):**

Full lifecycle: draft → candidate → staging → approved (HITL required).

**For Prompts (governance_tier = contextual):**

Lightweight: draft → approved (schema validation, no HITL required).

**For Prompts (governance_tier = formatting):**

Minimal: draft → active (no approval required, version tracked only).

### 10.2 Metric Thresholds by Entity and Materiality

| Entity | Capability | Materiality | Precision Min | Recall Min | F1 Min | Kappa Min |
|---|---|---|---|---|---|---|
| Triage Agent | outcome (risk score) | High | 0.85 | 0.82 | 0.83 | 0.75 |
| Appetite Agent | outcome (appetite) | High | 0.88 | 0.85 | 0.86 | 0.78 |
| Quote Assistant | outcome (terms) | High | 0.87 | 0.84 | 0.85 | 0.77 |
| Renewal Agent | outcome (recommendation) | High | 0.85 | 0.82 | 0.83 | 0.75 |
| Document Classifier | classification | Medium | 0.93 | 0.91 | 0.92 | — |
| ACORD 855 Extractor | extraction | Medium | — | — | — | — |
| ACORD 125 Extractor | extraction | Medium | — | — | — | — |
| Loss Run Parser | extraction | Medium | — | — | — | — |
| MDM Matcher | matching | Medium | 0.90 | 0.88 | 0.89 | — |
| Enrichment Aggregator | generation | Low | — | — | — | — |
| Document Validator | validation | Low | — | — | — | — |

For extraction tasks, threshold is per-field accuracy: all required fields ≥ 0.90.

---

## 11. Verity — Testing Framework

### 11.1 Mock Mode Architecture

Every tool has `mock_mode_enabled`. When an entity (agent or task) runs with `mock_mode=True` in its version config:

1. Execution engine checks each tool's `mock_mode_enabled` flag before calling
2. If True: reads from `uw/mock_responses/{tool_name}.json` keyed by `test_scenario_id`
3. Write operations (`is_write_operation=True`) are suppressed entirely — no DB writes, no ServiceNow writes
4. All inputs and would-have-been outputs logged to `agent_decision_log` with `mock_mode=TRUE`
5. Returns pre-defined mock response

Mock response format:

```json
{
  "default": { "status": "success", "data": {...} },
  "scenario_high_risk": { "status": "success", "data": {...} },
  "scenario_missing_docs": { "status": "partial", "data": {...} },
  "scenario_adversarial": { "status": "success", "data": {...} }
}
```

### 11.2 Test Suite Matrix

Every registered entity must have test suites covering:

| Entity Type | Required Suites | Metric Type |
|---|---|---|
| Task: classifier | `unit` (mock), `adversarial`, `ground_truth` | `classification_f1` |
| Task: extractor | `unit` (mock), `adversarial`, `ground_truth` | `field_accuracy` |
| Task: generator | `unit` (mock), `human_rubric` review | `semantic_similarity` |
| Task: matcher | `unit` (mock), `ground_truth` | `classification_f1` |
| Task: validator | `unit` (mock), `regression` | `exact_match` |
| Agent (Tier 1) | `unit` (mock), `integration`, `adversarial`, `ground_truth` | `classification_f1` + `human_rubric` |
| Agent (Tier 2/3) | `unit` (mock), `regression` | `schema_valid` |
| Prompt (behavioural) | `unit` (behavioural consistency test) | `semantic_similarity` |
| Pipeline | `integration` | `schema_valid` + `exact_match` per step |
| Tool | `unit` (input/output contract) | `exact_match` or `schema_valid` |

### 11.3 Description Ambiguity Check — Mandatory at Registration

Before any agent, task, or tool version can move beyond `candidate` state, the description similarity check must pass. The check:

1. Computes embedding for the entity's description using the Anthropic embeddings API
2. Stores embedding in `agent.description_embedding` / `task.description_embedding` / `tool.description_embedding`
3. Computes cosine similarity against all other active agents, tasks, and tools
4. Flags any pair with similarity score > 0.85
5. Logs to `description_similarity_log`
6. Blocks promotion if any unresolved flags exist

Threshold 0.85 is configurable per deployment. Flag resolution requires either:
- Updating one description to be more distinct (description re-embedded and re-checked)
- Human reviewer marks pair as `accepted_as_distinct` with justification

---

## 12. Verity — Compliance & Reporting

### 12.1 Model Inventory Report

The inventory report generated by `GET /v1/reports/model-inventory` covers both agents and tasks, since both are governed entities under SR 11-7:

```json
{
  "generated_at": "2024-10-21T09:00:00Z",
  "summary": {
    "total_agents": 5,
    "total_tasks": 9,
    "agents_by_tier": {"high": 4, "medium": 0, "low": 1},
    "tasks_by_tier": {"high": 0, "medium": 6, "low": 3}
  },
  "agents": [
    {
      "entity_type": "agent",
      "name": "triage_agent",
      "display_name": "Submission Triage Agent",
      "materiality_tier": "high",
      "champion_version": "2.1.0",
      "champion_since": "2024-10-01",
      "inference_config": "triage_balanced",
      "last_validation_date": "2024-09-28",
      "last_validation_passed": true,
      "model_card_status": "approved",
      "override_rate_30d": 0.042,
      "active_incidents": 0,
      "challenger_active": false,
      "fairness_last_assessed": "2024-09-28"
    }
  ],
  "tasks": [
    {
      "entity_type": "task",
      "name": "document_classifier",
      "display_name": "Document Classification Task",
      "capability_type": "classification",
      "materiality_tier": "medium",
      "champion_version": "1.2.0",
      "inference_config": "classification_strict",
      "last_validation_date": "2024-09-25",
      "last_validation_f1": 0.96,
      "model_card_status": "approved"
    }
  ]
}
```

### 12.2 Adverse Action Audit Trail

For any declined submission, `GET /v1/reports/audit-trail/{submission_id}` returns the complete chain including which task versions extracted the data that fed the agents, ensuring full traceability from raw document to final decision:

```json
{
  "submission_id": "uuid",
  "task_executions": [
    {
      "task_name": "document_classifier",
      "task_version": "1.2.0",
      "capability_type": "classification",
      "inference_config": {"model_name": "...", "temperature": 0.0},
      "output_summary": "Classified 3 documents: acord_855, loss_runs, supplemental_do",
      "precision_at_time": 0.96
    },
    {
      "task_name": "acord_855_extractor",
      "task_version": "1.1.0",
      "capability_type": "extraction",
      "output_summary": "Extracted 24 fields; 2 low-confidence",
      "low_confidence_fields": ["entity_type", "revenue_2021"]
    }
  ],
  "agent_executions": [
    {
      "agent_name": "triage_agent",
      "agent_version": "2.1.0",
      "system_prompt_version": "2.3",
      "user_template_version": "1.4",
      "inference_config": {"model_name": "...", "temperature": 0.2, "max_tokens": 4096},
      "reasoning_text": "Submission presents mixed risk profile...",
      "risk_score": "Red",
      "routing": "decline_without_review",
      "hitl_required": true,
      "hitl_approver": "James Okafor",
      "hitl_approved_at": "2024-10-15T11:05:00Z"
    }
  ],
  "overrides": [],
  "final_outcome": "declined",
  "adverse_action_summary": "Submission declined based on: [risk factors cited]"
}
```

---

## 13. UW Platform — FastAPI Middleware

*(API endpoints unchanged from v2.0. Key updates:)*

### 13.1 Updated Endpoint Groups

All `/agents/` endpoints now dispatch through the unified execution engine, which handles both agents and tasks:

```
POST /pipeline/run/{submission_id}      → Full pipeline (tasks + agents)
POST /agents/run/{agent_name}/{id}      → Named agent invocation
POST /tasks/run/{task_name}/{id}        → Named task invocation
GET  /agents/status/{submission_id}     → All agent + task run statuses
```

### 13.2 Inference Config Endpoints (Verity proxy)

```
GET  /verity/inference-configs          → List all named inference configs
GET  /verity/inference-configs/{name}   → Get specific config
```

---

## 14. UW Platform — Execution Engine

### 14.1 Unified Execution Engine

Create file: `uw/execution/engine.py`

The engine handles both agents and tasks through a common interface. The key distinction is in how Claude is called and what outputs are expected:

```python
class VerityExecutionEngine:

    async def run_agent(self, agent_name: str, context: dict,
                        submission_id: UUID, channel: str = "production") -> AgentResult:
        """
        Agents use full tool-use loop:
        1. Get champion config from Verity (includes prompts, tools, inference_config)
        2. Assemble prompts: apply condition_logic, sort by execution_order
           - system prompt (api_role='system', governance_tier='behavioural')
           - user message template (api_role='user', governance_tier='contextual')
           with context variables substituted
        3. Check tool authorisation against agent_version_tool junction
        4. Call Claude with tools enabled, allow multi-turn tool use
        5. Validate output against output_schema
        6. Check authority thresholds — flag HITL if exceeded
        7. Log to Verity BEFORE returning (stores inference_config_snapshot)
        8. Return AgentResult with decision_log_id
        """

    async def run_task(self, task_name: str, input_data: dict,
                       submission_id: UUID, channel: str = "production") -> TaskResult:
        """
        Tasks use single-turn invocation, no autonomous tool loop:
        1. Get champion config from Verity (inference_config, prompts)
        2. Assemble prompts:
           - task_instruction (api_role='system', governance_tier='behavioural')
           - input wrapper (api_role='user', governance_tier='formatting')
           with input_data variables substituted
        3. Call Claude — single turn, no tool use unless task has authorised tools
        4. Parse structured output (tasks always return structured JSON)
        5. Validate against task.output_schema
        6. Log to Verity BEFORE returning
        7. Return TaskResult with decision_log_id
        """
```

**Critical implementation rules:**
- `inference_config_snapshot` is always stored as a JSON column copy — never just the config ID
- Prompt assembly must respect `condition_logic` — conditionally included prompts are evaluated at runtime
- Tool authorisation is checked before each tool invocation: `agent_version_tool.authorized = TRUE`
- Tasks do NOT initiate the multi-turn tool loop even if Claude attempts to — the task runner catches and rejects unexpected tool calls
- Write tools (`is_write_operation=TRUE`) are blocked in `mock_mode` and in `shadow` channel

---

## 15. UW Platform — Agents and Tasks

All agents and tasks are registered in verity_db via `scripts/seed/seed_verity.py`. No AI definitions exist in application code. The following specifies the Verity registration for each.

### 15.1 Inference Configs to Seed

```python
INFERENCE_CONFIGS = [
    {
        "name": "classification_strict",
        "description": "Fully deterministic for classification tasks",
        "intended_use": "Document classification, appetite classification, routing decisions",
        "model_name": "claude-sonnet-4-20250514",
        "temperature": 0.0,
        "max_tokens": 512,
    },
    {
        "name": "extraction_deterministic",
        "description": "Deterministic for field extraction",
        "intended_use": "ACORD form extraction, loss run parsing, entity matching",
        "model_name": "claude-sonnet-4-20250514",
        "temperature": 0.0,
        "max_tokens": 2048,
    },
    {
        "name": "triage_balanced",
        "description": "Low temperature for consistent risk assessment",
        "intended_use": "Triage agent, appetite agent — requires consistency not creativity",
        "model_name": "claude-sonnet-4-20250514",
        "temperature": 0.2,
        "max_tokens": 4096,
    },
    {
        "name": "generation_narrative",
        "description": "Moderate temperature for professional narrative generation",
        "intended_use": "Quote letters, referral memos, renewal analysis narratives",
        "model_name": "claude-sonnet-4-20250514",
        "temperature": 0.4,
        "max_tokens": 8192,
    },
    {
        "name": "renewal_analytical",
        "description": "Low temperature for comparative analysis",
        "intended_use": "Renewal agent — structured comparison of prior vs current",
        "model_name": "claude-sonnet-4-20250514",
        "temperature": 0.1,
        "max_tokens": 4096,
    },
]
```

### 15.2 Tasks (4 bounded AI operations)

---

#### Task 1: Document Validator

**Verity Registration:**
```json
{
  "name": "document_validator",
  "display_name": "Document Completeness Validator",
  "capability_type": "validation",
  "materiality_tier": "low",
  "description": "Validates that a submission has the minimum required document types present in the document repository. Returns completeness status and list of missing document types. Does not assess document content or quality.",
  "purpose": "Prevent downstream extraction tasks from running on incomplete submissions.",
  "input_schema": {"submission_id": "uuid", "required_doc_types": "array"},
  "output_schema": {
    "validation_passed": "boolean",
    "documents_found": "array",
    "documents_missing": "array",
    "notes": "string"
  },
  "inference_config": "classification_strict"
}
```

**Prompts:**
- System (behavioural): "You are a document completeness checker. Given a list of found documents and required document types, determine if all required types are present. Return only valid JSON. Do not infer document types — use exact matches only."
- User template (formatting): "Required types: {{required_doc_types}}\nFound documents: {{found_documents}}\nReturn JSON with validation_passed, documents_found, documents_missing, notes."

**Tools:** `get_documents_for_submission`, `update_submission_event`

---

#### Task 2: Document Classifier

**Verity Registration:**
```json
{
  "name": "document_classifier",
  "display_name": "Insurance Document Classification Task",
  "capability_type": "classification",
  "materiality_tier": "medium",
  "description": "Classifies a single insurance document into one of the defined document types based on its text content. Returns document type and confidence score. Processes one document per invocation.",
  "purpose": "Identify document types to route to appropriate extraction tasks.",
  "input_schema": {"document_text": "string", "document_filename": "string"},
  "output_schema": {
    "document_type": "string",
    "confidence": "number",
    "classification_notes": "string"
  },
  "inference_config": "classification_strict"
}
```

**Prompts:**
- System (behavioural): "You are an insurance document classifier. Classify the provided document into exactly one of these types: acord_855, acord_125, loss_runs, supplemental_do, supplemental_gl, financial_statements, board_resolution, other. Return only valid JSON with document_type, confidence (0.0-1.0), and classification_notes. Base classification only on document content — never on filename."
- User template (formatting): "Document text:\n{{document_text}}"

**Ground truth:** 200 SME-labeled documents (50 per major type). Minimum F1 ≥ 0.93 before champion promotion.

---

#### Task 3: Field Extractor (D&O — ACORD 855)

**Verity Registration:**
```json
{
  "name": "acord_855_extractor",
  "display_name": "D&O ACORD 855 Field Extraction Task",
  "capability_type": "extraction",
  "materiality_tier": "medium",
  "description": "Extracts structured data fields from a D&O Directors and Officers liability ACORD 855 application form. Returns field values with per-field confidence scores. Does not extract from GL forms, loss runs, or supplementals.",
  "purpose": "Populate submission_do_detail table from ACORD 855 application text.",
  "input_schema": {"document_text": "string", "submission_id": "uuid"},
  "output_schema": {
    "fields": "object",
    "low_confidence_fields": "array",
    "unextractable_fields": "array",
    "extraction_complete": "boolean"
  },
  "inference_config": "extraction_deterministic"
}
```

**Prompts:**
- System (behavioural): "You are a specialist extraction system for D&O insurance applications (ACORD 855 form). Extract the following fields from the provided document text: named_insured, fein, entity_type, state_of_incorporation, annual_revenue, employee_count, board_size, independent_directors, effective_date, expiration_date, limits_requested, retention_requested, prior_carrier, prior_premium, securities_class_action_history, regulatory_investigation_history, merger_acquisition_activity, ipo_planned, going_concern_opinion, non_renewed_by_carrier. For each field: extract the value exactly as stated, assign confidence (0.0-1.0), and if not found, set to null with confidence 0.0. Never invent values. Return only valid JSON."
- User template (formatting): "ACORD 855 document text:\n{{document_text}}"

**Tools:** `update_submission_do_detail` (write), `update_document_extraction_status` (write)

**Ground truth:** 50 completed ACORD 855 forms with verified values. Field accuracy ≥ 0.90 per required field.

---

#### Task 4: Loss Run Parser

**Verity Registration:**
```json
{
  "name": "loss_run_parser",
  "display_name": "Loss Run Data Extraction Task",
  "capability_type": "extraction",
  "materiality_tier": "medium",
  "description": "Extracts structured loss history data from insurance loss run schedules. Parses multi-year loss data including claim counts, incurred losses, paid losses, and reserves per policy year. Returns structured annual loss data.",
  "purpose": "Populate loss_history table from loss run document text.",
  "input_schema": {"document_text": "string", "submission_id": "uuid"},
  "output_schema": {
    "years_extracted": "array",
    "total_claims": "integer",
    "total_incurred": "number",
    "extraction_complete": "boolean"
  },
  "inference_config": "extraction_deterministic"
}
```

**Note:** A separate `acord_125_extractor` task is registered with equivalent structure for GL submissions. Registers as a distinct task with its own description, prompt versions, and ground truth dataset — distinct from the ACORD 855 extractor despite similar capability.

**The description similarity check will flag these two as similar** (both are extraction tasks for insurance forms). The similarity flag must be resolved by a human reviewer who marks them as `accepted_as_distinct` with the justification that they target entirely different form schemas. This is the correct workflow — the system correctly identifies the similarity and requires explicit human acknowledgment.

### 15.3 Agents (5 goal-directed reasoning systems)

---

#### Agent 1: Triage Agent

**Verity Registration:**
```json
{
  "name": "triage_agent",
  "display_name": "Submission Risk Triage Agent",
  "materiality_tier": "high",
  "description": "Synthesises extracted submission data, account enrichment, and loss history into a structured risk assessment for commercial lines D&O and GL submissions. Produces a risk score, routing recommendation, and plain-language risk narrative by reasoning across multiple competing risk factors. Calls tools to retrieve all relevant context before assessment.",
  "purpose": "Assist underwriters by providing a structured first-pass risk assessment before human review, reducing data-gathering time and improving routing consistency.",
  "authority_thresholds": {
    "requires_hitl_above_premium": 500000,
    "low_confidence_threshold": 0.70,
    "auto_decline_red": false
  },
  "inference_config": "triage_balanced"
}
```

**Prompts:**
- System prompt v1.0 (behavioural): Full system prompt as defined in original PRD Section 15 — see seed script.
- User message template v1.0 (contextual): Structured context template assembling submission data, enrichment results, loss history summary, and guidelines excerpt with variable substitution.

**Tools:** `get_full_submission_context`, `get_underwriting_guidelines`, `update_snow_ai_analysis`, `update_submission_event`, `store_triage_result`

**Ground truth:** 20 SME-labeled submissions. Thresholds: precision ≥ 0.85, recall ≥ 0.82, F1 ≥ 0.83, kappa ≥ 0.75. Fairness analysis required.

---

#### Agent 2: Appetite Agent

**Verity Registration:**
```json
{
  "name": "appetite_agent",
  "display_name": "Underwriting Appetite Assessment Agent",
  "materiality_tier": "high",
  "description": "Assesses whether a commercial lines D&O or GL submission is within underwriting appetite by reasoning across the submission's characteristics and the relevant underwriting guidelines document. Cites specific guideline sections for each determination. Distinct from triage_agent: appetite_agent focuses exclusively on guidelines compliance, not overall risk scoring.",
  "purpose": "Provide a structured guidelines-based appetite determination with specific section citations, enabling consistent appetite decisions and regulatory defensibility.",
  "authority_thresholds": {},
  "inference_config": "triage_balanced"
}
```

**Tools:** `get_underwriting_guidelines`, `get_submission_detail`, `update_snow_appetite_status`

---

#### Agent 3: Quote Assistant Agent

**Verity Registration:**
```json
{
  "name": "quote_assistant",
  "display_name": "Quote Assistance Agent",
  "materiality_tier": "high",
  "description": "Assists underwriters in generating commercial insurance quotes by calling the rating engine, reasoning about appropriate schedule modifications based on the risk profile, recommending coverage terms, and generating a quote letter PDF. Requires underwriter initiation — does not auto-quote.",
  "purpose": "Reduce quote preparation time by synthesising rating output with risk profile intelligence and producing draft quote terms for underwriter review and approval.",
  "authority_thresholds": {
    "requires_senior_uw_approval_above_premium": 500000,
    "max_schedule_credit": -0.30,
    "max_schedule_debit": 0.50
  },
  "inference_config": "triage_balanced"
}
```

**Tools:** `get_full_submission_context`, `run_rating_engine`, `recommend_schedule_modification`, `recommend_terms`, `generate_quote_letter_pdf`, `create_quote_record`, `update_snow_quote_info`

---

#### Agent 4: Referral Memo Agent

**Verity Registration:**
```json
{
  "name": "referral_memo_agent",
  "display_name": "Senior UW Referral Memo Agent",
  "materiality_tier": "low",
  "description": "Generates a structured senior underwriter referral memo by synthesising triage assessment, clearance results, appetite determination, loss history, and draft quote terms into a professional document. Output requires human review before use — the agent produces a draft, not a final document.",
  "purpose": "Reduce the time underwriters spend preparing referral documentation by auto-drafting the memo from already-computed risk intelligence.",
  "authority_thresholds": {},
  "inference_config": "generation_narrative"
}
```

**Tools:** `get_full_submission_context`, `get_triage_results`, `get_clearance_results`, `get_appetite_results`, `get_quote_draft`, `generate_referral_memo_pdf`, `update_snow_referral_memo_link`

---

#### Agent 5: Renewal Analysis Agent

**Verity Registration:**
```json
{
  "name": "renewal_agent",
  "display_name": "Renewal Analysis Agent",
  "materiality_tier": "high",
  "description": "Analyses commercial lines policy renewals by comparing current submission data against the prior policy term across revenue changes, risk profile evolution, loss development, and market conditions. Produces a renewal recommendation with indicated rate change and supporting rationale.",
  "purpose": "Proactively surface renewal intelligence to underwriters, reducing the manual effort of prior-versus-current comparison and improving renewal decision consistency.",
  "authority_thresholds": {
    "auto_non_renew_triggers": ["going_concern_opinion", "securities_class_action"],
    "requires_senior_uw_above_rate_increase_pct": 0.20
  },
  "inference_config": "renewal_analytical"
}
```

**Tools:** `get_renewal_detail`, `get_prior_policy`, `get_prior_submission`, `get_prior_loss_development`, `get_current_submission_context`, `run_renewal_rating`, `update_renewal_record`, `update_snow_renewal`

### 15.4 Pipeline Registration

The UW submission pipeline is registered as a `pipeline` entity with a `pipeline_version`:

```python
PIPELINE = {
    "name": "uw_submission_pipeline",
    "display_name": "Underwriting Submission Processing Pipeline",
    "description": "Full submission processing pipeline from document validation through risk triage. Orchestrates tasks (validation, classification, extraction, matching) and agents (triage, appetite) in the correct dependency order with parallel execution where applicable."
}

PIPELINE_STEPS = [
    {"step_order": 1, "step_name": "validate_documents",
     "entity_type": "task", "entity_name": "document_validator",
     "depends_on": [], "parallel_group": None,
     "error_policy": "fail_pipeline"},

    {"step_order": 2, "step_name": "classify_documents",
     "entity_type": "task", "entity_name": "document_classifier",
     "depends_on": ["validate_documents"], "parallel_group": None,
     "error_policy": "fail_pipeline"},

    {"step_order": 3, "step_name": "extract_do_fields",
     "entity_type": "task", "entity_name": "acord_855_extractor",
     "depends_on": ["classify_documents"], "parallel_group": "extraction_group",
     "error_policy": "continue_with_flag",
     "condition": {"if_doc_type_present": "acord_855"}},

    {"step_order": 3, "step_name": "extract_gl_fields",
     "entity_type": "task", "entity_name": "acord_125_extractor",
     "depends_on": ["classify_documents"], "parallel_group": "extraction_group",
     "error_policy": "continue_with_flag",
     "condition": {"if_doc_type_present": "acord_125"}},

    {"step_order": 3, "step_name": "parse_loss_runs",
     "entity_type": "task", "entity_name": "loss_run_parser",
     "depends_on": ["classify_documents"], "parallel_group": "extraction_group",
     "error_policy": "continue_with_flag",
     "condition": {"if_doc_type_present": "loss_runs"}},

    {"step_order": 4, "step_name": "match_account",
     "entity_type": "task", "entity_name": "mdm_matcher",
     "depends_on": ["extraction_group"], "parallel_group": "enrichment_group",
     "error_policy": "continue_with_flag"},

    {"step_order": 4, "step_name": "aggregate_enrichment",
     "entity_type": "task", "entity_name": "enrichment_aggregator",
     "depends_on": ["extraction_group"], "parallel_group": "enrichment_group",
     "error_policy": "continue_with_flag"},

    {"step_order": 5, "step_name": "triage_submission",
     "entity_type": "agent", "entity_name": "triage_agent",
     "depends_on": ["enrichment_group"], "parallel_group": None,
     "error_policy": "fail_pipeline"},

    {"step_order": 6, "step_name": "assess_appetite",
     "entity_type": "agent", "entity_name": "appetite_agent",
     "depends_on": ["triage_submission"], "parallel_group": None,
     "error_policy": "continue_with_flag"},

    {"step_order": 7, "step_name": "push_to_servicenow",
     "entity_type": "tool", "tool_name": "update_snow_ai_analysis",
     "depends_on": ["triage_submission", "assess_appetite"],
     "error_policy": "fail_pipeline"}
]
```

**Note on missing tasks from original PRD:**
The original PRD listed "Enrichment Agent" and "Clearance Agent" as agents. These are now correctly registered as tasks:
- `enrichment_aggregator` — Task (generation) — aggregates 5 mock API results
- `mdm_matcher` — Task (matching) — fuzzy matches company name against account registry
- `clearance_checker` — Task (validation) — deterministic PAS database lookups (no LLM needed; can be non-AI)

The clearance check specifically does not require Claude — it is a series of database queries. It may be implemented as a standard Python function registered as a tool rather than a task. This is an implementation decision for Claude Code: if the clearance logic is purely deterministic database lookups, implement as a tool; if it requires reasoning about prior history (e.g., interpreting ambiguous prior submissions), implement as a task.

---

## 16. UW Platform — Rating Engine

*(Unchanged from v2.0 — see Section 16 of VERITY_COMBINED_PRD v2.0 for full D&O and GL rating logic)*

All rating calls logged to `workflow_db.rating_log` with full input and output.

---

## 17. ServiceNow Configuration

*(Unchanged from v2.0 — see Section 17)*

Key update: The ServiceNow AI Analysis Panel widget now displays both agent and task execution status:
- Task pipeline status (validate → classify → extract → enrich → match)
- Agent assessment results (triage → appetite)
- The `u_verity_decision_log_id` field on the submission record links to the triage agent's decision log

---

## 18. Seed Data

*(Unchanged from v2.0 — see Section 18)*

`scripts/seed/seed_verity.py` must register in this order to satisfy foreign key constraints:
1. Inference configs (no dependencies)
2. Tools (no dependencies)
3. MCP servers (no dependencies)
4. Tasks + task_versions + entity_prompt_assignments + task_version_tools
5. Agents + agent_versions + entity_prompt_assignments + agent_version_tools
6. Pipelines + pipeline_versions
7. Test suites + test cases for all entities
8. Ground truth datasets (metadata only — data uploaded to MinIO separately)
9. Metric thresholds for all entities
10. Mock approval records (to promote all entities to champion for demo)

---

## 19. Demo Scenario Script

*(Updated from v2.0 to reflect task/agent distinction)*

### Demo Moment 2: Verity Pipeline — Updated Narrative

**Story:** "Let me show you what Verity is actually doing. When this submission was received, Verity ran eight AI operations — four tasks and two agents — governed by the same framework."

**Steps:**
1. Click "Run Pipeline" in admin UI
2. Show live pipeline log: each step labelled with entity type
   - `[TASK] document_validator v1.0.0` → Passed — 3 documents found
   - `[TASK] document_classifier v1.2.0` → acord_855 (0.97), loss_runs (0.94), supplemental_do (0.91)
   - `[TASK] acord_855_extractor v1.1.0` → 24 fields extracted, 2 low-confidence
   - `[TASK] loss_run_parser v1.0.0` → 3 years extracted, $125K total incurred
   - `[TASK] mdm_matcher v1.0.0` → Acme Dynamics matched, confidence 0.94
   - `[TASK] enrichment_aggregator v1.0.0` → 5 sources aggregated
   - `[AGENT] triage_agent v2.1.0` → Amber, assign_to_senior_uw
   - `[AGENT] appetite_agent v1.3.0` → borderline, Guideline §3.2 cited
3. **Key demo moment:** Click on `document_classifier v1.2.0` in the log
4. Show: precision 0.96, recall 0.94, F1 0.95 — validated against 200 documents
5. Show: inference_config `classification_strict` — temperature 0.0, deterministic
6. "The same governance that applies to the triage agent applies to every task. The document classifier has its own version history, its own ground truth validation, its own model card."

---

## 20. Development Phases

### Phase 1: Infrastructure (Week 1)
- [ ] docker-compose.yml with pgvector/pgvector:pg16 image
- [ ] All 4 databases created including `CREATE EXTENSION vector;` in verity_db
- [ ] Verity API running on port 8001, UW API on port 8000
- [ ] All containers healthy

### Phase 2: Verity Core Schema & Registry (Week 1-2)
- [ ] Full verity_db schema applied (all tables including new ones: task, task_version, entity_prompt_assignment, inference_config, agent_version_tool, task_version_tool, pipeline_version, evaluation_run, model_card, description_similarity_log)
- [ ] `CREATE EXTENSION vector;` verified in verity_db
- [ ] All SQLAlchemy ORM models
- [ ] Registry API: `GET /v1/agents/{name}/champion` and `GET /v1/tasks/{name}/champion`
- [ ] Decision logging: `POST /v1/decisions/log` with inference_config_snapshot
- [ ] Description embedding compute endpoint functional

### Phase 3: UW Databases & Core Endpoints (Week 2)
- [ ] pas_db, workflow_db, broker_db schemas
- [ ] All UW API endpoints
- [ ] Rating engine D&O and GL
- [ ] Mock enrichment API

### Phase 4: Unified Execution Engine (Week 2-3)
- [ ] `agent_runner.py` and `task_runner.py` as distinct runners with shared interface
- [ ] Prompt assembly: condition_logic evaluation, execution_order sorting
- [ ] Inference config applied from Verity — never hardcoded
- [ ] Tool authorisation check via agent_version_tool / task_version_tool
- [ ] Inference_config_snapshot stored with every decision log
- [ ] Write operation suppression in mock mode

### Phase 5: Verity Seed + Description Embeddings (Week 3)
- [ ] All 5 inference configs registered
- [ ] All tools registered with descriptions
- [ ] Description embeddings computed for all tools
- [ ] All 4 tasks + task_versions registered with prompts
- [ ] All 5 agents + agent_versions registered with prompts
- [ ] Description embeddings computed for all tasks and agents
- [ ] Similarity checks run — ACORD extractor pair flagged and resolved
- [ ] Pipeline registered with correct steps
- [ ] Mock responses created for all tools

### Phase 6: ServiceNow Configuration (Week 3-4)
*(Unchanged from v2.0)*

### Phase 7: Seed Data in Databases (Week 4)
*(Unchanged from v2.0)*

### Phase 8: Verity Testing Framework (Week 4-5)
- [ ] Test suites registered for all entities (agents AND tasks)
- [ ] Correct metric_type per entity: classification_f1 for classifier, field_accuracy for extractors
- [ ] Ground truth datasets uploaded to MinIO and registered
- [ ] `POST /v1/testing/run-ground-truth` produces metrics per capability_type
- [ ] Validation_run records created per entity

### Phase 9: Verity Lifecycle Management (Week 5)
- [ ] Promotion pipeline enforcing criteria per entity type and materiality
- [ ] Approval records for all demo entities
- [ ] Prompt lifecycle: behavioural tier requires HITL, contextual does not
- [ ] Model cards seeded for all High-materiality agents and tasks

### Phase 10: Full Pipeline + Demo Polish (Week 5-6)
- [ ] Full pipeline executing tasks + agents in correct dependency order
- [ ] Parallel execution groups working (asyncio.gather for extraction_group, enrichment_group)
- [ ] Entity type labels visible in admin pipeline log
- [ ] All 4 demo moments executable

### Phase 11: Verity Compliance Reporting (Week 6-7)
- [ ] Model inventory report covering both agents and tasks
- [ ] Audit trail showing full task + agent chain per submission
- [ ] Override analysis
- [ ] Regulatory evidence packages (SR 11-7, NAIC, CO SB21-169)

### Phase 12: Demo Polish & Reset (Week 7)
*(Unchanged from v2.0)*

---

## 21. Non-Functional Requirements

### 21.1 Performance

| Operation | Target |
|---|---|
| Docker Compose cold start | < 90 seconds |
| FastAPI endpoint (excluding AI) | < 500ms |
| Verity API response (registry) | < 300ms |
| Single task execution (extraction) | < 8 seconds |
| Single agent execution (triage) | < 20 seconds |
| Full pipeline (all tasks + agents) | < 60 seconds |
| Description similarity check | < 3 seconds |
| Ground truth validation (20 records) | < 90 seconds |
| Model inventory report | < 2 seconds |
| Audit trail per submission | < 1 second |
| Demo reset | < 60 seconds |

### 21.2 Resource Requirements

| Resource | Minimum |
|---|---|
| RAM | 8GB available for Docker |
| CPU | 4 cores recommended |
| Disk | 15GB for volumes, documents, datasets |
| Network | Required for ServiceNow PDI + Anthropic API |

### 21.3 Reliability

- Verity API unavailability causes UW platform graceful error — never bypass Verity
- All agent and task failures logged to `agent_decision_log` — never crash pipeline
- Write tool suppression in mock mode enforced at tool level, not just at engine level
- `inference_config_snapshot` always stored regardless of success or failure

### 21.4 Security (Demo Scope)

- All secrets in `.env`, listed in `.gitignore`
- MinIO not publicly exposed — presigned URLs only
- Verity admin and UW admin protected by `ADMIN_API_KEY` header
- Anthropic API key in environment variables only

### 21.5 Observability

- Every Claude invocation logged with: entity_type, entity_name, version, submission_id, tokens, duration, status
- Pipeline run ID groups all decisions from a single pipeline execution
- Description similarity checks logged permanently in `description_similarity_log`
- `GET /health` on both services returns: postgres connections, MinIO, ServiceNow, Verity (for UW service)

---

## 22. Acceptance Criteria

### Infrastructure
- `docker-compose up` starts all services with no errors
- `SELECT * FROM pg_extension WHERE extname = 'vector';` returns a row in verity_db
- All services healthy within 90 seconds

### Verity Schema
- All tables created including: task, task_version, entity_prompt_assignment, inference_config, agent_version_tool, task_version_tool, pipeline_version, evaluation_run, model_card, description_similarity_log
- `vector(1536)` column type confirmed on agent.description_embedding, task.description_embedding, tool.description_embedding

### Verity Registry
- `GET /v1/agents/triage_agent/champion` returns: inference_config with temperature 0.2, two prompts (system/behavioural and user/contextual), 5 authorised tools
- `GET /v1/tasks/document_classifier/champion` returns: inference_config with temperature 0.0, capability_type = 'classification', two prompts

### Execution Engine
- Zero AI definitions in `uw/` application code (grep check: no hardcoded temperature, max_tokens, prompt text, or tool lists)
- Every Claude call (agent and task) creates a record in verity_db.agent_decision_log with entity_type correctly set
- inference_config_snapshot stored as JSON column on every decision log record
- Write tools suppressed in mock mode: no ServiceNow writes, no PAS writes during test runs

### Task-Agent Distinction
- Document classifier runs as Task (single turn, no tool loop)
- ACORD extractor runs as Task (single turn)
- Triage agent runs as Agent (multi-turn tool use)
- Pipeline log displays entity_type label for each step

### Description Embeddings
- `POST /v1/testing/check-descriptions` returns similarity scores for all entity pairs
- ACORD 855 extractor and ACORD 125 extractor flagged as similar — flag resolved in seed
- No unresolved similarity flags on any champion entity

### Testing
- Test suites exist for all 4 tasks with correct metric_type (classification_f1 for classifier, field_accuracy for extractors)
- Validation_run for document_classifier shows precision/recall/F1 (not kappa — classification task)
- Validation_run for triage_agent shows precision/recall/F1/kappa (agent outcome metrics)
- model_card records exist for all High-materiality agents and tasks

### Demo Scenario
- Pipeline log shows entity_type label per step
- Clicking a task in the log shows its validation metrics (precision/recall/F1 for classifier)
- Clicking an agent shows its ground truth validation (kappa included)
- All 4 demo moments executable end-to-end
- Reset restores clean state in < 60 seconds

---

## 23. Out of Scope

*(Unchanged from v2.0)*

---

## Appendix A: Entity Registration Template

**For Agents:**
```json
{
  "name": "agent_name",
  "display_name": "Human Readable Name",
  "description": "Precise, unambiguous. Will be embedded and similarity-checked against all tasks and tools.",
  "purpose": "One sentence: what this agent does and why.",
  "materiality_tier": "high|medium|low",
  "owner_name": "...",
  "inference_config": "config_name",
  "prompts": [
    {
      "api_role": "system",
      "governance_tier": "behavioural",
      "content": "Full system prompt...",
      "execution_order": 1,
      "is_required": true,
      "condition_logic": null
    },
    {
      "api_role": "user",
      "governance_tier": "contextual",
      "content": "Context template with {{variables}}...",
      "execution_order": 2,
      "is_required": true,
      "condition_logic": null
    }
  ],
  "tools": ["tool_name_1", "tool_name_2"],
  "authority_thresholds": {},
  "output_schema": {}
}
```

**For Tasks:**
```json
{
  "name": "task_name",
  "display_name": "Human Readable Name",
  "capability_type": "classification|extraction|generation|summarisation|matching|validation",
  "description": "Precise, unambiguous. Will be embedded and similarity-checked.",
  "purpose": "One sentence: what this task does and why.",
  "materiality_tier": "high|medium|low",
  "owner_name": "...",
  "inference_config": "config_name",
  "input_schema": {},
  "output_schema": {},
  "prompts": [
    {
      "api_role": "system",
      "governance_tier": "behavioural",
      "content": "Task instruction: classify/extract/generate...",
      "execution_order": 1
    },
    {
      "api_role": "user",
      "governance_tier": "formatting",
      "content": "Input: {{input_field}}",
      "execution_order": 2
    }
  ],
  "tools": []
}
```

## Appendix B: Prompt Governance Tier Decision Guide

| Question | If Yes | If No |
|---|---|---|
| Does changing this prompt change what decisions the AI reaches? | `behavioural` | → next |
| Does changing this prompt change how context is structured for the AI? | `contextual` | → next |
| Does this prompt only control output format or input wrapping? | `formatting` | (reconsider) |

**Governance requirements by tier:**

| Tier | Lifecycle States | HITL Required | Test Required | Ground Truth |
|---|---|---|---|---|
| `behavioural` | Full 7-state | Yes | Yes | Yes (if entity is High-materiality) |
| `contextual` | draft → approved → deprecated | No | Schema validation only | No |
| `formatting` | draft → active | No | No | No |

---

*End of PRD — PremiumIQ Verity v3.0*

*This document supersedes VERITY_COMBINED_PRD v2.0. The primary changes are: (1) introduction of the task entity as distinct from agent, (2) named inference_config entity replacing hardcoded parameters, (3) revised prompt model with api_role + governance_tier + entity_prompt_assignment junction, (4) description embeddings with similarity checking on all agent/task/tool descriptions, (5) test suites and ground truth datasets generalised to target any entity type with metric_type matching capability_type, (6) evaluation_run and model_card as new entities, (7) pipeline versioning. Claude Code should build from Phase 1 sequentially. The vocabulary reference at the top of this document is authoritative — use it to resolve any naming ambiguity during implementation.*
