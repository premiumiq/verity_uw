# PremiumIQ Verity

**The governance infrastructure that AI applications run on.** Compliant, auditable, and built for regulated industries — starting with P&C insurance.

> *"Application X, powered by Verity"* — your business app contains the domain logic; Verity contains the governance, audit, and compliance.

---

## The Problem

Agentic AI is taking on consequential decisions across underwriting and claims at unprecedented speed and scale. An agent can triage a submission, assess appetite against guidelines, extract fields from application forms, and route a risk — all in seconds.

But speed without accountability is a liability.

When a regulator asks why a submission was declined, when an auditor wants to see which model version was running on a specific date, when a compliance officer needs to prove that a prompt change went through proper review — the answer cannot be *"let me check with the engineering team."*

Accountability for AI decisions must be **engineered into the systems that support them**. Organizations that adopt agentic AI with confidence are the ones that made governance foundational, not remedial.

---

## What Verity Is

A metamodel-driven framework for deploying, testing, validating, and governing agentic AI in regulated environments. Verity is **not an AI application** — it is the substrate that AI applications run on.

```
┌──────────────────────────────────────────────────────────────────┐
│                     BUSINESS APPLICATIONS                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │ Underwriting │  │  Claims      │  │  Renewal     │  ...       │
│  │  Domain logic│  │  Domain logic│  │  Domain logic│            │
│  │  UI/Workflow │  │  UI/Workflow │  │  UI/Workflow │            │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘            │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │ register & invoke│                  │
          ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                  VERITY GOVERNANCE PLATFORM     (port 8000)       │
│                                                                   │
│  ── shipped ────────────────────────────────────────────────      │
│  Asset Registry · Lifecycle · Testing & Validation · Decision     │
│  Logging · Execution Engine · Model Mgmt · Quotas · Compliance    │
│         Admin UI  ·  REST API  ·  Python SDK  ·  Worker           │
│                                                                   │
│  ── future ─────────────────────────────────────────────────      │
│   Verity Agents (drift detection · lifecycle init · HITL valid.)  │
│   Verity Studio (Compose AI · Lifecycle · Ground Truth · Tests UI)│
└─────────┬──────────────────────────────────────┬─────────────────┘
          │ governed tool calls                  │
          ▼                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│                       SHARED SERVICES                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │   [Vault]    │  │  MDM         │  │  Enrichment  │            │
│  │   (port 8002)│  │  (future)    │  │  (future)    │            │
│  │  Documents   │  │  Entity      │  │  LexisNexis, │            │
│  │  + lineage   │  │  resolution  │  │  D&B, etc.   │            │
│  └──────────────┘  └──────────────┘  └──────────────┘            │
└──────────────────────────────────────────────────────────────────┘
```

**Business apps own** the domain — what a D&O submission looks like, what tools an underwriter needs, the workflow shape. They register their agents, tasks, and prompts with Verity, then call Verity to execute them.

**Verity governs everything** — stores the agent definitions, manages their lifecycle, executes them (or delegates execution to an external orchestrator), logs every decision, and provides the compliance reporting layer. **Verity knows nothing about insurance** — it knows about AI governance.

**Shared services are independent** — [Vault][vault] stores documents. MDM (future) resolves entities. Enrichment (future) provides external data. Verity governs the tool calls that reach these services but never connects to them directly.

---

## The Four Planes

Verity is organized into four logical planes. Two are shipped today; two are on the roadmap.

### 1. Verity Governance — *shipped*

The authoritative store and the decision-making surface. Owns the [Asset Registry][asset-registry], the [lifecycle state machine][lifecycle-state], the [Testing & Validation][validation-run] framework, the [decision log][decision-log] reader, the reporting layer, [model management][model-card], [quotas][quota], and the Admin UI.

It answers questions like: *Which version of `triage_agent` is champion? What did the validation run against this version show? How much did `uw_demo` spend on Claude Sonnet last week? Which decisions ran under prompt version `v2.1.0`?*

The Governance plane does not call LLMs. It does not execute tools. It does not loop. **It records, enforces, and reports.**

### 2. Verity Runtime — *shipped*

The execution surface. Owns two execution units — [Tasks][task] (single LLM call with structured output) and [Agents][agent] (the agentic loop with tool calling and [sub-agent delegation][sub-agent-delegation]) — plus the connector layer that resolves declared input [source bindings][source-binding] and fires declared output [write targets][write-target], the MCP client, the model invocation log, and the [decision log][decision-log] writer.

