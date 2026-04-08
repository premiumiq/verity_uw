"""EDMS Governance API routes — tag and document type management.

Controls the vocabularies used for document tags and classification types.
No rogue tag keys, no rogue values for critical tags like sensitivity.
"""

from typing import Optional

from fastapi import APIRouter, Form, HTTPException

from edms.core.db import EdmsDatabase


def create_governance_routes(db: EdmsDatabase) -> APIRouter:
    """Create the governance API router."""

    router = APIRouter(tags=["governance"])

    # ── TAG DEFINITIONS ───────────────────────────────────────

    @router.get("/tags")
    async def list_tag_definitions():
        """List all tag definitions (what tag keys are allowed on documents)."""
        definitions = await db.list_tag_definitions(active_only=False)
        return {"count": len(definitions), "tag_definitions": definitions}

    @router.get("/tags/{tag_key}")
    async def get_tag_definition(tag_key: str):
        """Get a tag definition and its allowed values (if restricted)."""
        defn = await db.get_tag_definition(tag_key)
        if not defn:
            raise HTTPException(status_code=404, detail=f"Tag key '{tag_key}' not found")

        result = dict(defn)
        if defn["value_mode"] == "restricted":
            values = await db.list_tag_allowed_values(tag_key)
            result["allowed_values"] = values
        return result

    @router.post("/tags")
    async def create_tag_definition(
        tag_key: str = Form(..., description="Machine name for the tag key"),
        display_name: str = Form(..., description="Human-readable name"),
        value_mode: str = Form("restricted", description="'restricted' or 'freetext'"),
        description: str = Form(None),
        is_required: bool = Form(False, description="Must every document have this tag?"),
        sort_order: int = Form(0),
    ):
        """Create a new tag definition.

        value_mode='restricted': only values from the allowed values list are accepted.
        value_mode='freetext': any string value is accepted.
        """
        if value_mode not in ("restricted", "freetext"):
            raise HTTPException(status_code=400, detail="value_mode must be 'restricted' or 'freetext'")

        existing = await db.get_tag_definition(tag_key)
        if existing:
            raise HTTPException(status_code=409, detail=f"Tag key '{tag_key}' already exists")

        return await db.insert_tag_definition(
            tag_key=tag_key, display_name=display_name,
            value_mode=value_mode, description=description,
            is_required=is_required, sort_order=sort_order,
        )

    @router.put("/tags/{tag_key}")
    async def update_tag_definition(
        tag_key: str,
        display_name: str = Form(None),
        description: str = Form(None),
        value_mode: str = Form(None),
        is_required: bool = Form(None),
        sort_order: int = Form(None),
        active: bool = Form(None),
    ):
        """Update a tag definition."""
        existing = await db.get_tag_definition(tag_key)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Tag key '{tag_key}' not found")

        kwargs = {}
        if display_name is not None:
            kwargs["display_name"] = display_name
        if description is not None:
            kwargs["description"] = description
        if value_mode is not None:
            if value_mode not in ("restricted", "freetext"):
                raise HTTPException(status_code=400, detail="value_mode must be 'restricted' or 'freetext'")
            kwargs["value_mode"] = value_mode
        if is_required is not None:
            kwargs["is_required"] = is_required
        if sort_order is not None:
            kwargs["sort_order"] = sort_order
        if active is not None:
            kwargs["active"] = active

        return await db.update_tag_definition(tag_key, **kwargs)

    @router.delete("/tags/{tag_key}")
    async def delete_tag_definition(tag_key: str):
        """Delete a tag definition and all its allowed values."""
        deleted = await db.delete_tag_definition(tag_key)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Tag key '{tag_key}' not found")
        return {"deleted": True, "tag_key": tag_key}

    # ── TAG ALLOWED VALUES ────────────────────────────────────

    @router.get("/tags/{tag_key}/values")
    async def list_tag_values(tag_key: str):
        """List allowed values for a restricted tag key."""
        defn = await db.get_tag_definition(tag_key)
        if not defn:
            raise HTTPException(status_code=404, detail=f"Tag key '{tag_key}' not found")
        if defn["value_mode"] != "restricted":
            return {"tag_key": tag_key, "value_mode": "freetext", "message": "This tag accepts any value"}

        values = await db.list_tag_allowed_values(tag_key)
        return {"tag_key": tag_key, "count": len(values), "allowed_values": values}

    @router.post("/tags/{tag_key}/values")
    async def add_tag_value(
        tag_key: str,
        value: str = Form(..., description="Machine value"),
        display_name: str = Form(..., description="Human-readable name"),
        description: str = Form(None),
        sort_order: int = Form(0),
    ):
        """Add an allowed value to a restricted tag key."""
        defn = await db.get_tag_definition(tag_key)
        if not defn:
            raise HTTPException(status_code=404, detail=f"Tag key '{tag_key}' not found")
        if defn["value_mode"] != "restricted":
            raise HTTPException(status_code=400, detail=f"Tag '{tag_key}' is freetext, not restricted")

        return await db.insert_tag_allowed_value(
            tag_key=tag_key, value=value, display_name=display_name,
            description=description, sort_order=sort_order,
        )

    @router.delete("/tags/{tag_key}/values/{value}")
    async def delete_tag_value(tag_key: str, value: str):
        """Remove an allowed value from a tag key."""
        deleted = await db.delete_tag_allowed_value(tag_key, value)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Value '{value}' not found for tag '{tag_key}'")
        return {"deleted": True, "tag_key": tag_key, "value": value}

    # ── DOCUMENT TYPE DEFINITIONS ─────────────────────────────

    @router.get("/document-types")
    async def list_document_types():
        """List all document type definitions."""
        types = await db.list_document_type_definitions(active_only=False)
        return {"count": len(types), "document_types": types}

    @router.get("/document-types/{type_key}")
    async def get_document_type(type_key: str):
        """Get a document type definition."""
        defn = await db.get_document_type_definition(type_key)
        if not defn:
            raise HTTPException(status_code=404, detail=f"Document type '{type_key}' not found")
        return defn

    @router.post("/document-types")
    async def create_document_type(
        type_key: str = Form(..., description="Machine name (e.g., 'do_application')"),
        display_name: str = Form(..., description="Human name (e.g., 'D&O Application')"),
        description: str = Form(None),
        sort_order: int = Form(0),
    ):
        """Create a new document type definition."""
        existing = await db.get_document_type_definition(type_key)
        if existing:
            raise HTTPException(status_code=409, detail=f"Document type '{type_key}' already exists")

        return await db.insert_document_type_definition(
            type_key=type_key, display_name=display_name,
            description=description, sort_order=sort_order,
        )

    @router.put("/document-types/{type_key}")
    async def update_document_type_defn(
        type_key: str,
        display_name: str = Form(None),
        description: str = Form(None),
        sort_order: int = Form(None),
        active: bool = Form(None),
    ):
        """Update a document type definition."""
        existing = await db.get_document_type_definition(type_key)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Document type '{type_key}' not found")

        kwargs = {}
        if display_name is not None:
            kwargs["display_name"] = display_name
        if description is not None:
            kwargs["description"] = description
        if sort_order is not None:
            kwargs["sort_order"] = sort_order
        if active is not None:
            kwargs["active"] = active

        return await db.update_document_type_definition(type_key, **kwargs)

    @router.delete("/document-types/{type_key}")
    async def delete_document_type(type_key: str):
        """Delete a document type definition."""
        deleted = await db.delete_document_type_definition(type_key)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Document type '{type_key}' not found")
        return {"deleted": True, "type_key": type_key}

    # ── CONTEXT TYPE DEFINITIONS ─────────────────────────────

    @router.get("/context-types")
    async def list_context_types():
        types = await db.list_context_type_definitions()
        return {"count": len(types), "context_types": types}

    @router.post("/context-types")
    async def create_context_type(
        type_key: str = Form(...), display_name: str = Form(...),
        description: str = Form(None),
    ):
        return await db.insert_context_type_definition(
            type_key=type_key, display_name=display_name, description=description,
        )

    @router.delete("/context-types/{type_key}")
    async def delete_context_type(type_key: str):
        deleted = await db.delete_context_type_definition(type_key)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Context type '{type_key}' not found")
        return {"deleted": True, "type_key": type_key}

    # ── VALIDATION ENDPOINT ───────────────────────────────────

    @router.post("/validate-tags")
    async def validate_tags(tags: dict):
        errors = await db.validate_tags(tags)
        return {"valid": len(errors) == 0, "errors": errors}

    return router
