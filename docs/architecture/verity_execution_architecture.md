# Verity Execution Architecture — Tasks, Agents, Declarative I/O, Async Runs

**Status:** Architecture decisions locked 2026-04-24. All phases (A–K)
implemented and validated end-to-end against UW + EDMS as of 2026-04-25.
**Scope:** How Verity shapes its two execution units (Task, Agent), how their
inputs and outputs are declared and resolved, how content (text and binary)
flows from data sources into LLM calls, how runs are submitted and tracked
asynchronously, and where orchestration stops being Verity's problem.

This document is the reference for the live architecture. It supersedes
`task_data_sources_targets.md` (pre-descope source/target design) and the
2026-04-23 version of this doc, which still included pipelines as a
first-class runtime entity.

---

## Guiding principle

Verity follows Anthropic's *Building Effective Agents* guidance: **prefer
workflows over agents**. Express as much work as possible as single-call tasks
against structured outputs; reserve agents for genuinely dynamic tool-use
reasoning.

Verity governs AI components (Tasks, Agents, Tools). **Apps orchestrate them.**
The prior doc modeled Pipelines as a third first-class execution unit with
their own runtime; this version descopes that entirely. Multi-step workflows
live in app code where they can integrate with the app's existing scheduler,
retry policies, human-in-the-loop gates, and async infrastructure.

The two concepts that map from Anthropic's framing onto Verity entities:

| Anthropic concept | Verity entity |
|---|---|
| Augmented LLM (single call with tools/retrieval) | **Task** |
| Agent (dynamic tool-use loop) | **Agent** |
| Workflow / prompt chain | App code, orchestrating Verity Tasks + Agents |

---

## Task and Agent, side-by-side

Both execution units are now at parity for declarative I/O. The only
semantic differences are what the runtime does between input and output.

| | **Task** | **Agent** |
|---|---|---|
| **LLM shape** | Single call. No tool loop. | Multi-turn loop with tool calls. Dynamic control flow. |
| **`input_schema`** | First-class column on `task_version`. Required. | First-class column on `agent_version` (new). Required. |
| **`output_schema`** | First-class. Required for structured output. | First-class. Optional. |
| **Output enforcement** | Forced via `tool_choice` on a synthetic `structured_output` tool when schema is declared. | Optional per run: `run_agent(enforce_output_schema=True)` injects a `submit_output` tool and forces `tool_choice` on the terminal turn. Off by default. |
| **Declared sources** | Rows in `source_binding` with `owner_kind='task_version'`. Resolved pre-prompt. | Rows in `source_binding` with `owner_kind='agent_version'`. Resolved pre-loop. |
| **Declared targets** | Rows in `write_target` (with `owner_kind='task_version'`) plus `target_payload_field` rows. Fired post-output. | Same tables with `owner_kind='agent_version'`. Fired post-terminal-turn. |
| **Tool calls (dynamic)** | None. | Through registered tools; write authority per tool's `is_write_operation` flag. |

### Tasks

A Task is the default. If work is expressible as "one LLM call with known
inputs produces a known structured output," it's a Task.

- **Input**: declared `input_schema`. Values can come straight from the caller
  or be resolved from declared sources before prompt assembly.
- **Output**: strictly conformed to `output_schema`. Enforced via `tool_choice`
  forcing a synthetic `structured_output` tool on the single call.
- **Side effects**: declared `write_target` rows only. No free-form tool calls.

### Agents

An Agent is for work that genuinely needs the dynamic tool-use loop. They
are the exception, not the rule.

- **Input**: declared `input_schema`. Same source-resolution story as Tasks —
  sources resolved pre-loop, template variables bundled into the initial
  context.
- **Output**: optional `output_schema`. When declared and the caller opts in
  with `enforce_output_schema=True`, the engine injects a `submit_output` tool
  on the terminal turn and uses `tool_choice` to force it. The returned
  envelope's `output` is that tool's input dict. When the caller does not opt
  in, the agent runs free-form and `output` is best-effort-parsed from the
  final text.
- **Side effects**: through registered tools (dynamic, per-turn) **and**
  through declared targets fired after the terminal turn. Both mechanisms
  coexist; targets are the governed declarative path, tools are the dynamic
  path.

