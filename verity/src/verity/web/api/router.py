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

from verity.web.api.reporting import build_reporting_router


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

    # Reporting — dashboard + inventory aggregates.
    router.include_router(build_reporting_router(verity))

    # Additional sub-routers (registry, runtime, lifecycle, decisions,
    # applications, authoring, draft edit, audit) will slot in here as
    # they are built out.

    return router
