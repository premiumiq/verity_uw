# PremiumIQ Verity - Product Vision

## The governance infrastructure that AI systems run on.

Compliant, auditable, and built for regulated industries.

---

## The Problem

Agentic AI is taking on consequential decisions across underwriting and claims at unprecedented speed and scale. An agent can triage a submission, assess appetite against guidelines, extract fields from application forms, and route a risk to the right underwriter - all in seconds.

But speed without accountability is a liability.

When a regulator asks why a submission was declined, when an auditor wants to see which model version was running on a specific date, when a compliance officer needs to prove that a prompt change went through proper review - the answer cannot be "let me check with the engineering team."

Accountability for AI decisions must be engineered into the systems that support them. Organizations that adopt agentic AI with confidence are those that made governance foundational, not remedial.

---

## What Verity Is

Verity is a metamodel-driven framework for deploying, testing, validating, and governing agentic AI systems in regulated P&C insurance environments.

It is not an AI application. It is the governance infrastructure that AI applications run on.

```
+-------------------------------------------------------------------+
|                                                                   |
|   "Application X, powered by Verity"                              |
|                                                                   |
|   Your business application contains the domain logic.            |
|   Verity contains the governance, audit, and compliance.          |
|                                                                   |
+-------------------------------------------------------------------+
```

---

## How It All Fits Together

### The Three-Layer Architecture

```
+====================================================================+
|                      BUSINESS APPLICATIONS                         |
|                                                                    |
|  +------------------+  +------------------+  +------------------+  |
|  | Underwriting App |  | Claims App       |  | Renewal App      |  |
|  | (Port 8001)      |  | (Port 8003)      |  | (Port 8004)      |  |
|  |                  |  |                  |  |                  |  |
|  | Domain logic     |  | Domain logic     |  | Domain logic     |  |
|  | UI / Workflows   |  | UI / Workflows   |  | UI / Workflows   |  |
|  | Tool impls       |  | Tool impls       |  | Tool impls       |  |
|  +--------+---------+  +--------+---------+  +--------+---------+  |
|           |                      |                      |          |
+===========|======================|======================|==========+
            |                      |                      |
            v                      v                      v
+====================================================================+
|                    VERITY GOVERNANCE PLATFORM                      |
|                         (Port 8000)                                |
|                                                                    |
|  +------------+  +-----------+  +-----------+  +---------------+  |
|  | Asset      |  | Lifecycle |  | Testing & |  | Decision      |  |
|  | Registry   |  | Framework |  | Validation|  | Logging       |  |
|  +------------+  +-----------+  +-----------+  +---------------+  |
|  +------------+  +-----------+  +--------------------------------+|
|  | Execution  |  | Compliance|  | Governance Admin UI            ||
|  | Control    |  | Reporting |  | (Dashboard, Inventory, Audit)  ||
|  +------------+  +-----------+  +--------------------------------+|
|                                                                    |
+========================+===============+===========================+
                         |               |
                         v               v
+====================================================================+
|                      SHARED SERVICES                               |
|                                                                    |
|  +------------------+  +------------------+  +------------------+  |
|  | EDMS             |  | MDM              |  | Enrichment       |  |
|  | (Port 8002)      |  | (Future)         |  | (Future)         |  |
|  |                  |  |                  |  |                  |  |
|  | Document storage |  | Entity resolution|  | LexisNexis       |  |
|  | Text extraction  |  | Golden records   |  | D&B, PitchBook   |  |
|  | Lineage tracking |  | Matching rules   |  | Regulatory feeds |  |
|  | Tag governance   |  |                  |  |                  |  |
|  +------------------+  +------------------+  +------------------+  |
|                                                                    |
+====================================================================+
```

### How the Layers Interact

**Business Applications** contain domain expertise. The underwriting app knows what a D&O submission looks like, what tools an underwriter needs, and what the workflow is. It registers its agents, tasks, prompts, and tools with Verity, then calls Verity to execute them.

**Verity** governs everything. It stores the agent definitions, manages their lifecycle, executes them (or delegates execution to an external orchestrator), logs every decision, and provides the compliance reporting layer. Verity knows nothing about insurance - it knows about AI governance.

**Shared Services** are independent systems that agents access through governed tool calls. EDMS manages documents. MDM resolves entities. Enrichment provides external data. Each service owns its own database and APIs. Verity governs the tool calls to these services but never connects to them directly.

