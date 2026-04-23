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
|  +------------+  +-----------+  +-----------+  +---------------+  |
|  | Execution  |  | Model     |  | Quotas &  |  | Compliance    |  |
|  | Control    |  | Mgmt      |  | Incidents |  | Reporting     |  |
|  +------------+  +-----------+  +-----------+  +---------------+  |
|  +----------------------------------------------------------------+|
|  | Governance Admin UI + REST API + DS Workbench                  ||
|  +----------------------------------------------------------------+|
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
| Which model was used, what it cost, who paid | Verity (Model Management, Usage & Spend) |
| When an application is over budget | Verity (Quotas & Incidents) |
| What the D&O underwriting guidelines say | Business App (domain knowledge) |
| How to extract text from a PDF | EDMS (shared service) |
| What company "Acme Corp" maps to in the golden record | MDM (shared service) |

---

## Governance, Runtime, and Agents

Internally, Verity is organized into three planes. Two are implemented today. The third is a roadmap extension that builds on the first two.

### 1. Verity Governance (shipped)

The authoritative store and the decision-making surface. It owns the registry, the lifecycle state machine, the testing and validation framework, the decision log reader, the reporting layer, model management, quotas, and the admin UI.

It answers questions like: *Which version of `triage_agent` is champion? What did the validation run against this version show? How much did the `uw_demo` application spend on Claude Sonnet last week? Which decisions ran under prompt version `v2.1.0`?*

The Governance plane does not call LLMs. It does not execute tools. It does not loop. It records, enforces, and reports.

### 2. Verity Runtime (shipped)

The execution surface. It owns the agentic loop, tool calling, pipeline execution, sub-agent delegation, MCP client, the model invocation log, and the decision log writer.

When the business app calls `verity.execution.run_agent(...)`, the Runtime resolves the champion version from Governance, assembles the prompt and tool authorizations, calls the LLM, handles the tool-use loop, and - as a non-negotiable side effect - writes one decision log entry per invocation.

The Runtime plane is constrained by Governance: inference parameters are pulled from the resolved config, tool calls are checked against the authorization list, and every call increments the model invocation log used for usage and spend.

### 3. Verity Agents (future)

Governance-plane agents that automate three capabilities that today require a human to notice, initiate, and drive:

- **Drift detection.** Continuously analyse the decision log against ground truth baselines for distribution shift, accuracy regression, and override-rate anomalies. When drift crosses a threshold, open an incident and notify the owner.
- **Lifecycle initiation.** When drift or a failing validation run warrants a new version, draft a candidate version (cloned from the current champion) and kick off the promotion sequence with a pre-filled change summary describing the observed drift.
- **Validation with HITL gates.** Run validation suites against candidate versions, route results to the designated SME for review, and only advance the version through `staging -> shadow -> challenger -> champion` after each HITL gate is signed off.

Verity Agents will themselves be Verity-governed agents - registered, versioned, validated, decision-logged. The governance system governing itself. The scaffolding they require (incidents, validation runs, HITL overrides, the 7-state lifecycle, the clone-and-edit workflow) is already in place.

### Deployment Topologies

**In-process (current).** Governance and Runtime live in the same FastAPI process. The business app imports the Verity SDK and calls Runtime methods directly. Governance and Runtime communicate in-process through the `Coordinator`.

```
+------------------------------------------+
| Business Application Process             |
|                                          |
|  Business Logic                          |
|       |                                  |
|       v                                  |
|  +------------------+                    |
|  | Verity SDK       |                    |
|  |  Runtime:        |                    |
|  |   Execution      |----> Claude API    |
|  |   Pipeline       |                    |
|  |   Decisions(W)   |--+                 |
|  |                  |  |                 |
|  |  Governance:     |  |                 |
|  |   Registry       |<-+                 |
|  |   Lifecycle      |----> verity_db     |
|  |   Decisions(R)   |                    |
|  |   Reporting      |                    |
|  +------------------+                    |
|                                          |
+------------------------------------------+
```