When a business app calls `verity.execute_task(...)` or `verity.execute_agent(...)`, the Runtime resolves the champion version from Governance, fetches data via connectors at execution time, assembles the prompt, calls the LLM, handles the tool-use loop if any, fires declared writes after the output, and — as a non-negotiable side effect — writes one decision-log entry per invocation.

**Constrained by Governance:** inference parameters come from the resolved config, tool calls are checked against the authorization list, and every call increments the model invocation log used for usage and spend.

### 3. Verity Agents — *future*

Governance-plane agents that automate three capabilities that today require a human to notice, initiate, and drive:

- **Drift detection** — continuously analyze the [decision log][decision-log] against ground-truth baselines for distribution shift, accuracy regression, and override-rate anomalies. Open an [incident][incident] when drift crosses a threshold.
- **Lifecycle initiation** — when drift or a failing validation warrants a new version, draft a candidate (cloned from the current champion) and kick off the promotion sequence.
- **Validation with HITL gates** — run validation suites against candidate versions, route results to the designated SME, and only advance the version through `staging → shadow → challenger → champion` after each gate is signed off.

Verity Agents will themselves be Verity-governed agents — registered, versioned, validated, decision-logged. **The governance system governing itself.** The scaffolding is already in place ([incidents][incident], [validation runs][validation-run], [HITL][approval-record], the 7-state [lifecycle][lifecycle-state], clone-and-edit authoring) — the agents are next. See [enhancements/verity-agents.md](docs/enhancements/verity-agents.md).

### 4. Verity Studio — *future, not yet designed*

A UI-driven authoring surface that lets non-developer users (underwriters, compliance officers, governance reviewers, SMEs) compose and govern AI assets without writing code. Today, registering an Agent, wiring its source bindings, building test cases, uploading ground-truth data, and driving the lifecycle all require Python scripts. **Studio is what makes Verity usable beyond the engineering team.**

Initial scope:

- **Compose AI** — visual authoring for Agents, Tasks, Prompts, Inference Configs, Tools, Connectors; reference-grammar autocomplete; source-binding / write-target wiring panels; sub-agent delegation graph
- **Lifecycle Management** — promotion workflow with evidence checklists, HITL approval routing, clone-and-edit with composition diff, rollback
- **Ground Truth Management** — dataset upload, annotator assignment, IAA dashboard, gold-label resolution
- **Test Management** — suite builder per [capability type][validation-run], expected-output editor, mock-fixture builder

Studio is a thick frontend over the existing Verity REST API — no new backend capabilities required initially; everything Studio writes goes through the same governance writes (so audit, lifecycle, and validation gates apply uniformly to UI-driven and SDK-driven changes). Design isn't started. See [enhancements/verity-studio.md](docs/enhancements/verity-studio.md).

---

## The Metamodel

Verity's substrate is a relational metamodel — every governed thing is a versioned database record. Six logical clusters group ~50 tables:

| Cluster | What it stores |
|---|---|
| **Application Registry** | Consuming apps + scoping mappings |
| **Asset Registry** | Agents, Tasks, Prompts, Tools, [Inference Configs][inference-config], wiring (source bindings, write targets), [delegations][sub-agent-delegation] |
| **Lifecycle & Approval** | 7-state lifecycle history + [HITL approval][approval-record] records + [overrides][override-log] |
| **Execution & Decisions** | Event-sourced [run lifecycle][execution-run] + [decision log][decision-log] + telemetry |
| **Testing & Validation** | Test suites, [ground-truth datasets][ground-truth-dataset], [validation runs][validation-run] |
| **Compliance & Docs** | [Model cards][model-card] + derived evidence (SR 11-7 / NAIC / NIST packages) |

The conceptual model:

![Verity DB conceptual model](docs/diagrams/verity_db_conceptual_model.svg)

For depth see [docs/architecture/technical-design.md](docs/architecture/technical-design.md) and the [conceptual diagram source](docs/diagrams/verity_db_conceptual_model.d2).

---

## How Applications Work With Verity

The contract is simple and deliberate:

| Apps own | Verity owns |
|---|---|
| Domain knowledge (insurance rules, what a D&O submission looks like) | The metamodel of every governed entity |
| UI and user workflow | The [lifecycle][lifecycle-state], approvals, audit |
| **Composing** the assets (registering agents, tasks, prompts, [data connectors][data-connector]) | Resolving champion versions and frozen compositions at run time |
| **Orchestrating** multi-step workflows in plain Python | Executing one [Task][task] or [Agent][agent] per call and writing the audit |
| Tool implementations (Python functions or MCP servers) | Tool authorization + dispatch + decision-log capture |

