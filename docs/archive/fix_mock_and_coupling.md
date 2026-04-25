# Fix: Mock Gateway + App-Verity Decoupling + Tools in Pipelines

## What's Wrong Today

### Problem 1: Mock Implementation
- UW app's `run_mock_pipeline()` bypasses the execution engine entirely — writes fake decisions directly to the DB
- `mock_mode_enabled` flags on agent_version/task_version exist in schema but are never checked in code
- Tool mock returns generic `{"mock": True}` — not realistic test data
- No way to mock the LLM call itself
- No way to replay a prior execution for audit testing

### Problem 2: App-Verity Key Coupling
- `submission_id` in `agent_decision_log` is a raw business key from the UW app
- `get_audit_trail(submission_id)` returns ALL decisions with that ID regardless of source
- Two apps or two entity types sharing a key would silently mix audit trails
- "View in Verity" links use the raw business key as the lookup

### Problem 3: Tools Can't Be Pipeline Steps
- Pipeline steps only support `agent` and `task` entity types
- Deterministic operations (clearance check, data lookups) that don't need LLM can't be pipeline steps

---

## Decisions Made
- **Full gateway pattern now** — every LLM call and tool call goes through an interceptor
- **Use pipeline_run_id for decoupling** — already exists, no new table needed
- **Include tools as pipeline steps** — add `tool` as valid pipeline entity_type

---

## Fix 1: Execution Gateway with MockContext

### Core Concept

Every call to an external system (Claude API, tool implementation) passes through a gateway function. The gateway checks if a `MockContext` is active. If yes, it returns the mock response. If no, it makes the real call.

```
Business app
    │
    ▼
verity.execute_agent(name, context, mock=MockContext(...))
    │
    ├─ Resolve config from registry (always real)
    ├─ Assemble prompts (always real)
    │
    ├─ LLM Call → [GATEWAY] → Claude API or mock response
    │       │
    │       ├─ mock=None → call Claude, return real response
    │       └─ mock has llm_response → return it, skip Claude
    │
    ├─ Tool Call → [GATEWAY] → tool implementation or mock response  
    │       │
    │       ├─ tool not in mock.tools → call real implementation
    │       ├─ tool in mock.tools → return mock response for this call
    │       └─ tool.mock_mode_enabled=True (DB flag) → return DB mock response
    │
    └─ Log decision (always real — governance trail identical)
```

### MockContext Object

```python
@dataclass
class MockContext:
    """Controls what gets mocked in an execution.
    
    Pass this to execute_agent(), execute_task(), or execute_pipeline()
    to control which calls are real and which return pre-built responses.
    
    Examples:
        # Mock everything — no Claude call, no tool calls
        mock = MockContext(
            llm_responses=[{"risk_score": "Green", "reasoning": "..."}],
        )
        
        # Real Claude, but mock specific tools (e.g., write operations)
        mock = MockContext(
            tool_responses={
                "store_triage_result": {"stored": True},
                "update_submission_event": {"event_id": "123"},
            },
        )
        
        # Audit replay — use responses from a prior decision log
        mock = MockContext.from_decision_log(prior_decision)
        
        # No mock — everything live (this is the default when mock=None)
    """
    
    # If set, each LLM call returns the next response from this list.
    # For single-turn tasks: one response.
    # For multi-turn agents: responses[0] is first turn, responses[1] after
    #   first tool call, etc. Enables replay of multi-step reasoning.
    llm_responses: list[dict] | None = None
    
    # Per-tool mock responses. Key = tool name, value = response.
    # Tools NOT in this dict make real calls.
    # If a tool appears here, its mock response is returned instead of
    #   calling the implementation.
    tool_responses: dict[str, Any] | None = None
    
    # If True, ALL tools are mocked using their DB-registered mock data
    # (tool.mock_mode_enabled flag). Individual tool_responses override this.
    mock_all_tools: bool = False
    
    @classmethod
    def from_decision_log(cls, decision: DecisionLogDetail) -> "MockContext":
        """Build a MockContext that replays a prior execution.
        
        Uses the stored output_json as the LLM response and the
        stored tool_calls_made as tool responses. This lets you
        re-run a decision with identical inputs/outputs for audit.
        """
        tool_responses = {}
        if decision.tool_calls_made:
            for tc in decision.tool_calls_made:
                tool_responses[tc["tool_name"]] = tc["output_data"]
        
        return cls(
            llm_responses=[decision.output_json] if decision.output_json else None,
            tool_responses=tool_responses if tool_responses else None,
        )
```