**Governance as sidecar (future).** As agentic patterns grow more complex - multi-agent orchestration, long-running sessions, parallel tool calling - some teams will prefer commercial orchestration platforms (LangGraph, CrewAI, Amazon Bedrock Agents, Anthropic Agent SDK). In the sidecar topology, Verity Runtime steps out of the loop and Verity Governance becomes the governance layer that any orchestrator reports to:

```
+------------------------------------------+
| Business Application Process             |
|                                          |
|  Business Logic                          |
|       |                                  |
|       v                                  |
|  +------------------+    +-----------+   |
|  | External         |    | Verity    |   |
|  | Orchestrator     |--->| Governance|   |
|  | (LangGraph,      |    | Sidecar   |   |
|  |  CrewAI,         |    |           |   |
|  |  Bedrock, etc.)  |    | Registry  |   |
|  |                  |    | Lifecycle |   |
|  |  Executes agents |    | Decisions |   |
|  |  Calls tools     |    | Reporting |   |
|  |  Manages state   |    |           |   |
|  +------------------+    +-----------+   |
|       |                       |          |
|       v                       v          |
|    Claude API             verity_db      |
+------------------------------------------+
```

The orchestrator queries Governance for which version to run, gets back the resolved configuration, executes the agent, and reports the result back through the Governance Contract (next section). This topology is not implemented today, but the REST API surface (`/api/v1/*`) is designed to support it.

### The Governance Contract

Whether the Verity Runtime or an external orchestrator is doing the execution, every AI invocation must be reported to Governance through the same contract:

```
{
    id:                        UUID (caller-supplied, so parents can
                                     reference in-flight children)
    entity_type:               "agent" | "task"
    entity_version_id:         UUID
    prompt_version_ids:        [UUID, ...]
    inference_config_snapshot: {model, temperature, max_tokens, ...}
    channel:                   "production" | "staging" | "shadow" | ...
    mock_mode:                 bool

    pipeline_run_id:           UUID | null
    parent_decision_id:        UUID | null
    decision_depth:            int
    step_name:                 str | null

    input_summary:             str | null
    input_json:                {...} | null
    output_summary:            str | null
    output_json:               {...} | null
    reasoning_text:            str | null
    risk_factors:              [...] | null
    confidence_score:          float | null
    low_confidence_flag:       bool

    model_used:                "claude-sonnet-4-6"
    input_tokens:              int | null
    output_tokens:             int | null
    duration_ms:               int | null
    tool_calls_made:           [{name, input, output}, ...]
    message_history:           [{role, content}, ...]

    application:               str
    run_purpose:               "production" | "test" | "validation" |
                               "audit_rerun"
    reproduced_from_decision_id: UUID | null
    execution_context_id:      UUID | null
    hitl_required:             bool
    status:                    "complete" | "failed" | ...
    error_message:             str | null
}
```

This is the hard requirement. Anything that executes agents under the Verity governance umbrella must produce this record. Everything else - the orchestration framework, the LLM provider, the tooling - is flexible.

---

## Verity in Action: Commercial Underwriting

### The Scenario

A commercial insurance submission arrives for a financial services company applying for General Liability coverage. The underwriting application - powered by Verity - processes it through two governed pipelines.

### Step 1: Documents Enter the System

The broker uploads an ACORD 125 application form and a loss run report to the EDMS. EDMS stores the files in MinIO, extracts text from each document, and tracks the lineage (original PDF -> extracted text).

```
Broker uploads documents
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

### Step 2: The Document-Processing Pipeline Runs

The underwriting app creates an execution context in Verity (`context_ref="submission:SUB-001"`) and triggers the `uw_document_processing` pipeline. Verity Governance resolves the champion version of each step; Verity Runtime executes them in order.

```
UW App: run_pipeline("uw_document_processing", context=submission:SUB-001)
        |
        v
