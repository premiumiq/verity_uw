"""Application-management endpoints.

An "application" is Verity's multi-tenancy anchor — every consuming
product (UW demo, the DS Workbench, any future business app) registers
itself as an application and maps its agents / tasks / prompts / tools /
pipelines to that app. The activity + purge + unregister endpoints here
are what powers the DS Workbench cleanup notebook's start-fresh flow.

Three-step cleanup contract (exercised by `99_cleanup.ipynb`):
    1. GET    /applications/{name}/activity   — show counts before deciding.
    2. DELETE /applications/{name}/activity   — wipe decisions + overrides
                                                 + execution_contexts
                                                 (guarded by VERITY_ALLOW_PURGE=1).
    3. DELETE /applications/{name}            — unregister the app + its
                                                 entity mappings (requires
                                                 step 2 first — otherwise
                                                 the execution_context FK
                                                 blocks the delete).
"""

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from psycopg.errors import Error as PsycopgError


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _require_app(verity, name: str) -> dict:
    """Resolve an application by name or raise 404."""
    app = await verity.registry.get_application_by_name(name)
    if not app:
        raise HTTPException(
            status_code=404, detail=f"Application '{name}' not found",
        )
    return app


def build_applications_router(verity) -> APIRouter:
    router = APIRouter(tags=["applications"])

    # ── Application CRUD ──────────────────────────────────────

    @router.post("/applications")
    async def register_application(body: dict[str, Any]) -> dict:
        """Register a new consuming application.

        Body: name (unique), display_name, description.
        """
        try:
            return await verity.registry.register_application(**body)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/applications")
    async def list_applications() -> list[dict]:
        return await verity.registry.list_applications()

    @router.get("/applications/{name}")
    async def get_application(name: str) -> dict:
        return await _require_app(verity, name)

    @router.delete("/applications/{name}")
    async def unregister_application(name: str) -> dict:
        """Unregister an application and drop all its entity mappings.

        Returns 409 if any activity (decisions / execution_contexts)
        is still linked — purge that first via the activity endpoint.
        """
        try:
            return await verity.registry.unregister_application(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PsycopgError as exc:
            # Most common case: execution_context FK still referenced.
            # Surface as 409 with a hint so the cleanup notebook knows
            # which endpoint to call first.
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Cannot unregister '{name}' while activity remains. "
                    f"Call DELETE /applications/{name}/activity first. "
                    f"({exc})"
                ),
            )

    # ── Entity mapping CRUD ───────────────────────────────────

    @router.get("/applications/{name}/entities")
    async def list_application_entities(
        name: str,
        entity_type: Optional[str] = Query(
            None,
            description="Filter by entity_type: agent, task, prompt, tool, pipeline.",
        ),
    ) -> list[dict]:
        """List entities mapped to this application."""
        app = await _require_app(verity, name)
        return await verity.registry.list_application_entities(
            application_id=app["id"], entity_type=entity_type,
        )

    @router.post("/applications/{name}/entities")
    async def map_entity(name: str, body: dict[str, Any]) -> dict:
        """Map an entity to this application.

        Body: entity_type (agent/task/prompt/tool/pipeline), entity_id (UUID).
        """
        app = await _require_app(verity, name)
        try:
            return await verity.registry.map_entity_to_application(
                application_id=app["id"],
                entity_type=body["entity_type"],
                entity_id=body["entity_id"],
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.delete("/applications/{name}/entities/{entity_type}/{entity_id}")
    async def unmap_entity(
        name: str, entity_type: str, entity_id: str,
    ) -> dict:
        """Remove a single entity mapping from this application.
        Returns 404 if no such mapping exists."""
        app = await _require_app(verity, name)
        try:
            row = await verity.registry.unmap_entity_from_application(
                application_id=app["id"],
                entity_type=entity_type,
                entity_id=entity_id,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No mapping of {entity_type} {entity_id} to "
                    f"application '{name}'."
                ),
            )
        return {"deleted_id": row["id"]}

    # ── Activity / purge ──────────────────────────────────────

    @router.get("/applications/{name}/activity")
    async def get_application_activity(name: str) -> dict:
        """Counts of decisions / overrides / execution_contexts /
        entity_mappings tied to this application. Read-only."""
        activity = await verity.registry.get_application_activity(name)
        if activity is None:
            raise HTTPException(
                status_code=404, detail=f"Application '{name}' not found",
            )
        return activity

    @router.delete("/applications/{name}/activity")
    async def purge_application_activity(name: str) -> dict:
        """Delete all decisions, overrides, and execution_contexts for
        this application. Leaves the application row and entity
        mappings intact. Irreversible — guarded by the environment
        flag VERITY_ALLOW_PURGE=1.

        Returns 400 if the env flag is not set, 404 if the app is
        unknown, 200 with per-table counts on success.
        """
        try:
            return await verity.registry.purge_application_activity(name)
        except ValueError as exc:
            # Two kinds of ValueError: missing env flag (400) vs unknown
            # app (404). Distinguished by message content — cleaner than
            # inventing a typed exception hierarchy for one call site.
            message = str(exc)
            if "not found" in message:
                raise HTTPException(status_code=404, detail=message)
            raise _as_400(exc)
        except PsycopgError as exc:
            raise _as_400(exc)

    # ── Execution contexts ────────────────────────────────────

    @router.post("/execution-contexts")
    async def create_execution_context(body: dict[str, Any]) -> dict:
        """Create (or upsert) a business-level execution context.

        Body: application_id (UUID), context_ref (string, unique per app),
        context_type (optional), metadata (optional dict).

        context_ref is opaque to Verity — the consuming app decides what
        it means (submission id, policy id, etc.). Uniqueness is per
        (application_id, context_ref); re-POSTing the same pair updates
        metadata.
        """
        try:
            return await verity.registry.create_execution_context(
                application_id=body["application_id"],
                context_ref=body["context_ref"],
                context_type=body.get("context_type"),
                metadata=body.get("metadata"),
            )
        except KeyError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Missing required field: {exc.args[0]}",
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    return router