**Verity executes one unit of work at a time.** Multi-step workflows are plain Python in your app, threading a caller-supplied [`workflow_run_id`][workflow-run-id] through every call so the audit clusters correctly:

```python
import uuid
from verity import VerityClient

verity = VerityClient(base_url="http://verity:8000")

# 1. Bind to a business operation (e.g. one submission)
ctx = await verity.create_execution_context(
    application="uw_demo",
    context_ref="submission:SUB-001",
)

# 2. One workflow → one correlation id
workflow_run_id = uuid.uuid4()

# 3. Iterate; each call writes its own decision-log row
for doc in submission_documents:
    classified = await verity.execute_task(
        task_name="document_classifier",
        input_data={"submission_id": "SUB-001", "documents": [doc]},
        execution_context_id=ctx.id,
        workflow_run_id=workflow_run_id,
    )
    if classified.output["document_type"] == "do_application":
        await verity.execute_task(
            task_name="field_extractor",
            input_data={"submission_id": "SUB-001", "documents": [doc]},
            execution_context_id=ctx.id,
            workflow_run_id=workflow_run_id,
        )
```

Every call produces: an [`execution_run`][execution-run] event chain, one [decision log][decision-log] row with frozen prompt versions and inference config, one model-invocation row per LLM call, plus per-binding source resolutions and per-target write records.

For the full developer surface — anatomy, composition handbook, orchestration patterns, mocking, error handling — see [docs/development/application-guide.md](docs/development/application-guide.md).

---

## What Goes In · What Comes Out

| Goes in | Comes out |
|---|---|
| Agent & Task definitions | Governed AI executions |
| Prompts (versioned) | [Decision logs][decision-log] (full snapshot per call) |
| [Inference configs][inference-config] | Audit trail per submission ([by execution context][execution-context]) |
| Tool registrations (in-process or MCP) | Model inventory report |
| [Test suites & ground truth][ground-truth-dataset] | Regulatory evidence packages |
| Application registrations | [Override & incident][override-log] logs |

---

## Vault — The Document Side App

[Vault][vault] is Verity's companion document service: collection-based storage on MinIO, document lineage tracking (original PDF → extracted text → derived JSON), governed tags (controlled-vocabulary keys/values plus freetext), document type and context type governance, and full CRUD via REST + Web UI.

It runs as a separate service ([port 8002][vault]) with its own database (`vault_db`). Verity reaches it through the canonical [`vault` data connector][data-connector] for declarative source binding (`fetch:vault/get_document_text(input.documents[0].id)`) and write targets (extracted-fields JSON written back as a lineage child of the source PDF).

Vault is the prototype shared service. MDM and Enrichment will follow the same pattern — independent service, own database, governed via tool calls and connectors. See [docs/apps/vault.md](docs/apps/vault.md) (coming) and [docs/enhancements/mdm-and-enrichment.md](docs/enhancements/mdm-and-enrichment.md).

> **Naming note:** Vault is renamed from the legacy "EDMS" name in this docs pass. The code-level rename (env vars `EDMS_URL` → `VAULT_URL`, directory `edms/` → `vault/`, etc.) is tracked as Phase 0 of [docs/enhancements/production-readiness-k8s.md](docs/enhancements/production-readiness-k8s.md).

---

## End-to-End Example

To see every piece in motion, walk through one D&O submission from broker upload to regulator audit query, with sequence diagrams, JSON contracts, status transitions, and a final summary table of every row written to the database:

→ **[docs/example-end-to-end.md](docs/example-end-to-end.md)**

Six phases: ingestion (Vault) · per-document classify+extract workflow · multi-agent risk-assessment workflow with sub-agent delegation · underwriter override · regulator audit query · audit replay. The whole flow ends in one SQL query against `execution_context_id` returning the complete decision chain — exactly the contemporaneous record SR 11-7, NAIC, and Colorado SB21-169 expect.

---

## Architecture Overview

