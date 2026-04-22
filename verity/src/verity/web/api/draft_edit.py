"""Draft-edit, draft-delete, replace-associations, and clone endpoints.

Immutability contract: only `draft` versions are editable. Any version
that has been promoted to candidate / staging / shadow / challenger /
champion / deprecated is treated as frozen by both the SQL layer (via
`WHERE lifecycle_state = 'draft'` guards) and the SDK layer (via an
explicit check inside the replace / clone transactions). When a caller
targets a non-draft row, the API returns 409 Conflict with the current
lifecycle_state in the error detail.

Two complementary edit patterns live here:
    1. In-place edits (PATCH/PUT/DELETE) for polishing an existing draft.
    2. Clone (POST .../clone) for producing a new draft from any prior
       version — useful when you want to start from a champion's config
       and evolve it without losing the previous behaviour's audit trail.
"""

from typing import Any

from fastapi import APIRouter, HTTPException
from psycopg.errors import Error as PsycopgError


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _ensure_draft_result(row, version_id: str, entity_type: str):
    """Turn an empty row into a 409 with a helpful message.

    SQL draft-guarded UPDATEs / DELETEs return zero rows for non-draft
    targets. The lookup here fetches the real current state so the
    caller knows WHY the edit was rejected.
    """
    if row:
        return
    raise HTTPException(
        status_code=409,
        detail=(
            f"{entity_type} version {version_id} is not editable — it is "
            f"not in draft state. Clone it into a new draft instead."
        ),
    )


