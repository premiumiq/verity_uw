# Multi-Application Support + Execution Context

## Context

Verity needs to support multiple consuming applications (UW Demo, Claims, Renewal, etc.) and provide a clean way for each application to register business-level execution contexts (submission, policy, renewal) without coupling Verity to business keys.

Today, all decisions log `application="default"` because there's no way for the business app to identify itself. The `submission_id` column is still a raw business key with no application scoping.

## What Gets Built

### 1. Schema: Two New Tables

```sql
-- Application registry — each consuming app registers itself
CREATE TABLE application (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Many-to-many: which agents/tasks/prompts/tools belong to which app
-- (entities can be shared across applications)
CREATE TABLE application_entity (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    entity_type     entity_type NOT NULL,
    entity_id       UUID NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_entity UNIQUE (application_id, entity_type, entity_id)
);

CREATE INDEX idx_ae_app ON application_entity(application_id);
CREATE INDEX idx_ae_entity ON application_entity(entity_type, entity_id);

-- Execution context — business-level grouping registered by the app
-- A context can span multiple pipeline runs (e.g., initial + re-run for audit)
CREATE TABLE execution_context (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id  UUID NOT NULL REFERENCES application(id),
    context_ref     VARCHAR(500) NOT NULL,
    -- Business app's identifier, e.g., "submission:SUB-001", "policy:POL-2026-001"
    context_type    VARCHAR(100),
    -- e.g., "submission", "policy", "renewal"
    metadata        JSONB DEFAULT '{}',
    -- Optional business data (Verity stores but doesn't interpret)
    created_at      TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_app_context UNIQUE (application_id, context_ref)
);

CREATE INDEX idx_ec_app ON execution_context(application_id);
```

### 2. Schema: Add `execution_context_id` to `agent_decision_log`

```sql
-- Add to agent_decision_log:
execution_context_id  UUID REFERENCES execution_context(id),
```

This links each decision to a business context. The `submission_id` column stays as informational metadata but `execution_context_id` is the proper FK for scoping.

### 3. SDK Methods (on Verity client)

```python
# Register an application (one-time setup)
app = await verity.register_application(
    name="uw_demo",
    display_name="Underwriting Demo",
    description="Commercial underwriting platform",
)

# Map entities to an application
await verity.map_entity_to_application(
    application_name="uw_demo",
    entity_type="agent",
    entity_id=triage_agent_id,
)

# Create an execution context (before running a pipeline)
ctx = await verity.create_execution_context(
    application_name="uw_demo",
    context_ref=f"submission:{submission_id}",
    context_type="submission",
    metadata={"named_insured": "Acme Dynamics", "lob": "D&O"},
)

# Execute pipeline within a context
result = await verity.execute_pipeline(
    pipeline_name="uw_submission_pipeline",
    context={...},
    execution_context_id=ctx["id"],  # Links decisions to this context
)

# Query by context (all pipeline runs for this business entity)
decisions = await verity.get_decisions_by_context(ctx["id"])
```

### 4. How the Business App Uses It

```python
# uw_demo/app/main.py — at startup
verity = Verity(
    database_url=settings.VERITY_DB_URL,
    anthropic_api_key=settings.ANTHROPIC_API_KEY,
    application="uw_demo",  # Identifies this app to Verity
)

# uw_demo/app/ui/routes.py — when running a pipeline
async def run_pipeline(request, submission_id, mode):
    # Create or get execution context for this submission
    ctx = await verity.create_execution_context(
        context_ref=f"submission:{submission_id}",
        context_type="submission",
        metadata={"named_insured": sub["named_insured"]},
    )

    result = await verity.execute_pipeline(
        pipeline_name="uw_submission_pipeline",
        context={...},
        execution_context_id=ctx["id"],
        mock=mock,
    )
    # pipeline_run_id groups steps within this run
    # execution_context_id groups all runs for this submission
```

### 5. Verity Admin UI Changes

- **Dashboard:** Filter by application (dropdown)
- **Pipeline Runs:** Show application column, filter by application
- **Decision Log:** Show application column, filter by application
- **Model Inventory:** Filter by application (show only entities mapped to selected app)
- **New page:** Application registry (list apps, see mapped entities)

---

## Files Modified

### Schema + SQL
| File | Change |
|---|---|
| `verity/src/verity/db/schema.sql` | Add `application`, `application_entity`, `execution_context` tables. Add `execution_context_id` to `agent_decision_log`. |
| `verity/src/verity/db/queries/registration.sql` | Add `insert_application`, `insert_application_entity`, `insert_execution_context` queries |
| `verity/src/verity/db/queries/registry.sql` | Add `list_applications`, `get_application_by_name`, `list_application_entities`, `get_execution_context` queries |
| `verity/src/verity/db/queries/decisions.sql` | Add `list_decisions_by_context` query. Update `log_decision` INSERT for `execution_context_id`. |

### Pydantic Models
| File | Change |
|---|---|
| `verity/src/verity/models/decision.py` | Add `execution_context_id` to DecisionLogCreate, DecisionLog, DecisionLogDetail |
| `verity/src/verity/models/application.py` | **NEW** — Application, ApplicationEntity, ExecutionContext models |

### Core SDK
| File | Change |
|---|---|
| `verity/src/verity/core/registry.py` | Add `register_application()`, `map_entity_to_application()`, `list_applications()`, `get_application_by_name()` |
| `verity/src/verity/core/client.py` | Accept `application` in `__init__`. Add `create_execution_context()`, `get_decisions_by_context()`. Pass `execution_context_id` through `execute_*` methods. |
| `verity/src/verity/core/execution.py` | Accept `execution_context_id` in `run_agent()`, `run_task()`, `run_tool()`. Pass to `_log_decision()`. |
| `verity/src/verity/core/pipeline_executor.py` | Accept `execution_context_id` in `run_pipeline()`. Pass to each step. |
| `verity/src/verity/core/decisions.py` | Update `log_decision()` to include `execution_context_id`. Add `get_decisions_by_context()`. |

### UW App
| File | Change |
|---|---|
| `uw_demo/app/main.py` | Pass `application="uw_demo"` to Verity constructor |
| `uw_demo/app/ui/routes.py` | Create execution context before pipeline runs. Pass `execution_context_id`. |
| `uw_demo/app/setup/register_all.py` | Register "uw_demo" application. Map entities. Create execution contexts for seeded submissions. |

### Verity Admin UI
| File | Change |
|---|---|
| `verity/src/verity/web/routes.py` | Add applications page route. Add application filter to pipeline runs and decisions. |
| `verity/src/verity/web/templates/applications.html` | **NEW** — Application registry page |
| `verity/src/verity/web/templates/base.html` | Add "Applications" to sidebar nav under Registry |

---

## Verification

1. UW app starts with `application="uw_demo"` → decisions logged with `application="uw_demo"` (not "default")
2. `verity.register_application("uw_demo", ...)` creates record in `application` table
3. `verity.map_entity_to_application("uw_demo", "agent", triage_agent_id)` creates mapping
4. `verity.create_execution_context(context_ref="submission:SUB-001")` creates context, returns ID
5. Pipeline run with `execution_context_id` → all decisions linked to that context
6. `get_decisions_by_context(ctx_id)` returns only decisions for that context
7. Two apps creating context_ref="submission:001" → separate contexts (unique on app_id + ref)
8. Verity admin Applications page shows registered apps with entity counts
9. Pipeline Runs page filterable by application
