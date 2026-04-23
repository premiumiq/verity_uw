# Verity Execution Architecture — Tasks, Agents, Pipelines, Envelope

**Status:** Architecture decisions locked 2026-04-23.
**Scope:** How Verity shapes its three execution units (Task, Agent, Pipeline),
what every execution returns (the canonical envelope), and where
orchestration stops being Verity's problem.

This document is the reference for Phase 2+ of the Task Data Sources &
Targets plan ([task_data_sources_targets.md](task_data_sources_targets.md))
and for the follow-on work on pipeline input mapping, agent output
contracts, and the unified envelope.

---

## Guiding principle

Verity follows Anthropic's "Building Effective Agents" guidance: **prefer
workflows over agents**. Express as much work as possible as a prescriptive
pipeline of tasks; reserve agents for genuinely dynamic tool-use reasoning.

This maps cleanly onto the three execution units:

| Anthropic concept | Verity entity |
|---|---|
| Augmented LLM (single call with tools/retrieval) | **Task** |
| Workflow / prompt chain | **Pipeline** of Tasks |
| Agent (dynamic tool-use loop) | **Agent** |

---

## The three execution units

### Task

- **Single LLM call.** No tool loop, no dynamic decisions.
- **Input**: declared input schema, optionally populated from declared
  **sources** (resolved pre-call by the execution engine via registered
  `data_connector` providers).
- **Output**: strictly conformed to declared `output_schema`. Enforced via
  `tool_choice` forcing a structured-output tool on the single call.
- **Side effects**: declared **targets** only (channel-gated + runtime-gated
  writes). No free-form tool calls.
- **Purpose**: the default. Deterministic workflow step for anything
  expressible as "one call with known inputs produces a known output."

### Agent

- **Multi-turn LLM loop** with tool calls. Dynamic control flow.
- **Input**: declared input schema.
- **Output**: **optional** declared `output_schema`. When declared, enforced
  by an engine-injected `submit_output` tool forced on the terminal turn via
  `tool_choice`.
- **Side effects**: through registered tools (the tool's `is_write_operation`
  flag governs write authority). No declared targets on agents in v1 —
  agents fetch and write via tools, not declarative I/O.
- **Purpose**: reasoning that genuinely needs the tool-use loop. Agents are
  the exception, not the rule.

#### Agents without declared outputs

