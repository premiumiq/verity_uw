"""Reporting endpoints — dashboard counts and model inventories.

Every route here is a thin wrapper over the existing `verity.reporting.*`
SDK methods. The Verity client is injected via closure in
`build_reporting_router(verity)` so these routes never reach into module
globals — the factory pattern mirrors `verity/src/verity/web/routes.py`
and keeps tests/dev sessions with multiple clients isolated.
"""

from fastapi import APIRouter

from verity.models.reporting import (
    DashboardCounts,
    ModelInventoryAgent,
    ModelInventoryTask,
)


def build_reporting_router(verity) -> APIRouter:
    """Build the /reporting/* subset of the REST API.

    Args:
        verity: an initialized Verity SDK client instance. Must already
            be `connect()`-ed by the time any request arrives (the caller
            handles that through the FastAPI lifespan hook).

    Returns:
        APIRouter with tag "reporting" and no prefix of its own — the
        parent router in `router.py` contributes the `/api/v1` prefix
        and the `/reporting` segment here comes from each route's path.
    """
    router = APIRouter(tags=["reporting"])

    @router.get("/reporting/dashboard-counts", response_model=DashboardCounts)
    async def dashboard_counts() -> DashboardCounts:
        """Aggregate counts across the Verity catalog — matches the
        numbers shown on the admin UI dashboard at `/admin/`."""
        return await verity.reporting.dashboard_counts()

    @router.get("/reporting/agents", response_model=list[ModelInventoryAgent])
    async def inventory_agents() -> list[ModelInventoryAgent]:
        """Full agent inventory with lifecycle state + owner + metadata."""
        return await verity.reporting.model_inventory_agents()

    @router.get("/reporting/tasks", response_model=list[ModelInventoryTask])
    async def inventory_tasks() -> list[ModelInventoryTask]:
        """Full task inventory with lifecycle state + owner + metadata."""
        return await verity.reporting.model_inventory_tasks()

    return router
