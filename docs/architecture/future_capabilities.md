# Future Capabilities — Deferred from Phase 2.5

These capabilities were identified during the critical architecture review (2026-04-04) and deferred to App 2 or later phases.

---

## FC-1: Agent-to-Agent Delegation (Sub-Agents)

**Gap:** An agent cannot programmatically invoke another agent during its execution. The execution engine supports tools but not delegation to other governed agents.

**Design:** Add a `delegate_to_agent` meta-tool that the execution engine intercepts. When Claude calls this tool, the engine:
1. Runs the target agent as a full governed Verity execution
2. Sets `parent_decision_id` to the parent agent's decision log ID
3. Increments `decision_depth`
4. Returns the sub-agent's output as the tool result

**Schema support:** Already in place — `parent_decision_id` and `decision_depth` columns added in Phase 2.5.

**Priority:** Medium — needed when agents need to compose results from other agents.

---

## FC-2: Session / Conversation Continuity

**Gap:** Each `execute_agent()` call starts with a fresh message history. No state is preserved across calls.

**Design:** Add a `session` table:
```sql
CREATE TABLE session (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_type     entity_type NOT NULL,
    entity_name     VARCHAR(100) NOT NULL,
    submission_id   UUID,
    message_history JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMP DEFAULT NOW(),
    last_active_at  TIMESTAMP DEFAULT NOW()
);
```

Add `create_session()` and `continue_session(session_id, new_message)` to `Verity` client.

**Priority:** Low for demo (all interactions are single-shot), Medium for production (multi-turn underwriter chat).

---

## FC-3: Agent Hooks (Pre/Post Middleware)

**Gap:** No way to inject logic before or after agent execution (input validation, output transformation, rate limiting, cost tracking).

**Design:** Add hook registration to `ExecutionEngine`:
```python
engine.register_hook("pre_execution", validate_input)
engine.register_hook("post_execution", track_cost)
engine.register_hook("pre_tool_call", check_rate_limit)
engine.register_hook("post_tool_call", log_tool_metrics)
```

Hooks are async callables. Pre-hooks can modify context or abort execution. Post-hooks can transform output or trigger side effects.

**Priority:** Medium — useful for production observability and policy enforcement.

---

## FC-4: Error Recovery with Retry/Backoff

**Gap:** Failures are logged but not retried. No backoff or fallback strategies.

**Design:** Add retry configuration to `inference_config.extended_params`:
```json
{
    "retry": {
        "max_attempts": 3,
        "backoff_ms": [1000, 2000, 4000],
        "retry_on": ["rate_limit", "overloaded", "timeout"]
    },
    "fallback_config": "extraction_deterministic_fallback"
}
```

Execution engine implements retry loop with exponential backoff. Optionally falls back to a different inference config.

**Priority:** Medium — important for production reliability, not needed for demo.

---

## FC-5: Vision / Image Input Support

**Gap:** Prompts only support text substitution. No image handling in prompt assembly or API params.

**Design:** Extend `_assemble_prompts()` to support content blocks with images:
```python
# Context can include images:
context = {
    "document_image": {"type": "image", "source": {"type": "base64", "data": "..."}}
}
# Prompt template: {{document_image}} → inserted as image content block
```

**Priority:** High for document processing (ACORD form images), Low for text-only demo.

---

## FC-6: Batch API Support

**Gap:** All executions are synchronous per request. No batch processing.

**Design:** Add `batch_execute_tasks()` to the client that:
1. Assembles multiple task invocations
2. Submits via Anthropic Batch API
3. Polls for completion
4. Logs each decision individually

**Priority:** Low — batch is for high-volume production, not demo.

---

## FC-7: System Prompt Caching

**Gap:** System prompts are sent fresh with every API call. No cache_control parameter.

**Design:** In `_build_api_params()`, when the system prompt exceeds a threshold (e.g., 1000 tokens), add cache_control:
```python
params["system"] = [
    {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}
]
```

This requires the system prompt to be passed as a list of content blocks rather than a plain string.

**Priority:** Medium — reduces cost and latency for repeated agent calls with long system prompts.

---

## FC-8: Version-Pinned Execution

**Gap:** `get_agent_config()` and `get_task_config()` always resolve the current champion version. There is no way to execute a specific prior version — needed for audit reproducibility ("re-run this decision using the same agent version that originally produced it").

**Design:** Add `get_agent_config_by_version(version_id)` and `get_task_config_by_version(version_id)` to the registry. The execution engine gains an optional `version_id` parameter:

```python
# Run triage_agent at version 1.0.0 (not current champion)
result = await verity.execute_agent(
    agent_name="triage_agent",
    context={...},
    version_id=prior_decision.entity_version_id,  # Pin to this version
    mock=MockContext.from_decision_log(prior, mock_llm=False, mock_tools=True),
)
```

This resolves the pinned version's prompts, tools, and inference config — not the current champion's. Combined with `MockContext.from_decision_log(mock_llm=False)`, this enables full audit re-testing: "run the exact same version with the exact same tool data, let Claude reason fresh, compare output."

**Schema support:** No changes needed — version IDs already exist. Registry just needs a second lookup path that takes `version_id` instead of resolving champion.

**Priority:** High — required for regulatory audit reproducibility (SR 11-7).

---

## FC-9: Multi-Application Support

**Gap:** Verity currently assumes a single consuming application. There is no `application` table, no way to map agents/tasks/prompts to specific applications, and no way to filter the admin UI by application. The `application` column on `agent_decision_log` (added in Phase 2.5) provides basic decision-level tagging but no registry-level scoping.

**Design:** Add two tables:

```sql
CREATE TABLE application (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE application_entity (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    entity_type     entity_type NOT NULL,
    entity_id       UUID NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_entity UNIQUE (application_id, entity_type, entity_id)
);
```

This enables:
- Registering multiple applications (UW Demo, Claims, Renewal)
- Mapping agents, tasks, prompts, tools to applications (many-to-many — entities can be shared)
- Filtering Verity admin UI by application (dropdown selector)
- Model inventory report per application
- Decision log filtered by application
- Reuse of common agents/tasks across applications with independent lifecycle per app

**Priority:** Medium — needed when a second application is built on Verity. Not needed for single-app demo.