An agent without a declared `output_schema` is fully supported. It may do
meaningful work purely through tool-call side effects (e.g. "investigate
submission X and log findings via the incident tool"). The envelope's
`output` block is `null`; the envelope still captures telemetry,
provenance, and status.

**Restriction:** such an agent can still participate as a pipeline step,
but its output is not referenceable by downstream steps' `input_mapping`.
Pipeline registration validates this — mappings that reference an
unschema'd agent's output field fail at admit time. This keeps agents
free-form without letting them break pipeline contracts.

### Pipeline

- **Ordered DAG of steps**, each step is a Task | Agent | Tool.
- **Input**: declared pipeline-level input schema.
- **Output**: declared pipeline-level output schema, assembled from step
  outputs via explicit **output mapping**.
- **Step wiring**: each step declares an **input_mapping** — per-input-field
  specification with three source kinds:
  - `context` — value from the pipeline's caller-supplied input
  - `step` — value from a named upstream step's declared output
  - `constant` — literal value baked in at registration
- **Path language**: dotted + array indices only
  (`fields.named_insured.value`, `documents[0].document_type`). No
  JSONPath, no Jinja, no arithmetic. If you need transformation, add a
  tool or task step.
- **Validation at admit time**: `register_pipeline_version` walks every
  mapping. Referenced steps must exist earlier in topological order;
  referenced paths must exist in the source entity's declared output
  schema; every required step input must be mapped or resolvable from
  context.
- **Synchronous internally.** One `execute_pipeline` call runs the whole
  DAG top to bottom (respecting parallel_group) and returns one envelope.
  No suspend, no resume, no callbacks, no triggers inside Verity.

---

## Where orchestration stops being Verity's problem

Verity's scope is **one execution unit at a time**. Composition beyond a
single pipeline belongs to the consuming application (or a future
platform service in front of Verity). Specifically:

- **Triggering**: "when X happens, run pipeline Y" — app's job.
- **Chaining pipelines**: "when pipeline A completes, run pipeline B with
  context from A" — app's job.
- **Long-running / human-in-the-loop waits**: not modeled inside
  pipelines. If the workflow needs to wait for a human approval or a
  downstream event, the app breaks the work into multiple pipeline runs
  separated by its own state.
- **Scheduling, retries across pipelines, distributed queues**: not
  Verity's concern.

Verity's contribution to that picture is the **envelope** (see below):
everything needed to wire pipeline outputs into the next thing is in the
envelope, so apps can do their own orchestration cheaply.

### Future direction: async pipeline submission

Today, `execute_pipeline` is a synchronous call — the HTTP request blocks
until the whole DAG completes. For production scale this does not hold.
The agreed target shape (not in current scope, but informs the design):

1. App submits a pipeline: returns `{run_id}` **immediately** (or an error
   if admit-time validation fails).
2. App polls for pipeline status: `{run_id, status, started_at,
   completed_at, ...}`.
3. When complete, the final envelope is retrievable from a secure output
   location (object store / queue / bus) — or the pipeline **emits the
   envelope to an event bus** the app subscribes to.

This is the industry-standard async job pattern (Airflow, Temporal,
Argo Workflows, AWS Step Functions all expose this shape). The current
synchronous SDK is a deliberate v1 simplification — the envelope shape
is designed to round-trip through any queue or bus unchanged, so the
switch to async submission is an API/runtime change, not a re-model.

---

## The canonical envelope

**Every** Task, Agent, and Pipeline execution returns the same envelope
shape. Rationale: a single canonical return type collapses caller-side
code, makes pipelines' step envelopes compose recursively, and
round-trips cleanly through any persistence or messaging layer.

### Design references
The shape borrows deliberately from established specs:
- **CloudEvents 1.0** — identity + typed event + time + data
- **JSON-RPC 2.0** — mutually-exclusive `result` / `error` discriminated
  by `status`
- **RFC 7807 Problem Details** — structured error with code + message
- **Anthropic Messages API** — `stop_reason`, `usage` as telemetry

### Shape

```json
{
  "envelope_version": "1.0",
  "run_id": "uuid",
  "parent_run_id": "uuid | null",

  "entity": {
    "type": "task | agent | pipeline",
    "name": "field_extractor",
    "version_label": "1.2.0",
    "version_id": "uuid",
    "channel": "champion"
  },

  "status": "success | failure | partial",

  "output": { /* present iff status in (success, partial). Conforms to entity's declared output schema. */ },
  "error":  { "code": "string", "message": "string", "retriable": false, "details": {} } /* present iff status == failure */,

  "started_at": "iso8601",
  "completed_at": "iso8601",
  "duration_ms": 1234,

  "telemetry": {
    "input_tokens": 1234,
    "output_tokens": 567,
    "cost_usd": 0.012,
    "turns": 2,
    "tool_calls": 3,
    "sources_resolved": ["document_text"],
    "targets_fired": [],
    "mocks_used": ["source:document_text", "tool:get_loss_runs"]
  },

  "provenance": {
    "decision_log_id": "uuid",
    "execution_context_id": "uuid",
    "mock_mode": false,
    "application": "uw_demo"
  },

  "steps": [ /* pipeline only — array of nested envelopes for each step that ran, in execution order */ ]
}
```

### Design notes

- **`status` is a three-value enum**.
  - `success` — all required work completed, output conforms to schema.
  - `partial` — pipeline only: at least one step failed with
    `error_policy="continue_with_flag"` but the pipeline completed what
    it could. Output is populated with whatever mappings could resolve.
  - `failure` — the unit of work failed. `output` absent, `error` populated.
- **`output` and `error` are mutually exclusive** and discriminated by
  `status`. This is the JSON-RPC / Problem Details convention.
- **`steps[]` on pipelines** — recursive envelopes. Each step's envelope
  is itself the same shape (so a task-within-pipeline's envelope looks
  exactly like that task's standalone envelope). Drill-through audit UIs
  get this for free.
- **`mocks_used` in telemetry** — audit artifact. Shows at a glance
  which mocks shaped a particular run. Critical for validation runs and
  test replays.
- **No narrative `summary` field in the envelope itself.** If an agent
  wants to emit a narrative, it lives in `output.summary` per the agent's
  declared output schema. Envelope fields are engine-generated and
  uniform across all entities.
- **`parent_run_id`** — when a pipeline step runs a task/agent, the
  step's envelope carries `parent_run_id = pipeline.run_id`. When an
  app chains two pipelines, it may set `parent_run_id` on the second
  run to the first run's `run_id` for end-to-end traceability. Verity
  does not set it across pipelines automatically — that's the app's
  call, consistent with Verity staying out of cross-pipeline orchestration.

---

## Locked decisions (2026-04-23)

1. **Pipelines are synchronous within themselves.** No suspend, resume,
   triggers, or cross-pipeline chaining inside Verity. Async submission
   is a future API layer; the envelope shape anticipates it.
2. **Envelope is the canonical return type** for Task, Agent, and
   Pipeline. All three return identical shape; pipelines nest child
   envelopes under `steps[]`.
3. **Agents without declared output schemas can run and can participate
   in pipelines as side-effect steps.** Their outputs are simply not
   referenceable by downstream `input_mapping`. Pipeline registration
   validates and rejects mappings that reference an unschema'd agent's
   output fields.
4. **FC-3 (Agent Hooks / Pre-Post Middleware) is deferred indefinitely.**
   See [future_capabilities.md](future_capabilities.md) for rationale.

---

## Implementation order (captured for reference)

The work is staged after the current Phase 1 (sources/targets schema +
models). Proposed order:

- **Phase 2 — Task source resolution** (in-flight): wire
  `task_version_source` into the Task execution path. Eager resolution
  before prompt build. Decision log entries. Mock-aware.
- **Phase 3 — EDMS provider + first real source**: register the `edms`
  connector, declare sources on classifier / extractor tasks, fix the
  "validation sees no document" bug.
- **Phase 4 — Task targets**: declarative output writes, channel-gated +
  runtime-gated.
- **Phase 5 — Canonical envelope**: replace ad-hoc `ExecutionResult` /
  `StepResult` shapes with the envelope. Pipelines nest step envelopes.
- **Phase 6 — Agent output contracts**: `submit_output` tool injection,
  `tool_choice`-forced terminal turn, `agent_version.output_schema`
  first-class column.
- **Phase 7 — Pipeline input_mapping + output mapping**: declarative
  field-level wiring between steps. Registration-time validation.
- **Phase 8 — Pipeline-level input/output schemas**: pipeline version
  declares its caller-facing contract; assembled output via output
  mapping.

Phases are sequential — each builds on the prior. Each is
independently deployable.
