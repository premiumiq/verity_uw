# Logging ContextVar Fix — SDK Mode Context Propagation

## Problem

In SDK mode, the Verity execution engine runs inside the UW Demo process. Both apps have their own logging module with their own ContextVar instances. The pipeline executor writes to Verity's vars, but the active ContextFilter reads from UW Demo's vars. Result: `pipeline_run_id`, `step_name`, `submission_id`, and `service` are always empty in the logs.

## Root Cause

`ContextVar("pipeline_run_id")` in two files creates two separate objects. Python ContextVars are identity-based, not name-based. Setting one does not affect the other.

```
verity/utils/logging.py:    pipeline_run_id_var = ContextVar("pipeline_run_id")   → Object A
uw_demo/app/utils/logging.py: pipeline_run_id_var = ContextVar("pipeline_run_id") → Object B

Pipeline executor writes to Object A.
ContextFilter reads from Object B.
Object B is always empty.
```

## Affected Fields

| Field | Written by | Read by | Status |
|---|---|---|---|
| `pipeline_run_id` | verity pipeline_executor.py (Object A) | UW Demo ContextFilter (Object B) | Always empty |
| `step_name` | verity pipeline_executor.py (Object A) | UW Demo ContextFilter (Object B) | Always empty |
| `submission_id` | Nobody sets it currently | UW Demo ContextFilter (Object B) | Always empty |
| `service` | UW Demo setup_logging (Object B) | UW Demo ContextFilter (Object B) | Shows "unknown" because set() runs before dictConfig installs the filter |
| `correlation_id` | UW Demo CorrelationMiddleware (Object B) | UW Demo ContextFilter (Object B) | Works correctly (same object) |

## Proposed Fix

### Step 1: UW Demo imports Verity SDK's context vars

UW Demo's logging module should import `pipeline_run_id_var`, `step_name_var`, and `submission_id_var` from the Verity SDK instead of creating duplicates. The Verity SDK is already pip-installed and imported (`from verity import Verity`). Context vars are part of the SDK's public API.

```python
# uw_demo/app/utils/logging.py — BEFORE
from contextvars import ContextVar
pipeline_run_id_var = ContextVar("pipeline_run_id")    # duplicate — broken
step_name_var = ContextVar("step_name")                # duplicate — broken
submission_id_var = ContextVar("submission_id")         # duplicate — broken

# uw_demo/app/utils/logging.py — AFTER
from verity.utils.logging import pipeline_run_id_var, step_name_var, submission_id_var
# Now reads from the same objects the pipeline executor writes to
```

UW Demo keeps its own `correlation_id_var` and `service_name_var` since those are set by UW Demo's middleware, not by Verity.

### Step 2: Fix service_name

Use `static_fields` in the JSON formatter (already done) instead of ContextVar for service name. The service name doesn't change per-request — it's a constant set at startup.

### Step 3: Set submission_id in the route handler

The UW Demo route handler knows the submission_id. Set it in the ContextVar before calling the pipeline:

```python
# uw_demo/app/ui/routes.py
from verity.utils.logging import submission_id_var

async def run_document_processing(request, submission_id):
    submission_id_var.set(submission_id)
    # Now all downstream logs include submission_id
    result = await verity.execute_pipeline(...)
```

### Step 4: EDMS is unaffected

EDMS runs in its own container, never uses the Verity SDK, never runs pipelines. Its context vars are self-contained and work correctly.

## Files to Change

| File | Change |
|---|---|
| `uw_demo/app/utils/logging.py` | Import `pipeline_run_id_var`, `step_name_var`, `submission_id_var` from `verity.utils.logging`. Remove duplicate ContextVar declarations for those three. |
| `uw_demo/app/ui/routes.py` | Set `submission_id_var` in pipeline route handlers before execution. |
| `verity/utils/logging.py` | No change — it already defines the authoritative vars. |
| `edms/src/edms/utils/logging.py` | No change — independent service. |

## Not Affected

- EDMS logging (independent container, no SDK)
- Verity standalone admin UI logging (its own process, its own vars)
- correlation_id (set by UW Demo middleware, read by UW Demo filter — same object, works)