- **[docs/vision.md](docs/vision.md)** — exec-facing narrative, three-layer framing, the five capabilities (compose / verify / deploy / govern / comply), full feature list with status
- **[docs/architecture/technical-design.md](docs/architecture/technical-design.md)** — every component in depth (~2500 lines), data layer, model layer, web layer, key flows
- **[docs/architecture/execution.md](docs/architecture/execution.md)** — Task & Agent contracts, the four-pattern reference grammar, async run lifecycle
- **[docs/architecture/decision-logging.md](docs/architecture/decision-logging.md)** — what gets logged at what level
- **[docs/architecture/decisions.md](docs/architecture/decisions.md)** — ADR log
- **[docs/diagrams/verity_db_conceptual_model.svg](docs/diagrams/verity_db_conceptual_model.svg)** — the metamodel as a single picture

---

## Getting Started

```bash
git clone <this-repo>
cd verity_uw
cp .env.example .env                # edit ANTHROPIC_API_KEY at minimum
docker compose up -d
```

Services come up at:

| Service | Port | What |
|---|---|---|
| `postgres` | 5432 | `verity_db`, `vault_db`, `pas_db` |
| `minio` | 9000 / 9001 | Object store (UI on 9001) |
| `vault` | 8002 | Document side app |
| `verity` | 8000 | Governance + Runtime + Admin UI |
| `uw_demo` | 8001 | Reference UW application |
| `ds_workbench` | 8888 | JupyterLab against Verity REST API |

Open http://localhost:8000 for the Verity Admin UI, http://localhost:8001 for the UW demo. For the full setup walkthrough including database seed, see [docs/guides/initial_setup.md](docs/guides/initial_setup.md). For your second day on Verity, the [Application Developer Guide](docs/development/application-guide.md) is the next read.

---

## Documentation Map

```
README.md                            ← you are here
CLAUDE.md                            ← Claude Code operating instructions for this repo

docs/
├── VERITY_COMBINED_PRD_v3.md        canonical PRD (frozen)
├── vision.md                        exec-facing narrative
├── documentation-guide.md           how this docs tree is organized + writing conventions
├── example-end-to-end.md            D&O walkthrough (recommended second read)
│
├── architecture/                    technical reference
│   ├── technical-design.md          every component in depth
│   ├── execution.md                 Task / Agent / I/O grammar
│   ├── decision-logging.md          what gets logged at what level
│   ├── logging.md                   operational logs
│   └── decisions.md                 ADR log
│
├── development/                     application developer reference
│   ├── application-guide.md         anatomy + composition + orchestration (single doc with TOC)
│   └── web-ui-design.md             admin UI conventions
│
├── apps/                            companion applications
│   ├── vault.md                     Vault (document store)
│   ├── uw-demo.md                   UW demo reference app
│   └── ds-workbench.md              JupyterLab data-science workbench
│
├── api/
│   └── api_and_ds_workbench.md      REST API + DS Workbench notes
│
├── guides/                          operational how-tos
│   ├── initial_setup.md
│   ├── running_apps.md
│   ├── live_execution.md
│   ├── seed_data_validation.md
│   └── web_ui_validation.md
│
├── enhancements/                    designed-but-not-built capabilities
│   ├── README.md                    categorized index with status tags
│   └── *.md                         one file per enhancement (15 files)
│
├── glossary/                        term-per-file vocabulary
│   ├── README.md                    alphabetical index
│   └── *.md                         48 terms
│
├── diagrams/                        Excalidraw / D2 / SVG sources
└── archive/                         historical plans (kept for traceability)
```

Conventions are documented in [docs/documentation-guide.md](docs/documentation-guide.md) — file naming, linking, tooltips, diagrams, archive policy, when to add a glossary term.

---

## Future Enhancements

The next set of capabilities, with status. See [docs/enhancements/README.md](docs/enhancements/README.md) for the categorized index.

- **[Production readiness + K8s migration](docs/enhancements/production-readiness-k8s.md)** — full plan to take Verity + Vault from local Docker Compose to a Kubernetes deployment with per-service Dockerfiles, runtime extraction, optional NATS dispatch, Helm chart, and observability stack
- **[Verity Agents](docs/enhancements/verity-agents.md)** — drift detection · lifecycle initiation · validation-with-HITL agents
- **[Verity Studio](docs/enhancements/verity-studio.md)** — UI-driven Compose AI · Lifecycle · Ground Truth · Test Management for non-developer users
- **[Tool versioning](docs/enhancements/tool-versioning.md)** — close the last gap in version-composition immutability
- **[Hard quotas](docs/enhancements/hard-quotas.md)** — runtime enforcement, scheduled checker, Slack/email notifications
- **[REST API auth](docs/enhancements/rest-api-auth.md)** — API keys + OIDC for any non-localhost deployment
- **[Sidecar topology](docs/enhancements/sidecar-topology.md)** — governance-as-sidecar for external orchestrators (LangGraph, CrewAI, Bedrock)
- **[Streaming events](docs/enhancements/streaming-events.md)** — wire `ExecutionEvent` to the Admin UI
- **[MDM + Enrichment](docs/enhancements/mdm-and-enrichment.md)** — future shared services alongside Vault

