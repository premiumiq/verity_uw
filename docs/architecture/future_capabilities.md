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

## FC-8: Version Management, Date Pinning & Version-Pinned Execution - DONE

**STATUS: IMPLEMENTING NOW**

### Problem

1. `get_agent_config()` resolves via `current_champion_version_id` pointer — ignores dates entirely. No temporal awareness.
2. No SCD Type 2 treatment: when a new champion is promoted, the old champion's `valid_to` is not always set correctly. Multiple champions could theoretically coexist.
3. No way to execute a specific prior version for audit reproducibility.
4. `prompt_version` has no `valid_from`/`valid_to` fields.
5. UI shows only the current champion — no way to browse all versions with their validity periods.

### Design

**SCD Type 2 temporal management for all versioned assets:**

- `valid_from` = timestamp when this version became champion
- `valid_to` = timestamp when this version was superseded (NULL = currently active)
- At any point in time, exactly ONE champion version has `valid_to IS NULL`
- Lifecycle `promote()` enforces this: sets `valid_from=NOW()` on new champion, `valid_to=NOW()` on old champion

**Date-based resolution (version pinning is really date pinning):**

```python
# Default: resolve champion as of NOW
config = await verity.get_agent_config("triage_agent")

# Date-pinned: resolve champion as of a specific date
config = await verity.get_agent_config("triage_agent", effective_date=datetime(2026, 3, 15))

# Version-pinned: resolve a specific version by ID (bypasses date logic)
config = await verity.get_agent_config_by_version(version_id)
```

**SQL resolution logic:**
```sql
-- Current champion (effective_date = NOW)
WHERE a.name = %(agent_name)s
  AND av.lifecycle_state = 'champion'
  AND av.valid_from <= %(effective_date)s
  AND (av.valid_to IS NULL OR av.valid_to > %(effective_date)s)

-- Direct version lookup (no date logic)
WHERE av.id = %(version_id)s
```

**Schema changes:**
- Add `valid_from`, `valid_to` to `prompt_version` (agent_version and task_version already have them)
- Ensure lifecycle promotion functions correctly manage `valid_from`/`valid_to` on all versioned tables
- Pipeline_version already has `valid_from`/`valid_to`

**Execution engine changes:**
- `execute_agent()`, `execute_task()` gain optional `effective_date` and `version_id` parameters
- `effective_date` resolves the champion that was active at that date
- `version_id` resolves a specific version directly (for audit replay)
- Both pass through to registry resolution

**UI changes:**
- All version tables show `valid_from` and `valid_to` columns
- Version history pages show the full temporal timeline
- Detail pages show which version was active at any given date

**Audit reproducibility workflow:**
```python
# 1. Get a prior decision
prior = await verity.get_decision(decision_id)

# 2. Re-run using the SAME version that originally produced it
result = await verity.execute_agent(
    agent_name="triage_agent",
    context=original_context,
    version_id=prior.entity_version_id,  # Pin to exact version
    mock=MockContext.from_decision_log(prior, mock_llm=False, mock_tools=True),
)
# Claude runs fresh with the old prompt, old config, old tools — same controlled data
```

**Priority:** High — required for regulatory audit reproducibility (SR 11-7), and foundational for all UI version browsing.

---

## FC-9: Multi-Application Support - DONE

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

---

## FC-10: Execution Context - DONE

**Gap:** Business applications currently pass raw business keys (`submission_id`) to Verity's decision log. While `pipeline_run_id` provides Verity-owned grouping for pipeline runs, there is no formal registration of business-level execution contexts. A business app should be able to register a named execution context (e.g., `submission:SUB-001`) that is unique within that application, and Verity should guarantee uniqueness of (application + context_ref).

**Design:** Add an `execution_context` table linked to the `application` table (FC-9):

```sql
CREATE TABLE execution_context (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    -- The business app's own identifier for this context (opaque to Verity)
    context_ref     VARCHAR(500) NOT NULL,
    -- e.g., "submission:00000001-...", "policy:POL-2026-001", "renewal:REN-123"
    context_type    VARCHAR(100),
    -- e.g., "submission", "policy", "renewal"
    metadata        JSONB DEFAULT '{}',
    -- Optional business metadata (Verity doesn't interpret this)
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_context UNIQUE (application_id, context_ref)
);
```

Usage:
```python
# Business app registers a context before running a pipeline
ctx = await verity.create_execution_context(
    application="uw_demo",
    context_ref=f"submission:{submission_id}",
    context_type="submission",
    metadata={"named_insured": "Acme Dynamics", "lob": "D&O"},
)

# Pipeline runs link to this context
result = await verity.execute_pipeline(..., execution_context_id=ctx["id"])
```

The `agent_decision_log.pipeline_run_id` groups steps within one run. The `execution_context_id` groups multiple runs for the same business entity (e.g., initial run + re-run for audit). Together with the `application` table, this provides full scoping: application → context → pipeline run → individual decisions.

**Depends on:** FC-9 (Multi-Application Support)

**Priority:** High — required for proper multi-application isolation.

---

## FC-11: Lifecycle Management UI