### Separation of Concerns

| Concern | Who Owns It |
|---------|------------|
| What agents exist, what version is live | Verity (Asset Registry) |
| Whether a prompt change can go to production | Verity (Lifecycle Framework) |
| Whether an agent meets accuracy thresholds | Verity (Testing & Validation) |
| What happened when agent X processed submission Y | Verity (Decision Logging) |
| What the D&O underwriting guidelines say | Business App (domain knowledge) |
| How to extract text from a PDF | EDMS (shared service) |
| What company "Acme Corp" maps to in the golden record | MDM (shared service) |

---

## The Sidecar Architecture

### Verity as Embedded SDK (Current)

Today, business applications use Verity as a Python library. The app imports the Verity SDK, and execution happens inside the app's process.

```
+------------------------------------------+
| Business Application Process             |
|                                          |
|  Business Logic                          |
|       |                                  |
|       v                                  |
|  +------------------+                    |
|  | Verity SDK       |                    |
|  |  - Registry      |                    |
|  |  - Lifecycle     |----> verity_db     |
|  |  - Execution     |----> Claude API    |
|  |  - Decisions     |                    |
|  +------------------+                    |
|                                          |
+------------------------------------------+
```

### Verity as Governance Sidecar (Future)

As agentic patterns grow more complex - multi-agent orchestration, sub-agents, long-running sessions, parallel tool calling - maintaining a full execution engine inside Verity becomes a liability. Commercial orchestration platforms (LangGraph, CrewAI, Amazon Bedrock Agents, Anthropic Agent SDK) do agent orchestration better and will continue to evolve faster.

In the sidecar model, Verity becomes the governance layer that any orchestrator reports to:

```
+------------------------------------------+
| Business Application Process             |
|                                          |
|  Business Logic                          |
|       |                                  |
|       v                                  |
|  +------------------+    +-----------+   |
|  | Agent            |    | Verity    |   |
|  | Orchestrator     |--->| Sidecar   |   |
|  | (LangGraph,      |    |           |   |
|  |  CrewAI,         |    | - Registry|   |
|  |  Bedrock, etc.)  |    | - Logging |   |
|  |                  |    | - Lifecycl|   |
|  |  Executes agents |    | - Audit   |   |
|  |  Calls tools     |    |           |   |
|  |  Manages state   |    +-----------+   |
|  +------------------+         |          |
|       |                       v          |
|       v                   verity_db      |
|    Claude API                            |
|                                          |
+------------------------------------------+
```

### What Changes, What Stays

| Capability | Embedded SDK | Sidecar |
|-----------|-------------|---------|
| Agent definitions (prompts, tools, configs) | Stored in Verity | Stored in Verity (source of truth) OR synced from orchestrator (record of truth) |
| Agent execution (LLM calls, tool calls) | Verity executes | Orchestrator executes |
| Decision logging | Verity logs directly | Orchestrator reports to Verity after each execution |
| Lifecycle management | Verity enforces | Verity enforces (orchestrator queries Verity for which version to run) |
| Testing & validation | Verity runs test suites | Verity triggers tests via orchestrator, collects results |
| Tool authorization | Verity checks before each call | Orchestrator checks against Verity's registry |
| Mock mode | Verity's MockContext | Orchestrator's own mocking + Verity's test framework |

### The Governance Contract

Regardless of which orchestrator runs the agents, it must report to Verity after every AI invocation:

```
{
    entity_type:              "agent" | "task"
    entity_version_id:        UUID (which version ran)
    prompt_version_ids:       [UUIDs] (which prompts were used)
    inference_config_snapshot: {model, temperature, max_tokens, ...}
    channel:                  "production" | "staging" | ...
    execution_context_id:     UUID (business context link)
    run_purpose:              "production" | "test" | "validation"
    input_json:               {...}
    output_json:              {...}
    tool_calls_made:          [{name, input, output}, ...]
    message_history:          [{role, content}, ...]
    model_used:               "claude-sonnet-4-6"
    input_tokens:             1500
    output_tokens:            800
    duration_ms:              2300
    status:                   "complete" | "failed"
}
```

This is the hard requirement. Everything else is flexible.

---

## Verity in Action: Commercial Underwriting

### The Scenario

A commercial insurance submission arrives for Meridian Holdings Corp, a financial services company applying for General Liability coverage. The underwriting application - powered by Verity - processes it through a governed pipeline.