15 enhancement files in total. Each has status (`planned` / `partial` / `designed`), priority, sketch of the approach, acceptance criteria, and notes.

---

## Project Status

Demo-stage, single-process Docker Compose deployment. Under active development; targeting v0.1.0 as the first taggable milestone. Reference application is `uw_demo` (commercial D&O underwriting). Production deployment plan is documented but not yet executed.

## License

(TBD — to be added with the v0.1.0 tag.)

---

<!-- ─────────────────────── Glossary references ─────────────────────────────── -->
<!-- Hover the linked terms above to see a tooltip; click to read the full glossary entry.  -->
<!-- These references are kept in sync with docs/glossary/*.md.  Update both when a term     -->
<!-- definition changes (a sync script will land later — see docs/documentation-guide.md).  -->

[asset-registry]: docs/glossary/asset-registry.md "Verity Governance subsystem storing every governed entity as a versioned database record."
[lifecycle-state]: docs/glossary/lifecycle-state.md "Seven states an entity version moves through: draft → candidate → staging → shadow → challenger → champion → deprecated."
[validation-run]: docs/glossary/validation-run.md "Execution of an entity version against every record in a ground-truth dataset; computes aggregate metrics, gates staging→shadow."
[decision-log]: docs/glossary/decision-log.md "One immutable row per AI invocation in agent_decision_log capturing prompts, config, I/O, tool calls, tokens, durations."
[model-card]: docs/glossary/model-card.md "Per-entity documentation of purpose, design, limitations, conditions of use, validation evidence (SR 11-7 style)."
[quota]: docs/glossary/quota.md "Spend or invocation-count budget scoped by application/model/entity over a rolling time window."
[task]: docs/glossary/task.md "Single-shot LLM call with input_schema → structured output_schema. No tool loop, no sub-agents."
[agent]: docs/glossary/agent.md "Multi-turn agentic loop with tool use and (optionally) sub-agent delegation. Authorized tools per version."
[sub-agent-delegation]: docs/glossary/sub-agent-delegation.md "Built-in delegate_to_agent meta-tool; parent → child relationships authorized via agent_version_delegation."
[source-binding]: docs/glossary/source-binding.md "Declarative input I/O row defining what to fetch and where to put it."
[write-target]: docs/glossary/write-target.md "Declarative output I/O row describing where to write the LLM output."
[incident]: docs/glossary/incident.md "Production triage row: legacy incidents + active quota breaches."
[approval-record]: docs/glossary/approval-record.md "Per-promotion-gate sign-off row: who approved, what evidence reviewed, rationale."
[ground-truth-dataset]: docs/glossary/ground-truth-dataset.md "SME-labeled data scoped to one governed entity. Three tables: dataset, record, annotation."
[inference-config]: docs/glossary/inference-config.md "Versioned LLM API parameter set: model, temperature, max_tokens, extended_params. Frozen on entity version promotion."
[override-log]: docs/glossary/override-log.md "Separate immutable record of a human disagreeing with an AI decision; preserves both AI recommendation and human decision."
[execution-run]: docs/glossary/execution-run.md "Event-sourced record of one Task or Agent invocation; lifecycle events live in execution_run_status."
[execution-context]: docs/glossary/execution-context.md "Business-level grouping registered by the consuming app; opaque to Verity. Scopes runs to a customer-facing operation (e.g. submission)."
[workflow-run-id]: docs/glossary/workflow-run-id.md "Caller-supplied UUID threaded through every execute_* call in one workflow so the audit clusters correctly."
[data-connector]: docs/glossary/data-connector.md "Registered integration providing fetch/write methods used by source_bindings and write_targets. Vault is the canonical example."
[vault]: docs/glossary/vault.md "Companion document service (collections, lineage, tags, text extraction). Independent DB. Verity reaches it via the canonical data_connector."
