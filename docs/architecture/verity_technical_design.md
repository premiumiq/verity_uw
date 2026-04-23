# Verity Technical Design

## Document Purpose

This document describes the internal architecture of the Verity AI governance platform at the code level: how components are wired, how data flows through the system, what each layer does, and what is and is not supported today.

---

## System Overview

The Verity package is split into two planes. **Governance** owns the registry, lifecycle, decision-log reader, reporting, testing metadata, model management, and quotas. **Runtime** owns agent / task / tool execution, pipeline execution, the decision-log writer, MCP client, and mock / fixture backends. A thin `Coordinator` wires the two together. The business app consumes both via the `Verity` facade in `client/inprocess.py`.

```
+----------------------------------------------------------------------------+
|                              Verity Package                                 |
|                         (verity/src/verity/)                                |
|                                                                            |
|  +-----------------------+   +-----------------------+                     |
|  | governance/           |   | runtime/              |                     |
|  |                       |   |                       |                     |
|  | registry.py           |   | engine.py             |---> Claude API      |
|  | lifecycle.py          |   | pipeline.py           |                     |
|  | decisions.py (reader) |   | decisions_writer.py   |                     |
|  | reporting.py          |   | mcp_client.py         |                     |
|  | testing_meta.py       |   | connectors.py         |                     |
|  | models.py             |   | mock_context.py       |                     |
|  | quotas.py             |   | fixture_backend.py    |                     |
|  | coordinator.py  <-----+---+ test_runner.py        |                     |
|  +----------+------------+   | validation_runner.py  |                     |
|             |                | metrics.py            |                     |
|             |                | runtime.py            |                     |
|             |                +-----------+-----------+                     |
|             |                            |                                 |
|  +----------+----------------------------+-----------+                     |
|  | client/inprocess.py  -- Verity facade (SDK entry) |                     |
|  +----------+----------------------------------------+                     |
|             |                                                              |
|  +----------+--------+   +------------------+   +----------------+         |
|  | contracts/        |   | models/          |   | db/            |         |
|  | decision.py       |   | agent.py         |   | connection.py  |         |
|  | pipeline.py       |   | task.py          |   | schema.sql     |         |
|  | inference.py      |   | prompt.py        |   | migrate.py     |         |
|  | prompt.py         |   | decision.py      |   | queries/       |         |
|  | tool.py           |   | lifecycle.py     |   |   registry.sql |         |
|  | testing.py        |   | inference_config |   |   registration.sql      |
|  | config.py         |   | pipeline.py      |   |   decisions.sql|         |
|  | enums.py          |   | testing.py       |   |   lifecycle.sql|         |
|  | mock.py           |   | reporting.py     |   |   reporting.sql|         |
|  +-------------------+   | application.py   |   |   testing.sql  |         |
|                          | model.py         |   |   models.sql   |         |
|                          | quota.py         |   |   quotas.sql   |         |
|                          | pipeline_run.py  |   |   runtime.sql  |         |
|                          +------------------+   +----------------+         |
|                                                                            |
|  +----------------------------------------------------------------------+ |
|  | web/                                                                 | |
|  |  app.py          - FastAPI sub-app factory                          | |
|  |  routes.py       - HTML (admin UI) routes                           | |
|  |  templates/      - Jinja2 templates                                 | |
|  |  static/         - verity.css                                       | |
|  |  middleware.py   - CorrelationMiddleware                             | |
|  |  api/            - REST API (/api/v1/*)                              | |
|  |      router.py                                                      | |
|  |      registry.py / runtime.py / authoring.py / draft_edit.py        | |
|  |      lifecycle.py / applications.py / decisions.py / reporting.py   | |
|  |      models.py / usage.py / quotas.py / schemas.py                  | |
|  +----------------------------------------------------------------------+ |
+----------------------------------------------------------------------------+
```

**Plane responsibilities (the "Governance Contract"):**
- Governance *owns* the data of record (registry, decisions, approvals, validation evidence) and *enforces* the rules (lifecycle gates, tool authorization, quota definitions).
- Runtime *executes* governed configurations and *writes* decisions back through the contract. It depends on Governance for what to run; Governance depends on Runtime for nothing.

---

## 1. Governance & Runtime Layers

There is no `verity/src/verity/core/` directory. It was split into two planes early in the project: `verity/src/verity/governance/` (the system of record) and `verity/src/verity/runtime/` (the execution surface). Both are wired through the `Verity` facade in `client/inprocess.py`.

### 1.1 Client (`client/inprocess.py`)

The main entry point for all SDK operations. Every business application instantiates one `Verity` client.

```python
from verity import Verity

verity = Verity(
    database_url="postgresql://...",
    anthropic_api_key="sk-...",
    application="uw_demo"
)
await verity.connect()
```

**What it does:** Facade over Governance and Runtime. Holds shared instances of the `Database`, the Governance `Coordinator` (which in turn owns Registry / Lifecycle / DecisionsReader / Reporting / TestingMeta / Models / Quotas), and the `Runtime` (which owns ExecutionEngine / PipelineExecutor / DecisionsWriter / TestRunner / ValidationRunner / MCPClient).

**Module initialization (in constructor):**

```
Verity.__init__()
    |
    +-- self.db = Database(database_url)
    +-- self.governance = Coordinator(self.db)
    |       +-- self.registry           = Registry(self.db)
    |       +-- self.lifecycle          = Lifecycle(self.db)
    |       +-- self.decisions (reader) = DecisionsReader(self.db)
    |       +-- self.reporting          = Reporting(self.db)
    |       +-- self.testing            = TestingMeta(self.db)
    |       +-- self.models             = Models(self.db)
    |       +-- self.quotas             = Quotas(self.db)
    +-- self.runtime = Runtime(
    |       governance=self.governance,
    |       anthropic_api_key=api_key,
    |       application=application,
    |   )
    |       +-- self.execution          = ExecutionEngine(...)
    |       +-- self.pipeline_executor  = PipelineExecutor(...)
    |       +-- self.decisions_writer   = DecisionsWriter(self.db)
    |       +-- self.test_runner        = TestRunner(...)
    |       +-- self.validation_runner  = ValidationRunner(...)
    |       +-- self.mcp_client         = MCPClient(...)
    +-- Top-level attributes re-exported for ergonomic access:
            verity.registry, verity.lifecycle, verity.decisions,
            verity.reporting, verity.testing, verity.models, verity.quotas,
            verity.execution, verity.pipeline_executor
```

**Key dependency flow:** Runtime depends on Governance (to resolve configs, read authorizations, write decisions). Governance has no dependency on Runtime — that is the whole point of the split and the reason the Governance-as-sidecar topology is possible without rewriting the core.

**Public surface:** ~100 methods across the sub-facades (registry, lifecycle, execution, pipeline_executor, decisions, reporting, testing, models, quotas, applications). The REST API at `/api/v1/*` is a thin JSON wrapper over this facade.

---

### 1.2 Execution Engine (`runtime/engine.py`)

The runtime that invokes Claude and tools. Three execution modes: agent (multi-turn), task (single-turn), tool (no LLM).

#### Gateway Architecture

All external calls pass through gateway functions that check MockContext before executing:

```
run_agent() / run_task() / run_tool()
        |
        v
+-------------------+         +-------------------+
| _gateway_llm_call |         | _gateway_tool_call|
|                   |         |                   |
| if mock.has_llm:  |         | if mock has tool:  |
|   return mock     |         |   return mock     |
| else:             |         | elif mock_all:    |
|   call Claude API |         |   return DB mock  |
+-------------------+         | else:             |
                              |   call real func  |
                              +-------------------+
```

#### Agent Execution Flow (`run_agent`)

```
1. Resolve agent config (champion version from registry)
2. Assemble prompts (_assemble_prompts)
   a. Sort by execution_order
   b. Evaluate condition_logic for optional prompts
   c. Validate template variables against context
   d. Substitute {{variables}} with context values
   e. Split into system prompt + user messages
3. Build tool definitions from authorized tools
4. Enter agentic loop (max 10 turns):
   a. Call _gateway_llm_call (Claude API or mock)
   b. If stop_reason == "end_turn": extract output, break
   c. If stop_reason == "tool_use":
      - For each tool_use block in response:
        - Call _gateway_tool_call (real or mock)
        - Append tool result to messages
      - Continue loop with updated messages
5. Log decision via _log_decision
6. Return ExecutionResult
```

**What is NOT supported:**
- Sub-agent delegation (FC-1: planned, not implemented)
- Session continuity across calls (FC-2: planned)
- Retry/fallback on failure (FC-4: planned)
- Vision/image input (FC-5: planned)
- Batch API (FC-6: planned)
- Streaming with tool calls (partial - events emitted but no streaming tool results)

#### Task Execution Flow (`run_task`)

```
1. Resolve task config (champion version from registry)
2. Assemble prompts (same as agent)
3. If task has valid JSON Schema output_schema:
   - Use tool_choice to force structured output
4. Single LLM call (no loop)
5. Parse response as JSON
6. Log decision
7. Return ExecutionResult
```

**Key difference from agent:** Tasks cannot call tools. Single turn only. If the task needs external data, it must be in the context dict.

#### Tool Execution Flow (`run_tool`)

```
1. Look up tool definition from registry
2. Build tool authorization record
3. Call _gateway_tool_call (mock or real)
4. Log decision with entity_type='tool'
5. Return ExecutionResult
```

**Used for:** Pipeline steps that are pure data operations (no LLM reasoning needed).

#### Decision Logging (`_log_decision`)

Every execution path ends here. Creates a `DecisionLogCreate` with:

```
_log_decision()
    |
    +-- Determine version_id from config
    +-- Snapshot inference config (full copy, not just ID)
    +-- Extract prompt_version_ids from config.prompts
    +-- Build DecisionLogCreate with ALL fields
    +-- Call decisions.log_decision() -> INSERT into agent_decision_log
    +-- Return {decision_log_id, created_at}
```

**Critical invariant:** The inference_config_snapshot is a JSONB copy of the full config at execution time, not a reference to the config ID. If the config is later modified, the snapshot preserves what was actually used.

#### Prompt Assembly (`_assemble_prompts`)

```
_assemble_prompts(prompts: [PromptAssignment], context: dict)
    |
    +-- Sort prompts by execution_order
    +-- For each prompt:
    |     +-- If not required and has condition_logic:
    |     |     evaluate condition against context, skip if false
    |     +-- Validate template_variables against context keys
    |     |     (raises ValueError if any declared variable is missing)
    |     +-- Substitute {{variable}} placeholders with context values
    |     +-- Route to system_parts[] or user_messages[] by api_role
    +-- Return (system_prompt, [user_messages])
```

**Template variable validation:** When a prompt_version is registered, `{{variable}}` placeholders are auto-extracted via regex and stored in the `template_variables TEXT[]` column. At execution time, these are checked against the context dict. A missing variable produces a clear error message instead of sending `{{document_text}}` literally to Claude.

#### Tool Registration

Tools are registered as Python function references at app startup:

```python
verity.register_tool_implementation("get_submission_context", get_submission_context)
```

Stored in: `self.execution.tool_implementations["get_submission_context"] = func`

At execution time, the gateway looks up by name and calls the function:

```python
func = self.tool_implementations.get(tool_name)
if asyncio.iscoroutinefunction(func):
    result = await func(**tool_input)
else:
    result = func(**tool_input)
```

**What this means:** Tool implementations live in the consuming application's process, not in Verity. Verity holds the function pointer. The tool's database connections, API keys, and state belong to the app.

---

### 1.3 Registry (`governance/registry.py`)

The source of truth for all AI asset definitions. Handles registration (write) and config resolution (read).

#### Config Resolution (3-Tier)

```
get_agent_config(agent_name, effective_date=None, version_id=None)
    |
    +-- If version_id provided:
    |     Direct lookup: get_agent_version_by_id(version_id)
    |     (Ignores dates, ignores champion pointer)
    |
    +-- If effective_date provided:
    |     Temporal lookup: get_agent_champion_at_date(name, date)
    |     WHERE valid_from <= date AND valid_to > date
    |     (SCD Type 2 - returns the version that was champion on that date)
    |
    +-- Default (no args):
          Champion pointer: get_agent_champion(name)
          Follows agent.current_champion_version_id pointer
          (Fastest - single join, no date comparison)
```

After resolving the version, config assembly adds:

```
AgentConfig = {
    agent_id, agent_name, display_name, description,
    materiality_tier, purpose, domain,
    agent_version_id, version_label, lifecycle_state,
    inference_config: InferenceConfig,        # resolved by ID
    prompts: [PromptAssignment],              # from entity_prompt_assignment
    tools: [ToolAuthorization],               # from agent_version_tool
    authority_thresholds: dict,               # from agent_version.authority_thresholds
    output_schema: dict                       # from agent_version.output_schema
}
```