### Step 1: Documents Enter the System

The broker uploads an ACORD 125 application form, a loss run report, and financial statements to the EDMS. EDMS stores the files in MinIO, extracts text from each document, and tracks the lineage (original PDF -> extracted text).

```
Broker uploads 3 documents
        |
        v
+------------------+
| EDMS Service     |
| - Store in MinIO |
| - Extract text   |
| - Track lineage  |
| - Apply tags     |
+------------------+
```

### Step 2: The Pipeline Runs

The underwriting app creates an execution context in Verity ("submission:Meridian-GL-2026") and triggers the pipeline. Verity resolves the champion version of each agent and task, pulling the exact prompt versions, inference configs, and tool authorizations that governance approved.

```
UW App: "Run the submission pipeline for Meridian Holdings"
        |
        v
Verity: Resolve champion versions
        - document_classifier agent v1.0.0 (champion since 2026-03-15)
        - field_extractor agent v1.0.0
        - triage_agent v2.0.0 (promoted after ground truth validation)
        - appetite_agent v1.0.0
        |
        v
Execute pipeline (4 steps, governed)
```

### Step 3: Each Step is Governed

**Document Classification:**
The classifier agent calls `list_documents("submission:Meridian-GL-2026")` through the EDMS tool (governed by Verity - the tool call is authorized and logged). It retrieves the extracted text for each document and classifies them: GL Application, Loss Run, Financial Statement.

**Field Extraction:**
The extractor agent retrieves the GL application text via EDMS tool and extracts 20 structured fields: company name, revenue, SIC code, employee count, etc.

**Risk Triage:**
The triage agent calls `get_submission_context`, `get_loss_history`, and `get_enrichment_data` tools. It synthesizes the data and scores the submission RED - going concern qualification, SIC code 6159 in the excluded financial services range, 12 claims in 3 years exceeding the guideline maximum of 5.

**Appetite Assessment:**
The appetite agent retrieves the GL underwriting guidelines and compares each criterion against the submission. It determines OUTSIDE APPETITE, citing three disqualifying factors: excluded SIC code (guideline section 4.1), going concern (section 4.3), and excessive claims frequency (section 6.1).

### Step 4: Every Decision is Logged

Verity creates 4 decision log entries - one per pipeline step. Each entry captures:

- The exact agent version and prompt versions used
- The complete inference config (model, temperature, max tokens)
- Every tool call with inputs and outputs
- The full message history (for replay)
- The agent's output, reasoning, and confidence score
- Token counts and execution duration
- The execution context linking this to the Meridian submission

### Step 5: The Underwriter Reviews

The underwriter sees the RED risk score and the detailed reasoning. She disagrees - she knows Meridian's regulatory situation and believes the going concern will be resolved. She overrides the triage decision from RED to AMBER.

Verity logs the override with her name, role, reason code, the AI's original recommendation, and her decision. The audit trail now shows: AI recommended RED, senior underwriter overrode to AMBER, with documented rationale.

### Step 6: The Regulator Asks

Six months later, a market conduct examiner asks: "Show me how the Meridian Holdings submission was processed, including any AI involvement."

One query to Verity produces:

- The complete pipeline execution (4 steps, with exact versions)
- The AI's reasoning at each step (with confidence scores)
- The human override (with documented rationale)
- The exact prompt and model versions used (reproducible)
- The tool calls made and data retrieved
- The ground truth validation results for each agent version

This is not reconstructed from memory. It is a contemporaneous record produced by the system that made the decisions.

---

## Five Pillars of Governed AI

### 01 COMPOSE

Every agent, task, and prompt is a database record with a version, an owner, and an approval state. Nothing runs without being registered.

An underwriter cannot paste a new prompt into a text box and have it affect production decisions. A developer cannot change a temperature parameter without creating a new version. The governed registry is the single source of truth for what AI assets exist and what state they are in.

### 02 VERIFY

Before anything reaches production, it must pass test suites and ground truth validation. Verity tracks every validation run.

