"""Verity Studio Routes — Server-side rendered HTML pages.

The routing layer for Verity Studio (see ``studio_app.py``). Studio
mounts at ``/studio/`` on the main FastAPI app and presents a
four-mode IA — Compose, Validate, Deploy, Govern — over the same
governance registry the Admin console reads.

Studio routes call the in-process Verity SDK directly rather than the
public ``/api/v1/*`` JSON API. The two surfaces share the same write
paths (PATCH endpoints, validation rules, optimistic concurrency) but
Studio renders HTML and uses HTMX for partial updates.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from psycopg.errors import Error as PsycopgError

logger = logging.getLogger(__name__)


def _render(
    templates: Jinja2Templates,
    request: Request,
    template_name: str,
    **context: Any,
):
    """Render a Jinja2 template with Starlette 1.0's calling convention.

    Starlette 1.0 changed TemplateResponse to take ``request`` as the
    first positional argument (used to be inside the context dict).
    Centralised here so route handlers stay clean.
    """
    return templates.TemplateResponse(request, template_name, context)


def _isoformat_or_empty(value: Any) -> str:
    """Render a datetime as ISO 8601, or return '' for None / non-datetime."""
    if value is None:
        return ""
    iso = getattr(value, "isoformat", None)
    return iso() if callable(iso) else str(value)


def create_studio_routes(verity, templates_dir: str) -> APIRouter:
    """Build the APIRouter for all Studio pages.

    Args:
        verity: Initialized Verity SDK client.
        templates_dir: Filesystem path to the Jinja2 templates dir.

    Returns:
        An APIRouter ready to be ``include_router``-ed onto the Studio
        FastAPI sub-app.
    """
    router = APIRouter()
    templates = Jinja2Templates(directory=templates_dir)

    # ── ROOT REDIRECT ────────────────────────────────────────
    @router.get("/")
    async def studio_home():
        # Compose is the natural landing page — the four modes are
        # equally first-class, but Compose is where authoring sessions
        # tend to start.
        return RedirectResponse(url="/studio/compose")

    # ── MODE LANDING PAGES ───────────────────────────────────

    @router.get("/compose", response_class=HTMLResponse)
    async def compose(request: Request):
        await verity.ensure_connected()
        # One round-trip to fetch every count card on the landing.
        summary = await verity.registry.db.fetch_one(
            "studio_compose_summary",
        ) or {}
        return _render(
            templates, request, "studio/compose.html",
            active_mode="compose",
            summary=summary,
        )

    @router.get("/validate", response_class=HTMLResponse)
    async def validate(request: Request):
        return _render(
            templates, request, "studio/validate.html",
            active_mode="validate",
        )

    @router.get("/deploy", response_class=HTMLResponse)
    async def deploy(request: Request):
        return _render(
            templates, request, "studio/deploy.html",
            active_mode="deploy",
        )

    @router.get("/govern", response_class=HTMLResponse)
    async def govern(request: Request):
        return _render(
            templates, request, "studio/govern.html",
            active_mode="govern",
        )

    # ── COMPOSE: PROMPTS ─────────────────────────────────────
    # Browse the prompt library, drill into one prompt's versions,
    # edit drafts in place. Non-draft versions are read-only with a
    # clone-to-draft action surfaced in the UI (clone handler is a
    # follow-up).

    @router.get("/compose/prompts", response_class=HTMLResponse)
    async def compose_prompts_list(request: Request):
        await verity.ensure_connected()
        # The summary query returns one row per prompt enriched with
        # version_count / draft_count / champion_label / last_modified
        # so the table can render real signal per row in a single
        # round-trip — no N+1 fetch over prompt_version.
        prompts = await verity.registry.db.fetch_all(
            "list_prompts_with_state_summary",
        )
        return _render(
            templates, request, "studio/compose_prompts_list.html",
            active_mode="compose",
            prompts=prompts,
        )

    @router.get("/compose/prompts/{name}", response_class=HTMLResponse)
    async def compose_prompt_detail(request: Request, name: str):
        await verity.ensure_connected()
        prompt = await verity.registry.get_prompt_by_name(name)
        if not prompt:
            return HTMLResponse(
                f"<h1>Prompt {name!r} not found</h1>", status_code=404,
            )

        versions = await verity.registry.list_prompt_versions(prompt["id"])
        consumers = await verity.registry.get_entity_consumers(
            "prompt", prompt["id"],
        )
        return _render(
            templates, request, "studio/compose_prompt_detail.html",
            active_mode="compose",
            prompt=prompt,
            versions=versions,
            consumers=consumers,
        )

    @router.get(
        "/compose/prompts/{name}/versions/{version_id}/edit",
        response_class=HTMLResponse,
    )
    async def compose_prompt_edit(
        request: Request, name: str, version_id: str,
    ):
        await verity.ensure_connected()
        prompt = await verity.registry.get_prompt_by_name(name)
        if not prompt:
            return HTMLResponse(
                f"<h1>Prompt {name!r} not found</h1>", status_code=404,
            )

        # Look up the specific version directly. We need the full row
        # (content, etc.), so go through the schema rather than the
        # truncated list_prompt_versions output.
        version = await verity.db.fetch_one_raw(
            """
            SELECT *
            FROM governance.prompt_version
            WHERE id = %(id)s::uuid
            """,
            {"id": str(version_id)},
        )
        if not version or str(version["prompt_id"]) != str(prompt["id"]):
            return HTMLResponse(
                f"<h1>Version not found</h1>", status_code=404,
            )

        # Non-draft versions are immutable — bounce back to detail.
        # The detail page shows a "Clone to Draft" action on those rows.
        state = str(version.get("lifecycle_state"))
        if state != "draft":
            return RedirectResponse(
                url=f"/studio/compose/prompts/{name}",
                status_code=303,
            )

        consumers = await verity.registry.get_entity_consumers(
            "prompt", prompt["id"],
        )

        return _render(
            templates, request, "studio/compose_prompt_edit.html",
            active_mode="compose",
            prompt=prompt,
            version=version,
            consumers=consumers,
            updated_at_iso=_isoformat_or_empty(version.get("updated_at")),
        )

    @router.post(
        "/compose/prompts/{name}/versions/{source_version_id}/clone-to-draft",
        response_class=HTMLResponse,
    )
    async def compose_prompt_clone_to_draft(
        request: Request, name: str, source_version_id: str,
    ):
        """Create a new draft from a non-draft version, then redirect
        to its edit page.

        Most prompts in a mature system are in promoted states
        (champion / challenger / etc.), so the natural authoring loop
        for an SME is "click Clone to Draft on the champion → edit
        the new draft → run validation → promote". This route is
        what makes that loop work without leaving Studio.
        """
        await verity.ensure_connected()

        prompt = await verity.registry.get_prompt_by_name(name)
        if not prompt:
            return HTMLResponse(
                f"<h1>Prompt {name!r} not found</h1>", status_code=404,
            )

        source = await verity.db.fetch_one_raw(
            """
            SELECT id, prompt_id, version_label
            FROM governance.prompt_version
            WHERE id = %(id)s::uuid
            """,
            {"id": str(source_version_id)},
        )
        if not source or str(source["prompt_id"]) != str(prompt["id"]):
            return HTMLResponse(
                "<h1>Source version not found</h1>", status_code=404,
            )

        new_label = await _next_available_version_label(
            verity, str(prompt["id"]), str(source["version_label"]),
        )

        try:
            new_version = await verity.registry.clone_prompt_version(
                source_version_id=str(source_version_id),
                new_version_label=new_label,
                change_summary=f"Cloned from v{source['version_label']} via Studio.",
            )
        except (ValueError, PsycopgError) as exc:
            logger.warning("clone-to-draft failed: %s", exc)
            return HTMLResponse(
                f"<h1>Could not clone</h1><p>{exc}</p>", status_code=400,
            )

        return RedirectResponse(
            url=(
                f"/studio/compose/prompts/{name}"
                f"/versions/{new_version['id']}/edit"
            ),
            status_code=303,
        )

    @router.post(
        "/compose/prompts/{name}/versions/{version_id}/save",
        response_class=HTMLResponse,
    )
    async def compose_prompt_save(
        request: Request, name: str, version_id: str,
    ):
        """HTMX save handler. Returns the #save-status partial.

        Wraps ``Registry.update_prompt_version_draft`` and translates
        the three failure modes (404 / lifecycle / stale_write) into
        flavoured partial responses for the editor.
        """
        await verity.ensure_connected()
        form = await request.form()

        # Build the SDK update payload. The expected_updated_at field
        # carries the optimistic-concurrency stamp the editor read on
        # GET; if it's an empty string, treat that as "no check".
        expected = form.get("expected_updated_at") or None

        # Only include fields the user actually edited. The SDK uses
        # COALESCE so an absent key preserves the existing value.
        fields: dict[str, Any] = {}
        for key in (
            "content", "change_summary", "api_role",
            "governance_tier", "sensitivity_level", "author_name",
        ):
            value = form.get(key)
            if value is not None:
                fields[key] = value
        if expected is not None:
            fields["expected_updated_at"] = expected

        try:
            row = await verity.registry.update_prompt_version_draft(
                version_id=version_id, **fields,
            )
        except (ValueError, PsycopgError) as exc:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message=f"Save rejected: {exc}",
            )

        if row:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="ok",
                new_updated_at=_isoformat_or_empty(row.get("updated_at")),
                entity_label=f"v{row.get('version_label')}" if row.get("version_label") else None,
            )

        # Zero rows from the SDK update — figure out why and surface
        # the right partial.
        return await _classify_save_failure(
            request, templates, verity, name, version_id,
        )

    # ── COMPOSE: INFERENCE CONFIGS ───────────────────────────
    # Configs aren't versioned, so the editor flow is:
    #   list → edit page (same URL as detail) → save in place.
    # No clone-to-draft since there's no draft concept; an edit
    # immediately affects every consumer that references the config.
    # The where-used panel surfaces consumer lifecycle states so the
    # author can see the blast radius before saving.

    @router.get("/compose/configs", response_class=HTMLResponse)
    async def compose_configs_list(request: Request):
        await verity.ensure_connected()
        configs = await verity.registry.list_inference_configs()
        return _render(
            templates, request, "studio/compose_configs_list.html",
            active_mode="compose",
            configs=configs,
        )

    @router.get("/compose/configs/{name}", response_class=HTMLResponse)
    async def compose_config_detail(request: Request, name: str):
        await verity.ensure_connected()
        config = await verity.registry.get_inference_config_by_name(name)
        if not config:
            return HTMLResponse(
                f"<h1>Inference config {name!r} not found</h1>",
                status_code=404,
            )

        consumers = await verity.registry.get_entity_consumers(
            "inference_config", config["id"],
        )

        # Stop sequences come back from psycopg as a Python list of
        # strings (the column is TEXT[]). Render as newline-joined for
        # the textarea; on save the inverse parse turns blank lines
        # into ``None`` and keeps non-empty lines.
        stop_seq_text = "\n".join(config.get("stop_sequences") or [])

        # Extended params is JSONB. Display as pretty-printed JSON
        # for the textarea so authors can hand-edit thinking, caching,
        # batch params, etc.
        import json as _json
        ext_params = config.get("extended_params") or {}
        ext_params_text = _json.dumps(ext_params, indent=2) if ext_params else ""

        return _render(
            templates, request, "studio/compose_config_detail.html",
            active_mode="compose",
            config=config,
            consumers=consumers,
            updated_at_iso=_isoformat_or_empty(config.get("updated_at")),
            stop_sequences_text=stop_seq_text,
            extended_params_text=ext_params_text,
        )

    @router.post(
        "/compose/configs/{name}/save",
        response_class=HTMLResponse,
    )
    async def compose_config_save(request: Request, name: str):
        """HTMX save handler for inference_config edits."""
        await verity.ensure_connected()
        form = await request.form()

        config = await verity.registry.get_inference_config_by_name(name)
        if not config:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message=f"Inference config {name!r} no longer exists.",
            )

        expected = form.get("expected_updated_at") or None

        # Build the update payload. Empty strings on optional fields
        # are treated as "unchanged" (matches COALESCE semantics),
        # not "set to empty string" — saving a literally-empty
        # description is rare and the API path supports it explicitly.
        fields: dict[str, Any] = {}
        for key in (
            "display_name", "description", "intended_use", "model_name",
        ):
            value = form.get(key)
            if value is not None and value != "":
                fields[key] = value

        # Numeric fields parse — empty string is unchanged.
        for key in ("temperature", "top_p"):
            raw = (form.get(key) or "").strip()
            if raw:
                try:
                    fields[key] = float(raw)
                except ValueError:
                    return _render(
                        templates, request, "studio/_partials/save_status.html",
                        status="error",
                        message=f"{key!r} must be a number; got {raw!r}.",
                    )

        for key in ("max_tokens", "top_k"):
            raw = (form.get(key) or "").strip()
            if raw:
                try:
                    fields[key] = int(raw)
                except ValueError:
                    return _render(
                        templates, request, "studio/_partials/save_status.html",
                        status="error",
                        message=f"{key!r} must be an integer; got {raw!r}.",
                    )

        # stop_sequences: textarea, one entry per line.
        stop_raw = form.get("stop_sequences")
        if stop_raw is not None:
            sequences = [
                line.strip()
                for line in stop_raw.splitlines()
                if line.strip()
            ]
            # Always send the list — explicit empty list means "clear".
            fields["stop_sequences"] = sequences

        # extended_params: JSON textarea. Empty string → no change.
        ext_raw = (form.get("extended_params") or "").strip()
        if ext_raw:
            import json as _json
            try:
                fields["extended_params"] = _json.loads(ext_raw)
            except _json.JSONDecodeError as exc:
                return _render(
                    templates, request, "studio/_partials/save_status.html",
                    status="error",
                    message=f"extended_params must be valid JSON: {exc}",
                )

        if expected is not None:
            fields["expected_updated_at"] = expected

        try:
            row = await verity.registry.update_inference_config(
                config_id=config["id"], **fields,
            )
        except (ValueError, PsycopgError) as exc:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message=f"Save rejected: {exc}",
            )

        if row:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="ok",
                new_updated_at=_isoformat_or_empty(row.get("updated_at")),
                entity_label=row.get("name"),
            )

        # Zero rows → either the row vanished or the stamp was stale.
        # Configs aren't versioned, so there's no lifecycle case here
        # (only "not found" or "stale_write").
        status_row = await verity.db.fetch_one(
            "get_inference_config_status_for_concurrency",
            {"config_id": str(config["id"])},
        )
        if not status_row:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message="This config no longer exists in the database.",
            )

        return _render(
            templates, request, "studio/_partials/save_status.html",
            status="conflict",
            current_updated_at=_isoformat_or_empty(status_row.get("updated_at")),
            reload_url=f"/studio/compose/configs/{name}",
        )

    # ── COMPOSE: TOOLS ───────────────────────────────────────
    # Tools are global, unversioned code/integration assets. The
    # editor flow mirrors configs:
    #   list → edit page (same URL as detail) → save in place.
    # An edit immediately affects every agent_version / task_version
    # that authorises the tool. The where-used panel + warning banner
    # surface the production-blast-radius before save.

    @router.get("/compose/tools", response_class=HTMLResponse)
    async def compose_tools_list(request: Request):
        await verity.ensure_connected()
        tools = await verity.registry.list_tools()
        return _render(
            templates, request, "studio/compose_tools_list.html",
            active_mode="compose",
            tools=tools,
        )

    @router.get("/compose/tools/{name}", response_class=HTMLResponse)
    async def compose_tool_detail(request: Request, name: str):
        await verity.ensure_connected()
        tool = await verity.registry.db.fetch_one(
            "get_tool_by_name", {"tool_name": name},
        )
        if not tool:
            return HTMLResponse(
                f"<h1>Tool {name!r} not found</h1>", status_code=404,
            )

        consumers = await verity.registry.get_entity_consumers(
            "tool", tool["id"],
        )

        # JSON / list fields → render-friendly text representations.
        import json as _json
        input_schema_text = _json.dumps(tool.get("input_schema") or {}, indent=2)
        output_schema_text = _json.dumps(tool.get("output_schema") or {}, indent=2)
        mock_responses = tool.get("mock_responses") or {}
        mock_responses_text = (
            _json.dumps(mock_responses, indent=2) if mock_responses else ""
        )
        tags_text = "\n".join(tool.get("tags") or [])

        return _render(
            templates, request, "studio/compose_tool_detail.html",
            active_mode="compose",
            tool=tool,
            consumers=consumers,
            updated_at_iso=_isoformat_or_empty(tool.get("updated_at")),
            input_schema_text=input_schema_text,
            output_schema_text=output_schema_text,
            mock_responses_text=mock_responses_text,
            tags_text=tags_text,
        )

    @router.post(
        "/compose/tools/{name}/save",
        response_class=HTMLResponse,
    )
    async def compose_tool_save(request: Request, name: str):
        """HTMX save handler for a tool edit."""
        await verity.ensure_connected()
        form = await request.form()

        tool = await verity.registry.db.fetch_one(
            "get_tool_by_name", {"tool_name": name},
        )
        if not tool:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message=f"Tool {name!r} no longer exists.",
            )

        expected = form.get("expected_updated_at") or None

        fields: dict[str, Any] = {}

        # Plain text fields — empty string treated as "no change"
        # to match the COALESCE pattern.
        for key in (
            "display_name", "description",
            "transport", "mcp_server_name", "mcp_tool_name",
            "implementation_path", "mock_response_key",
            "data_classification_max",
        ):
            value = form.get(key)
            if value is not None and value != "":
                fields[key] = value

        # JSON-typed fields. Empty string → no change. Bad JSON → error.
        import json as _json
        for key in ("input_schema", "output_schema", "mock_responses"):
            raw = (form.get(key) or "").strip()
            if raw:
                try:
                    fields[key] = _json.loads(raw)
                except _json.JSONDecodeError as exc:
                    return _render(
                        templates, request, "studio/_partials/save_status.html",
                        status="error",
                        message=(
                            f"{key!r} must be valid JSON: {exc}"
                        ),
                    )

        # Boolean checkboxes. HTML form sends the field only when
        # checked, so absence means False — but absence ALSO needs to
        # turn into an explicit False (not "no change"), otherwise a
        # user can never uncheck a flag. The form template uses
        # ``<input type="hidden" name="X" value="0">`` followed by
        # ``<input type="checkbox" name="X" value="1">`` so we always
        # see at least one value here; the truthy-or-not interpretation
        # picks the right answer.
        for key in (
            "mock_mode_enabled", "is_write_operation", "requires_confirmation",
        ):
            values = form.getlist(key)
            if values:
                # Last value wins — when both hidden=0 and checkbox=1
                # are submitted, the checkbox comes second and we read
                # truthy. When only the hidden=0 is submitted (unchecked),
                # we read falsy.
                fields[key] = values[-1] not in ("0", "false", "False", "")

        # tags: textarea, one per line. Always send the parsed list so
        # clearing the textarea actually clears the tags.
        tags_raw = form.get("tags")
        if tags_raw is not None:
            tags = [
                line.strip()
                for line in tags_raw.splitlines()
                if line.strip()
            ]
            fields["tags"] = tags

        if expected is not None:
            fields["expected_updated_at"] = expected

        try:
            row = await verity.registry.update_tool(
                tool_id=tool["id"], **fields,
            )
        except (ValueError, PsycopgError) as exc:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message=f"Save rejected: {exc}",
            )

        if row:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="ok",
                new_updated_at=_isoformat_or_empty(row.get("updated_at")),
                entity_label=row.get("name"),
            )

        # Zero rows → look up the row to distinguish missing vs stale.
        status_row = await verity.db.fetch_one(
            "get_tool_status_for_concurrency",
            {"tool_id": str(tool["id"])},
        )
        if not status_row:
            return _render(
                templates, request, "studio/_partials/save_status.html",
                status="error",
                message="This tool no longer exists in the database.",
            )

        return _render(
            templates, request, "studio/_partials/save_status.html",
            status="conflict",
            current_updated_at=_isoformat_or_empty(status_row.get("updated_at")),
            reload_url=f"/studio/compose/tools/{name}",
        )

    return router


# ── Save-failure classifier ────────────────────────────────────────────────
# Lives at module level so it's testable in isolation. Mirrors the API
# layer's _classify_update_failure but renders an HTML partial instead
# of raising HTTPException.


async def _classify_save_failure(
    request: Request,
    templates: Jinja2Templates,
    verity,
    name: str,
    version_id: str,
):
    """Diagnose a zero-row PATCH and pick the right save_status partial.

    Three cases mirror the JSON API's:
      * row not found → "error" with a not-found message
      * row exists, not draft → "error" with a clone-to-draft hint
      * row in draft, stamp differs → "conflict" partial showing the
        current updated_at so the user can reload deliberately
    """
    status_row = await verity.db.fetch_one(
        "get_prompt_version_status_for_concurrency",
        {"version_id": str(version_id)},
    )
    if not status_row:
        return _render(
            templates, request, "studio/_partials/save_status.html",
            status="error",
            message="This version no longer exists in the database.",
        )

    state = str(status_row.get("lifecycle_state"))
    if state != "draft":
        return _render(
            templates, request, "studio/_partials/save_status.html",
            status="error",
            message=(
                f"This version is now in '{state}' state and cannot be "
                "edited in place. Reload the page and clone to a new "
                "draft to keep working."
            ),
        )

    # Same lifecycle but updated_at differs → stale write.
    return _render(
        templates, request, "studio/_partials/save_status.html",
        status="conflict",
        current_updated_at=_isoformat_or_empty(status_row.get("updated_at")),
        reload_url=(
            f"/studio/compose/prompts/{name}/versions/{version_id}/edit"
        ),
    )


async def _next_available_version_label(
    verity, prompt_id: str, source_label: str,
) -> str:
    """Pick the next free patch-bumped version_label for a prompt.

    Starts from the source's patch + 1 and increments until the
    candidate doesn't collide with an existing prompt_version. Most
    prompts have small version histories so this finishes immediately;
    the loop exists for safety when patch slots have already been used.
    """
    try:
        major_str, minor_str, patch_str = source_label.split(".")
        major, minor, patch = int(major_str), int(minor_str), int(patch_str)
    except ValueError:
        # If the source label is non-semver (shouldn't happen for
        # prompts we created, but defensive), default to a 0.0.1
        # bump from a synthetic 0.0.0 start.
        major, minor, patch = 0, 0, 0

    while True:
        patch += 1
        candidate = f"{major}.{minor}.{patch}"
        existing = await verity.db.fetch_one_raw(
            """
            SELECT 1
            FROM governance.prompt_version
            WHERE prompt_id = %(pid)s::uuid
              AND version_label = %(label)s
            """,
            {"pid": prompt_id, "label": candidate},
        )
        if not existing:
            return candidate
