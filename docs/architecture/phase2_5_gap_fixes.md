# Phase 2.5: Fix Gaps Before API + Web UI

## Context
Critical review found 6 gaps that need fixing before building Phase 3 (API + Web UI). User chose to fix all 6 (critical + important) and wants full parallel pipeline support.

---

## Changes to Make

### 1. Schema Additions (`schema.sql`)

Add 3 columns to `agent_decision_log`:
```sql
parent_decision_id  UUID REFERENCES agent_decision_log(id),
decision_depth      INTEGER DEFAULT 0,
step_name           VARCHAR(100)
```

Add index:
```sql
CREATE INDEX idx_adl_parent ON agent_decision_log(parent_decision_id);
```

Re-apply schema to running database (drop + recreate since no real data yet).

### 2. Pydantic Model Updates

**`models/decision.py`** — Add to `DecisionLogCreate`, `DecisionLog`, `DecisionLogDetail`, `AuditTrailEntry`:
- `parent_decision_id: Optional[UUID]`
- `decision_depth: int = 0`
- `step_name: Optional[str]`

### 3. SQL Query Updates

**`queries/decisions.sql`** — Update `log_decision` INSERT to include new columns. Update `list_decisions_by_submission` to return new columns and ORDER BY `decision_depth, created_at`.

### 4. Pipeline Executor (`core/pipeline_executor.py`)

New module. Responsibilities:
- Load pipeline champion config from registry
- Resolve each step's entity (agent or task) champion config
- Build dependency graph from `depends_on` field
- Execute steps in topological order
- Steps in the same `parallel_group` run concurrently via `asyncio.gather`
- Each step calls `execution.run_agent()` or `execution.run_task()` with shared `pipeline_run_id` and `step_name`
- Handle error policies per step: `fail_pipeline`, `continue_with_flag`, `skip`
- Evaluate step conditions (e.g., `{"if_doc_type_present": "acord_855"}`) against accumulated results
- Return `PipelineResult` with per-step results and overall status

Key design:
```python
@dataclass
class PipelineResult:
    pipeline_run_id: UUID
    pipeline_name: str
    steps_completed: list[StepResult]
    steps_failed: list[StepResult]
    steps_skipped: list[StepResult]
    status: str  # "complete", "partial", "failed"
    duration_ms: int
```

### 5. Execution Engine Enhancements (`core/execution.py`)

**a) Remove tool call truncation:**
Change `input_summary: str(tool_input)[:200]` → `input_data: tool_input` (full payload)
Change `output_summary: str(tool_output)[:200]` → `output_data: tool_output` (full payload)

**b) Wire extended_params through to Claude API:**
In `_build_api_params()`, add:
```python
if inference_config.extended_params:
    for key, value in inference_config.extended_params.items():
        if key not in params:  # don't override explicit params
            params[key] = value
```
This enables extended thinking (`{"thinking": {"type": "enabled", "budget_tokens": 8000}}`), prompt caching, etc. — anything stored in the config's `extended_params` flows through.

**c) Add structured output via tool_choice:**
For tasks with output_schema, use tool_choice to force structured JSON:
- Create a synthetic tool from the task's output_schema
- Pass `tool_choice={"type": "tool", "name": "structured_output"}`
- Extract the tool_use result as the task's output (guaranteed valid JSON)

**d) Add streaming support:**
Add `stream: bool = False` parameter to `run_agent()` and `run_task()`. When True:
- Use `client.messages.stream()` context manager instead of `client.messages.create()`
- Yield `ExecutionEvent` objects (tool_call_start, tool_result, text_delta, complete)
- Return an async generator for the caller to consume
- Decision logging still happens at the end (complete event)

### 6. Client Updates (`core/client.py`)

Add to `Verity` class:
- `execute_pipeline(pipeline_name, context, submission_id)` → delegates to pipeline executor
- `execute_agent(..., stream=False)` → passes stream flag through
- `execute_task(..., stream=False)` → passes stream flag through

### 7. Future Capabilities Doc

Create `docs/architecture/future_capabilities.md` tracking gaps 7-11:
- Agent-to-agent delegation (sub-agents)
- Session/conversation continuity
- Agent hooks (pre/post middleware)
- Error recovery with retry/backoff
- Vision/image, batch API, system prompt caching

---

## Files Modified

| File | Change |
|---|---|
| `verity/src/verity/db/schema.sql` | Add 3 columns + 1 index to agent_decision_log |
| `verity/src/verity/db/queries/decisions.sql` | Update log_decision INSERT, list queries |
| `verity/src/verity/models/decision.py` | Add parent_decision_id, decision_depth, step_name |
| `verity/src/verity/core/execution.py` | Full tool logging, extended_params passthrough, tool_choice, streaming |
| `verity/src/verity/core/pipeline_executor.py` | **NEW** — Pipeline orchestration with parallel groups |
| `verity/src/verity/core/client.py` | Add execute_pipeline(), stream params |
| `docs/architecture/future_capabilities.md` | **NEW** — Track deferred gaps |

## Verification

1. Schema re-applied with new columns: `\d agent_decision_log` shows `parent_decision_id`, `decision_depth`, `step_name`
2. Pipeline executor: define a 4-step pipeline → execute → 4 decision logs with same `pipeline_run_id`, correct `step_name` values, parallel steps ran concurrently
3. Extended thinking: inference_config with `extended_params: {"thinking": {...}}` → params appear in Claude API call
4. Structured output: task with output_schema → response is valid JSON (tool_use extraction)
5. Tool calls logged with full payloads (no 200-char truncation)
6. Streaming: `run_agent(stream=True)` yields events progressively