Governance: resolve champions
        - pipeline uw_document_processing v1
        - task document_classifier (champion)
        - task field_extractor (champion)
        |
        v
Runtime: execute 2 governed steps
        Step 1: classify_documents
                task = document_classifier (classification)
                input = each uploaded document's extracted text
                output = {document_type, confidence, classification_notes}
                -> one decision_log row per document + one
                   model_invocation_log row with token cost
        Step 2: extract_fields  (depends on classify_documents)
                task = field_extractor (extraction)
                input = the document classified as "gl_application"
                tool calls (governed): get_document_text()
                                       store_extraction_result()
                output = 20 structured fields + per-field confidence
        |
        v
pipeline_run row: status=running -> complete, steps_complete=2/2
```

### Step 3: The Risk-Assessment Pipeline Runs

Once fields are extracted and confirmed, the UW app triggers the `uw_risk_assessment` pipeline against the same execution context. This pipeline runs agents rather than single-turn tasks - they loop, call tools, and reason.

```
Runtime: execute 2 governed steps
        Step 1: triage_submission
                agent = triage_agent (materiality: high)
                tool calls (governed, every call authorized
                  against the version's tool authorization list):
                    get_submission_context(submission_id)
                    get_loss_history(submission_id)
                    get_enrichment_data(submission_id)
                    store_triage_result(...)  [write]
                output = {risk_score, routing, narrative, risk_factors}
        Step 2: assess_appetite  (depends on triage_submission,
                                  error_policy: continue_with_flag)
                agent = appetite_agent (materiality: high)
                tool calls: get_submission_context,
                            get_document_text (guidelines),
                            update_appetite_status [write]
                output = {appetite_determination, cited_sections, notes}
        |
        v
Every LLM call:   decision_log row + model_invocation_log row
Every tool call:  captured inside the decision's tool_calls_made
Sub-agents:       parent_decision_id set BEFORE the parent row is
                  written (id is caller-supplied), so the audit
                  trail graphs correctly
Cost:             joined through v_model_invocation_cost at point
                  in time (SCD-2 on model_price)
```

### Step 4: Every Decision is Logged

Verity writes a decision log entry per AI invocation - one per classified document, one per extraction, one per agent turn. Each entry captures:

- The exact agent version and prompt versions used
- The complete inference config snapshot (model, temperature, max_tokens)
- Every tool call with inputs and outputs
- The full message history (for replay)
- The agent's output, reasoning, confidence score, and risk factors
- Token counts (including prompt-cache hits) and execution duration
- The execution context linking this to the submission
- The application tag (`uw_demo`) for spend attribution
- The pipeline_run_id for end-to-end audit trails

In parallel, the `model_invocation_log` captures per-call model usage. Joined with `model_price` through `v_model_invocation_cost`, this powers the Usage & Spend dashboard and the soft quotas.

### Step 5: The Underwriter Reviews

The underwriter sees the triage output (risk_score, narrative, factors) and the appetite determination with its cited guideline sections. She disagrees with the triage assessment - she knows context the agent did not. She overrides the triage decision.

Verity logs the override with her name, role, reason code, the AI's original recommendation, and her decision. The audit trail now shows: AI recommended X, senior underwriter overrode to Y, with documented rationale.

### Step 6: The Regulator Asks

Six months later, a market conduct examiner asks: "Show me how submission SUB-001 was processed, including any AI involvement."

One query to Verity produces:

- The complete pipeline executions (both pipelines, all 4 steps, with exact versions and pipeline_run status)
- The AI's reasoning at each step (with confidence scores and risk factors)
- The human override (with documented rationale)
- The exact prompt, inference config, and tool authorizations in effect (reproducible via version-pinned resolve)
- Every tool call made and every data value retrieved
- The ground truth validation results for each agent version at promotion time
- The token and cost line items tied back to the `uw_demo` application

This is not reconstructed from memory. It is a contemporaneous record produced by the system that made the decisions.

---

## Five Capabilities We Expect from Governed AI

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

Verity's compliance layer does not generate new data. It presents the governance data that the other four pillars accumulated. Model inventory, model cards, override-rate analysis, adverse action audit trails, ground truth validation evidence, cost attribution by application and model - all queryable from the governed database.

---

## Components

### 1. Asset Registry (Governance)

Answers the first question regulators ask: what AI is in production, who owns it, and what version is live.

Every agent, task, prompt, inference config, tool, MCP server, and pipeline is stored as a versioned database record - not hidden in code. Each asset has a display name, a machine name, a materiality tier, and a champion pointer to its current production version.

The registry supports three resolution modes:
- **Default:** Returns the current champion version
- **Date-pinned:** Returns the version that was champion on a specific date (SCD Type 2 temporal)
- **Version-pinned:** Returns a specific version by ID (for replay and audit)

It also supports the clone-and-edit authoring workflow: clone any version into a new draft, PATCH fields, PUT replacements for prompt assignments / tool authorizations / delegations, then promote through the lifecycle. The new draft carries a `cloned_from_version_id` pointer for lineage.

SR 11-7's model inventory requirement and the NAIC transparency principle both resolve to this component.

### 2. Lifecycle Framework (Governance)

Enforces the change management discipline that agentic systems otherwise lack.

Every asset version moves through a defined sequence of 7 states - from draft through shadow deployment to champion - with human approval gates at the points that matter. The transitions are:

| Gate | Evidence Required |
|------|------------------|
| Candidate -> Staging | Description similarity check passed |
| Staging -> Shadow | Staging tests passed, results reviewed by approver |
| Shadow -> Challenger | Shadow period complete, metrics at parity |
| Challenger -> Champion | Ground truth validation passed, model card reviewed, challenger metrics reviewed |

A prompt change cannot reach production without the same controls applied to a code change. Version composition is immutable after promotion - the exact combination of prompts, config, and tools that was tested is the combination that runs.

### 3. Testing & Validation (Governance)

Replaces ad-hoc demonstration with structured evidence.

**Test Suites:** Collections of test cases with defined inputs and expected outputs. Each test case specifies a metric type (classification F1, field accuracy, exact match, schema valid). Tests gate `candidate -> staging`.

**Ground Truth Datasets:** SME-labeled data stored as three tables - dataset (metadata), record (input items), and annotation (labels from human SMEs or LLM judges). Multiple annotators per record are supported for gold-tier datasets. Inter-annotator agreement is computed and tracked.

**Validation Runs:** Execute an agent version against every record in a ground truth dataset. Compare outputs to authoritative annotations. Compute aggregate metrics (precision, recall, F1, Cohen's kappa for classification; per-field accuracy for extraction). Check against metric thresholds. Store per-record results for drill-down. Validation gates `staging -> champion`.

Colorado SB21-169's bias testing requirement and SR 11-7's independent validation requirement both have a direct answer here.

### 4. Execution Control (Runtime)

Ensures that what runs in production is exactly what governance approved.

At runtime, the engine pulls the current champion configuration from the governed registry. The resolved config includes the exact prompt versions, inference parameters, and tool authorizations that were validated and promoted through the lifecycle.

Agents can access only authorized tools. Inference parameters cannot be changed at runtime. Mock mode (driven by `FixtureEngine`) allows testing with controlled inputs without touching production systems. Sub-agent delegation is enforced against the caller version's delegation authorizations. MCP-served tools are invoked through a governed client that normalises them into the standard tool-call contract.

**Deployment topologies:**
- **In-process (current):** Verity Runtime executes agents directly inside the host process
- **Governance sidecar (future):** External orchestrator executes; Governance governs and logs via the Governance Contract

### 5. Decision Logging (Runtime writes, Governance reads)

Produces the contemporaneous record that the NAIC explainability requirement and Colorado's adverse-action provisions demand.

Every AI invocation is logged with:
- The exact prompt version and inference config used
- Complete input and output (JSON)
- Every tool call made (with inputs and outputs)
- Full message history (for multi-turn agents)
- Token counts (including prompt-cache hits), duration, and model used
- The execution context (business operation link)
- The application tag (for spend attribution)
- The pipeline_run_id and parent_decision_id (for end-to-end audit trails, including sub-agents)
- The run purpose (production, test, validation, audit rerun)
- Mock mode flag
- HITL-required flag

Human overrides are captured as a separate record linked to the original AI decision, with the overrider's identity, role, reason code, the AI's recommendation, and the human's decision.

When a market conduct examiner asks how a specific decision was made, the answer is a query, not a reconstruction.

### 6. Compliance & Reporting (Governance)

Makes the governance data useful to the people who need it.

- **Model Inventory Report:** All champion agents and tasks with version, materiality tier, validation status, override rate, and last review date
- **Model Cards:** Per-entity documentation of purpose, design rationale, known limitations, conditions of use, and validation evidence
- **Audit Trail:** Complete decision chain for any business operation, showing every AI step with exact versions, reasoning, and outcomes
- **Override Analysis:** Override rates by entity, trends over time, and pattern flags
- **Regulatory Evidence Packages:** Generated on demand from the records the other components accumulate

These reports are not assembled manually when the examination notice arrives. They are generated from live governance data at any time.

### 7. Model Management (Governance)

Tracks which foundation models are in use, what they cost, and what each application is spending.

- **Model registry:** Every model (Anthropic, OpenAI, etc.) registered with provider, display name, context window, default limits
- **Price history (SCD-2):** Each model carries a versioned price list with `effective_from`/`effective_to`; cost for a historical invocation is always computed against the price that was active at invocation time
- **Model invocation log:** One row per LLM call with input/output/cache tokens, duration, model_id, decision_log_id
- **Cost view (`v_model_invocation_cost`):** Point-in-time price-join view used by the Usage & Spend dashboard
- **Usage & Spend UI:** Cost-over-time chart, by-model breakdown, by-application breakdown, filterable by application and date range

### 8. Quotas & Incidents (Governance)

Soft-governance layer over usage and spend.

- **Quotas:** Spend or invocation-count budgets by application, model, or entity, over a rolling time window (daily, weekly, monthly)
- **On-demand checker:** Evaluates all active quotas against live usage, flags breaches, writes a quota_check row
- **Incidents page:** Unified view of the legacy `incident` table plus any active quota breaches - the starting point for operational triage
- **Future:** Hard quota enforcement at invocation time; scheduled checks; Slack/email notifications

### 9. Verity Agents (future)

Governance automation. Three agents, all themselves Verity-governed:

- **Drift detection agent** - watches decision log distributions and override rates against baselines, opens incidents on anomalies
- **Lifecycle initiation agent** - when drift or validation failure warrants a new version, clones the champion into a draft and starts the promotion sequence
- **Validation agent with HITL gates** - runs validation suites, routes results to designated SMEs, only advances a version after each HITL gate is signed off

The scaffolding they need - incidents, validation runs, HITL overrides, 7-state lifecycle, clone-and-edit authoring - already ships. The agents themselves are next.

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

## Full Feature List: Verity All-In

Status legend: **Shipped** = in production and exercised by the UW demo; **Partial** = implemented with follow-up scoped; **Coming** = designed, not yet built.

### Governance plane

| Capability | What it does | Status |
|---|---|---|
| Agent / task / prompt / inference-config / tool / MCP-server / pipeline registration | Versioned records with display name, materiality tier, ownership | Shipped |
| Application registration + entity-to-application mapping | Multi-tenant catalog; every decision is attributable to an application | Shipped |
| Version composition (prompts + config + tools + delegations) bound to agent / task versions | Immutable after promotion | Shipped |
| Champion resolution: current, date-pinned, version-pinned | SCD-2 temporal resolve | Shipped |
| Clone-and-edit authoring | `cloned_from_version_id` lineage; PATCH/PUT on drafts; draft-only guards on non-draft versions | Shipped |
| Sub-agent delegation authorizations (`agent_version_delegation`) | Parent may only delegate to authorized children | Shipped |
| 7-state lifecycle with promotion gates | draft -> candidate -> staging -> shadow -> challenger -> champion -> deprecated | Shipped |
| HITL approval records on promotions | Evidence-review checkboxes per gate | Shipped |
| Rollback (deprecate champion, restore prior) | | Shipped |
| Fast-track seeding (candidate -> champion) | For demo / initial load | Shipped |
| Test suite management (per entity, multiple suite types) | Cases with input, expected output, metric type | Shipped |
| Ground truth datasets (dataset / record / annotation tables) | Multi-annotator, IAA, lineage | Shipped |
| Validation runner | Execute entity version against ground truth, compute metrics, store per-record results | Shipped |
| Metric thresholds (aggregate + per-field) | Gate logic | Shipped |
| Metrics: F1, precision, recall, Cohen's kappa, per-field accuracy | | Shipped |
| Description similarity checking (pgvector embeddings) | Gate for candidate -> staging | Partial |
| Model registry + price history (SCD-2) | Provider, context window, effective dates on price | Shipped |
| Model invocation log | One row per LLM call, linked to decision_log | Shipped |
| Usage & spend (cost-over-time, by-model, by-application) | `v_model_invocation_cost` view, filterable UI, dashboard tile | Shipped |
| Soft quotas (application / model / entity / rolling window) | On-demand checker, quota_check history | Shipped |
| Incidents page (legacy incidents + active quota breaches) | Triage surface | Shipped |
| Hard quota enforcement at invocation time | | Coming |
| Scheduled quota checker + Slack / email notifications | | Coming |
| Decision log reader + detail view | Full I/O, tool calls, reasoning, message history, token cost | Shipped |
| Audit trail by pipeline_run_id and execution_context_id | | Shipped |
| Override logging (AI recommendation + human decision + reason code) | Separate record linked to original decision | Shipped |
| Override analysis (rate, trends) | | Shipped |
| Dashboard (assets, decisions, pipelines, overrides, cost this month) | Interactive charts | Shipped |
| Model inventory report | All champions with status | Shipped |
| Model cards | Purpose, limitations, validation evidence | Shipped |
| Regulatory evidence packages | Generated on demand | Partial |

### Runtime plane

| Capability | What it does | Status |
|---|---|---|
| Multi-turn agentic loop with tool calling | Anthropic AsyncAnthropic client | Shipped |
| Single-turn structured output (task mode) | Classification, extraction, generation, matching, validation | Shipped |
| Tool authorization enforcement | Checked per call against version's authorization list | Shipped |
| Prompt assembly with template-variable substitution + validation | Missing-variable errors at execution time | Shipped |
| Conditional prompt inclusion | Governance-tier-aware | Shipped |
| Pipeline executor | Dependency resolution, parallel groups, error policies (`fail_pipeline`, `continue_with_flag`) | Shipped |
| Pipeline run lifecycle (`pipeline_run` table, status: running / complete / partial / failed) | Accurate in-flight status with steps_complete tracking | Shipped |
| Sub-agent delegation at runtime | Parent-supplied decision id; `parent_decision_id`/`decision_depth` on child | Shipped |
| MCP client integration | External MCP servers exposed as governed tools | Shipped |
| MockContext / FixtureEngine | Mock LLM responses, mock tool responses, replay | Shipped |
| Execution context management | Business operation grouping | Shipped |
| Run purpose tracking (production / test / validation / audit_rerun) | | Shipped |
| Reproduced-from linking for audit reruns | `reproduced_from_decision_id` | Shipped |
| Prompt-cache token tracking | Separate counters for cache reads / creates | Shipped |
| Decision log writer | Non-negotiable side effect of every invocation | Shipped |
| Streaming execution events | `ExecutionEvent` contract present, end-to-end streaming to UI | Partial |
| Rate limiting + retry/backoff generalisation | | Coming |

### Verity Agents plane (future)

| Capability | What it does | Status |
|---|---|---|
| Drift detection agent | Watches decision distributions + override rates, opens incidents | Coming |
| Lifecycle initiation agent | Drafts candidate from champion on drift / validation failure, starts promotion | Coming |
| Validation agent with HITL gates | Routes validation outcomes to SMEs, advances version after sign-off | Coming |

### Integration & surfaces

| Surface | What it does | Status |
|---|---|---|
| Python SDK (`verity.*`: registry / lifecycle / execution / pipeline_executor / decisions / reporting / testing / models / quotas) | In-process governance + runtime access | Shipped |
| REST API at `/api/v1/*` (~78 operations: read / runtime / authoring / draft-edit / lifecycle / applications / models / usage / quotas / decisions / reporting) | Swagger UI at `/api/v1/docs`, OpenAPI at `/api/v1/openapi.json` | Shipped |
| Admin Web UI (Jinja + HTMX + Tailwind) | Dashboard, Registry pages, Observability (decisions, pipeline runs, overrides, usage & spend, quotas), Governance (inventory, lifecycle, testing, ground truth, validation runs, incidents), Settings | Shipped |
| Detail pages per entity with version history | | Shipped |
| Audit-trail viewer (by pipeline run / execution context) | | Shipped |
| Correlation IDs across services | Structured logging middleware | Shipped |
| DS Workbench (JupyterLab Docker service) | Capability walkthroughs over the REST API; `ds_workbench` registered as an application for self-clean-up | Shipped |
| Tool registration (function pointer or HTTP callback) | | Shipped |
| Storage-abstracted document references (MinIO / S3 / Azure Blob) | | Shipped |
| Multi-database architecture (verity_db, pas_db, edms_db) | | Shipped |
| Docker-based deployment (postgres, minio, edms, verity, uw-demo, ds-workbench) | | Shipped |
| REST API auth | | Coming |
| Governance-as-sidecar topology for external orchestrators | API surface supports it; orchestrator integrations not built | Coming |

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
|                                                                   |
|  +-----------------+                                              |
|  | DS Workbench    |                                              |
|  | :8888           |                                              |
|  | (JupyterLab,    |                                              |
|  |  talks to       |                                              |
|  |  Verity REST)   |                                              |
|  +-----------------+                                              |
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
6. **Governance and Runtime are separable.** Today they share a process; tomorrow Governance can run as a sidecar to an external orchestrator - the Governance Contract is the boundary.
7. **Shared services are independent.** EDMS, MDM, enrichment each own their database and APIs.
8. **Declarative over imperative.** Verity's governance primitives (schemas, sources/targets, quotas, thresholds, mock kinds) are stored in the metamodel and validated at admit time. Imperative extension mechanisms — e.g. pre/post execution hooks (FC-3) — are deliberately NOT offered; they would sit outside the metamodel, unversioned and invisible to governance reviewers. See [future_capabilities.md § FC-3](future_capabilities.md) for the full rationale.
9. **Orchestration lives in the application, not Verity.** Verity executes one unit of work at a time (Task, Agent, or Pipeline) and returns a canonical envelope. Triggers, chaining, waits, and retries across units are the consuming app's responsibility. See [verity_execution_architecture.md](verity_execution_architecture.md) for the full Task/Agent/Pipeline contracts and envelope spec.

---

*PremiumIQ Verity - Because the decisions your AI makes deserve the same governance as the decisions your people make.*