#### Prompt Version Auto-Extraction

When `register_prompt_version()` is called:

```python
if "template_variables" not in kwargs and "content" in kwargs:
    variables = re.findall(r"\{\{(\w+)\}\}", kwargs["content"])
    kwargs["template_variables"] = deduplicated(variables)
```

This populates the `template_variables TEXT[]` column automatically. The caller never has to declare them manually.

---

### 1.4 Lifecycle (`governance/lifecycle.py`)

Manages the 7-state promotion workflow.

#### State Machine

```
                            +------------+
                            | deprecated |
                            +------+-----+
                                   ^
                   +---------------+----------------+
                   |               |                |
+-------+    +-----------+    +---------+    +------------+    +---------+
| draft |--->| candidate |--->| staging |--->| shadow     |--->|challngr |
+-------+    +-----+-----+    +---------+    +------------+    +----+----+
                   |                                                |
                   +------------------+                             |
                                      |                             v
                                      +----------------------> +---------+
                                       (fast-track for demo)   | champion|
                                                               +---------+
```

**Valid transitions:**

| From | To |
|------|-----|
| draft | candidate |
| candidate | staging, champion (fast-track), deprecated |
| staging | shadow, deprecated |
| shadow | challenger, deprecated |
| challenger | champion, deprecated |
| champion | deprecated |

#### Gate Requirements

Each transition checks prerequisites on the version record:

| Transition | Gate Checks |
|-----------|------------|
| Any -> Shadow | `staging_tests_passed == TRUE`, approver reviewed staging results |
| Any -> Challenger | `shadow_period_complete == TRUE`, approver reviewed shadow metrics |
| Challenger -> Champion | `ground_truth_passed == TRUE`, model card reviewed, challenger metrics reviewed |
| Candidate -> Champion | Minimal (fast-track for demo seeding) |

Gate check returns `list[str]` of issues. Empty list = pass.

#### Champion Promotion

When promoting to champion:

```
_set_champion(entity_type, current_version, new_version_id)
    |
    +-- Find prior champion (get_current_champion_agent_version)
    +-- If prior exists and is different from new:
    |     deprecate_agent_version(prior_id)
    |     Sets: lifecycle_state='deprecated', valid_to=NOW()
    +-- set_agent_champion(new_version_id, agent_id)
          Sets: lifecycle_state='champion', valid_from=NOW(),
                valid_to='2999-12-31', channel='production'
          Updates: agent.current_champion_version_id = new_version_id
```

**SCD Type 2 temporal management:** Only champion versions have `valid_from`/`valid_to` set. Pre-champion versions have NULL dates. At any point in time, exactly one version has `valid_from <= NOW() AND valid_to > NOW()`.

---

### 1.5 Decisions — Reader (`governance/decisions.py`) and Writer (`runtime/decisions_writer.py`)

The decisions capability is split across the two planes by design. The **reader** (Governance) serves list, detail, audit-trail, and override queries — no writes. The **writer** (Runtime) is the single code path that produces `agent_decision_log` rows; every agent / task / tool invocation must route through it. Pipeline-run rows and model-invocation-log rows are also written here.

Audit trail management. Every AI invocation produces an immutable record.

#### Log Decision Serialization

```
log_decision(DecisionLogCreate)
    |
    +-- Serialize entity_type as .value (enum -> string)
    +-- Serialize UUIDs as strings
    +-- Serialize dicts/lists as JSON strings:
    |     inference_config_snapshot, input_json, output_json,
    |     risk_factors, tool_calls_made, message_history
    +-- Serialize run_purpose as .value
    +-- INSERT into agent_decision_log RETURNING id, created_at
    +-- Return {decision_log_id, created_at}
```

**31 columns** inserted per decision (after removing business keys).

#### Audit Trail Queries

Two ways to query audit trails:

```
get_audit_trail_by_run(pipeline_run_id)
    WHERE adl.pipeline_run_id = :pipeline_run_id
    → Shows one specific pipeline execution (4 steps)

get_audit_trail(execution_context_id)
    WHERE adl.execution_context_id = :execution_context_id
    → Shows ALL runs for a business context (e.g., all pipeline runs for a submission)
```

Both return `[AuditTrailEntry]` with: entity name, version, capability type, channel, reasoning, confidence, tool calls, duration, status.

**What was removed:** `submission_id`, `policy_id`, `renewal_id`, `business_entity` - all business keys were removed from `agent_decision_log`. Business context is linked exclusively through `execution_context_id`.

---

### 1.6 Pipeline Executor (`runtime/pipeline.py`)

Orchestrates multi-step pipelines with dependency resolution.

#### Execution Flow

```
run_pipeline(pipeline_name, context, ...)
    |
    +-- Resolve pipeline champion version from registry
    +-- Parse steps from pipeline_version.steps JSONB
    +-- Generate pipeline_run_id (UUID)
    +-- Build execution groups (group by step_order)
    +-- For each group (sequential):
    |     +-- If pipeline_failed: skip all steps in group
    |     +-- Check dependencies (depends_on list vs accumulated_results)
    |     +-- Evaluate conditions (condition dict vs context)
    |     +-- If single step: execute directly
    |     +-- If multiple steps: asyncio.gather(*tasks)
    |     +-- Accumulate results (step output added to step_context for downstream)
    +-- Determine overall status:
          - All complete → "complete"
          - pipeline_failed → "failed"
          - Some failed → "partial"
```

#### Step Context Propagation

Each step receives the original pipeline context PLUS outputs from all prior completed steps:

```python
step_context = dict(context)  # original pipeline context
for dep_name, dep_result in accumulated_results.items():
    if dep_result.execution_result and dep_result.execution_result.output:
        step_context[dep_name] = dep_result.execution_result.output
```

This means Step 3 (triage) can see the outputs of Step 1 (classify) and Step 2 (extract) in its context.

**What is NOT supported:**
- Long-running async execution (all steps run synchronously in one request)
- Pipeline-level status persistence (no pipeline_run table - only step-level decision logs)
- Complex DAG patterns (only sequential groups with optional parallelism within a group)
- Retry on failure
- Dynamic step generation

**Architecture decision pending:** Pipeline should become a lightweight container for cooperating agents/tasks, not a DAG orchestrator. See `project_pipeline_rethink.md`.

---

### 1.7 Mock Context (`runtime/mock_context.py`, `runtime/fixture_backend.py`)

Two independent mocking dimensions for testing.

#### Dimension 1: LLM Mocking

```
MockContext(llm_responses=[
    {"risk_score": "Green", "confidence": 0.89},  # Simple: 1 response = skip loop
])

MockContext(llm_responses=[
    {"type": "tool_use", "name": "get_submission", "input": {...}},  # Replay: tool request
    {"risk_score": "Green", "confidence": 0.89},                      # Then final answer
])
```

- `has_llm_mock`: True if responses provided
- `is_simple_mock`: True if 1 response that's not a tool_use (skips entire agentic loop)
- Responses consumed in order via `_llm_call_index`

#### Dimension 2: Tool Mocking

```
MockContext(tool_responses={
    "get_submission_context": {"named_insured": "Acme Corp", ...},
    "get_loss_history": [                       # List = multi-call
        {"year": 2023, "claims": 0},
        {"year": 2024, "claims": 1},
    ],
})
```

- Per-tool by name. Tools NOT in the dict make REAL calls.
- `mock_all_tools=True`: All tools use DB-registered mock responses
- List values support multi-call patterns (consumed in order)

#### Gateway Priority (when MockContext provided)

```
_gateway_tool_call():
    1. Check mock.tool_responses[tool_name]  → runtime mock
    2. Check mock.mock_all_tools             → DB mock
    3. Neither                               → REAL call (DB flag ignored)
```

When NO MockContext: check `tool.mock_mode_enabled` DB flag, then real call.

#### Replay from Decision Log

```python
mock = MockContext.from_decision_log(prior_decision, mock_llm=True, mock_tools=True)
```

Reconstructs a MockContext from a stored decision's `message_history` and `tool_calls_made`. Three replay patterns:

| mock_llm | mock_tools | Use Case |
|----------|-----------|----------|
| True | True | Full replay: audit reproducibility |
| False | True | New prompt test: real Claude + original tool data |
| True | False | New tool test: original LLM behavior + new tool implementation |

---

### 1.8 Testing metadata (`governance/testing_meta.py`)

Testing is split across planes: Governance (`testing_meta.py`) owns **metadata reads** (list suites, list cases, list validation runs, list ground truth datasets/records/annotations). Runtime (`test_runner.py`, `validation_runner.py`) owns **execution** (see §14).

**Methods:** list_test_suites, list_test_cases, log_test_result, list_test_results, get_latest_validation, list_model_cards, list_metric_thresholds, list_field_extraction_configs, list_ground_truth_datasets, list_ground_truth_records, list_ground_truth_annotations, list_validation_runs, list_validation_record_results.

---

### 1.9 Reporting (`governance/reporting.py`)

Dashboard and model inventory queries.

**Methods:** dashboard_counts (asset + decision + override + pipeline + cost tiles), model_inventory_agents, model_inventory_tasks, override_analysis (grouped by reason_code over N days).

---

### 1.10 Models (`governance/models.py`)

Foundation-model registry and usage accounting.

**Tables owned:** `model`, `model_price` (SCD-2), `model_invocation_log`, `v_model_invocation_cost` (view).

**Methods:**
- `register_model(name, display_name, provider, context_window, ...)` — registers a model row
- `register_model_price(model_id, input_price_per_1m, output_price_per_1m, cache_read_price, cache_create_price, effective_from)` — appends an SCD-2 price row, closes the prior price
- `list_models()`, `get_model(name)`, `list_model_prices(model_id)`
- `log_invocation(model_id, decision_log_id, input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens, duration_ms, ...)` — called by `decisions_writer` on every Anthropic call
- `usage_by_time_bucket(from_ts, to_ts, bucket, application_ids?)` — drives the cost-over-time chart
- `usage_by_model(from_ts, to_ts, application_ids?)`, `usage_by_application(from_ts, to_ts)` — breakdowns for the Usage & Spend dashboard

**Cost computation.** Every `model_invocation_log` row stores raw token counts. Cost is **never** stored on the row — it is joined through `v_model_invocation_cost`, which `LEFT JOIN`s the price that was effective at the invocation timestamp. Price edits therefore cannot retroactively alter historical cost; they only affect invocations from `effective_from` forward.

---

### 1.11 Quotas (`governance/quotas.py`)

Soft-governance layer over model usage.

**Tables owned:** `quota`, `quota_check`.

**Methods:**
- `register_quota(name, scope_type, scope_id, metric, limit_value, period, ...)` — scope_type ∈ {application, model, entity}; metric ∈ {spend_usd, invocation_count}; period ∈ {day, week, month}
- `list_quotas()`, `get_quota(id)`, `deactivate_quota(id)`
- `run_check(quota_id)` — computes current consumption over the rolling window, writes a `quota_check` row, returns `{consumption, limit, status: ok | warning | breach}`
- `run_all_checks()` — iterates all active quotas; used by the on-demand button in the UI and by the (future) scheduler
- `list_active_breaches()` — feeds the Incidents page

**Enforcement model.** V1 is *soft*: no blocking at invocation time. Breaches appear on Incidents and drive operational triage. Hard enforcement at `DecisionsWriter.log_invocation` time is on the roadmap.

---

### 1.12 MCP Client (`runtime/mcp_client.py`)

Bridge that surfaces tools served by external Model Context Protocol servers as normal, governed Verity tools.

**Flow.**
1. An `mcp_server` row is registered in Governance (URL, auth, description, lifecycle).
2. A `tool` row can be registered with `implementation_path = "mcp://<server_name>/<tool_name>"`.
3. At runtime, when the engine resolves a tool authorization and the tool is MCP-served, it delegates to `MCPClient.call_tool(server_name, tool_name, input)`.
4. The MCP call result is wrapped in the same `{input, output}` shape as function-pointer tools, so `tool_calls_made` in the decision log is uniform.

Governance (tool authorization, data classification, write-op flag) applies identically to MCP tools — Verity enforces before the MCP call is issued.

---

### 1.13 Coordinator (`governance/coordinator.py`)

Thin composition root for the governance plane. Instantiates the registry / lifecycle / decisions_reader / reporting / testing_meta / models / quotas facades against a shared `Database`, and exposes them as attributes. It is the single dependency the Runtime needs in order to honour the Governance Contract.

In the in-process topology (current), `Verity.__init__` constructs the `Coordinator` and passes it to the `Runtime`. In the sidecar topology (future), the `Coordinator` sits behind the REST API and the Runtime — wherever it executes — talks to it over HTTP.

---

## 2. Data Layer

### 2.1 Database Connection (`db/connection.py`)