#### Agents without declared output schemas

Fully supported — they may do meaningful work purely through tool-call side
effects (e.g. "investigate submission X and log findings via the incident
tool"). The envelope's `output` is an empty dict; telemetry, provenance, and
status are still populated.

---

## Reference grammar (declarative wiring)

Every source binding and every target-payload field is a mapping from a
`target_field` name to a **reference string**. The reference is parsed into
one of four kinds:

| Reference kind | Syntax | Valid on |
|---|---|---|
| This unit's own input | `input.<dotted.path[i]>` | source_binding, target_payload_field |
| This unit's own output | `output.<dotted.path[i]>` | target_payload_field only |
| Literal constant | `const:<value>` | source_binding, target_payload_field |
| Connector fetch | `fetch:<connector>/<method>(input.<field>)` | source_binding only |

**Path grammar:** dotted keys + bracketed integer indices
(`fields.named_insured.value`, `documents[0].document_type`). No JSONPath, no
arithmetic, no conditionals. If transformation is needed, add an intermediate
task in the app's orchestration layer.

No `context.*` or `step.*` references exist — those were pipeline-scope only
and pipelines are descoped. Each reference resolves entirely against the
unit's own `input` and `output` dicts.

### Modality — `binding_kind` decides where the value lands

A `source_binding` row carries a `binding_kind` discriminator that controls
how the resolved value reaches the LLM:

| `binding_kind`  | Resolved value type | Where it lands in the Claude call |
|---|---|---|
| `text` (default) | string | Bound to `{{template_var}}` in the prompt template, substituted before the API call. |
| `content_blocks` | list of Claude content-block dicts | Prepended to the **first user message** as content blocks, ahead of the template-rendered text. The prompt template SHOULD NOT reference `{{template_var}}` for content_blocks bindings — the data does not flow through template substitution. |

A binding declared with `binding_kind='content_blocks'` requires its connector
method to return a list of content-block dicts in Claude's API shape:

- `{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "<b64>"}}` — for PDFs.
- `{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "<b64>"}}` — for images.
- `{"type": "text", "text": "<contents>"}` — for plain text.

This is the **only** path through which non-text content reaches the LLM.
There is no side-channel: the runtime does not inspect input fields named
`_documents` or any other reserved key, and `_assemble_prompts` never
synthesises content blocks from `input_data` directly. Vision and multimodal
behaviour is exclusively driven by declared source bindings.

`source_resolutions` audit rows record `binding_kind` per binding so operators
can see, per run, which path each declared source took (and how big the
returned payload was, regardless of modality).

### Example — text source (extractor)

The field extractor's prompt template uses `{{document_text}}`. The binding
fetches text from EDMS:

```yaml
source_binding on task:field_extractor
  template_var: document_text
  reference:    fetch:edms/get_documents_text(input.documents)
  binding_kind: text
  required:     true
```

When the caller invokes the task with `{documents: [{id: "<edms-uuid>", ...}, ...]}`,
the runtime calls `edms.get_documents_text(<list>)` once, gets the
concatenated extracted text, and substitutes it for `{{document_text}}` in the
prompt template.

### Example — content_blocks source (vision classifier)

The document classifier needs to *see* PDFs and read text files; the connector
returns one content block per ref, the runtime attaches them to the first
user message, and the prompt template carries no document placeholder:

```yaml
source_binding on task:document_classifier
  template_var: documents_content
  reference:    fetch:edms/get_document_content_blocks(input.documents)
  binding_kind: content_blocks
  required:     true
```

For an input with `documents = [{id: "<pdf-uuid>", content_type: "application/pdf"}]`,
the runtime calls `edms.get_document_content_blocks(<list>)`. The connector
fetches per-ref `content_type` from EDMS metadata and emits the matching
block shape (PDF → document, image → image, text → text). The classifier
prompt receives `[<doc/image/text block>, <text-rendered prompt>]` as the
first user message content array. Claude sees the document natively without
any text extraction step in the prompt path.

### Example — task target payload

The same extractor writes its `extracted_fields` back to EDMS as a child
document linked to the original, using fields from both input and output:

```yaml
write_target on task:field_extractor
  name:           extracted_fields_sink
  connector:      edms
  write_method:   create_derived_json
  required:       false
  target_payload_field rows:
    parent_id:         input.destination_document_id
    derivative_type:   input.derivative_type
    data:              output.extracted_fields
```

The runtime assembles the payload dict by resolving each field's reference,
then calls `edms.write("create_derived_json", container, {parent_id, derivative_type, data})`.

### Target writes — the channel-gated `auto` mode

Declared `write_target` rows fire after the LLM call (Task) or terminal turn
(Agent). Whether the call to the connector's `write()` actually happens or
gets recorded as a logged-only intent is decided per-run by an effective
write-mode resolver. Precedence, strongest first:

1. **`MockContext.target_blocks`** — explicit per-target block always wins.
   Used by validation/test runners to guarantee no side effects regardless
   of channel or `write_mode`.
2. **Caller-supplied `write_mode`** kwarg on `run_task` / `run_agent`:
   `"log_only"` and `"write"` are explicit overrides with named reasons.
3. **`write_mode='auto'`** (the default) — channel-gated:
   - `channel == 'production'` → writes fire.
   - Any other channel (`development`, `staging`, `shadow`, `evaluation`) →
     logged only.

The `target_writes` audit JSONB on the decision row carries
`mode_reason` (e.g. `"auto_channel=production"`, `"write_mode=log_only"`,
`"mock_target_block"`) so operators can answer "why didn't this write?"
without re-deriving the policy.

The `auto`-mode gate explicitly tests against `production` (the canonical
live-traffic deployment_channel value). It does **not** key off lifecycle
state — a version's `lifecycle_state` of `champion` does not by itself enable
writes; only being executed on the `production` channel does.

### Admit-time validation

`register_task_version` and `register_agent_version` run a wiring validator
against the declarations before accepting them:

- Every source_binding reference must resolve syntactically and semantically:
  - `input.<path>` → the path exists in this unit's `input_schema`.
  - `const:<value>` → always valid.
  - `fetch:<connector>/<method>(input.<field>)` → the connector name exists
    in `data_connector`, the provider supports the method (verified through
    a startup-time capability query), and the argument path exists in
    `input_schema`.
- Every source_binding's `template_var` must appear in at least one prompt
  template variable declaration (prevents orphan fetches).
- Every target_payload_field reference must resolve:
  - `input.<path>` → path in `input_schema`.
  - `output.<path>` → path in `output_schema`. **Illegal if `output_schema` is
    not declared.**
  - `const:<value>` → always valid.
- Every write_target's connector method must accept the payload shape the
  payload-field rows construct (via the provider's method-signature query).

The result is that a version that registers cleanly cannot fail at runtime
due to wiring errors. Only real-world failures (LLM call timeout, connector
IO error, schema-violation output from the model) can fail a run.

---

## Decision log and audit

Verity's audit story rests on one immutable append-only table
(`agent_decision_log`) and four identity columns that thread related decisions
together. Pipelines are no longer the unit of grouping; `execution_context_id`
was always the primary identity linker and continues to be.

### Identity columns

| Column | Populated by | What it groups |
|---|---|---|
| `execution_context_id` | App (registers a context per business entity) | **Submission-level.** All decisions for `submission:SUB-001` share one execution_context_id. |
| `workflow_run_id` | App (generates a UUID per workflow invocation) | **Workflow-level.** All decisions made in one invocation of a multi-step app workflow. Renamed from `pipeline_run_id` now that Verity no longer owns pipelines. |
| `parent_decision_id` | Runtime (set when an agent delegates to a sub-agent) | **Delegation-tree-level.** Threads sub-agent calls under their parent. |
| `execution_run_id` | Runtime (set when a run is submitted via the async path) | **Run-level.** Ties a decision row to the event-sourced `execution_run` record. |

### Reconstructing a submission

Given a submission reference like `submission:SUB-001`, the app looks up its
`execution_context_id` and queries:

- **All decisions for the submission** — `list_decisions_by_execution_context`.
  One query; returns every task, agent, and tool decision made for the
  submission, across all workflow invocations.
- **All decisions for one workflow invocation** — filter the above by
  `workflow_run_id`. Shows the DAG the app ran (typically 2–5 decisions —
  classify + extract, or triage + appetite + letter_draft, etc.).
- **Drill into a single agent tree** — filter by `parent_decision_id` or walk
  the tree from a root decision.
- **Live state of a submitted run** — join through `execution_run_id` to the
  `execution_run_current` view.

### Mocking — three independent concerns, no fall-through to live LLM

Verity supports three kinds of caller-supplied mocking through `MockContext`,
each addressing a different concern. They compose — a single run can use any
combination — but they do not *fall through* to one another. The semantics
are explicit on purpose, because a missing fixture should never silently
turn into a real Claude call (and a real bill).

| Field | Targets | Lookup behaviour |
|---|---|---|
| `step_responses` | The full LLM call | Keyed by `step_name` first, then `entity_name`. **Hard semantics:** when this dict is non-empty and no key matches, the engine raises `MockMissingError` — supplying step_responses means "this run is fully scripted," and a missing fixture is a bug, not a license to fall through to live Claude. The engine closes the self-tracked run with an error event before propagating, so the failure is visible in `/admin/runs`. |
| `tool_responses` | Individual tool calls | Keyed by tool name. Tools NOT in this dict make real calls (or use the tool's DB-registered `mock_mode_enabled` default). This is the path for partial mocking — "mock this one tool, run the rest live." |
| `source_responses` | Source binding fetches | Keyed by the binding's input field name. Skips the connector fetch and uses the supplied payload verbatim. Coexists with `binding_kind`: a content_blocks binding's mock value must already be a list of content-block dicts. |

A run that uses `step_responses` exclusively never calls Claude, never resolves
sources, never fires targets. The engine still writes a `decision_log` row
with `mock_mode=True` and an `execution_run` row tagged `submitted_by='inproc'`
so the audit shape is identical to a live run.

### Run tracking is event-sourced

Live run state is **not** stored on a mutable row. Four append-only tables
plus a view give the lifecycle:

- `execution_run` — the request. One row per submission. Never updated.
- `execution_run_status` — ledger of `submitted | claimed | heartbeat |
  released` transitions. Never updated.
- `execution_run_completion` — successful terminal row (`complete | cancelled`).
  At most one per run.
- `execution_run_error` — failure terminal row. At most one per run.
- `execution_run_current` — VIEW that surfaces the combined state. All API /
  UI reads go through this view.

The same immutability invariant that applies to `agent_decision_log` applies
to run tracking: reads produce a complete history from insert-only writes.
No UPDATE contention. Full audit of every claim, heartbeat, release, and
terminal outcome.

---

## Async execution

Task and Agent runs are asynchronous by default. The synchronous `run_task` /
`run_agent` SDK methods remain as sugar that internally submits and waits.

### Lifecycle

```
App submits a run  →  POST /api/v1/runs
                      INSERT execution_run
                      INSERT execution_run_status (status='submitted')
                      ────────────────────────────────── return {run_id}

Worker picks it up  →  SELECT candidate FOR UPDATE SKIP LOCKED
                       INSERT execution_run_status (status='claimed', worker_id)
                       ─────────────────────────────────
                       Heartbeat every 30s:
                         INSERT execution_run_status (status='heartbeat')

Worker executes    →   run_task() / run_agent() (existing engine code)
                       INSERT agent_decision_log (immutable audit)

Success            →   INSERT execution_run_completion
                         (final_status='complete', decision_log_id, duration_ms)
Failure            →   INSERT execution_run_error
                         (error_code, error_message, error_trace, worker_id)
Cancel (pre-claim) →   INSERT execution_run_completion
                         (final_status='cancelled')
Cancel (mid-run)   →   Worker checks between steps, aborts, inserts
                         execution_run_completion(final_status='cancelled')
Stuck run          →   Janitor inserts execution_run_status(status='released')
                       — re-claimable by any worker
```

### Worker model

Workers are a separate Docker service (`verity-worker`) that run the same
Verity package as the API. They are stateless, horizontally scalable
(`docker compose up --scale verity-worker=4`), and use `SELECT ... FOR UPDATE
SKIP LOCKED` to guarantee no two workers claim the same run.

### API surface

```
POST /api/v1/runs                    — submit a run, returns {run_id, status}
GET  /api/v1/runs                    — list (filter by execution_context_id, workflow_run_id, status, entity, channel)
GET  /api/v1/runs/{id}               — current state (reads from execution_run_current view)
GET  /api/v1/runs/{id}/lifecycle     — full event sequence (status + terminal rows in time order)
GET  /api/v1/runs/{id}/result        — envelope (409 if not yet complete)
POST /api/v1/runs/{id}/cancel        — request cancellation
```

### SDK surface

```python
run_id   = await verity.submit_task("field_extractor", input_data, ...)
state    = await verity.get_run(run_id)                    # current state only
envelope = await verity.get_run_result(run_id)             # terminal envelope; raises if not ready
envelope = await verity.wait_for_run(run_id, timeout=60)   # blocks until terminal

# Sync sugar — unchanged public name; internally submit + wait
envelope = await verity.run_task("field_extractor", input_data, ...)
```

---

## Where orchestration stops being Verity's problem

Verity governs AI components. Apps orchestrate them. This is a hard line.

Specifically, Verity does **not**:

- **Trigger** runs. "When X happens, run task Y" is the app's job.
- **Chain** multiple runs. "When task A completes, run task B with context
  from A" is the app's job.
- **Model human-in-the-loop waits.** If a workflow needs to wait for human
  approval, the app breaks the work into multiple run submissions with its
  own state between them.
- **Schedule**, **retry across runs**, or run **distributed queues**.

### What the app writes

Multi-step workflows are plain Python in the consuming app. The submission
doc-processing workflow runs **per document**: classify each one, extract
from each one classified as a D&O application. Every call gets its own
audit row + its own EDMS write where applicable.

```python
async def run_doc_workflow(submission_id):
    wf_run_id = uuid4()
    ctx_id = await verity.register_execution_context(f"submission:{submission_id}")

    # EDMS returns originals only by default (lineage children are
    # filtered out — they're an implementation detail of upload +
    # auto-extraction, not items the caller needs to reason about).
    documents = await edms.list_documents(f"submission:{submission_id}")

    for doc in documents:
        classify = await verity.run_task(
            "document_classifier",
            {
                "submission_id": submission_id,
                "lob": "DO",
                "named_insured": "...",
                "documents": [doc],   # single-element list per call
            },
            step_name=f"classify_documents:{doc['filename']}",
            execution_context_id=ctx_id,
            workflow_run_id=wf_run_id,
        )
        if classify.output.get("document_type") == "do_application":
            await verity.run_task(
                "field_extractor",
                {
                    "submission_id": submission_id,
                    "named_insured": "...",
                    "documents": [doc],
                },
                step_name=f"extract_fields:{doc['filename']}",
                execution_context_id=ctx_id,
                workflow_run_id=wf_run_id,
            )
```

Things to notice:

- The app passes **only EDMS document references** in `input.documents` —
  `id`, `filename`, `content_type`, `document_type`. No base64 PDFs, no
  inlined extracted text. The audit `input_json` shows exactly that small
  reference list, not "elided" placeholders.
- Each task version's source_binding decides what to fetch from each
  reference. Classifier uses `binding_kind='content_blocks'` (PDFs go to
  Claude vision); extractor uses `binding_kind='text'` (extracted text bound
  to `{{document_text}}`). Both bindings are declarative — the workflow code
  is unchanged when modality changes.
- The workflow is readable, version-controlled in the app repo, integrates
  with whatever scheduler / retry / async infrastructure the app already
  has, and produces the full Verity audit trail because every call threads
  `execution_context_id` + `workflow_run_id` and a unique `step_name`.

### What Verity still contributes

- Per-entity governance (7-state lifecycle on each task/agent version, prompt
  versioning, output-schema enforcement, source/target declarations, admit-time
  wiring validation).
- Immutable decision log per run.
- Event-sourced run tracking (submit/poll/cancel, lifecycle ledger).
- Unified "Runs" UI — list, drill-through, submission-scoped view — giving
  one place to see every task and agent run in the system.

---

## The canonical envelope

**Every** Task and Agent execution returns the same envelope shape.
Rationale: one canonical return type collapses caller-side code, round-trips
cleanly through any persistence or messaging layer, and anticipates async
submission (same shape whether delivered synchronously or retrieved after a
poll).

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
    "type": "task | agent",
    "name": "field_extractor",
    "version_label": "1.2.0",
    "version_id": "uuid",
    "channel": "champion"
  },

  "status": "success | failure",

  "output": { /* present iff status == success. Conforms to entity's declared output schema. */ },
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
    "targets_fired": ["extracted_fields_sink"],
    "mocks_used": ["source:document_text", "tool:get_loss_runs"]
  },

  "provenance": {
    "decision_log_id": "uuid",
    "execution_context_id": "uuid",
    "workflow_run_id": "uuid",
    "execution_run_id": "uuid",
    "mock_mode": false,
    "application": "uw_demo"
  }
}
```

### Design notes

- **`status` is a two-value enum**: `success` or `failure`. There's no
  `partial` state — a single task or agent either produces its output or it
  doesn't. Partial-success semantics belong to the app's orchestration layer
  (e.g. "classify succeeded but extract failed" → the app decides what to do).
- **`output` and `error` are mutually exclusive**, discriminated by `status`.
- **No nested `steps[]`.** Envelopes are flat; pipelines no longer exist.
  Apps that want to present a workflow as a single object can compose their
  own wrapper from multiple per-run envelopes sharing a `workflow_run_id`.
- **`parent_run_id`** — set automatically when an agent delegates to a
  sub-agent (the sub-agent's envelope carries `parent_run_id = parent agent's
  run_id`). Apps may also set it across their own chained runs for end-to-end
  traceability; Verity never sets it on behalf of app-level orchestration.
- **`mocks_used` in telemetry** — audit artifact. Shows at a glance which
  mocks shaped a particular run. Critical for validation runs and replays.
- **No narrative `summary` field.** If an agent wants to emit a narrative, it
  lives in `output.summary` per the agent's declared `output_schema`.
  Envelope fields are engine-generated and uniform across entities.

---

## Locked decisions (2026-04-24, validated 2026-04-25)

Supersedes the 2026-04-23 set.

1. **Two execution units, not three.** Pipelines are descoped entirely — no
   `pipeline`, `pipeline_version`, or `pipeline_step` tables; no
   `execute_pipeline` runtime. Apps orchestrate multi-step workflows in their
   own code.
2. **Tasks and Agents at I/O parity.** Both have first-class `input_schema`
   and `output_schema`, both can declare sources and targets. The only
   semantic difference is what happens between input and output (single LLM
   call vs. tool-use loop).
3. **One reference grammar** for all declarative wiring — `input.*`,
   `output.*`, `const:*`, `fetch:C/M(input.X)`. No `context.*` or `step.*`
   references.
4. **Wiring is split into two purpose-named tables**: `source_binding` and
   `target_payload_field` (the latter subordinate to `write_target`).
5. **`source_binding.binding_kind` decides modality.** `text` substitutes the
   resolved value into `{{template_var}}`; `content_blocks` prepends the
   resolved value (a list of Claude content-block dicts) to the first user
   message. There is no parallel side-channel — the runtime never inspects
   reserved input keys for vision content.
6. **Agent output enforcement is opt-in per run** —
   `run_agent(enforce_output_schema=True)` injects a `submit_output` tool and
   forces `tool_choice` on the terminal turn. Off by default.
7. **Async runs with event-sourced tracking.** Submit/poll/cancel over REST;
   external worker pool; all lifecycle state is append-only across four
   tables (`execution_run`, `execution_run_status`, `execution_run_completion`,
   `execution_run_error`) surfaced through the `execution_run_current` view.
8. **Submission audit continues via `execution_context_id`.** Multi-step
   workflow grouping continues via caller-supplied `workflow_run_id` (renamed
   from `pipeline_run_id`).
9. **Flat envelope.** No nested `steps[]`. Parent/child linkage is
   `parent_run_id` on each envelope; app-level workflow envelopes are the
   app's construction.
10. **Apps pass references, not content.** Callers put EDMS document
    references (or other resource refs) into `input` and let declared
    source_bindings fetch the actual content via the connector at execution
    time. Audit `input_json` carries the references, not inlined binaries
    or extracted text. EDMS reinforces this contract by returning *originals*
    only from its `/documents` listing by default; lineage children
    (auto-extracted text, JSON derivatives) are an opt-in.
11. **`step_responses` mocks are strict.** When `MockContext.step_responses`
    is supplied and no key matches the requested step, the engine raises
    `MockMissingError`. Mock mode never falls through to a real Claude call.
    Partial mocking (mock some tools, run others live) is the role of
    `tool_responses`, not `step_responses`.
12. **Write-mode `auto` gates on `channel='production'`.** Declared targets
    fire only on the production deployment_channel under `auto` mode; every
    other channel logs the intended write without invoking the connector.
    Lifecycle-state `champion` is an orthogonal concept and does not by
    itself enable writes.
13. **FC-3 (Agent Hooks / Pre-Post Middleware) remains deferred indefinitely.**
    See `future_capabilities.md`.

---

## Implementation order — completed 2026-04-25

All phases below have shipped, are on the `main` branch, and were
validated end-to-end against a live Claude run + real EDMS write on the
UW demo. Existing Phase 2/3 work (task sources + EDMS connector) was
preserved conceptually and migrated to the new schema; former Phase 7/8
(pipeline-specific wiring) was deleted.

- ✅ **Phase A — Schema foundations.** All new tables plus the
  `execution_run_current` view. `agent_version.input_schema`.
  `pipeline_run_id` → `workflow_run_id`. `execution_run_id` FK on
  `agent_decision_log`.
- ✅ **Phase B — Data migration.** `task_version_source` →
  `source_binding`; `task_version_target` → `write_target` +
  `target_payload_field`. Old tables dropped.
- ✅ **Phase C — Async primitive + worker.** `POST /runs` + lifecycle
  endpoints, `verity-worker` service, SDK `submit_*` / `get_run` /
  `wait_for_run` / `cancel_run`. Existing `run_task` / `run_agent` are now
  sync sugar over the async primitive.
- ✅ **Phase D — Unified runtime I/O.** Generic `_resolve_sources` /
  `_write_targets` / `_resolve_reference` against the new tables.
- ✅ **Phase E — Agent parity.** Source resolution + target writes wired
  in `run_agent`. `execution_run_id` threaded through.
- ✅ **Phase F — Agent output enforcement.** `enforce_output_schema=True`
  injects a `submit_output` tool on the terminal turn.
- ✅ **Phase G — Envelope unification.** One canonical envelope shape for
  task and agent returns.
- ✅ **Phase H — Pipeline descope.** Pipeline runtime, contracts, models,
  queries, and UI pages deleted. UW orchestration moved to plain Python
  in `uw_demo/app/workflows.py`.
- ✅ **Phase I — Runs UI.** `/admin/runs`, `/admin/runs/{id}`,
  `/admin/workflows/{id}` pages live. `/pipelines/*` retired. The
  `/admin/runs` listing renders entity + application by display name and
  exposes a registered-applications dropdown filter.
- ✅ **Phase J — EDMS write endpoint + extractor target + multimodal.**
  EDMS `POST /documents/{parent_id}/derived` (creates JSON-derivative
  child + lineage row). `EdmsProvider.write("create_derived_json", ...)`.
  Field-extractor `write_target` + payload fields registered. Validated
  end-to-end against EDMS on `channel=production`.

  Extensions that landed during Phase J validation:
  - `source_binding.binding_kind` (`text` | `content_blocks`) — vision
    and multimodal flow through declarative source bindings rather than
    a side-channel input field. The classifier uses content_blocks; the
    extractor uses text.
  - EDMS `GET /documents` defaults to originals only (`include_derivatives=false`)
    — lineage children (auto-extracted text, JSON derivatives) are
    omitted unless explicitly requested.
  - UW `run_doc_processing` iterates per-document — one classifier call
    per doc, one extractor call per doc classified as `do_application`.
    Each call is its own audit row with a unique `step_name`.
  - `MockContext.step_responses` is strict — missing fixture raises
    `MockMissingError` rather than falling through to a live Claude
    call. The strict-miss closes the self-tracked run with an error
    event before propagating.
- ✅ **Phase K — Doc rewrite.** This document; product vision and
  technical design synced; `task_data_sources_targets.md` superseded;
  cross-references updated in `registry_runtime_split_plan.md`.
