"""Top-level API router assembly.

Assembles the individual per-concern sub-routers (reporting, registry,
runtime, lifecycle, decisions, applications, authoring, ...) behind a
single `/api/v1` prefix. The Verity SDK client is injected once here
and passed down to each sub-router factory.

Wiring lives in `verity/src/verity/main.py`:

    from verity.web.api.router import build_api_router
    app.include_router(build_api_router(verity))

All endpoints appear in the main FastAPI app's OpenAPI spec at
`/docs` and `/openapi.json`.
"""

from fastapi import APIRouter

from verity.web.api.applications import build_applications_router
from verity.web.api.authoring import build_authoring_router
from verity.web.api.decisions import build_decisions_router
from verity.web.api.draft_edit import build_draft_edit_router
from verity.web.api.lifecycle import build_lifecycle_router
from verity.web.api.models import build_models_router
from verity.web.api.quotas import build_quotas_router
from verity.web.api.registry import build_registry_router
from verity.web.api.reporting import build_reporting_router
from verity.web.api.runtime import build_runtime_router
from verity.web.api.usage import build_usage_router


def build_api_router(verity) -> APIRouter:
    """Build the full `/api/v1/*` router, wiring in every sub-router.

    Args:
        verity: an initialized Verity SDK client — the shared instance
            from `main.py`. The same instance is threaded into each
            sub-router factory so all endpoints talk to the same DB
            pool and governance/runtime state.

    Returns:
        APIRouter with prefix `/api/v1`. Include on the main FastAPI
        app via `app.include_router(build_api_router(verity))`.
    """
    router = APIRouter(prefix="/api/v1")

    # Registry — catalog lists, resolved configs, version listings.
    router.include_router(build_registry_router(verity))

    # Runtime — synchronous run_agent / run_task / run_pipeline.
    router.include_router(build_runtime_router(verity))

    # Authoring — POST wrappers for every register_* SDK method (headers,
    # versions, associations, governance artifacts).
    router.include_router(build_authoring_router(verity))

    # Draft edit — PATCH/PUT/DELETE for in-place edits on draft versions,
    # plus POST .../clone to produce a new draft from any prior version.
    router.include_router(build_draft_edit_router(verity))

    # Models — catalog CRUD + SCD-2 price history.
    router.include_router(build_models_router(verity))

    # Usage & spend — aggregations over the model invocation log +
    # point-in-time price view.
    router.include_router(build_usage_router(verity))

    # Quotas — per-scope budget caps, checker, and breach records.
    router.include_router(build_quotas_router(verity))

    # Applications — multi-tenant anchor, entity mappings, activity +
    # purge for the cleanup-notebook flow, and execution-context creation.
    router.include_router(build_applications_router(verity))

    # Lifecycle — promote / rollback / list approvals.
    router.include_router(build_lifecycle_router(verity))

    # Decisions & audit trails — list, get-by-id, trail by context or
    # pipeline run, and human override logging.
    router.include_router(build_decisions_router(verity))

    # Reporting — dashboard + inventory aggregates.
    router.include_router(build_reporting_router(verity))

    return router