```python
class Database:
    def __init__(self, database_url):
        self.pool = None  # AsyncConnectionPool (psycopg v3)
        self.queries = {}  # {query_name: sql_text}
```

**Connection pooling:** Uses `psycopg.AsyncConnectionPool` with min_size=2, max_size=10.

**Named query system:** All SQL lives in `.sql` files under `db/queries/`. Each file contains multiple queries separated by `-- name: query_name` comments. On `connect()`, all files are loaded and parsed into the `queries` dict.

**Methods:**
- `fetch_one(query_name, params)` - Execute named query, return first row as dict
- `fetch_all(query_name, params)` - Return all rows as list of dicts
- `execute_returning(query_name, params)` - INSERT/UPDATE with RETURNING clause
- `fetch_one_raw(sql, params)` - Raw SQL (escape hatch, used sparingly)
- `fetch_all_raw(sql, params)` - Raw SQL

**Row format:** All queries return `dict_row` (psycopg row_factory). No ORM mapping - dicts flow directly to Pydantic models via `**row` unpacking.

### 2.2 Schema (`db/schema.sql`)

**~45 tables + 1 view** across 8 functional groups. All `*_version` tables (agent_version, task_version, prompt_version, pipeline_version) carry a `cloned_from_version_id UUID NULL` column so lineage is traceable when a draft is produced by the clone-and-edit workflow.

#### Asset Registry (14 tables)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| inference_config | Named LLM parameter sets | name, model_name, temperature, max_tokens |
| agent | Agent header (one per agent) | name, materiality_tier, current_champion_version_id |
| agent_version | Agent versions with lifecycle | lifecycle_state, channel, inference_config_id, valid_from/to, cloned_from_version_id, decision_log_detail |
| task | Task header | name, capability_type, materiality_tier |
| task_version | Task versions | lifecycle_state, channel, output_schema, cloned_from_version_id, decision_log_detail |
| prompt | Prompt header | name, governance_tier |
| prompt_version | Prompt content versions | content, template_variables[], api_role, cloned_from_version_id |
| entity_prompt_assignment | Links prompts to agent/task versions | entity_type, entity_version_id, execution_order, condition_logic |
| tool | Tool definitions | name, input_schema, output_schema, mock_mode_enabled, implementation_path |
| agent_version_tool | Tool authorization for agents | agent_version_id, tool_id |
| task_version_tool | Tool authorization for tasks | task_version_id, tool_id |
| agent_version_delegation | Authorizes parent→child sub-agent delegation | parent_agent_version_id, child_agent_name |
| pipeline / pipeline_version | Pipeline definitions | steps JSONB, lifecycle_state, cloned_from_version_id |
| mcp_server | Registered Model Context Protocol servers | name, url, auth_mode, lifecycle_state |

#### Multi-App & Context (3 tables)

| Table | Purpose |
|-------|---------|
| application | Registered consuming apps (uw_demo, ai_ops, model_validation, compliance_audit, ds_workbench) |
| application_entity | Maps entities to applications |
| execution_context | Business operation context (context_ref, context_type, metadata JSONB, application_id) |

#### Testing & Validation (9 tables)

| Table | Purpose |
|-------|---------|
| test_suite | Test suite containers |
| test_case | Individual test cases (input_data, expected_output, metric_type) |
| test_execution_log | Test run results |
| ground_truth_dataset | Dataset metadata (quality_tier, status lifecycle, IAA metrics) |
| ground_truth_record | Input items (no labels - labels are in annotation table) |
| ground_truth_annotation | Annotator labels (human_sme, llm_judge, adjudicator) with is_authoritative flag |
| validation_run | Aggregate validation metrics (precision, recall, F1, kappa) |
| validation_record_result | Per-record predictions for drill-down |
| metric_threshold | Pass/fail thresholds per entity (with optional field_name for extraction) |

#### Decisions & Audit (4 tables)

| Table | Purpose |
|-------|---------|
| agent_decision_log | Every AI invocation (~35 columns: full snapshots + pipeline_run_id + parent_decision_id + decision_depth + step_name + application + decision_log_detail + redaction_applied + hitl_required + reproduced_from_decision_id) |
| override_log | Human overrides of AI decisions |
| approval_record | Lifecycle promotion approvals with evidence review flags |
| pipeline_run | Pipeline-level run lifecycle (status: running / complete / partial / failed, steps_complete, steps_total, started_at / ended_at, application, execution_context_id) |

#### Model Management (3 tables + 1 view)

| Table / View | Purpose |
|--------------|---------|
| model | Foundation-model registry (provider, display_name, context_window, default_limits) |
| model_price | SCD-2 price history per model (input / output / cache-read / cache-create per-1M-token rates, effective_from / effective_to) |
| model_invocation_log | One row per LLM call (model_id, decision_log_id, token counts incl. cache, duration_ms, created_at) |
| v_model_invocation_cost | View that joins `model_invocation_log` to `model_price` by timestamp so cost is always point-in-time — drives Usage & Spend |

#### Quotas & Incidents (3 tables)

| Table | Purpose |
|-------|---------|
| quota | Active quota definitions (scope_type / scope_id, metric, limit_value, period, active) |
| quota_check | History of check runs (quota_id, observed_value, status, checked_at) |
| incident | Incident tracking with rollback records — Incidents page unifies this with active `quota` breaches |

#### Quality & Monitoring (3 tables)

| Table | Purpose |
|-------|---------|
| evaluation_run | Shadow/challenger production monitoring |
| model_card | Per-version documentation |
| field_extraction_config | Per-field tolerance for extraction validation |

#### Infrastructure (2 tables)

| Table | Purpose |
|-------|---------|
| description_similarity_log | pgvector similarity checks between entity descriptions |
| platform_settings | Key-value Verity-wide configuration read at runtime |

### 2.3 Named Queries (`db/queries/`)

**10 SQL files.** All SQL lives here; nothing is constructed via string concatenation in Python.

| File | Purpose |
|------|---------|
| registry.sql | Config resolution (current / date-pinned / version-pinned), entity listing, cross-references, agent / task / prompt config assembly |
| registration.sql | INSERT operations for all entity types (headers, versions, associations, MCP servers) |
| authoring.sql | Draft-only updates (PATCH / PUT semantics), clone-a-version into new draft, replace prompt-assignments / tool-authorizations / delegations, draft DELETE |
| lifecycle.sql | State transitions, champion setting + SCD-2 valid_from/to, deprecation, approval records, rollback |
| decisions.sql | Decision logging, list / detail / audit-trail queries, overrides, pipeline_run lifecycle writes (start / complete / fail), application activity + purge |
| testing.sql | Test suites + cases, ground truth datasets / records / annotations, validation runs + per-record results, metric thresholds |
| reporting.sql | Dashboard aggregations, model inventory, override analysis |
| models.sql | Model registry CRUD, SCD-2 price history, invocation logging, usage aggregations for cost-over-time / by-model / by-application |
| quotas.sql | Quota CRUD, quota_check history, consumption rollups, active-breach listing |
| connectors.sql | MCP server registration + resolution queries used by `runtime/mcp_client.py` |

### 2.4 Enumerations

All defined as PostgreSQL ENUMs and mirrored as Python `str, Enum` classes:

| Enum | Values |
|------|--------|
| lifecycle_state | draft, candidate, staging, shadow, challenger, champion, deprecated |
| deployment_channel | development, staging, shadow, evaluation, production |
| materiality_tier | high, medium, low |
| capability_type | classification, extraction, generation, summarisation, matching, validation |
| entity_type | agent, task, prompt, pipeline, tool |
| governance_tier | behavioural, contextual, formatting |
| api_role | system, user, assistant_prefill |
| metric_type | exact_match, schema_valid, field_accuracy, classification_f1, semantic_similarity, human_rubric |
| run_purpose | production, test, validation, audit_rerun |
| gt_dataset_status | collecting, labeling, adjudicating, ready, deprecated |
| gt_quality_tier | silver, gold |
| gt_source_type | document, submission, synthetic |
| gt_annotator_type | human_sme, llm_judge, adjudicator |
| data_classification | tier1_public, tier2_internal, tier3_confidential, tier4_pii_restricted |
| trust_level | trusted, conditional, sandboxed, blocked |

---

## 3. Model Layer (`verity/src/verity/models/`)

**9 model files, ~48 Pydantic model classes.**

### Key Runtime Models

| Model | Used By | Purpose |
|-------|---------|---------|
| AgentConfig | execution.run_agent | Complete resolved config: inference, prompts, tools, thresholds |
| TaskConfig | execution.run_task | Complete resolved config for tasks |
| PromptAssignment | _assemble_prompts | One prompt bound to a version (with content, role, order, conditions) |
| ToolAuthorization | _gateway_tool_call | Tool definition with authorization and mock settings |
| InferenceConfig | API call building | Model name, temperature, max tokens, extended params |
| ExecutionResult | Return from all execution | decision_log_id, output, tokens, duration, status |
| DecisionLogCreate | _log_decision | 31-field input for decision INSERT |
| AuditTrailEntry | Audit trail queries | One step in a pipeline's audit trail |
| MockContext | Testing/mocking | Two-dimensional mock control |
| PipelineStep | Pipeline execution | Step definition (entity, order, dependencies, conditions) |
| PromotionRequest | Lifecycle promotion | Target state + approver + evidence flags |

### Key Enums

| Enum | Values | Used For |
|------|--------|----------|
| LifecycleState | 7 states | Version promotion workflow |
| RunPurpose | production, test, validation, audit_rerun | Separates governance executions from business executions |
| GtAnnotatorType | human_sme, llm_judge, adjudicator | Ground truth labeling roles |

---

## 4. Web Layer (`verity/src/verity/web/`)

### 4.1 App Factory (`app.py`)

```python
def create_verity_web(verity: Verity) -> FastAPI:
    app = FastAPI(title="Verity Admin")
    app.mount("/static", StaticFiles(directory=static_dir))
    router = create_routes(verity)
    app.include_router(router)
    return app
```

The consuming application mounts this at `/admin/`:

```python
# In verity/src/verity/main.py (standalone server)
verity_web = create_verity_web(verity)
app.mount("/admin", verity_web)
```

### 4.2 Routes (`routes.py`)

Admin UI HTML routes served via Jinja2. Grouped to match the sidebar.

| Route Group | Routes | Purpose |
|-------------|--------|---------|
| Home | `/` | Dashboard with asset counts, decision + override + pipeline charts, current-month cost tile |
| Registry | `/applications`, `/pipelines`, `/agents`, `/tasks`, `/prompts`, `/configs`, `/tools`, `/mcp-servers`, `/models` and detail pages | Browse and detail pages for all entity types |
| Observability | `/pipeline-runs`, `/decisions`, `/overrides`, `/usage`, `/quotas` | Decision log, pipeline run lifecycle, overrides, Usage & Spend, quota status |
| Governance | `/model-inventory`, `/lifecycle`, `/testing`, `/ground-truth`, `/validation-runs`, `/incidents` | Inventory, lifecycle overview, test suites, ground truth datasets, validation runs, incidents (incidents + active quota breaches) |
| Audit | `/audit-trail/run/{id}`, `/audit-trail/context/{id}` | Pipeline-run and context-scoped audit trails |
| Settings | `/settings` | Platform settings (`platform_settings` table) |

### 4.3 Template Rendering

All routes use a `_render()` helper that wraps Starlette 1.0's TemplateResponse:

```python
def _render(templates, request, template_name, **context):
    return templates.TemplateResponse(request, template_name, context)
```

Custom Jinja2 filters:
- `_enum_value` (finalize filter): Converts `EntityType.AGENT` to `"agent"` for display
- `_short_id`: Formats UUID as `"abcd...wxyz"` (first 4 + last 4)

### 4.4 Shared Data Loaders

Three helpers load cross-reference data used by multiple pages:

```python
_load_entity_apps()      # Maps (entity_type, entity_id) -> "App Display Name"
_load_agent_summaries()  # Maps agent_id -> {prompt_names: "P1, P2", tool_names: "T1, T2"}
_load_task_summaries()   # Maps task_id -> {prompt_names: "P1, P2"}
```

### 4.5 REST API (`web/api/`)

Mounted on the same FastAPI app at `/api/v1/*`. JSON-only; thin wrappers over the SDK facade (`client/inprocess.py`).

**Sub-routers** (in `web/api/router.py`):