**Gap:** The `/admin/lifecycle` page is a placeholder. There is no UI for promoting a new entity version through the 7-state lifecycle, recording approvals, or viewing promotion history.

**Design:** Build a lifecycle management page with:
- Entity selector (pick an agent or task)
- Version list showing all versions with current lifecycle state
- "Create New Version" form (major/minor/patch, change summary, inference config)
- "Promote" button per version with approval form (approver name, role, rationale, evidence checkboxes)
- Promotion history timeline showing all state transitions with approver and timestamp
- Rollback button on champion versions

This is the key governance demo moment: "let me show you how we promote a new model version with human-in-the-loop approval gates."

**Priority:** Medium — high demo value for CIO audiences, but the SDK methods already work (used by seed script).

---

## FC-12: Version Composition Immutability

**Gap:** Nothing currently prevents mutation of an agent version's composition (prompt assignments, tool authorizations, inference config) after creation. The schema allows someone to change which prompts are assigned to agent v1.0.0 even after it has been promoted to champion. This violates the governance principle that a champion version is a fully validated, frozen snapshot.

**Governance Rationale:**

An agent version is not just a version number — it is a **complete, frozen composition** of:
- Prompt versions (system + user, specific version numbers)
- Inference configuration (model, temperature, max_tokens)
- Tool authorizations (which tools, with what permissions)
- Authority thresholds (HITL triggers, confidence thresholds)
- Output schema

Any change to any of these components **is a new version**. If you want to use a different prompt, you create agent v1.1.0 that references the new prompt version, and promote it through the lifecycle (draft → candidate → staging → champion). This ensures:

1. Every production change is tested before deployment
2. The audit trail can reconstruct exactly what ran — the agent version ID resolves to a frozen composition
3. Version pinning and date pinning work correctly — the composition at any point in time is deterministic
4. SR 11-7 compliance: "the model that was validated is the model that runs in production"

**Design:**

1. **Enforce immutability in the SDK:** Once an agent_version or task_version leaves `draft` state (i.e., is promoted to `candidate` or beyond), reject any attempt to modify its prompt assignments, tool authorizations, or inference config reference.

```python
# In registry.py assign_prompt():
version = await self._get_version(entity_type, entity_version_id)
if version["lifecycle_state"] != "draft":
    raise ValueError(
        f"Cannot modify prompt assignments for version in '{version['lifecycle_state']}' state. "
        f"Create a new version to change prompts."
    )

# Same check in authorize_agent_tool(), authorize_task_tool()
```

2. **Database constraint (optional additional safety):** Add a trigger that prevents UPDATE/INSERT on `entity_prompt_assignment` and `agent_version_tool` when the referenced version is not in `draft` state. This provides defense-in-depth beyond the SDK check.

3. **UI enforcement:** The lifecycle management UI should not offer prompt reassignment or tool changes for any version beyond `draft`. The "Edit" controls should be disabled/hidden for candidate, staging, shadow, challenger, and champion versions.

**Audit Replay Under This Model:**

When replaying a prior decision for audit:
1. Pin the agent version (by ID or by date) — resolves the frozen composition
2. The prompt versions, inference config, and tools are exactly what was validated
3. Mock the tools with `MockContext.from_decision_log(prior, mock_llm=False, mock_tools=True)` — feed the same data
4. Claude runs fresh with the original prompts and config
5. Compare output to the original — verifies reproducibility
6. The `prompt_version_ids` stored in the decision log serves as evidence of which exact prompts were used

**Priority:** High — foundational for audit integrity. Should be implemented before any production use.

---

## FC-13: Tool Versioning

**Gap:** Tools currently have no version table. The `tool` table represents the current state only. There is no `tool_version` table analogous to `agent_version` or `task_version`. This means:
- Tool changes are not tracked (no version history)
- Tool implementations cannot be version-pinned
- The version composition immutability principle (FC-12) cannot extend to tools
- Audit replay cannot verify that the same tool implementation was used

**Design:** Add `tool_version` table following the same pattern as `agent_version`:

```sql
CREATE TABLE tool_version (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tool_id             UUID NOT NULL REFERENCES tool(id),
    major_version       INTEGER NOT NULL DEFAULT 1,
    minor_version       INTEGER NOT NULL DEFAULT 0,
    patch_version       INTEGER NOT NULL DEFAULT 0,
    version_label       VARCHAR(20) GENERATED ALWAYS AS
                        (major_version::text || '.' || minor_version::text || '.' || patch_version::text) STORED,
    lifecycle_state     lifecycle_state NOT NULL DEFAULT 'draft',
    implementation_path VARCHAR(500) NOT NULL,
    input_schema        JSONB NOT NULL,
    output_schema       JSONB NOT NULL,
    mock_responses      JSONB DEFAULT '{}',
    valid_from          TIMESTAMP,
    valid_to            TIMESTAMP,
    change_summary      TEXT,
    developer_name      VARCHAR(200),
    created_at          TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tool_version UNIQUE (tool_id, major_version, minor_version, patch_version)
);
```

Agent/task version tool authorizations would then reference `tool_version_id` instead of `tool_id`, completing the frozen composition model.

**Priority:** Medium — needed for full version-pinned execution and audit completeness. Not blocking for demo.
