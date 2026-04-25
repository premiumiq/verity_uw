"""EDMS REST API routes.

All document operations are exposed as HTTP endpoints. These are what
Verity calls as tool callbacks and what consuming apps use via EdmsClient.
"""

import os
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from edms.core.db import EdmsDatabase
from edms.core.storage import StorageClient
from edms.core.text_extractor import extract_text_from_bytes


def create_routes(
    db: EdmsDatabase,
    storage: StorageClient,
    default_bucket: str,
) -> APIRouter:
    """Create the EDMS API router with injected dependencies."""

    router = APIRouter(prefix="/documents", tags=["documents"])

    # ── LIST DOCUMENTS ────────────────────────────────────────

    @router.get("")
    async def list_documents(
        context_ref: str = Query(..., description="Business context reference"),
        document_type: Optional[str] = Query(None, description="Filter by document type"),
        context_type: Optional[str] = Query(None, description="Filter by context type"),
        include_derivatives: bool = Query(
            False,
            description=(
                "When false (default) returns only original documents — "
                "anything with a parent in document_lineage (extracted text, "
                "JSON derivatives, etc.) is omitted. Set true to get the flat "
                "list including lineage children."
            ),
        ),
    ):
        """List documents for a business context.

        Examples:
            GET /documents?context_ref=submission:SUB-001
            GET /documents?context_ref=submission:SUB-001&include_derivatives=true
        Optional: &document_type=do_application&context_type=submission
        """
        docs = await db.list_documents(
            context_ref, include_derivatives=include_derivatives,
        )
        # Apply optional filters (db returns all for context_ref, we filter here)
        if document_type:
            docs = [d for d in docs if d.get("document_type") == document_type]
        if context_type:
            docs = [d for d in docs if d.get("context_type") == context_type]
        return {"context_ref": context_ref, "count": len(docs), "documents": docs}

    # ── GET DOCUMENT METADATA ─────────────────────────────────

    @router.get("/{document_id}")
    async def get_document(document_id: UUID):
        """Get metadata for a single document."""
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")
        return doc

    # ── GET DOCUMENT TEXT ─────────────────────────────────────

    @router.get("/{document_id}/text")
    async def get_document_text(document_id: UUID):
        """Get extracted text for a document.

        If text hasn't been extracted yet, returns 404 with instructions
        to call POST /documents/{id}/extract first.

        This is the endpoint that Verity tool callbacks invoke when
        an agent needs document content.
        """
        # Check if the document exists
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        # Look for existing text extraction child
        text_child = await db.get_text_child(document_id)
        if not text_child:
            raise HTTPException(
                status_code=404,
                detail=f"No extracted text for document {document_id}. "
                       f"Call POST /documents/{document_id}/extract first.",
            )

        # Read the extracted text from MinIO (bucket from collection)
        try:
            coll = await db.get_collection(doc["collection_id"])
            bucket = coll["storage_container"] if coll else default_bucket
            text = storage.download_text(bucket, text_child["storage_key"])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read text from storage: {e}")

        return {
            "document_id": str(document_id),
            "text_document_id": str(text_child["id"]),
            "text": text,
            "char_count": len(text),
        }

    # ── GET DOCUMENT CONTENT (original file bytes) ─────────────

    @router.get("/{document_id}/content")
    async def get_document_content(document_id: UUID):
        """Download original file bytes from MinIO.

        Returns the raw file content (PDF, text, etc.) so consuming apps
        can send PDFs directly to Claude for classification, or display
        them in a viewer.

        Returns:
            StreamingResponse with original file bytes and content type.
        """
        from fastapi.responses import Response

        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        coll = await db.get_collection(doc["collection_id"])
        bucket = coll["storage_container"] if coll else default_bucket

        try:
            content = storage.download_bytes(bucket, doc["storage_key"])
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to download from storage: {e}")

        return Response(
            content=content,
            media_type=doc.get("content_type", "application/octet-stream"),
            headers={"Content-Disposition": f'inline; filename="{doc["filename"]}"'},
        )

    # ── GET CHILDREN (derived documents) ──────────────────────

    @router.get("/{document_id}/children")
    async def get_children(document_id: UUID):
        """Get all documents derived from a parent document."""
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        children = await db.get_children(document_id)
        return {"parent_document_id": str(document_id), "count": len(children), "children": children}

    # ── UPLOAD DOCUMENT ───────────────────────────────────────

    @router.post("/upload")
    async def upload_document(
        file: UploadFile = File(...),
        collection_id: str = Form(..., description="Collection UUID"),
        context_ref: str = Form(..., description="Business context reference"),
        context_type: str = Form(None), uploaded_by: str = Form("system"),
        document_type: str = Form(None), folder_id: str = Form(None),
        tags: str = Form("{}"),
    ):
        """Upload a document to a collection.

        The MinIO bucket is determined by the collection's storage_container.
        """
        import io
        import json as _json

        # Resolve collection to get bucket
        coll = await db.get_collection(UUID(collection_id))
        if not coll:
            raise HTTPException(status_code=400, detail=f"Collection not found")
        if coll["status"] != "active":
            raise HTTPException(status_code=400, detail=f"Collection '{coll['name']}' is {coll['status']}, cannot upload")

        # Validate tags
        try:
            tags_dict = _json.loads(tags) if isinstance(tags, str) else tags
        except _json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="tags must be valid JSON")
        tag_errors = await db.validate_tags(tags_dict)
        if tag_errors:
            raise HTTPException(status_code=400, detail={"message": "Tag validation failed", "errors": tag_errors})

        # Validate document type
        if document_type:
            type_error = await db.validate_document_type(document_type)
            if type_error:
                raise HTTPException(status_code=400, detail=type_error)

        content = await file.read()
        filename = file.filename or "unnamed"
        bucket = coll["storage_container"]
        safe_prefix = context_ref.replace(":", "/").replace(" ", "_")
        storage_key = f"{safe_prefix}/{filename}"

        stream = io.BytesIO(content)
        storage.client.put_object(bucket, storage_key, stream, len(content),
            content_type=file.content_type or "application/octet-stream")

        fid = UUID(folder_id) if folder_id else None
        doc = await db.insert_document(
            collection_id=UUID(collection_id), folder_id=fid,
            context_ref=context_ref, context_type=context_type,
            filename=filename, content_type=file.content_type,
            file_size_bytes=len(content), storage_key=storage_key,
            document_type=document_type or None, uploaded_by=uploaded_by, tags=tags_dict,
        )
        return doc

    # ── EXTRACT TEXT ───────────────────────────────────────────

    @router.post("/{document_id}/extract")
    async def extract_text(document_id: UUID):
        """Extract text from a document and store as a child document.

        Flow:
        1. Download original file from MinIO
        2. Extract text (PDF page text + form field values, or plain text)
        3. Upload extracted text as {key}.extracted.txt in MinIO
        4. Create child document record
        5. Create lineage record (parent → child, type=text_extraction)

        Returns the extracted text and the child document metadata.
        Idempotent — if text already extracted, returns existing result.
        """
        parent = await db.get_document(document_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        # Get the collection to find the MinIO bucket
        coll = await db.get_collection(parent["collection_id"])
        bucket = coll["storage_container"] if coll else default_bucket

        # Check if already extracted
        existing = await db.get_text_child(document_id)
        if existing:
            text = storage.download_text(bucket, existing["storage_key"])
            return {
                "document_id": str(document_id),
                "text_document_id": str(existing["id"]),
                "text": text,
                "char_count": len(text),
                "already_extracted": True,
            }

        try:
            content = storage.download_bytes(bucket, parent["storage_key"])
            text = extract_text_from_bytes(content, parent["filename"])

            text_key = f"{parent['storage_key']}.extracted.txt"
            text_size = storage.upload_text(bucket, text_key, text)

            child = await db.insert_document(
                collection_id=parent["collection_id"],
                folder_id=parent.get("folder_id"),
                context_ref=parent["context_ref"],
                context_type=parent.get("context_type"),
                filename=f"{parent['filename']}.extracted.txt",
                content_type="text/plain",
                file_size_bytes=text_size,
                storage_key=text_key,
                uploaded_by="edms:text_extraction",
                tags={"transformation": ["text_extraction"], "source_document": [str(document_id)]},
            )

            char_count = len(text)
            includes_form_fields = "FORM FIELD VALUES" in text
            await db.insert_lineage(
                parent_document_id=document_id,
                child_document_id=child["id"],
                transformation_type="text_extraction",
                transformation_method="pymupdf_get_text",
                transformation_status="complete",
                transformation_metadata={
                    "char_count": char_count,
                    "includes_form_fields": includes_form_fields,
                    "source_content_type": parent.get("content_type"),
                },
            )

            return {
                "document_id": str(document_id),
                "text_document_id": str(child["id"]),
                "text": text,
                "char_count": char_count,
                "already_extracted": False,
            }

        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")

    # ── UPDATE DOCUMENT TYPE (after classification) ───────────

    @router.put("/{document_id}/type")
    async def update_document_type(document_id: UUID, document_type: str = Form(...)):
        """Update a document's classified type.

        Called by the classifier agent after it determines the document type.
        Validates against document_type_definition governance table.
        """
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        # Validate against governance table
        type_error = await db.validate_document_type(document_type)
        if type_error:
            raise HTTPException(status_code=400, detail=type_error)

        updated = await db.update_document_type(document_id, document_type)
        return updated

    # ── UPDATE TAGS ───────────────────────────────────────────

    @router.put("/{document_id}/tags")
    async def update_document_tags(document_id: UUID, tags: dict):
        """Update tags on a document (replaces entire tags dict).

        Validates against tag governance tables before applying.
        """
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        tag_errors = await db.validate_tags(tags)
        if tag_errors:
            raise HTTPException(status_code=400, detail={"message": "Tag validation failed", "errors": tag_errors})

        updated = await db.update_document_tags(document_id, tags)
        return updated

    # ── DELETE DOCUMENT ───────────────────────────────────────

    # ── CREATE DERIVED JSON DOCUMENT ──────────────────────────────
    # Generic counterpart to /extract: takes a JSON payload produced by
    # any downstream consumer (a Verity Task today, future agents) and
    # stores it as a new child document under the parent. Same shape as
    # text extraction — child document + lineage row — so the document
    # graph stays consistent regardless of who produced the derivative.
    #
    # Storage key follows the parent's prefix so children co-locate with
    # their parent in MinIO. Idempotency is intentionally NOT enforced
    # here — repeated calls produce repeated derivatives, which lets
    # callers re-run extractors and compare outputs over time.
    @router.post("/{parent_id}/derived")
    async def create_derived_json(parent_id: UUID, body_in: dict):
        """Persist a JSON derivative of an existing document.

        JSON body fields:
          payload                — the dict to store as JSON (required)
          transformation_type    — short label (e.g. 'field_extraction', required)
          transformation_method  — provenance label (e.g. 'claude:field_extractor')
          uploaded_by            — actor name for audit

        Returns the new child document row.
        """
        import json as _json

        payload = body_in.get("payload")
        transformation_type = body_in.get("transformation_type")
        transformation_method = body_in.get("transformation_method", "verity")
        uploaded_by = body_in.get("uploaded_by", "verity")

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")
        if not transformation_type or not isinstance(transformation_type, str):
            raise HTTPException(status_code=400, detail="transformation_type is required")

        parent = await db.get_document(parent_id)
        if not parent:
            raise HTTPException(status_code=404, detail=f"Document {parent_id} not found")

        coll = await db.get_collection(parent["collection_id"])
        bucket = coll["storage_container"] if coll else default_bucket

        body = _json.dumps(payload, indent=2, sort_keys=True, default=str)
        derived_key = f"{parent['storage_key']}.{transformation_type}.json"
        body_size = storage.upload_text(bucket, derived_key, body)

        child = await db.insert_document(
            collection_id=parent["collection_id"],
            folder_id=parent.get("folder_id"),
            context_ref=parent["context_ref"],
            context_type=parent.get("context_type"),
            filename=f"{parent['filename']}.{transformation_type}.json",
            content_type="application/json",
            file_size_bytes=body_size,
            storage_key=derived_key,
            uploaded_by=uploaded_by,
            tags={"transformation": [transformation_type], "source_document": [str(parent_id)]},
        )

        await db.insert_lineage(
            parent_document_id=parent_id,
            child_document_id=child["id"],
            transformation_type=transformation_type,
            transformation_method=transformation_method,
            transformation_status="complete",
            transformation_metadata={
                "payload_size_bytes": body_size,
                "payload_keys": list(payload.keys())[:50],
            },
        )

        return {
            "parent_id": str(parent_id),
            "child_id": str(child["id"]),
            "storage_key": derived_key,
            "size_bytes": body_size,
            "transformation_type": transformation_type,
        }

    @router.delete("/{document_id}")
    async def delete_document(document_id: UUID):
        """Delete a document and its lineage records.

        Also deletes the file from MinIO storage.
        """
        doc = await db.get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

        # Delete from MinIO (bucket from collection)
        try:
            coll = await db.get_collection(doc["collection_id"])
            bucket = coll["storage_container"] if coll else default_bucket
            storage.client.remove_object(bucket, doc["storage_key"])
        except Exception:
            pass  # File may already be gone

        # Delete from database (cascades lineage)
        await db.delete_document(document_id)
        return {"deleted": True, "document_id": str(document_id)}

    return router