### How Multi-Step Reasoning Works with Mocks

For an agent that does: LLM → tool call A → LLM → tool call B → LLM (final):

```python
mock = MockContext(
    llm_responses=[
        # Turn 1: Claude decides to call tool A
        {"type": "tool_use", "name": "get_submission_context", "input": {...}},
        # Turn 2: After tool A, Claude decides to call tool B
        {"type": "tool_use", "name": "get_guidelines", "input": {...}},
        # Turn 3: Final response
        {"risk_score": "Green", "reasoning": "..."},
    ],
    tool_responses={
        "get_submission_context": {"account": "Acme", "revenue": 50000000},
        "get_guidelines": {"text": "Section 2.1: Revenue > $10M..."},
    },
)
```

**But this is complex.** For most use cases (demo, testing, audit replay), we only need:

```python
# Simple: mock the final output only (skip the entire agentic loop)
mock = MockContext(
    llm_responses=[{"risk_score": "Green", "reasoning": "..."}],
)

# Or: let Claude run, but control what tools return
mock = MockContext(
    tool_responses={"store_triage_result": {"stored": True}},
)
```

**Implementation:** The gateway tracks a `_llm_call_index` counter. Each LLM call through the gateway increments it and returns `llm_responses[index]` if available. If the mock response is a final answer (not a tool_use), the agentic loop ends immediately.

### Gateway Implementation in execution.py

Two new internal methods on `ExecutionEngine`:

```python
async def _gateway_llm_call(self, api_params: dict, mock: MockContext | None, call_index: int):
    """Gateway for all LLM calls. Intercepts if mock is active."""
    if mock and mock.llm_responses and call_index < len(mock.llm_responses):
        return _build_mock_llm_response(mock.llm_responses[call_index])
    # No mock — make real Claude API call
    return self.client.messages.create(**api_params)

async def _gateway_tool_call(self, tool_name: str, tool_input: dict, 
                              authorized_tools: list, mock: MockContext | None):
    """Gateway for all tool calls. Intercepts if mock is active."""
    # Check runtime mock first (takes priority)
    if mock and mock.tool_responses and tool_name in mock.tool_responses:
        return {"tool_name": tool_name, "output_data": mock.tool_responses[tool_name], 
                "mock_mode": True, "mock_source": "runtime"}
    
    # Check mock_all_tools flag
    if mock and mock.mock_all_tools:
        return {"tool_name": tool_name, "output_data": _get_db_mock_response(tool_name),
                "mock_mode": True, "mock_source": "db_flag"}
    
    # Check per-tool DB flag (tool.mock_mode_enabled)
    tool_def = next((t for t in authorized_tools if t.name == tool_name), None)
    if tool_def and tool_def.mock_mode_enabled:
        return {"tool_name": tool_name, "output_data": _get_db_mock_response(tool_name),
                "mock_mode": True, "mock_source": "db_flag"}
    
    # No mock — call real tool implementation
    return await self._execute_real_tool(tool_name, tool_input)
```

### DB-Registered Mock Responses

The `tool` table already has `mock_response_key VARCHAR(200)`. We add a `mock_responses` JSONB column to store realistic mock data per tool:

```sql
-- Add to tool table:
mock_responses  JSONB DEFAULT '{}',
-- Example: {"default": {"account": "Acme", "revenue": 50000000}, 
--           "high_risk": {"account": "DangerCo", "claims": 12}}
```

The seed script populates these with realistic responses matching the demo submissions.

### How the UW App Changes

Delete `run_mock_pipeline()` entirely. Replace with:

```python
# Mock mode: everything goes through the execution engine
mock = MockContext(llm_responses=get_mock_outputs(submission_id))
result = await verity.execute_pipeline(
    pipeline_name="uw_submission_pipeline",
    context={...},
    execution_context_id=pipeline_run_id,
    mock=mock,
)

# Live mode: no mock, everything real
result = await verity.execute_pipeline(
    pipeline_name="uw_submission_pipeline",
    context={...},
)
```

Both paths go through the same execution engine. Same governance trail. Same decision logging.

---

## Fix 2: Decoupling with pipeline_run_id

### What Changes

**Decision log:** `submission_id`, `policy_id`, `renewal_id` stay as **informational metadata** columns (not removed — they're useful for humans reading the audit trail). But they are **NOT used for querying or linking between apps**.

**Linking between apps:** Uses `pipeline_run_id` (for pipeline runs) or `decision_log_id` (for standalone executions). These are Verity-owned UUIDs, not business keys.

**New column on decision log:**
```sql
-- Add to agent_decision_log:
application  VARCHAR(100) DEFAULT 'default',
-- Scopes decisions by source application
```

**Audit trail query changes:**

```sql
-- OLD (broken): queries by raw business key
WHERE adl.submission_id = %(submission_id)s

-- NEW: queries by Verity-owned pipeline_run_id
WHERE adl.pipeline_run_id = %(pipeline_run_id)s
ORDER BY adl.decision_depth, adl.created_at
```

### How the UW App Links to Verity

```python
# Execute pipeline — returns PipelineResult with pipeline_run_id
result = await verity.execute_pipeline(...)

# UW app stores the pipeline_run_id in its own submission record
# (or just keeps it in the SUBMISSIONS dict for the demo)
sub["last_pipeline_run_id"] = str(result.pipeline_run_id)

# "View in Verity" link uses pipeline_run_id, not submission_id
# <a href="/admin/audit-trail/{{ sub.last_pipeline_run_id }}">
```

**Audit trail page updates:** Instead of `audit-trail/{submission_id}`, the URL becomes `audit-trail/run/{pipeline_run_id}`. The query filters by `pipeline_run_id`, which is unique per execution — no collision possible.

### For Standalone Agent/Task Runs

When you run a single agent or task (not part of a pipeline), the `decision_log_id` is the unique reference. The UW app stores it and uses it for "View in Verity" links.

### Business Key Metadata

The `submission_id` column stays — it's useful for humans. But:
- It's passed as `metadata` in the mock context or context dict
- It's never used as a query key for audit trails
- The `application` column distinguishes which app wrote the record

---

## Fix 3: Tools as First-Class Pipeline Steps

### What Changes

**Pipeline step definition:** `entity_type` enum already includes `tool`. The pipeline executor's `_execute_step()` gains a third branch:

```python
if entity_type == "agent":
    exec_result = await self.engine.run_agent(...)
elif entity_type == "task":
    exec_result = await self.engine.run_task(...)
elif entity_type == "tool":
    # Call tool implementation directly — no LLM involved
    exec_result = await self.engine.run_tool(
        tool_name=step.entity_name,
        input_data=step_context,
        execution_context_id=...,
        mock=mock,
    )
```

**New method `run_tool()` on ExecutionEngine:**
- Resolves tool from registry (gets implementation_path, mock settings)
- Goes through the tool gateway (respects mock context)
- Logs a decision in the decision log (entity_type='tool') for audit completeness
- Returns ExecutionResult

**Decision log:** The `entity_type` check constraint already allows `'tool'` (it's in the entity_type enum in schema.sql). No schema change needed.

**Use cases:**
- Clearance check (deterministic DB lookups, no LLM)
- Data enrichment aggregation (combine API responses)
- Document validation (check file presence in MinIO)
- Any deterministic operation that should be part of the governed pipeline

---

## Schema Changes Summary

```sql
-- 1. Add to agent_decision_log:
application       VARCHAR(100) DEFAULT 'default',
message_history   JSONB,    -- Full conversation array for multi-turn replay

-- 2. Add to tool:
mock_responses    JSONB DEFAULT '{}',   -- Realistic mock responses keyed by scenario

-- 3. Add index for pipeline_run_id audit trail queries:
-- (index already exists: idx_adl_pipeline)
```

No new tables. No removed columns. `submission_id` stays as informational metadata.

---

## Mock + Test Suite Integration

Test cases define expected behavior. MockContext replays that behavior through the execution engine. Metrics evaluate whether the prompt produces matching output.

```python
# In testing.py run_test_suite():
for case in test_cases:
    mock = MockContext(llm_responses=[case.expected_output])
    result = await engine.run_task(entity_name, input=case.input_data, mock=mock)
    passed = evaluate_metric(result.output, case.expected_output, case.metric_type)
```

### Mock Sources (where mock data comes from)

| Source | Stored Where | Who Creates | When Used |
|---|---|---|---|
| DB-registered | `tool.mock_responses` JSONB | Seed script / developer | Demo, development |
| Prior execution | `decision_log.message_history` + `tool_calls_made` | Verity (automatically) | Audit replay, regression |
| Test case | `test_case.expected_output` | Test author | Test suite execution |
| Runtime | Passed as `MockContext` param | Calling code | Ad hoc testing |

---

## Files Modified

| File | Change |
|---|---|
| `verity/src/verity/core/execution.py` | Add `_gateway_llm_call()`, `_gateway_tool_call()`. Accept `mock` param on `run_agent()`, `run_task()`. Add `run_tool()`. Store `message_history`. |
| `verity/src/verity/core/mock_context.py` | **NEW** — `MockContext` dataclass with `from_decision_log()` |
| `verity/src/verity/core/pipeline_executor.py` | Pass `mock` through to each step. Add `tool` entity_type handling. |
| `verity/src/verity/core/client.py` | Add `mock` param to `execute_*()`. Add `get_audit_trail_by_run()`. |
| `verity/src/verity/core/decisions.py` | Add `get_audit_trail_by_run(pipeline_run_id)`. Update `log_decision` for new fields. |
| `verity/src/verity/db/queries/decisions.sql` | Add `list_decisions_by_pipeline_run` query. Update `log_decision` INSERT. |
| `verity/src/verity/db/schema.sql` | Add `application`, `message_history` to decision log. Add `mock_responses` to tool. |
| `verity/src/verity/models/decision.py` | Add `application`, `message_history` fields. |
| `uw_demo/app/pipeline.py` | Delete `run_mock_pipeline()`. Add `get_mock_context()` that builds MockContext. |
| `uw_demo/app/ui/routes.py` | Use `mock=MockContext(...)` with `execute_pipeline()`. Link by `pipeline_run_id`. |
| `uw_demo/app/ui/templates/submission_detail.html` | Update "View in Verity" link to use pipeline_run_id. |
| `uw_demo/app/setup/register_all.py` | Seed `mock_responses` on tools. Set `application='uw_demo'` on decisions. |
| `verity/src/verity/web/routes.py` | Add `/audit-trail/run/{pipeline_run_id}` route. |

---

## Verification

### Mock Gateway
1. `execute_agent("triage_agent", context, mock=MockContext(llm_responses=[...]))` → returns pre-built output, no Claude call, decision logged
2. `execute_agent("triage_agent", context, mock=MockContext(tool_responses={"store_triage_result": {...}}))` → Claude runs live, tool returns mock, decision logged with `mock_mode=True` on that tool
3. `execute_agent("triage_agent", context)` → everything live, no mocking
4. `MockContext.from_decision_log(prior_decision)` → replays a prior execution exactly
5. Pipeline with `mock=MockContext(...)` → all steps use mock, all decisions logged, governance trail complete

### Decoupling
6. `execute_pipeline()` returns `PipelineResult.pipeline_run_id`
7. UW app stores `pipeline_run_id`, links to `/admin/audit-trail/run/{pipeline_run_id}`
8. Audit trail by `pipeline_run_id` returns only decisions from that specific run — no collision
9. `submission_id` remains in decision log as metadata but is not used for linking

### Tools in Pipeline
10. Pipeline with step `{"entity_type": "tool", "entity_name": "clearance_check"}` → tool runs directly, decision logged, result passed to next step