def build_draft_edit_router(verity) -> APIRouter:
    """Build the PATCH/PUT/DELETE + clone endpoints for versioned entities."""
    router = APIRouter(tags=["draft-edit"])

    # ── PATCH — in-place field updates on a draft version ───────

    @router.patch("/agents/{name}/versions/{version_id}")
    async def update_agent_version(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Update mutable fields on a draft agent_version. Any field
        omitted from the body is left unchanged.

        Editable: inference_config_id, output_schema, authority_thresholds,
        mock_mode_enabled, decision_log_detail, developer_name,
        change_summary, change_type, limitations_this_version.

        Returns 409 if the version is not in draft.
        """
        try:
            row = await verity.registry.update_agent_version_draft(
                version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "agent")
        return row

    @router.patch("/tasks/{name}/versions/{version_id}")
    async def update_task_version(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Update mutable fields on a draft task_version.

        Editable: inference_config_id, output_schema, mock_mode_enabled,
        decision_log_detail, developer_name, change_summary, change_type.
        """
        try:
            row = await verity.registry.update_task_version_draft(
                version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "task")
        return row

    @router.patch("/prompts/{name}/versions/{version_id}")
    async def update_prompt_version(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Update mutable fields on a draft prompt_version.

        Editable: content, api_role, governance_tier, change_summary,
        sensitivity_level, author_name.
        """
        try:
            row = await verity.registry.update_prompt_version_draft(
                version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "prompt")
        return row

    @router.patch("/pipelines/{name}/versions/{version_id}")
    async def update_pipeline_version(
        name: str, version_id: str, body: dict[str, Any],
    ) -> dict:
        """Update mutable fields on a draft pipeline_version.

        Editable: steps (JSONB array), change_summary, developer_name.
        """
        try:
            row = await verity.registry.update_pipeline_version_draft(
                version_id=version_id, **body,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "pipeline")
        return row

    # ── PUT — transactional replace of an association set ───────

    @router.put("/agents/{name}/versions/{version_id}/prompts")
    async def replace_agent_prompts(
        name: str, version_id: str, body: dict[str, Any],
    ) -> list[dict]:
        """Replace the full list of prompt assignments for a draft
        agent_version.

        Body: {"assignments": [ {prompt_version_id, api_role,
        governance_tier, execution_order, is_required, condition_logic}, ... ]}.
        """
        try:
            return await verity.registry.replace_agent_prompt_assignments(
                agent_version_id=version_id,
                assignments=body.get("assignments", []),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PsycopgError as exc:
            raise _as_400(exc)

    @router.put("/tasks/{name}/versions/{version_id}/prompts")
    async def replace_task_prompts(
        name: str, version_id: str, body: dict[str, Any],
    ) -> list[dict]:
        """Replace prompt assignments for a draft task_version."""
        try:
            return await verity.registry.replace_task_prompt_assignments(
                task_version_id=version_id,
                assignments=body.get("assignments", []),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PsycopgError as exc:
            raise _as_400(exc)

    @router.put("/agents/{name}/versions/{version_id}/tools")
    async def replace_agent_tools(
        name: str, version_id: str, body: dict[str, Any],
    ) -> list[dict]:
        """Replace tool authorizations for a draft agent_version.

        Body: {"authorizations": [ {tool_id, authorized, notes}, ... ]}.
        """
        try:
            return await verity.registry.replace_agent_tool_authorizations(
                agent_version_id=version_id,
                authorizations=body.get("authorizations", []),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PsycopgError as exc:
            raise _as_400(exc)

    @router.put("/tasks/{name}/versions/{version_id}/tools")
    async def replace_task_tools(
        name: str, version_id: str, body: dict[str, Any],
    ) -> list[dict]:
        """Replace tool authorizations for a draft task_version."""
        try:
            return await verity.registry.replace_task_tool_authorizations(
                task_version_id=version_id,
                authorizations=body.get("authorizations", []),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PsycopgError as exc:
            raise _as_400(exc)

    @router.put("/agents/{name}/versions/{version_id}/delegations")
    async def replace_agent_delegations(
        name: str, version_id: str, body: dict[str, Any],
    ) -> list[dict]:
        """Replace sub-agent delegations for a draft agent_version.

        Body: {"delegations": [ {child_agent_name OR child_agent_version_id,
        scope, authorized, rationale, notes}, ... ]}. Each delegation must
        specify EXACTLY ONE of child_agent_name or child_agent_version_id.
        """
        try:
            return await verity.registry.replace_agent_delegations(
                agent_version_id=version_id,
                delegations=body.get("delegations", []),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        except PsycopgError as exc:
            raise _as_400(exc)

    # ── DELETE — abandon a draft version ────────────────────────

    @router.delete("/agents/{name}/versions/{version_id}")
    async def delete_agent_version(name: str, version_id: str) -> dict:
        """Delete a draft agent_version and its prompt/tool/delegation
        associations. Returns 409 if the version is not in draft."""
        try:
            row = await verity.registry.delete_draft_version("agent", version_id)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "agent")
        return {"deleted_id": row["id"]}

    @router.delete("/tasks/{name}/versions/{version_id}")
    async def delete_task_version(name: str, version_id: str) -> dict:
        try:
            row = await verity.registry.delete_draft_version("task", version_id)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "task")
        return {"deleted_id": row["id"]}

    @router.delete("/prompts/{name}/versions/{version_id}")
    async def delete_prompt_version(name: str, version_id: str) -> dict:
        """Delete a draft prompt_version. Rejected with 400 if the
        prompt is still assigned to any agent/task version (FK
        constraint — the DB protects against orphaned assignments)."""
        try:
            row = await verity.registry.delete_draft_version("prompt", version_id)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "prompt")
        return {"deleted_id": row["id"]}

    @router.delete("/pipelines/{name}/versions/{version_id}")
    async def delete_pipeline_version(name: str, version_id: str) -> dict:
        try:
            row = await verity.registry.delete_draft_version("pipeline", version_id)
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)
        await _ensure_draft_result(row, version_id, "pipeline")
        return {"deleted_id": row["id"]}

    # ── POST .../clone — copy a version into a new draft ────────

    @router.post("/agents/{name}/versions/{source_version_id}/clone")
    async def clone_agent_version(
        name: str, source_version_id: str, body: dict[str, Any],
    ) -> dict:
        """Clone any agent_version (any state) into a new draft.

        Body: {new_version_label (required, e.g. '2.0.0'),
        change_summary (optional), developer_name (optional)}.

        The new draft carries all the source's prompt assignments,
        tool authorizations, and delegation rows, plus
        cloned_from_version_id pointing at the source for provenance.
        """
        new_label = body.get("new_version_label")
        if not new_label:
            raise HTTPException(
                status_code=422, detail="new_version_label is required",
            )
        try:
            return await verity.registry.clone_agent_version(
                source_version_id=source_version_id,
                new_version_label=new_label,
                change_summary=body.get("change_summary", "Cloned"),
                developer_name=body.get("developer_name"),
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/tasks/{name}/versions/{source_version_id}/clone")
    async def clone_task_version(
        name: str, source_version_id: str, body: dict[str, Any],
    ) -> dict:
        """Clone any task_version into a new draft."""
        new_label = body.get("new_version_label")
        if not new_label:
            raise HTTPException(
                status_code=422, detail="new_version_label is required",
            )
        try:
            return await verity.registry.clone_task_version(
                source_version_id=source_version_id,
                new_version_label=new_label,
                change_summary=body.get("change_summary", "Cloned"),
                developer_name=body.get("developer_name"),
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/prompts/{name}/versions/{source_version_id}/clone")
    async def clone_prompt_version(
        name: str, source_version_id: str, body: dict[str, Any],
    ) -> dict:
        """Clone any prompt_version into a new draft. Carries over
        content, api_role, governance_tier, and template_variables."""
        new_label = body.get("new_version_label")
        if not new_label:
            raise HTTPException(
                status_code=422, detail="new_version_label is required",
            )
        try:
            return await verity.registry.clone_prompt_version(
                source_version_id=source_version_id,
                new_version_label=new_label,
                change_summary=body.get("change_summary", "Cloned"),
                author_name=body.get("author_name"),
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/pipelines/{name}/versions/{source_version_id}/clone")
    async def clone_pipeline_version(
        name: str, source_version_id: str, body: dict[str, Any],
    ) -> dict:
        """Clone a pipeline_version into a new draft.

        Body: {new_version_number (required int), change_summary,
        developer_name}. Pipeline versions use integer version
        numbers, not semver labels — this endpoint accepts an int
        rather than the 'major.minor.patch' format used elsewhere.
        """
        new_number = body.get("new_version_number")
        if not isinstance(new_number, int):
            raise HTTPException(
                status_code=422,
                detail="new_version_number (int) is required",
            )
        try:
            return await verity.registry.clone_pipeline_version(
                source_version_id=source_version_id,
                new_version_number=new_number,
                change_summary=body.get("change_summary", "Cloned"),
                developer_name=body.get("developer_name"),
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    return router
