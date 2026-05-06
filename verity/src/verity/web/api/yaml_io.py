"""YAML import / export endpoints.

Two endpoints share this module:

  ``POST /api/v1/yaml/export`` (slice 4A)
    Takes a single entity reference (kind + name + optional version)
    and returns the transitive-closure bundle as YAML text in the
    response body.

  ``POST /api/v1/yaml/import`` (slice 4B)
    Takes a YAML bundle in the request body (text/yaml or
    application/yaml) and persists it to the registry. Two-phase:
    validate references → write. Validation failures return 422 with
    a structured error report; bad YAML returns 400.

The body for both endpoints is YAML text — not JSON — because the
caller is usually a CLI piping a file or an editor pasting content.
The API prefix is /api/v1 because the endpoint shape (request/response,
error codes) matches the rest of the JSON API even though the payload
is a different content-type.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from verity.governance.yaml_io import (
    Exporter,
    Importer,
    ImportValidationError,
    dumps_bundle,
    loads_bundle,
)


# Map the request's ``kind`` field to the exporter method that fetches
# the corresponding entity. Each method accepts a single ``name`` and
# returns a Bundle.
_EXPORT_DISPATCH: dict[str, str] = {
    "agent": "export_agent",
    "task": "export_task",
    "prompt": "export_prompt",
    "tool": "export_tool",
    "inference_config": "export_inference_config",
    "data_connector": "export_data_connector",
}


class ExportRequest(BaseModel):
    """Body for POST /api/v1/yaml/export.

    ``kind`` selects which exporter method runs; ``name`` is passed
    through unchanged. We accept lowercase kind values here even
    though the YAML output uses CamelCase ``kind:`` discriminators —
    the API parameter is for ergonomics, the YAML field is for the
    discriminated union.

    ``version`` (optional) restricts the export to a single version
    of the starting entity. Omitted → all versions of the starting
    entity are included (lineage). Specified → only that version,
    plus the transitive deps it actually references. Ignored for
    header-only kinds (Tool / InferenceConfig / DataConnector) since
    those aren't versioned.
    """
    kind: Literal[
        "agent", "task", "prompt", "tool", "inference_config", "data_connector",
    ]
    name: str
    version: Optional[str] = None


def build_yaml_io_router(verity) -> APIRouter:
    """Build the YAML import/export router. Mounted under /api/v1/."""
    router = APIRouter(tags=["yaml"])

    @router.post(
        "/yaml/export",
        response_class=PlainTextResponse,
        responses={
            200: {
                "content": {"application/yaml": {}},
                "description": "Bundle as YAML text.",
            },
            404: {"description": "No entity with that kind+name."},
            422: {"description": "Invalid ``kind`` or missing ``name``."},
        },
    )
    async def export_yaml(req: ExportRequest) -> PlainTextResponse:
        """Export an entity and its transitive dependencies as a YAML
        bundle.

        The returned YAML is sufficient to recreate the entity (and
        every prompt / tool / config / connector / sub-agent it
        references) in another database via the ``import`` endpoint
        (slice 4B). All references are by name — UUIDs never appear
        in the output.
        """
        method_name = _EXPORT_DISPATCH.get(req.kind)
        if method_name is None:
            # Pydantic's Literal validates this already, but keep an
            # explicit guard so the dispatch table and the type stay
            # in sync as new kinds are added.
            raise HTTPException(
                status_code=422,
                detail=f"Unsupported export kind: {req.kind!r}",
            )

        exporter = Exporter(verity.registry)
        method = getattr(exporter, method_name)

        # The versioned-entity export methods accept ``version`` as a
        # keyword; the header-only ones don't. Branch accordingly so
        # passing ``version`` to a header-only kind is a no-op rather
        # than a TypeError.
        if req.kind in ("agent", "task", "prompt"):
            bundle = await method(req.name, version=req.version)
        else:
            if req.version is not None:
                # Surface the user error rather than silently ignoring.
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"version field is not valid for kind={req.kind!r} "
                        "(only agent / task / prompt are versioned)."
                    ),
                )
            bundle = await method(req.name)

        # The entry-point entity is always the LAST (or only) bucket
        # in the BFS output. If nothing was discovered the entities
        # list is empty — surface that as a 404 so callers don't
        # silently get a bundle with no content.
        if not bundle.entities:
            raise HTTPException(
                status_code=404,
                detail=f"No {req.kind} found with name {req.name!r}.",
            )

        yaml_text = dumps_bundle(bundle)
        return PlainTextResponse(
            yaml_text,
            media_type="application/yaml",
        )

    @router.post(
        "/yaml/import",
        responses={
            200: {"description": "Per-entity import outcomes."},
            400: {"description": "Body is not valid YAML or doesn't match the bundle schema."},
            422: {"description": "Validation failed (dangling references, missing required fields)."},
        },
    )
    async def import_yaml(request: Request) -> dict:
        """Import a YAML bundle into the registry.

        Body: YAML text (Content-Type: application/yaml or text/yaml).

        Behaviour:
            - References are validated against the bundle and the
              target DB before any writes happen.
            - Existing rows are skipped (re-import is a safe no-op).
            - New versions are inserted as ``draft`` regardless of
              the YAML's ``lifecycle_state`` field — promotion is a
              separate, deliberate human action.

        Returns a JSON object summarising what was inserted and what
        was skipped.
        """
        body_bytes = await request.body()
        try:
            yaml_text = body_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Request body must be UTF-8 text: {exc}",
            )

        try:
            bundle = loads_bundle(yaml_text)
        except (yaml.YAMLError, ValueError, ValidationError) as exc:
            # ``loads_bundle`` raises ValueError for empty/non-mapping
            # bodies, ValidationError for shape mismatches, and YAMLError
            # for parse failures. Surface them all as 400 with the
            # exception message so the user can fix it.
            raise HTTPException(
                status_code=400,
                detail=f"Could not parse YAML bundle: {exc}",
            )

        importer = Importer(verity.registry)
        try:
            result = await importer.import_bundle(bundle)
        except ImportValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "error_code": "validation_failed",
                    "errors": [e.to_dict() for e in exc.errors],
                },
            )

        return result.to_dict()

    return router