The document classifier was tested against 200 SME-labeled documents (50 per type) and achieved F1 = 0.95 before promotion. The triage agent was validated against 20 SME-scored submissions and met all metric thresholds (F1 >= 0.83, Cohen's kappa >= 0.75). These results are stored against the specific version - not in a spreadsheet, not in an email.

### 03 DEPLOY

The 7-state lifecycle is not process theater. It is an evidence trail. Every promotion gate has an approval record attached to it.

```
draft -> candidate -> staging -> shadow -> challenger -> champion -> deprecated
              |            |         |           |            |
              |            |         |           |            +-- Regulatory hold
              |            |         |           +-- A/B metrics reviewed
              |            |         +-- Shadow period: runs on live
              |            |             inputs, outputs not used
              |            +-- Staging tests passed, results reviewed
              +-- Development complete, similarity check passed
```

Each arrow is a promotion with an approval record: who approved, what evidence they reviewed, and their rationale. Fast-track is available for demo seeding (candidate -> champion), but production promotions go through the full sequence.

### 04 GOVERN

Every AI invocation is logged with the exact prompt version, inference config, input, output, tool calls, and duration. Human overrides are captured with reason codes.

This is not sampling. This is not opt-in. Every call to Claude that flows through Verity produces an immutable decision record. When a human disagrees with an AI decision and overrides it, the original AI recommendation and the human's decision are both preserved with full context.

### 05 COMPLY

When a regulator asks for your model inventory, or an auditor asks to see the decision trail for a declined submission - it is one report. On demand.

Verity's compliance layer does not generate new data. It presents the governance data that the other four pillars accumulated. Model inventory, model cards, override-rate analysis, adverse action audit trails, ground truth validation evidence - all queryable from the governed database.

---

## The Six Components

### 1. Asset Registry

Answers the first question regulators ask: what AI is in production, who owns it, and what version is live.

Every agent, task, prompt, inference config, and tool is stored as a versioned database record - not hidden in code. Each asset has a display name, a machine name, a materiality tier, and a champion pointer to its current production version.

The registry supports three resolution modes:
- **Default:** Returns the current champion version
- **Date-pinned:** Returns the version that was champion on a specific date (SCD Type 2 temporal)
- **Version-pinned:** Returns a specific version by ID (for replay and audit)

SR 11-7's model inventory requirement and the NAIC transparency principle both resolve to this component.

### 2. Lifecycle Framework

Enforces the change management discipline that agentic systems otherwise lack.

Every asset version moves through a defined sequence of 7 states - from draft through shadow deployment to champion - with human approval gates at the points that matter. The transitions are:

| Gate | Evidence Required |
|------|------------------|
| Candidate -> Staging | Description similarity check passed |
| Staging -> Shadow | Staging tests passed, results reviewed by approver |
| Shadow -> Challenger | Shadow period complete, metrics at parity |
| Challenger -> Champion | Ground truth validation passed, model card reviewed, challenger metrics reviewed |

A prompt change cannot reach production without the same controls applied to a code change. Version composition is immutable after promotion - the exact combination of prompts, config, and tools that was tested is the combination that runs.

### 3. Testing & Validation

Replaces ad-hoc demonstration with structured evidence.

**Test Suites:** Collections of test cases with defined inputs and expected outputs. Each test case specifies a metric type (classification F1, field accuracy, exact match, schema valid).

**Ground Truth Datasets:** SME-labeled data stored as three tables - dataset (metadata), record (input items), and annotation (labels from human SMEs or LLM judges). Multiple annotators per record are supported for gold-tier datasets. Inter-annotator agreement is computed and tracked.

**Validation Runs:** Execute an agent version against every record in a ground truth dataset. Compare outputs to authoritative annotations. Compute aggregate metrics (precision, recall, F1, Cohen's kappa for classification; per-field accuracy for extraction). Check against metric thresholds. Store per-record results for drill-down.

Colorado SB21-169's bias testing requirement and SR 11-7's independent validation requirement both have a direct answer here.

### 4. Execution Control

Ensures that what runs in production is exactly what governance approved.

At runtime, the framework pulls the current champion configuration from the governed registry. The resolved config includes the exact prompt versions, inference parameters, and tool authorizations that were validated and promoted through the lifecycle.

Agents can access only authorized tools. Inference parameters cannot be changed at runtime. Mock mode allows testing with controlled inputs without touching production systems.

**Deployment model options:**
- **Embedded SDK:** Verity executes agents directly (current)
- **Governance Sidecar:** External orchestrator executes, Verity governs and logs (future)

### 5. Decision Logging

Produces the contemporaneous record that the NAIC explainability requirement and Colorado's adverse-action provisions demand.

Every AI invocation is logged with:
- The exact prompt version and inference config used
- Complete input and output (JSON)
- Every tool call made (with inputs and outputs)
- Full message history (for multi-turn agents)
- Token counts, duration, and model used
- The execution context (business operation link)
- The run purpose (production, test, validation, audit rerun)
- Mock mode flag

Human overrides are captured as a separate record linked to the original AI decision, with the overrider's identity, role, reason code, the AI's recommendation, and the human's decision.

When a market conduct examiner asks how a specific decision was made, the answer is a query, not a reconstruction.

### 6. Compliance & Reporting

Makes the governance data useful to the people who need it.

- **Model Inventory Report:** All champion agents and tasks with version, materiality tier, validation status, override rate, and last review date
- **Model Cards:** Per-entity documentation of purpose, design rationale, known limitations, conditions of use, and validation evidence
- **Audit Trail:** Complete decision chain for any business operation, showing every AI step with exact versions, reasoning, and outcomes
- **Override Analysis:** Override rates by entity, trends over time, and pattern flags
- **Regulatory Evidence Packages:** Generated on demand from the records the other five components accumulate

These reports are not assembled manually when the examination notice arrives. They are generated from live governance data at any time.

---

## Full Feature List: Verity All-In

### Asset Registry

- Agent registration with display name, materiality tier, description
- Task registration with capability type (classification, extraction, generation, matching, validation)
- Prompt registration with governance tier (behavioural, contextual, formatting)
- Prompt version management with 3-part versioning (major.minor.patch)
- Template variable auto-extraction and validation at execution time
- Inference config management (model, temperature, max tokens, extended params)
- Tool registration with input/output schemas, data classification, write flag
- Pipeline registration with ordered steps, dependencies, and error policies
- Application registration (multi-tenant: UW app, Claims app, etc.)
- Entity-to-application mapping
- Version composition: prompts + config + tools bound to agent/task versions
- Champion pointer resolution (current, date-pinned, version-pinned)
- SCD Type 2 temporal version management

### Lifecycle Framework

- 7-state lifecycle: draft, candidate, staging, shadow, challenger, champion, deprecated
- Configurable promotion gates per materiality tier
- HITL approval records with evidence review checkboxes
- Gate requirements: staging tests passed, ground truth validated, model card reviewed, fairness analysis reviewed, shadow metrics reviewed, challenger metrics reviewed
- Rollback capability (deprecate champion, restore prior)
- Fast-track promotion for seeding (candidate -> champion)
- Lifecycle state to deployment channel mapping

### Testing & Validation

- Test suite management (per entity, multiple suite types)
- Test case management with input data, expected output, metric type
- Test execution with mock mode support
- Ground truth dataset management (three-table: dataset, record, annotation)
- Multi-annotator support (human SME, LLM judge, adjudicator)
- Inter-annotator agreement computation
- Annotation lineage and correction tracking
- Validation runner: execute entity against ground truth, compute metrics
- Per-record validation results for drill-down
- Metric threshold management (aggregate and per-field)
- Field extraction tolerance configuration
- Metrics computation: F1, precision, recall, Cohen's kappa, field accuracy

### Execution Control

- Multi-turn agentic loop with tool calling
- Single-turn structured output (task mode)
- Tool authorization enforcement
- Prompt assembly with template variable substitution and validation
- Conditional prompt inclusion
- MockContext: mock LLM responses, mock tool responses, replay from prior execution
- Pipeline execution with dependency resolution and parallel groups
- Execution context management (business operation grouping)
- Run purpose tracking (production, test, validation, audit rerun)
- Reproduced-from linking for audit reruns

### Decision Logging

- Immutable decision log for every AI invocation
- Full inference config snapshot (not just config ID)
- Prompt version tracking (exact versions used)
- Complete input/output capture
- Tool call recording (name, input, output per call)
- Message history for multi-turn replay
- Token usage and duration tracking
- Execution context linking
- Pipeline run grouping
- Override logging with AI recommendation and human decision
- Override reason codes and rationale

### Compliance & Reporting

- Dashboard with asset counts, decision trends, override trends
- Model inventory report (all champions with status)
- Model cards (purpose, limitations, validation evidence)
- Audit trail by pipeline run ID or execution context
- Override analysis (rate, trends, patterns)
- Description similarity checking (pgvector embeddings)
- Incident tracking with rollback records

### Governance Applications

- AI Operations (test suite execution, regression testing)
- Model Validation (independent ground truth validation for promotion gates)
- Compliance & Audit (audit reruns, regulatory reproduction)

### Admin Web UI

- Dashboard with 7 interactive charts (assets, decisions, pipelines, overrides)
- Registry pages: Agents, Tasks, Prompts, Configs, Tools, Pipelines, Applications
- Detail pages for every entity with version history
- Decision log browser with pagination
- Pipeline runs viewer
- HITL override viewer
- Audit trail viewer (by pipeline run or execution context)
- Model inventory page
- Lifecycle management page (in development)
- Test status page (in development)
- Ground truth management page (in development)

### Integration

- Python SDK (pip-installable package)
- REST API (planned)
- Tool registration (function pointer or HTTP callback)
- Storage-abstracted document references (MinIO, S3, Azure Blob)
- Multi-database architecture (verity_db, pas_db, edms_db)
- Docker-based deployment (separate containers per service)

---

## Shared Services

### EDMS (Enterprise Document Management System)

Independent service for document storage, text extraction, metadata management, and governance.

- **Collection-based storage:** Documents organized into governed collections that map to MinIO buckets. Collections carry lifecycle status, default tags, and ownership.
- **Virtual folder hierarchy:** Folders within collections for organizational structure. Tag inheritance: collection defaults -> folder defaults -> document tags (overrideable at each level).
- **Document lineage:** Parent-child transformation tracking. When text is extracted from a PDF, both the original and the extracted text are tracked as separate documents with a lineage record.
- **Tag governance:** Controlled vocabulary for tag keys and values. Restricted tags (sensitivity, category, LOB) only accept predefined values. Freetext tags for flexible annotation.
- **Document type governance:** Two-level hierarchy (type -> subtype). Classifier agents output types from this governed list.
- **Context type governance:** Controlled context types (submission, policy, claim, etc.) as dropdown, not freetext.
- **Task tracking:** Every operation (text extraction, OCR) tracked with lifecycle (pending, running, complete, failed), duration, and results.
- **REST APIs:** Full CRUD for documents, collections, folders, governance definitions.
- **Web UI:** Browse, upload, extract, classify, manage tags/types/folders/collections.

### MDM (Master Data Management) - Future

Entity resolution, golden record management, matching rules.

### Enrichment Services - Future

LexisNexis litigation and regulatory data, D&B financial scores, PitchBook company intelligence.

---

## Technical Architecture

```
+------------------------------------------------------------------+
|                        Docker Compose                             |
|                                                                   |
|  +------------+  +--------+  +-------+  +--------+  +---------+  |
|  | PostgreSQL |  | MinIO  |  | EDMS  |  | Verity |  | UW Demo |  |
|  | (pg16 +    |  | Object |  | :8002 |  | :8000  |  | :8001   |  |
|  |  pgvector) |  | Store  |  |       |  |        |  |         |  |
|  |            |  |        |  | Own DB|  | Own DB |  | Uses    |  |
|  | verity_db  |  | Buckets|  | edms_ |  | verity_|  | Verity  |  |
|  | uw_db      |  |        |  | db    |  | db     |  | SDK +   |  |
|  | edms_db    |  |        |  |       |  |        |  | EDMS    |  |
|  +------------+  +--------+  +-------+  +--------+  | Client  |  |
|                                                      +---------+  |
+------------------------------------------------------------------+
```

### Technology Stack

- **Backend:** Python 3.12, FastAPI, psycopg v3 (async)
- **Database:** PostgreSQL 16 with pgvector, raw SQL (no ORM)
- **Object Storage:** MinIO (S3-compatible)
- **AI:** Anthropic Claude (AsyncAnthropic client)
- **Frontend:** Jinja2 + HTMX + Tailwind CSS (server-rendered, no npm)
- **Data Models:** Pydantic v2
- **Deployment:** Docker Compose

### Design Principles

1. **No ORM.** Raw SQL in .sql files with Pydantic models. Transparent, debuggable, auditable.
2. **Verity knows nothing about insurance.** Business logic belongs in the consuming application.
3. **Every AI invocation is logged.** No exceptions, no sampling, no opt-out.
4. **Version composition is immutable.** What was tested is what runs.
5. **Schema-first.** The database schema is the source of truth, built complete from day one.
6. **Shared services are independent.** EDMS, MDM, enrichment each own their database and APIs.

---

*PremiumIQ Verity - Because the decisions your AI makes deserve the same governance as the decisions your people make.*
