"""Registry read endpoints — catalog lists, config resolution, version listings.

All routes here are GET-only and wrap existing `verity.registry.*` SDK
methods. Authoring POST/PATCH/PUT/DELETE endpoints live in a separate
module so this file stays scoped to read operations.

Resolution paths for `get_*_config` follow the SDK priority:
    version_id (direct)  >  effective_date (SCD-2 temporal)  >  champion
When neither query param is supplied, the caller receives the current
champion, matching what the runtime would resolve in live production.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from verity.contracts.config import AgentConfig, TaskConfig


def build_registry_router(verity) -> APIRouter:
    """Build the catalog + resolve + versions subset of the REST API."""
    router = APIRouter(tags=["registry"])

    # ── Catalog lists ─────────────────────────────────────────
    # Raw dicts from the SDK go straight out as JSON — no Pydantic
    # response model because these rows carry a wide, read-heavy mix of
    # joined columns that differs per query. FastAPI will still document
    # them in OpenAPI as `list[dict]`.

    @router.get("/agents")
    async def list_agents() -> list[dict]:
        """List every agent header (one row per named agent) with
        joined champion metadata."""
        return await verity.registry.list_agents()

    @router.get("/tasks")
    async def list_tasks() -> list[dict]:
        return await verity.registry.list_tasks()

    @router.get("/prompts")
    async def list_prompts() -> list[dict]:
        return await verity.registry.list_prompts()

    @router.get("/tools")
    async def list_tools() -> list[dict]:
        return await verity.registry.list_tools()

    @router.get("/pipelines")
    async def list_pipelines() -> list[dict]:
        return await verity.registry.list_pipelines()

    @router.get("/inference-configs")
    async def list_inference_configs() -> list[dict]:
        return await verity.registry.list_inference_configs()

    @router.get("/mcp-servers")
    async def list_mcp_servers() -> list[dict]:
        return await verity.registry.list_mcp_servers()

    # ── Full resolved configs ─────────────────────────────────
    # The response IS the "complete entity config of a version": agent
    # row + inference_config + prompt assignments + tool authorizations.
    # Callers that want to modify-and-re-register use this as input to
    # the clone-and-patch workflow (see /versions/{id}/clone endpoints).

    @router.get("/agents/{name}/config", response_model=AgentConfig)
    async def get_agent_config(
        name: str,
        version_id: Optional[UUID] = Query(
            None,
            description="Direct version lookup. If set, ignores effective_date and champion.",
        ),
        effective_date: Optional[datetime] = Query(
            None,
            description="SCD Type 2 temporal resolution. If set, returns the champion at this date.",
        ),
    ) -> AgentConfig:
        try:
            return await verity.registry.get_agent_config(
                name, effective_date=effective_date, version_id=version_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @router.get("/tasks/{name}/config", response_model=TaskConfig)
    async def get_task_config(
        name: str,
        version_id: Optional[UUID] = Query(None),
        effective_date: Optional[datetime] = Query(None),
    ) -> TaskConfig:
        try:
            return await verity.registry.get_task_config(
                name, effective_date=effective_date, version_id=version_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    # ── Version listings ──────────────────────────────────────
    # Endpoints accept a name (caller-friendly), resolve it to the id,
    # then list versions. The 404 path returns early with a clear
    # message so the notebook/client knows which entity was missing.

    @router.get("/agents/{name}/versions")
    async def list_agent_versions(name: str) -> list[dict]:
        header = await verity.registry.get_agent_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
        return await verity.registry.list_agent_versions(header["id"])

    @router.get("/tasks/{name}/versions")
    async def list_task_versions(name: str) -> list[dict]:
        header = await verity.registry.get_task_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Task '{name}' not found")
        return await verity.registry.list_task_versions(header["id"])

    @router.get("/prompts/{name}/versions")
    async def list_prompt_versions(name: str) -> list[dict]:
        header = await verity.registry.get_prompt_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")
        return await verity.registry.list_prompt_versions(header["id"])

    @router.get("/pipelines/{name}/versions")
    async def list_pipeline_versions(name: str) -> list[dict]:
        header = await verity.registry.get_pipeline_by_name(name)
        if not header:
            raise HTTPException(status_code=404, detail=f"Pipeline '{name}' not found")
        return await verity.registry.list_pipeline_versions(header["id"])

    return router