| Module | Surface |
|--------|---------|
| `registry.py` | `GET /agents`, `/tasks`, `/prompts`, `/pipelines`, `/inference-configs`, `/tools`, `/mcp-servers`; per-entity `/{name}/config` (resolved) and `/{name}/versions` |
| `runtime.py` | `POST /runtime/agents/{name}/run`, `/tasks/{name}/run`, `/pipelines/{name}/run` |
| `authoring.py` | `POST` for all `register_*` headers, versions, and associations (prompts / tools / delegations / MCP servers / ground truth / validation runs / model cards / thresholds / test suites) |
| `draft_edit.py` | `PATCH / PUT / DELETE` on draft versions only (draft-guard enforced in SQL); `POST /{name}/versions/{source_id}/clone` for clone-and-edit |
| `lifecycle.py` | `POST /lifecycle/promote`, `/lifecycle/rollback`, `GET /lifecycle/approvals` |
| `applications.py` | `POST/GET/DELETE /applications`, `/applications/{name}/entities` + map/unmap, `/activity` read + purge (env-flag guarded) |
| `models.py` | Model + price CRUD |
| `usage.py` | Usage & spend aggregations (time buckets, by-model, by-application) |
| `quotas.py` | Quota CRUD + `run_check` + `run_all_checks` |
| `decisions.py` | Decisions list / detail / audit-trail / overrides |
| `reporting.py` | Dashboard counts, inventory |

**Swagger UI:** `/api/v1/docs`. **OpenAPI JSON:** `/api/v1/openapi.json`.

**Pydantic boundary:** Every method returning a BaseModel is serialized with `.model_dump(mode="json")` inside a single helper. Request bodies use request-specific Pydantic models in `web/api/schemas.py` that mirror the SDK method signatures.

**Middleware:** `CorrelationMiddleware` (in `web/middleware.py`) attaches a correlation ID to every request for structured logging and trace inheritance — this applies to both the admin UI and the REST API.

---

## 5. Cross-Cutting Concerns

### 5.1 Temporal Version Management (SCD Type 2)

Only champion versions have temporal dates set:

| Event | valid_from | valid_to |
|-------|-----------|----------|
| Version created (draft) | NULL | NULL |
| Through candidate/staging/shadow/challenger | NULL | NULL |
| Promoted to champion | NOW() | 2999-12-31 23:59:59 |
| Superseded by new champion | unchanged | NOW() |

Query for "champion on March 15, 2026":
```sql
WHERE valid_from <= '2026-03-15' AND valid_to > '2026-03-15'
```

### 5.2 Execution Context (Business Decoupling)

Verity never stores business keys (submission_id, policy_id). The business app registers a context:

```python
ctx = await verity.create_execution_context(
    context_ref="submission:00000001-...",   # opaque to Verity
    context_type="submission",               # opaque to Verity
    metadata={"named_insured": "Acme Corp"}, # opaque to Verity
)
```

All decisions link to `execution_context_id`. The business app interprets the context_ref. Verity just groups decisions by it.

### 5.3 Run Purpose

Every decision is tagged with why it happened:

| Purpose | Who | Why |
|---------|-----|-----|
| production | Business app (uw_demo) | Normal business operation |
| test | AI Operations (ai_ops) | Test suite execution |
| validation | Model Validation (model_validation) | Ground truth validation for promotion |
| audit_rerun | Compliance & Audit (compliance_audit) | Regulatory reproduction |

Three governance applications are seeded: ai_ops, model_validation, compliance_audit.

### 5.4 Version Composition Immutability

An agent/task version is a frozen snapshot of: prompts (specific versions) + inference config + tool authorizations + authority thresholds + output schema.

Once promoted beyond draft, these bindings cannot change. A modification requires creating a new version. This ensures what was tested is what runs.

**Current enforcement:** Application-level only. Database triggers for defense-in-depth are planned (FC-12).

---

## 6. What Is Not Built Yet

The items below are what remains open. Everything not listed here is shipped.

| Feature | Status |
|---------|--------|
| Verity Agents (drift detection, lifecycle initiation, HITL-gated validation agents) | Designed; no code yet |
| REST API authentication | Open — the API binds unauthenticated to the Docker network / localhost |
| Hard quota enforcement at invocation time | Soft enforcement only (breaches surface on Incidents); blocking at `DecisionsWriter.log_invocation` is on the roadmap |
| Scheduled quota checker | On-demand button only; no background scheduler |
| Slack / email notifications for incidents and quota breaches | Not started |
| Composition immutability enforcement via DB triggers | Application-level guards only; defense-in-depth triggers planned |
| Session continuity (long-running conversational memory) | Not started |
| Execution hooks (pre/post invocation) | Not started |
| Retry / fallback / circuit breaker around Claude API | Not started (single failure = failed decision) |
| Vision / image input | Not started |
| Batch API | Not started |
| Response caching (outside of Claude's prompt cache) | Not started |
| Tool versioning | Not started |
| Description similarity computation | Schema ready; pgvector columns always NULL; embedding backfill and similarity check not built |
| Streaming execution from Runtime to UI end-to-end | `ExecutionEvent` contract present; UI does not yet consume the stream |
| Governance-as-sidecar deployment topology | REST API surface supports it; no external-orchestrator integration shipped |

---

## 7. Key Flows

### 7.1 Asset Registration Flow

**Use case:** A business application seeds its AI assets into Verity during initial setup. This is the "COMPOSE" pillar - nothing runs without being registered.

**Example:** Registering the triage_agent with prompts, tools, and promoting to champion.

**Input:** Agent definition (name, materiality tier, description), inference config reference, prompt content, tool references.

**Output:** Agent with champion version ready for execution.

**Tables involved:** agent, agent_version, inference_config, prompt, prompt_version, entity_prompt_assignment, tool, agent_version_tool, approval_record.

#### Sequence

```
Business App (register_all.py)          Registry                    Database
        |                                   |                          |
        |  1. register_agent(name,          |                          |
        |     display_name, materiality)    |                          |
        |---------------------------------->|  INSERT agent            |
        |                                   |------------------------->|
        |                                   |                          |
        |  2. register_agent_version(       |                          |
        |     agent_id, version=1.0.0,      |                          |
        |     inference_config_id,          |                          |
        |     output_schema, thresholds)    |                          |
        |---------------------------------->|  INSERT agent_version    |
        |                                   |  (lifecycle_state=draft) |
        |                                   |------------------------->|
        |                                   |                          |
        |  3. register_prompt_version(      |                          |
        |     prompt_id, content,           |                          |
        |     api_role="system")            |                          |
        |---------------------------------->|  Auto-extract {{vars}}   |
        |                                   |  from content via regex  |
        |                                   |  INSERT prompt_version   |
        |                                   |  (template_variables=[]) |
        |                                   |------------------------->|
        |                                   |                          |
        |  4. assign_prompt(                |                          |
        |     entity_type="agent",          |                          |
        |     entity_version_id,            |                          |
        |     prompt_version_id,            |                          |
        |     execution_order=1)            |                          |
        |---------------------------------->|  INSERT                  |
        |                                   |  entity_prompt_assignment|
        |                                   |------------------------->|
        |                                   |                          |
        |  5. authorize_agent_tool(         |                          |
        |     agent_version_id, tool_id)    |                          |
        |---------------------------------->|  INSERT                  |
        |   (repeat for each tool)          |  agent_version_tool      |
        |                                   |------------------------->|
        |                                   |                          |
        |  6. promote(AGENT, version_id,    |                          |
        |     target=CANDIDATE)             |                          |
        |---------------------------------->|                          |
        |                                   |  Lifecycle               |
        |                                   |     |                    |
        |                                   |     | UPDATE             |
        |                                   |     | agent_version      |
        |                                   |     | state=candidate    |
        |                                   |     |                    |
        |                                   |     | INSERT             |
        |                                   |     | approval_record    |
        |                                   |     |------------------->|
        |                                   |                          |
        |  7. promote(AGENT, version_id,    |                          |
        |     target=CHAMPION)              |                          |
        |---------------------------------->|                          |
        |                                   |  Lifecycle               |
        |                                   |     |                    |
        |                                   |     | Gate check:        |
        |                                   |     | (fast-track =      |
        |                                   |     |  minimal gates)    |
        |                                   |     |                    |
        |                                   |     | UPDATE             |
        |                                   |     | agent_version      |
        |                                   |     | state=champion     |
        |                                   |     | valid_from=NOW()   |
        |                                   |     | valid_to=2999-12-31|
        |                                   |     |                    |
        |                                   |     | Deprecate prior    |
        |                                   |     | champion (if any)  |
        |                                   |     | valid_to=NOW()     |
        |                                   |     |                    |
        |                                   |     | UPDATE agent       |
        |                                   |     | champion_ptr =     |
        |                                   |     | new_version_id     |
        |                                   |     |                    |
        |                                   |     | INSERT             |
        |                                   |     | approval_record    |
        |                                   |     |------------------->|
```

**Nuances:**
- Template variables in prompts are auto-extracted during registration. A prompt with `"Assess {{submission_id}} for {{lob}}"` automatically gets `template_variables = ['submission_id', 'lob']`.
- Champion promotion uses SCD Type 2: the new champion gets `valid_from=NOW(), valid_to=2999-12-31`. The prior champion gets `valid_to=NOW()` (end of its validity).
- The `agent.current_champion_version_id` pointer is updated for fast runtime resolution.

---

### 7.2 Agent Execution Flow (Live)

**Use case:** A business application runs an agent against real data, calling the Claude API and real tool implementations. Every call is logged to the decision trail.

**Input:** Agent name, context dict (business data), channel, execution_context_id.

**Output:** ExecutionResult with decision_log_id, structured output, tool calls, token usage, duration.

**Tables read:** agent, agent_version, inference_config, entity_prompt_assignment, prompt_version, agent_version_tool, tool.

**Tables written:** agent_decision_log (1 row per execution).

#### Sequence

```
Business App             Verity SDK              Registry          Claude API       Tools          Decisions
     |                       |                      |                  |              |                |
     | execute_agent(        |                      |                  |              |                |
     |   "triage_agent",     |                      |                  |              |                |
     |   context={...})      |                      |                  |              |                |
     |---------------------->|                      |                  |              |                |
     |                       |                      |                  |              |                |
     |                       | get_agent_config()   |                  |              |                |
     |                       |--------------------->|                  |              |                |
     |                       |                      | SQL: get_agent   |              |                |
     |                       |                      |   _champion      |              |                |
     |                       |                      | SQL: get_entity  |              |                |
     |                       |                      |   _prompts       |              |                |
     |                       |                      | SQL: get_entity  |              |                |
     |                       |                      |   _tools         |              |                |
     |                       |<- AgentConfig -------|                  |              |                |
     |                       |                      |                  |              |                |
     |                       | _assemble_prompts()  |                  |              |                |
     |                       | - validate {{vars}}  |                  |              |                |
     |                       | - substitute values  |                  |              |                |
     |                       | - split system/user  |                  |              |                |
     |                       |                      |                  |              |                |
     |                       |===== TURN 1 ========================================= |                |
     |                       |                      |                  |              |                |
     |                       | _gateway_llm_call()  |                  |              |                |
     |                       |-------------------------------->|       |              |                |
     |                       |                      |  messages.create |              |                |
     |                       |<--- response --------|----------|       |              |                |
     |                       |                      |                  |              |                |
     |                       | stop_reason="tool_use"                  |              |                |
     |                       |                      |                  |              |                |
     |                       | _gateway_tool_call("get_submission")    |              |                |
     |                       |------------------------------------------------>|      |                |
     |                       |                      |                  | get_sub()    |                |
     |                       |<--- tool result -----|------------------|------|        |                |
     |                       |                      |                  |              |                |
     |                       | Append tool result to messages                         |                |
     |                       |                      |                  |              |                |
     |                       |===== TURN 2 =========================================  |                |
     |                       |                      |                  |              |                |
     |                       | _gateway_llm_call()  |                  |              |                |
     |                       |-------------------------------->|       |              |                |
     |                       |<--- response --------|----------|       |              |                |
     |                       |                      |                  |              |                |
     |                       | stop_reason="end_turn"                  |              |                |
     |                       | Break loop                              |              |                |
     |                       |                      |                  |              |                |
     |                       | _log_decision()      |                  |              |                |
     |                       |------------------------------------------------------------------------>|
     |                       |                      |                  |              |  INSERT         |
     |                       |                      |                  |              |  agent_decision |
     |                       |                      |                  |              |  _log           |
     |                       |<- {decision_log_id} -|------------------|--------------|----------------|
     |                       |                      |                  |              |                |
     |<- ExecutionResult ----|                      |                  |              |                |
```

**What gets logged (31 columns):**
- Entity identity: entity_type, entity_version_id, prompt_version_ids[]
- Config snapshot: inference_config_snapshot (full JSONB copy, not just ID)
- Context: channel, pipeline_run_id, execution_context_id, step_name
- Input/Output: input_json, output_json, input_summary, output_summary, reasoning_text
- AI metrics: confidence_score, risk_factors, model_used, input_tokens, output_tokens, duration_ms
- Tool audit: tool_calls_made[] (every call with input and output)
- Replay data: message_history[] (full conversation for replay)
- Governance: run_purpose, mock_mode, application, status

---

### 7.3 Agent Execution Flow (Mocked)

**Use case:** Testing an agent without calling Claude API or real tools. Uses pre-built responses from MockContext.

**Alternate case A - Simple mock (skip entire loop):**

```
mock = MockContext(
    llm_responses=[{"risk_score": "Green", "confidence": 0.89}]
)
result = await verity.execute_agent("triage_agent", context, mock=mock)
```

```
Business App             Verity SDK
     |                       |
     | execute_agent(        |
     |   mock=MockContext)   |
     |---------------------->|
     |                       |
     |                       | get_agent_config()   (same as live)
     |                       |
     |                       | is_simple_mock?
     |                       | YES (1 response, not tool_use)
     |                       |
     |                       | output = mock.llm_responses[0]
     |                       |
     |                       | _log_decision(mock_mode=True)
     |                       |   (decision logged identically to live,
     |                       |    but mock_mode=True flag set)
     |                       |
     |<- ExecutionResult ----|
     |   (no Claude API call,
     |    no tool calls,
     |    instant return)
```

**Alternate case B - Replay mock (multi-turn with tool mocks):**

```
mock = MockContext(
    llm_responses=[
        [{"type": "tool_use", "name": "get_submission", ...}],  # Turn 1: tool request
        [{"type": "text", "text": '{"risk_score": "Green"}'}],  # Turn 2: final answer
    ],
    tool_responses={
        "get_submission": {"named_insured": "Acme Corp", ...},
    }
)
```

```
Business App             Verity SDK
     |                       |
     | execute_agent(mock)   |
     |---------------------->|
     |                       |
     |                       | is_simple_mock? NO (2 responses)
     |                       |
     |                       |== TURN 1 ==
     |                       | _gateway_llm_call(mock)
     |                       |   returns mock.llm_responses[0]   (tool_use)
     |                       |
     |                       | _gateway_tool_call("get_submission", mock)
     |                       |   returns mock.tool_responses["get_submission"]
     |                       |   (NO real tool call made)
     |                       |
     |                       |== TURN 2 ==
     |                       | _gateway_llm_call(mock)
     |                       |   returns mock.llm_responses[1]   (end_turn)
     |                       |
     |                       | _log_decision(mock_mode=True)
     |                       |
     |<- ExecutionResult ----|
```

**Alternate case C - Replay from prior decision:**

```
prior_decision = await verity.get_decision(decision_id)
mock = MockContext.from_decision_log(prior_decision, mock_llm=True, mock_tools=True)
result = await verity.execute_agent("triage_agent", context, mock=mock)
```

This reconstructs the mock from the stored decision's `message_history` (extracts assistant turns as LLM responses) and `tool_calls_made` (extracts tool outputs keyed by name).

---

### 7.4 Task Execution Flow

**Use case:** Single-turn structured output. No tool calling, no multi-turn loop.

**Input:** Task name, input_data dict.

**Output:** ExecutionResult with structured JSON output.

**Tables:** Same read tables as agent. Writes 1 row to agent_decision_log.

#### Sequence

```
Business App             Verity SDK              Claude API
     |                       |                       |
     | execute_task(          |                       |
     |   "document_classifier",                       |
     |   input_data={...})   |                       |
     |---------------------->|                       |
     |                       |                       |
     |                       | get_task_config()     |
     |                       | _assemble_prompts()   |
     |                       |                       |
     |                       | Check output_schema:  |
     |                       | Is it valid JSON Schema?
     |                       | YES -> use tool_choice|
     |                       |   to force structured |
     |                       |   output              |
     |                       |                       |
     |                       | Single LLM call       |
     |                       |---------------------->|
     |                       |<--- response ---------|
     |                       |                       |
     |                       | Extract from          |
     |                       | tool_use block        |
     |                       | (structured output)   |
     |                       |                       |
     |                       | _log_decision()       |
     |                       |                       |
     |<- ExecutionResult ----|
```

**Structured output nuance:** If the task has a valid JSON Schema in `output_schema`, Verity creates a synthetic tool called `"structured_output"` with that schema and forces Claude to call it via `tool_choice`. This guarantees the output matches the schema. If the schema is informal (e.g., `"revenue": "number"` instead of `"revenue": {"type": "number"}`), the tool_choice is skipped and Claude returns freeform text that's parsed as JSON.

---

### 7.5 Pipeline Execution Flow

**Use case:** Multi-step orchestration - run a sequence of agents and tasks as a governed unit.

**Input:** Pipeline name, context dict, optional mock.

**Output:** PipelineResult with per-step results, overall status, total duration.

**Tables read:** pipeline, pipeline_version (for step definitions), plus all tables from agent/task execution per step.

**Tables written:** agent_decision_log (1 row per step), all sharing the same pipeline_run_id.

#### Sequence

```
Business App        Pipeline Executor       Execution Engine        Database
     |                    |                       |                     |
     | execute_pipeline(  |                       |                     |
     |  "uw_submission")  |                       |                     |
     |------------------->|                       |                     |
     |                    |                       |                     |
     |                    | Generate pipeline_run_id (UUID)             |
     |                    |                       |                     |
     |                    | Load pipeline version |                     |
     |                    | Parse steps JSONB     |                     |
     |                    |                       |                     |
     |                    | Build execution groups|                     |
     |                    | (group by step_order) |                     |
     |                    |                       |                     |
     |                    |=== GROUP 1 (order=1) =|===================  |
     |                    |                       |                     |
     |                    | Build step_context:   |                     |
     |                    | original context      |                     |
     |                    | (no prior outputs yet)|                     |
     |                    |                       |                     |
     |                    | run_agent(            |                     |
     |                    |  "doc_classifier",    |                     |
     |                    |  context=step_context, |                    |
     |                    |  pipeline_run_id,     |                     |
     |                    |  step_name="classify") |                    |
     |                    |---------------------->|                     |
     |                    |                       | (full agent flow)   |
     |                    |<- StepResult ---------|                     |
     |                    |                       |                     |
     |                    | accumulated_results[  |                     |
     |                    |   "classify_documents"|                     |
     |                    | ] = step_result       |                     |
     |                    |                       |                     |
     |                    |=== GROUP 2 (order=2) =|===================  |
     |                    |                       |                     |
     |                    | Build step_context:   |                     |
     |                    | original context +    |                     |
     |                    | classify output       |                     |
     |                    | (step_context[        |                     |
     |                    |  "classify_documents"]|                     |
     |                    |  = prior output)      |                     |
     |                    |                       |                     |
     |                    | run_agent(            |                     |
     |                    |  "field_extractor",   |                     |
     |                    |  context=step_context) |                    |
     |                    |---------------------->|                     |
     |                    |<- StepResult ---------|                     |
     |                    |                       |                     |
     |                    | ... (repeat for steps 3, 4)                |
     |                    |                       |                     |
     |                    | Determine overall:    |                     |
     |                    | all complete? "complete"                    |
     |                    | any failed?   "partial"                     |
     |                    | pipeline_failed? "failed"                   |
     |                    |                       |                     |
     |<- PipelineResult --|                       |                     |
     |   (pipeline_run_id,|                       |                     |
     |    all_steps[],    |                       |                     |
     |    status,         |                       |                     |
     |    duration_ms)    |                       |                     |
```

**Context propagation nuance:** Each step receives the original pipeline context PLUS the output of every prior completed step, keyed by step_name. Step 3 (triage) sees: `context["classify_documents"] = {classifier output}`, `context["extract_fields"] = {extractor output}`, plus the original `context["submission_id"]`, `context["lob"]`, etc.

**Parallel execution nuance:** Steps with the same `step_order` run concurrently via `asyncio.gather()`. They all receive the same accumulated_results from prior groups. Their individual outputs are collected after all complete.

---

### 7.6 Lifecycle Promotion Flow (Full Gates)

**Use case:** Promoting a challenger version to champion after passing all validation gates. Requires evidence review by an approver.

**Input:** Entity type, version ID, target state, approver identity, evidence review flags.

**Output:** Approval record with from/to states.

**Tables read:** agent_version (current state + gate flags), agent (for prior champion lookup).

**Tables written:** agent_version (2 rows: new champion + deprecated prior), agent (champion pointer), approval_record.

#### Sequence

```
Governance User          Verity SDK              Lifecycle              Database
     |                       |                      |                      |
     | promote(              |                      |                      |
     |   AGENT,              |                      |                      |
     |   version_id,         |                      |                      |
     |   target=CHAMPION,    |                      |                      |
     |   approver="S.Chen",  |                      |                      |
     |   ground_truth_       |                      |                      |
     |     reviewed=True,    |                      |                      |
     |   model_card_         |                      |                      |
     |     reviewed=True,    |                      |                      |
     |   challenger_metrics_ |                      |                      |
     |     reviewed=True)    |                      |                      |
     |---------------------->|                      |                      |
     |                       |--------------------->|                      |
     |                       |                      |                      |
     |                       |                      | 1. Fetch version     |
     |                       |                      | SQL: get_agent_version
     |                       |                      |--------------------->|
     |                       |                      | state = "challenger" |
     |                       |                      |                      |
     |                       |                      | 2. Validate          |
     |                       |                      | transition:          |
     |                       |                      | challenger->champion |
     |                       |                      | IS VALID             |
     |                       |                      |                      |
     |                       |                      | 3. Check gates:      |
     |                       |                      | ground_truth_passed? |
     |                       |                      |   YES (version flag) |
     |                       |                      | ground_truth_reviewed|
     |                       |                      |   YES (request flag) |
     |                       |                      | model_card_reviewed? |
     |                       |                      |   YES (request flag) |
     |                       |                      | challenger_metrics   |
     |                       |                      |   _reviewed? YES     |
     |                       |                      | Gates: PASS          |
     |                       |                      |                      |
     |                       |                      | 4. Update version    |
     |                       |                      | SQL: update_agent_   |
     |                       |                      |   version_state      |
     |                       |                      | state=champion       |
     |                       |                      | channel=production   |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |                       |                      | 5. Set champion      |
     |                       |                      | SQL: get_current_    |
     |                       |                      |   champion (prior)   |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |                       |                      | SQL: deprecate_agent |
     |                       |                      |   _version (prior)   |
     |                       |                      | valid_to=NOW()       |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |                       |                      | SQL: set_agent_      |
     |                       |                      |   champion (new)     |
     |                       |                      | valid_from=NOW()     |
     |                       |                      | valid_to=2999-12-31  |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |                       |                      | 6. Approval record   |
     |                       |                      | SQL: create_approval |
     |                       |                      |   _record            |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |<- approval_record ----|<---------------------|                      |
```

**Gate check nuance:** Two sources of evidence are checked:
1. **Version flags** (on `agent_version`): `ground_truth_passed`, `staging_tests_passed`, `shadow_period_complete` - set by the validation/testing framework after tests run.
2. **Request flags** (on `PromotionRequest`): `ground_truth_reviewed`, `model_card_reviewed`, `challenger_metrics_reviewed` - asserted by the approver at promotion time.

Both must be true. The version must have passed the tests AND the approver must confirm they reviewed the results.

---

### 7.7 Config Resolution Flow (Date-Pinned)

**Use case:** Regulatory audit - need to know exactly which agent version was running on a specific historical date.

**Input:** Agent name, effective_date (e.g., "2026-03-15").

**Output:** AgentConfig with the version that was champion on that date.

#### Sequence

```
Auditor                  Verity SDK              Registry               Database
     |                       |                      |                      |
     | get_agent_config(     |                      |                      |
     |   "triage_agent",     |                      |                      |
     |   effective_date=     |                      |                      |
     |   "2026-03-15")       |                      |                      |
     |---------------------->|                      |                      |
     |                       |--------------------->|                      |
     |                       |                      |                      |
     |                       |                      | SQL: get_agent_      |
     |                       |                      |   champion_at_date   |
     |                       |                      |                      |
     |                       |                      | WHERE agent.name =   |
     |                       |                      |   'triage_agent'     |
     |                       |                      | AND av.valid_from <= |
     |                       |                      |   '2026-03-15'       |
     |                       |                      | AND av.valid_to >    |
     |                       |                      |   '2026-03-15'       |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |                       |                      | Returns: v1.0.0      |
     |                       |                      | (was champion from   |
     |                       |                      |  2026-03-01 to       |
     |                       |                      |  2026-04-15 when     |
     |                       |                      |  v2.0.0 took over)   |
     |                       |                      |                      |
     |                       |                      | Assemble full config |
     |                       |                      | (prompts, tools,     |
     |                       |                      |  inference config    |
     |                       |                      |  from that version)  |
     |                       |                      |                      |
     |<- AgentConfig --------|<---------------------|                      |
     |   (v1.0.0 as of       |                      |                      |
     |    March 15, 2026)    |                      |                      |
```

**SCD Type 2 nuance:** Only champion versions have `valid_from`/`valid_to` set. Pre-champion versions (draft, candidate, staging, etc.) have NULL dates and are never returned by temporal queries. This means the temporal query always returns the version that was actually in production on that date.

**Three resolution modes compared:**

| Mode | When to Use | Speed | SQL Query |
|------|------------|-------|-----------|
| Default (champion) | Runtime execution | Fastest (pointer follow) | get_agent_champion |
| Date-pinned | Audit, regulatory | Medium (date range scan) | get_agent_champion_at_date |
| Version-pinned | Replay, debugging | Fast (PK lookup) | get_agent_version_by_id |

---

### 7.8 Audit Replay Flow

**Use case:** Compliance officer needs to reproduce a prior decision to verify it was correct, using the exact same inputs and configuration.

**Input:** Original decision_id.

**Output:** New ExecutionResult that should match the original (if deterministic).

#### Sequence

```
Compliance Officer       Verity SDK              Mock Context         Execution
     |                       |                      |                    |
     | 1. get_decision(      |                      |                    |
     |    decision_id)       |                      |                    |
     |---------------------->|                      |                    |
     |<- DecisionLogDetail --|                      |                    |
     |   (full snapshot:     |                      |                    |
     |    message_history,   |                      |                    |
     |    tool_calls_made,   |                      |                    |
     |    input_json, etc.)  |                      |                    |
     |                       |                      |                    |
     | 2. MockContext.from_  |                      |                    |
     |    decision_log(      |                      |                    |
     |    decision,          |                      |                    |
     |    mock_llm=True,     |                      |                    |
     |    mock_tools=True)   |                      |                    |
     |---------------------->|--------------------->|                    |
     |                       |                      |                    |
     |                       |  Rebuild llm_responses:                   |
     |                       |  Extract all assistant turns              |
     |                       |  from message_history                     |
     |                       |                      |                    |
     |                       |  Rebuild tool_responses:                  |
     |                       |  Extract outputs from                     |
     |                       |  tool_calls_made, key by name             |
     |                       |                      |                    |
     |<- MockContext ------  |<---------------------|                    |
     |                       |                      |                    |
     | 3. execute_agent(     |                      |                    |
     |    "triage_agent",    |                      |                    |
     |    context=decision   |                      |                    |
     |      .input_json,     |                      |                    |
     |    mock=mock,         |                      |                    |
     |    execution_context  |                      |                    |
     |      _id=rerun_ctx)   |                      |                    |
     |---------------------->|                      |                    |
     |                       |                      |                    |
     |                       | run_agent(mock=mock) |                    |
     |                       |--------------------------------------------->|
     |                       |                      |                    |
     |                       | (Replays exact sequence:                  |
     |                       |  Turn 1: mock LLM returns tool_use       |
     |                       |  Tool call: mock returns stored result    |
     |                       |  Turn 2: mock LLM returns final answer)  |
     |                       |                      |                    |
     |                       | _log_decision(                            |
     |                       |   run_purpose="audit_rerun",              |
     |                       |   reproduced_from_decision_id=            |
     |                       |     original_decision_id,                 |
     |                       |   application="compliance_audit")         |
     |                       |                      |                    |
     |<- ExecutionResult ----|                      |                    |
     |                       |                      |                    |
     | 4. Compare original   |                      |                    |
     |    output vs replay   |                      |                    |
     |    output             |                      |                    |
```

**Replay nuance:** The replayed decision is logged as a NEW decision with `run_purpose=audit_rerun` and `reproduced_from_decision_id` pointing to the original. This creates a direct FK link for auditors to compare. The original decision is never modified.

**Three replay patterns:**

| mock_llm | mock_tools | What it tests |
|----------|-----------|---------------|
| True | True | Full replay - verify audit trail is reproducible |
| False | True | New prompt test - same tool data, different reasoning |
| True | False | New tool test - same reasoning, different data source |

---

### 7.9 Override Recording Flow

**Use case:** An underwriter disagrees with the AI's risk assessment and overrides it. Both the AI recommendation and the human decision must be preserved.

**Input:** Decision log ID, overrider identity, AI recommendation, human decision, reason code.

**Output:** Override record linked to the original decision.

**Tables written:** override_log (1 row).

#### Sequence

```
Underwriter              Business App            Verity SDK             Database
     |                       |                      |                      |
     | "I disagree with      |                      |                      |
     |  the Red score.       |                      |                      |
     |  This should be       |                      |                      |
     |  Amber."              |                      |                      |
     |---------------------->|                      |                      |
     |                       |                      |                      |
     |                       | record_override(     |                      |
     |                       |   OverrideLogCreate( |                      |
     |                       |     decision_log_id, |                      |
     |                       |     entity_type=AGENT|                      |
     |                       |     entity_version_id|                      |
     |                       |     overrider_name=  |                      |
     |                       |       "Lisa Wong",   |                      |
     |                       |     overrider_role=  |                      |
     |                       |       "Sr UW",       |                      |
     |                       |     override_reason  |                      |
     |                       |       _code=         |                      |
     |                       |       "risk_disagree"|                      |
     |                       |     ai_recommendation|                      |
     |                       |       ={"risk_score":|                      |
     |                       |         "Red"},      |                      |
     |                       |     human_decision=  |                      |
     |                       |       {"risk_score": |                      |
     |                       |         "Amber"},    |                      |
     |                       |   ))                 |                      |
     |                       |--------------------->|                      |
     |                       |                      | SQL: record_override |
     |                       |                      | INSERT override_log  |
     |                       |                      |--------------------->|
     |                       |                      |                      |
     |                       |<- {override_id} -----|                      |
     |<- "Override recorded" |                      |                      |
```

**Audit trail nuance:** The override links to the original decision via `decision_log_id`. A query for the business context shows both: the AI's decision AND the human override, with the override's reason code explaining why they diverged.

---

## 8. Data Model Reference

The 33 tables are organized into 6 functional groups. An Excalidraw diagram (`verity_db.excalidraw`) provides the visual ER view. This section documents the key relationships and JSONB field schemas.

### 8.1 Key Foreign Key Relationships

```
agent --(1:N)--> agent_version --(N:1)--> inference_config
                      |
                      +--(N:M via entity_prompt_assignment)--> prompt_version --> prompt
                      |
                      +--(N:M via agent_version_tool)--> tool

task  --(1:N)--> task_version  --(N:1)--> inference_config
                      |
                      +--(N:M via entity_prompt_assignment)--> prompt_version --> prompt
                      |
                      +--(N:M via task_version_tool)--> tool

pipeline --(1:N)--> pipeline_version (steps stored as JSONB, not FK)

application --(1:N)--> application_entity (maps to agent, task, tool, prompt, pipeline)
            --(1:N)--> execution_context

agent_decision_log --(N:1)--> execution_context
                   --(self)--> parent_decision_id (for sub-agent hierarchy)
                   --(self)--> reproduced_from_decision_id (for audit replay)

override_log --(N:1)--> agent_decision_log (via decision_log_id)

approval_record: no FK to version tables (entity_type + entity_version_id as soft FK)

ground_truth_dataset --(1:N)--> ground_truth_record --(1:N)--> ground_truth_annotation
validation_run --(N:1)--> ground_truth_dataset
validation_record_result --(N:1)--> validation_run
                         --(N:1)--> ground_truth_record
```

### 8.2 JSONB Field Schemas

| Table.Column | Structure | Example |
|---|---|---|
| agent_version.output_schema | JSON Schema for agent output | `{"risk_score": {"type": "string"}, "confidence": {"type": "number"}}` |
| agent_version.authority_thresholds | Decision thresholds by category | `{"auto_approve_below": 0.7, "require_hitl_above": 0.9}` |
| pipeline_version.steps | Array of PipelineStep objects | `[{"step_name": "classify", "entity_type": "agent", "entity_name": "doc_classifier", "step_order": 1, "depends_on": []}]` |
| entity_prompt_assignment.condition_logic | Conditional prompt inclusion rules | `{"if_lob": "DO"}` or `null` (always include) |
| tool.input_schema | JSON Schema for tool parameters | `{"type": "object", "properties": {"context_ref": {"type": "string"}}, "required": ["context_ref"]}` |
| tool.mock_responses | Mock data keyed by scenario | `{"default": {"status": "success", "data": {...}}}` |
| agent_decision_log.inference_config_snapshot | Full config copy at execution time | `{"model_name": "claude-sonnet-4-6", "temperature": 0.2, "max_tokens": 4096}` |
| agent_decision_log.tool_calls_made | Array of tool call records | `[{"tool_name": "get_submission", "call_order": 1, "input_data": {...}, "output_data": {...}, "mock_mode": false}]` |
| agent_decision_log.message_history | Full Claude conversation | `[{"role": "user", "content": "..."}, {"role": "assistant", "content": [{"type": "tool_use", ...}]}]` |
| ground_truth_annotation.expected_output | Annotator's answer (matches entity output schema) | `{"document_type": "do_application", "confidence": 0.97}` |
| validation_run.confusion_matrix | Classification results | `{"labels": ["do_app", "gl_app"], "matrix": [[48, 2], [1, 49]], "per_class": {...}}` |
| validation_run.field_accuracy | Extraction results | `{"per_field": {"named_insured": {"correct": 48, "total": 50, "accuracy": 0.96}}, "overall_accuracy": 0.91}` |
| execution_context.metadata | Business context (opaque to Verity) | `{"named_insured": "Acme Corp", "lob": "DO"}` |

---

## 9. Error Handling

### 9.1 Claude API Errors

**Where:** `_gateway_llm_call()` in execution.py.

**Behavior:** If the Claude API call throws (network error, rate limit, invalid request), the exception propagates up to the `run_agent()` or `run_task()` try/except block.

```
_gateway_llm_call() throws
    |
    v
run_agent() catches Exception:
    1. Calculates duration_ms
    2. Logs a FAILED decision to agent_decision_log:
       - status = "failed"
       - error_message = str(exception)
       - output = {} (empty)
       - tool_calls_made = [] (whatever completed before failure)
    3. Returns ExecutionResult(status="failed", error_message=...)
```

**What this means:**
- Failed API calls ARE logged to the decision trail (with status="failed")
- The caller (pipeline executor or business app) sees a failed ExecutionResult
- No retry. No fallback. The call fails once and that's it.
- If failure happens mid-loop (e.g., turn 3 of 10), all prior tool calls are lost from the log - only the error is recorded.

**Known gap:** If the _log_decision() call itself fails (database down), the error is unhandled and propagates as an unstructured exception. There is no circuit breaker.

### 9.2 Tool Execution Errors

**Where:** `_execute_real_tool()` and `_gateway_tool_call()` in execution.py.

**Behavior:** Tool exceptions are caught and converted to error responses:

```
_execute_real_tool() catches Exception:
    Returns: {
        "tool_name": name,
        "output_data": {"error": "Tool execution failed: <message>"},
        "error": True
    }
```

This error response is sent back to Claude as a `tool_result` with `is_error=True`. Claude sees the error and can:
- Retry the tool call (next turn)
- Provide a final answer noting the tool failure
- Call a different tool

**What this means:**
- Tool failures do NOT crash the agent loop
- Claude receives the error and decides how to proceed
- The error is visible in tool_calls_made in the decision log
- If ALL tools fail, Claude will eventually produce a final answer (likely low confidence) or hit the 10-turn limit

### 9.3 Database Errors

**Where:** All Database methods in connection.py.

**Behavior:** Database errors from psycopg propagate as unhandled exceptions. The connection pool (`AsyncConnectionPool`) handles connection lifecycle:

```
async with self._pool.connection() as conn:
    cursor = await conn.execute(sql, params)
```

The `async with` block checks out a connection from the pool and returns it when done (or on exception). The pool handles:
- Connection recycling (stale connections are replaced)
- Connection validation on checkout
- Pool exhaustion (blocks until a connection is available, up to pool timeout)

**What is NOT handled:**
- Database down at startup: `await db.connect()` throws, app fails to start. No retry.
- Database down mid-operation: Query throws `psycopg.OperationalError`, propagates to caller.
- Connection pool exhaustion: Blocks, then times out with `PoolTimeout`.
- No graceful degradation. If the database is unreachable, all operations fail.

### 9.4 Prompt Validation Errors

**Where:** `_assemble_prompts()` in execution.py.

**Behavior:** If a prompt declares template variables (e.g., `template_variables = ['document_text']`) and the context dict doesn't contain that key, a `ValueError` is raised immediately:

```
ValueError: Prompt 'doc_classifier_input' requires template variables
['document_text'] but they are not in the execution context.
Available context keys: ['lob', 'named_insured', 'submission_id']
```

This happens BEFORE any Claude API call, so no tokens are wasted.

### 9.5 Lifecycle Validation Errors

**Where:** `promote()` in lifecycle.py.

**Behavior:** Two types of validation errors:

1. **Invalid transition:** Attempting a transition not in VALID_TRANSITIONS:
   ```
   ValueError: Invalid transition: draft -> champion.
   Valid targets: ['candidate']
   ```

2. **Gate requirements not met:** Evidence flags are false:
   ```
   ValueError: Promotion gate requirements not met:
   Ground truth validation has not passed; Model card not reviewed by approver
   ```

Both raise ValueError before any database writes. The version state is unchanged.

### 9.6 Error Handling Summary

| Error Source | Caught? | Logged to Decision Trail? | Retried? | Impact |
|---|---|---|---|---|
| Claude API failure | Yes (in run_agent/run_task) | Yes (status="failed") | No | ExecutionResult with status="failed" |
| Tool execution failure | Yes (in _execute_real_tool) | Tool error sent to Claude | No (Claude may retry) | Claude sees error, decides next action |
| Database failure | No (propagates) | No | No | Unstructured exception to caller |
| Decision logging failure | No (propagates) | N/A | No | Execution result lost |
| Template variable missing | Yes (ValueError) | No (fails before execution) | No | Clear error message |
| Invalid lifecycle transition | Yes (ValueError) | No | No | Promotion rejected |
| Config not found | Yes (ValueError) | No | No | Agent/task cannot execute |

---

## 10. Concurrency and Thread Safety

### 10.1 Async Architecture

Verity is fully async (Python asyncio). The FastAPI server runs on a single event loop. All I/O operations (database, Claude API, tool calls) use `await` and yield the event loop during waits.

```
One Python process
    |
    +-- One asyncio event loop
    |       |
    |       +-- FastAPI request handlers (concurrent via async)
    |       +-- Claude API calls (concurrent via AsyncAnthropic)
    |       +-- Database queries (concurrent via AsyncConnectionPool)
    |       +-- Tool implementations (concurrent if async, blocking if sync)
    |
    +-- No threading, no multiprocessing
```

### 10.2 Database Concurrency

**Connection pool:** `AsyncConnectionPool(min_size=2, max_size=10)`. Up to 10 concurrent database operations. The 11th request blocks until a connection is available.

**Transaction isolation:** Each Database method (`fetch_one`, `execute_returning`, etc.) checks out a connection, executes, and returns it. There are no explicit transactions spanning multiple operations.

**Race condition: champion promotion.** If two promotions execute concurrently for the same entity:
1. Both call `get_current_champion_agent_version` - both see the same prior champion
2. Both call `deprecate_agent_version` on the prior - one succeeds, one is a no-op (already deprecated)
3. Both call `set_agent_champion` - last one wins

**Impact:** The champion pointer could be set to a version that didn't properly deprecate its predecessor. No database-level locking prevents this. The risk is low in practice (promotions are human-initiated, not automated) but exists.

**No explicit transactions:** The registration flow (insert agent, insert version, assign prompts, authorize tools) is not wrapped in a transaction. If the process crashes between steps, partial registration data exists. The seed script is idempotent and re-runnable to recover.

### 10.3 Claude API Concurrency

**AsyncAnthropic client:** Uses httpx under the hood with connection pooling. Multiple concurrent Claude API calls are supported.

**Pipeline parallelism:** When a pipeline group has multiple steps with the same `step_order`, they execute via `asyncio.gather()`. This means multiple Claude API calls run concurrently - one per parallel step.

**Rate limiting:** Not handled by Verity. If the Claude API returns a rate limit error (429), it propagates as an exception. No backoff, no retry queue. The caller (pipeline executor) sees a failed step.

### 10.4 Tool Call Concurrency

**Within one agent turn:** Tool calls within a single response are executed sequentially (for loop over `response.content` blocks). Even if Claude requests 3 tools in one turn, they run one at a time.

**Across pipeline steps:** Parallel pipeline steps each run their own agent loop, so their tool calls run concurrently via `asyncio.gather()`.

**Sync tool implementations:** If a registered tool implementation is synchronous (not async), it blocks the event loop during execution. For I/O-heavy tools (database queries, HTTP calls), this blocks ALL other concurrent operations until the tool returns. Always register async tool implementations.

---

## 11. Configuration and Environment

### 11.1 Environment Variables

| Variable | Default | Used By | Purpose |
|----------|---------|---------|---------|
| `VERITY_DB_URL` | `postgresql://verityuser:veritypass123@localhost:5432/verity_db` | verity/main.py, uw_demo config | PostgreSQL connection URL |
| `ANTHROPIC_API_KEY` | `""` (empty) | uw_demo config | Claude API key for live execution |
| `APP_ENV` | `demo` | uw_demo config | Environment identifier |
| `LOG_LEVEL` | `INFO` | verity/logging.py | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `LOG_FORMAT` | `json` | verity/logging.py | Log format: `json` or `text` |
| `LOG_FILE_ENABLED` | `false` | verity/logging.py | Write logs to file |
| `LOG_DIR` | `./logs` | verity/logging.py | Log file directory |

### 11.2 .env File Loading

Both verity/main.py and uw_demo/config.py load `.env` from `Path.cwd()` (the current working directory at startup). Environment variables set by Docker take priority - the `.env` file only fills in values not already in `os.environ`.

### 11.3 Missing API Key Behavior

If `ANTHROPIC_API_KEY` is empty or not set:
- The `AsyncAnthropic` client is initialized with an empty string
- Live execution calls to Claude API fail with an authentication error
- Mock mode works fine (no API call made)
- The error propagates as a failed execution, logged to the decision trail

### 11.4 Database URL Behavior

If `VERITY_DB_URL` is wrong or the database is unreachable:
- `await verity.connect()` fails during app startup
- FastAPI lifespan raises the exception
- The container exits and Docker restarts it (restart: unless-stopped)
- No retry logic on startup

---

## 12. Known Limitations

### 12.1 Scale Limitations

| Area | Limitation | Impact |
|------|-----------|--------|
| List queries | Most have no pagination (return all rows) | Will slow down with >1000 entities |
| Dashboard queries | Full table scans with GROUP BY | Slow with >10K decisions |
| Decision log | Every AI call creates a row with JSONB columns | Table grows linearly; no archival strategy |
| Connection pool | max_size=10 | Cannot exceed 10 concurrent database operations |
| Pipeline execution | Synchronous on request thread | Long pipelines block the HTTP response |
| No caching | Every request queries the database | Config resolution for every execution adds latency |

### 12.2 Missing Infrastructure

| Feature | Status | Impact |
|---------|--------|--------|
| Authentication | None | Any network-accessible client can call any endpoint |
| Authorization | None | No role-based access (who can promote, who can override) |
| Rate limiting | None | No protection against API abuse |
| Background jobs | None | All operations synchronous on request thread |
| Retry logic | None | Single failure = permanent failure |
| Circuit breaker | None | Cascading failures possible if database or Claude API is down |
| Health checks | Basic (`/health` returns 200) | No deep health (database connectivity, pool status) |
| Metrics/telemetry | Logging only | No Prometheus, no OpenTelemetry |
| Data encryption | None | Database, MinIO, and network traffic unencrypted |

### 12.3 Functional Gaps

| Gap | Description |
|-----|-------------|
| Tool calls sequential within a turn | Claude may request 3 tools, but they execute one at a time |
| Streaming not consumed by UI | Runtime emits `ExecutionEvent` but the admin UI does not stream live — users wait for completion |
| No cleanup / archival strategy | Decision log, model_invocation_log, test results grow forever |
| pgvector unused | Embedding columns exist but are always NULL; similarity checks not implemented |
| Soft quotas only | Breaches surface on Incidents but do not block invocation |
| Price edits apply going forward only (by design) | SCD-2 means a pricing mistake cannot be retroactively corrected by editing — requires issuing a corrected price row with a backdated `effective_from`, which itself is a governance event worth noting |

---

## 13. Integration Contract

### 13.1 Integrating a New Business Application

A new business application (e.g., Claims App) integrates with Verity in 5 steps:

**Step 1: Install Verity SDK**

```bash
pip install -e verity/
```

The Verity package is installed into the app's Python environment. No separate server needed for SDK mode.

**Step 2: Initialize the Client**

```python
from verity import Verity

verity = Verity(
    database_url="postgresql://...@.../verity_db",  # Same verity_db
    anthropic_api_key="sk-ant-...",                  # App's own key
    application="claims_app",                         # App identity
)
await verity.connect()
```

All apps share the same `verity_db` database. The `application` parameter identifies this app in the decision trail.

**Step 3: Register the Application**

```python
await verity.register_application(
    name="claims_app",
    display_name="Claims Processing Application",
    description="Automated claims triage and assessment",
)
```

This creates a row in the `application` table. The app can then map entities and create execution contexts.

**Step 4: Register Tool Implementations**

```python
verity.register_tool_implementation("get_claim_data", get_claim_data)
verity.register_tool_implementation("get_policy_details", get_policy_details)
```

Tool implementations are Python functions (sync or async) that the app provides. They run in the app's process. Verity calls them by name when Claude requests a tool.

**Step 5: Execute Agents**

```python
# Create execution context (links decisions to business operation)
ctx = await verity.create_execution_context(
    context_ref="claim:CLM-2026-001",
    context_type="claim",
    metadata={"claimant": "John Doe", "policy_number": "POL-123"},
)

# Run an agent
result = await verity.execute_agent(
    agent_name="claims_triage",
    context={"claim_id": "CLM-2026-001", "loss_type": "auto"},
    execution_context_id=ctx["id"],
)
```

### 13.2 Tool Implementation Requirements

Tool implementations must conform to this contract:

```python
# Async (preferred) - does not block the event loop
async def get_claim_data(claim_id: str) -> dict:
    # Fetch from database, call API, etc.
    return {"claimant": "John Doe", "loss_amount": 15000, ...}

# Sync (allowed but blocks) - use only for CPU-bound operations
def calculate_score(factors: dict) -> dict:
    return {"score": 0.85}
```

**Input:** The tool receives keyword arguments matching the `input_schema` defined when the tool was registered in Verity. Claude provides these arguments.

**Output:** Must return a JSON-serializable dict. This dict is:
1. Sent back to Claude as a `tool_result` message
2. Stored in `agent_decision_log.tool_calls_made` for audit

**Error handling:** If the tool raises an exception, Verity catches it and sends an error response to Claude:
```json
{"error": "Tool execution failed: <exception message>"}
```
Claude sees this and decides whether to retry or provide a final answer.

**Async strongly recommended:** Sync tool implementations block the entire event loop. A 2-second database query in a sync tool blocks ALL other concurrent requests for 2 seconds.

### 13.3 Minimum Viable Integration

The simplest possible integration:

```python
from verity import Verity

verity = Verity(database_url="postgresql://...", application="my_app")
await verity.connect()

# Assume agents are already registered (by a seed script or another app)
result = await verity.execution.run_agent("existing_agent", context={"key": "value"})
print(result.output)  # The agent's structured output
print(result.decision_log_id)  # UUID of the audit record
```

No tool registration needed if the agent doesn't use tools. No application registration needed if you don't need execution context grouping. No lifecycle management needed if you use existing champion versions.

### 13.4 Integration Over the REST API

An out-of-process consumer (a notebook, a non-Python service, an external orchestrator) integrates via `/api/v1/*` instead of importing the SDK.

```python
import httpx

api = httpx.Client(base_url="http://verity:8000")

# Register / map application (idempotent patterns)
api.post("/api/v1/applications",
         json={"name": "my_app", "display_name": "My App"})

# Run a champion agent
r = api.post("/api/v1/runtime/agents/triage_agent/run",
             json={"context": {"submission_id": "SUB-001"},
                   "application": "my_app"})
r.raise_for_status()
out = r.json()
print(out["output"], out["decision_log_id"])
```

**Notes:**
- Every POST `/runtime/*` endpoint accepts an `application` override in the body; if omitted, the decision is tagged with the Verity process default. This is how the `ds-workbench` JupyterLab service attributes all its activity to the `ds_workbench` application.
- Tool implementations must still live somewhere executable. For REST-only consumers that don't host Python tools, the tools must be MCP-served (registered as `mcp://` tools) or the agent must not require tools.
- Full Swagger UI at `/api/v1/docs` enumerates the ~78 operations.

---

## 14. Testing, Validation & Lifecycle Components

Three runtime modules implement the VERIFY pillar: metrics computation, test execution, and ground truth validation. They complete the governance loop from asset registration through validation to promotion.

### 14.1 Metrics Engine (`runtime/metrics.py`)

Pure computation module. No database access, no I/O. Implements all metrics from scratch for regulatory auditability (no sklearn dependency).

**Functions:**

| Function | Input | Output | Used By |
|----------|-------|--------|---------|
| `classification_metrics(actual, expected)` | Two lists of label strings | precision, recall, F1 (macro), Cohen's kappa, confusion matrix, per_class breakdown | Validation runner (classification entities) |
| `field_accuracy(actual_fields, expected_fields, field_configs)` | Two dicts of field values + optional tolerance configs | per_field accuracy, overall_accuracy, missing/extra fields | Validation runner (extraction entities) |
| `exact_match(actual, expected)` | Two values (any type) | matched (bool), differences (list) | Test runner (default metric) |
| `schema_valid(output, schema)` | Dict + schema dict | valid (bool), errors (list) | Test runner (schema metric) |
| `check_thresholds(metrics, thresholds)` | Metrics dict + threshold list | all_passed, per-threshold details | Validation runner (gate check) |

**Classification metrics implementation:**
- Builds confusion matrix from label pairs
- Per-class: TP, FP, FN, precision, recall, F1
- Macro F1 = unweighted mean across classes
- Cohen's kappa: `(observed_agreement - expected_agreement) / (1 - expected_agreement)`

**Field accuracy with tolerance:**
- Supports match types: `exact`, `case_insensitive`, `contains`, `numeric_tolerance`
- Numeric tolerance: percent-based (default 5%) or absolute
- Normalizes `{value: "Acme", confidence: 0.95}` dicts to plain values before comparison
- Tracks missing fields (in expected but not actual) and extra fields separately

### 14.2 Test Runner (`runtime/test_runner.py`)

Executes test suites against entity versions using the SAME execution path as production. MockContext controls what's mocked.

**Key design:** Test cases use the expected output as the mock LLM response. This means:
- When `mock_llm=True`: Claude is not called, the expected output is returned as if Claude said it, then metrics are computed to verify the execution path works correctly
- When `mock_llm=False`: Claude is called for real (costs money), output is compared against expected

```
TestRunner.run_suite(entity_type, entity_version_id, suite_id, mock_llm=True)
    |
    +-- Load test cases from test_case table
    +-- For each case:
    |     +-- Build MockContext(llm_responses=[expected_output], mock_all_tools=True)
    |     +-- Call execution_engine.run_agent() or run_task()
    |     |   (full execution path: config resolution, prompt assembly, gateway calls)
    |     +-- Compare actual_output vs expected_output using metric_type:
    |     |     classification_f1 -> classification_metrics()
    |     |     field_accuracy -> field_accuracy()
    |     |     schema_valid -> schema_valid()
    |     |     exact_match -> exact_match()
    |     +-- Log result to test_execution_log
    |
    +-- Return SuiteResult(passed_cases, failed_cases, pass_rate, case_results[])
```

**Result types:**
- `CaseResult`: test_case_id, passed, actual_output, expected_output, metric_type, metric_result, duration_ms, failure_reason
- `SuiteResult`: suite_id, total_cases, passed_cases, pass_rate, case_results[], passed (all cases passed)

**Tables read:** test_suite, test_case, plus all tables from agent/task config resolution.
**Tables written:** test_execution_log (1 row per case), agent_decision_log (1 row per case execution).

### 14.3 Validation Runner (`runtime/validation_runner.py`)

Validates entity versions against ground truth datasets. More comprehensive than test runner: runs against every record in a dataset, computes aggregate metrics, checks thresholds, stores per-record results.

**Flow:**

```
ValidationRunner.run_validation(entity_type, entity_version_id, dataset_id, run_by)
    |
    +-- Load dataset metadata from ground_truth_dataset
    +-- Load authoritative annotations:
    |     JOIN ground_truth_record + ground_truth_annotation
    |     WHERE is_authoritative = TRUE
    |
    +-- For each record:
    |     +-- Build MockContext from record.tool_mock_overrides
    |     +-- Execute entity (agent or task)
    |     +-- Compare output to annotation.expected_output:
    |     |     Classification: label match on document_type/risk_score/determination
    |     |     Extraction: field_accuracy() with 80% threshold for "correct"
    |     +-- Collect actual/expected labels for aggregate metrics
    |
    +-- Compute aggregate metrics:
    |     Classification: classification_metrics(all_actual_labels, all_expected_labels)
    |     Extraction: field_accuracy(combined_fields) + field_extraction_configs
    |
    +-- Check metric thresholds from metric_threshold table
    |     check_thresholds(metrics, thresholds) -> all_passed
    |
    +-- Store validation_run record (aggregate metrics, threshold results)
    +-- Store validation_record_result per record (for drill-down)
    |
    +-- Return ValidationResult(precision, recall, f1, kappa, thresholds_met, per_record_results[])
```

**Ground truth integration with EDMS:**
The ground_truth_record table has `source_provider`, `source_container`, `source_key` fields for storage-abstracted document references. Records can point to documents stored in EDMS collections. The `input_data` JSONB contains what gets fed to the entity during validation. For document-based tasks (classifier, extractor), this includes the document text extracted by EDMS.

**Result types:**
- `RecordResult`: record_id, expected_output, actual_output, correct, match_score, confidence, field_results, decision_log_id
- `ValidationResult`: validation_run_id, total_records, correct_records, precision, recall, f1, kappa, thresholds_met, per_record_results[], passed

**Tables read:** ground_truth_dataset, ground_truth_record, ground_truth_annotation, metric_threshold, field_extraction_config.
**Tables written:** validation_run (1 row), validation_record_result (1 row per record), agent_decision_log (1 row per record execution).

### 14.4 Decision Log Detail Levels

A new `decision_log_detail` column on `agent_version` and `task_version` controls how much data is captured per decision. This is set per entity version as a governance policy.

| Level | What's Captured | Use Case |
|-------|----------------|----------|
| `full` | Complete payload: input, output, message history, tool calls, all JSONB | Audit, regulatory compliance, high-materiality entities |
| `standard` | Binary content redacted, large text truncated, tool payloads summarized | Default for most entities |
| `summary` | First 500 chars of input/output only, no message history | Low-materiality, high-volume entities |
| `metadata` | Status, tokens, duration only - no payload data | Operational monitoring only |
| `none` | No decision log entry created | Testing/development only |

The `agent_decision_log` table now has:
- `decision_log_detail VARCHAR(20)` - which level was applied
- `redaction_applied JSONB` - what was redacted (null if nothing)

### 14.5 Platform Settings

A new `platform_settings` table stores Verity-wide configuration as key-value pairs. Read at runtime - no restart needed to change settings.

```sql
CREATE TABLE platform_settings (
    key          TEXT PRIMARY KEY,
    value        TEXT NOT NULL,
    category     TEXT NOT NULL DEFAULT 'general',
    display_name TEXT,
    description  TEXT,
    input_type   TEXT DEFAULT 'text',  -- text, select, number
    options      TEXT,                 -- comma-separated for select type
    sort_order   INTEGER DEFAULT 0,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Managed via the Settings page in the admin UI (`/admin/settings`).

### 14.6 New Web Routes and Templates

**9 new templates** for the governance UI:

| Template | Route | Purpose |
|----------|-------|---------|
| `lifecycle.html` | `/admin/lifecycle` | All entity versions across types with lifecycle state, gate flags |
| `testing.html` | `/admin/testing` | Test suites overview with case counts, pass rates, last run |
| `test_suite_detail.html` | `/admin/testing/{suite_id}` | Suite detail with cases, results, "Run Suite" button |
| `ground_truth.html` | `/admin/ground-truth` | Ground truth datasets with record/annotation counts |
| `ground_truth_detail.html` | `/admin/ground-truth/{dataset_id}` | Dataset detail with authoritative annotations |
| `ground_truth_record.html` | `/admin/ground-truth/{dataset_id}/records/{record_id}` | Record detail with all annotations |
| `validation_runs.html` | `/admin/validation-runs` | All validation runs with metrics |
| `validation_run_detail.html` | `/admin/validation-runs/{run_id}` | Run detail with metrics, confusion matrix, per-record results |
| `settings.html` | `/admin/settings` | Platform settings key-value editor |

**Run Suite button:** The test suite detail page has a "Run Suite" button that POSTs to `/admin/testing/{suite_id}/run`. This triggers `test_runner.run_suite()` against the entity's champion version with `mock_llm=True`. Results appear immediately on page refresh.

### 14.7 New SQL Queries (15+ added to testing.sql)

| Query | Purpose |
|-------|---------|
| `list_all_test_suites` | All suites with case counts, pass counts, last run (for testing overview) |
| `get_test_suite` | Single suite with entity name |
| `list_test_results_for_suite` | Results for a suite (for detail page) |
| `list_all_ground_truth_datasets` | All datasets with entity names |
| `get_ground_truth_dataset` | Single dataset with entity name |
| `list_ground_truth_records` | Records for a dataset |
| `list_authoritative_annotations` | Records + authoritative annotations (for validation runner) |
| `get_ground_truth_record` | Single record |
| `list_annotations_for_record` | All annotations for a record (for record detail) |
| `list_validation_runs` | All validation runs with entity/dataset names |
| `get_validation_run_by_id` | Single run with joins |
| `list_validation_record_results` | Per-record results for a run |
| `list_validation_record_failures` | Failed records only (for debugging) |
| `list_metric_thresholds` | Thresholds for an entity |
| `list_field_extraction_configs` | Field tolerance configs for extraction entities |
| `list_all_entity_versions_with_state` | UNION ALL across agent_version + task_version (for lifecycle overview) |
| `insert_validation_record_result` | Store per-record validation result |

### 14.8 Client Integration

The Verity client (`client/inprocess.py`) initializes TestRunner and ValidationRunner as part of the Runtime construction, alongside ExecutionEngine and PipelineExecutor:

```python
self.test_runner = TestRunner(
    registry=self.registry,
    execution_engine=self.execution,
    testing=self.testing,
)
self.validation_runner = ValidationRunner(
    registry=self.registry,
    execution_engine=self.execution,
    testing=self.testing,
    db=self.db,
)
```

Both are accessible via `verity.test_runner` and `verity.validation_runner` from consuming applications.

---

## 15. EDMS Integration Points

### 15.1 How Ground Truth Connects to EDMS

Ground truth records can reference documents stored in EDMS via the storage-abstracted fields:

```
ground_truth_record:
    source_type       = 'document'
    source_provider   = 'minio'
    source_container  = 'submissions'        (from EDMS collection)
    source_key        = 'submission/00001/do_app_acme.pdf'
    source_description = 'D&O application for Acme Dynamics'
    input_data        = {"document_text": "...extracted text from EDMS..."}
```

The `input_data` JSONB contains what the entity receives during validation. For document-based entities, this is the extracted text from EDMS (retrieved via `get_document_text` tool during validation, or pre-populated from EDMS extraction results).

### 15.2 EDMS Seed Data

The EDMS seed script (`edms/src/edms/seed.py`) creates three collections aligned with Verity's use cases:

| Collection | Bucket | Purpose | Default Tags |
|-----------|--------|---------|-------------|
| `general` | submissions | Default collection for uncategorized documents | sensitivity: internal |
| `underwriting` | submissions | UW submission documents organized by submission ID | sensitivity: confidential |
| `ground_truth` | ground-truth-datasets | SME-labeled data for validation | sensitivity: internal |

The `underwriting` collection has per-submission folders. The `ground_truth` collection has per-entity folders with `input` subfolders.

---

## 16. Statistics

| Metric | Count |
|--------|-------|
| Database tables | ~45 (registry, multi-app, context, testing, decisions, pipeline_run, model / model_price / model_invocation_log, quota / quota_check, incidents, evaluation, model_card, field_extraction_config, description_similarity_log, platform_settings, mcp_server) |
| Views | 1 (`v_model_invocation_cost`) |
| Named SQL queries | ~223 across 10 files (registry, registration, authoring, lifecycle, decisions, testing, reporting, models, quotas, connectors) |
| Pydantic models | 60+ (including contracts/ boundary types) |
| Python enums | 15+ |
| Admin UI HTML routes (Jinja2) | ~40 |
| REST API endpoints (`/api/v1/*`) | ~78 across 11 sub-routers |
| Jinja2 templates | 36 |
| Governance modules | 7 (registry, lifecycle, decisions reader, reporting, testing_meta, models, quotas) + coordinator |
| Runtime modules | 11 (engine, pipeline, decisions_writer, mcp_client, connectors, mock_context, fixture_backend, test_runner, validation_runner, metrics, runtime) |
| SDK public methods (`client/inprocess.py` + sub-facades) | ~100 |
| `agent_decision_log` columns | ~35 (adds pipeline_run_id, parent_decision_id, decision_depth, step_name, application, reproduced_from_decision_id, hitl_required, decision_log_detail, redaction_applied) |
