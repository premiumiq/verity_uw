"""EDMS Web UI routes — Jinja2 + HTMX server-rendered pages.

Mounted at /ui/ on the EDMS service (port 8002).
Provides a full CRUD interface for documents, tags, and document types.
"""

import json
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from edms.core.db import EdmsDatabase
from edms.core.storage import StorageClient
from edms.core.text_extractor import extract_text_from_bytes


_TEMPLATES_DIR = Path(__file__).parent / "templates"


def create_ui_routes(
    db: EdmsDatabase,
    storage: StorageClient,
    default_bucket: str,
) -> APIRouter:
    """Create the UI router for the EDMS web interface."""

    router = APIRouter(prefix="/ui", tags=["ui"])
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    def _render(request: Request, template: str, **context):
        """Render a template with common context."""
        return templates.TemplateResponse(request, template, context)

    async def _get_bucket(collection_id) -> str:
        """Resolve MinIO bucket from a collection_id."""
        coll = await db.get_collection(collection_id)
        return coll["storage_container"] if coll else default_bucket

    # ── DOCUMENT BROWSER ──────────────────────────────────────

    @router.get("/", response_class=HTMLResponse)
    async def documents_page(
        request: Request,
        collection_id: Optional[str] = None,
        context_ref: Optional[str] = None,
        document_type: Optional[str] = None,
        folder_id: Optional[str] = None,
    ):
        """Browse documents. Filter by collection, folder, context, or type."""
        if collection_id and folder_id:
            documents = await db.list_documents_in_collection(UUID(collection_id), UUID(folder_id))
        elif collection_id:
            documents = await db.list_documents_in_collection(UUID(collection_id))
        elif context_ref:
            documents = await db.list_documents(context_ref)
        else:
            documents = await db.list_all_documents()

        if document_type:
            documents = [d for d in documents if d.get("document_type") == document_type]

        doc_types = await db.list_document_type_definitions()
        collections = await db.list_collections()
        selected_collection = None
        folder_tree = []
        if collection_id:
            selected_collection = await db.get_collection(UUID(collection_id))
            folder_tree = await db.get_folder_tree(UUID(collection_id))

        return _render(request, "documents.html",
            active_page="documents",
            documents=documents,
            document_types=doc_types,
            collections=collections,
            selected_collection=selected_collection,
            folder_tree=folder_tree,
            filter_context=context_ref,
            filter_type=document_type,
            filter_folder=folder_id,
            filter_collection=collection_id,
        )

    # ── DOCUMENT DETAIL ───────────────────────────────────────

    @router.get("/documents/{document_id}", response_class=HTMLResponse)
    async def document_detail(request: Request, document_id: UUID):
        """View a single document with metadata, tags, text, lineage, and task history."""
        doc = await db.get_document(document_id)
        if not doc:
            return HTMLResponse("<h1>Document not found</h1>", status_code=404)

        # Document types for classification dropdown
        doc_types = await db.list_document_type_definitions()

        # Tag definitions with allowed values for the tag editor
        tag_defs = await db.list_tag_definitions()
        for td in tag_defs:
            if td["value_mode"] == "restricted":
                td["allowed_values"] = await db.list_tag_allowed_values(td["tag_key"])
            else:
                td["allowed_values"] = []

        # Extracted text (if exists)
        extracted_text = None
        text_child = await db.get_text_child(document_id)
        if text_child:
            try:
                bucket = await _get_bucket(doc["collection_id"])
                extracted_text = storage.download_text(bucket, text_child["storage_key"])
            except Exception:
                extracted_text = None

        # Lineage: parent (upstream) and children (downstream)
        parent_doc = await db.get_parent(document_id)
        children = await db.get_children(document_id)

        # Task history for this document
        tasks = await db.list_tasks_for_document(document_id)

        # Folders for the folder assignment dropdown
        all_folders_result = await db._conn.execute("SELECT * FROM folder ORDER BY name")
        all_folders = await all_folders_result.fetchall()

        return _render(request, "document_detail.html",
            active_page="documents",
            doc=doc,
            document_types=doc_types,
            tag_definitions=tag_defs,
            extracted_text=extracted_text,
            parent_doc=parent_doc,
            children=children,
            tasks=tasks,
            all_folders=all_folders,
        )

    # ── UPLOAD PAGE ───────────────────────────────────────────

    @router.get("/upload", response_class=HTMLResponse)
    async def upload_page(request: Request):
        """Show the upload form with folder, type hierarchy, and tag editors."""
        doc_types = await db.list_document_type_definitions()
        type_hierarchy = await db.get_type_hierarchy()
        tag_defs = await db.list_tag_definitions()
        for td in tag_defs:
            if td["value_mode"] == "restricted":
                td["allowed_values"] = await db.list_tag_allowed_values(td["tag_key"])
            else:
                td["allowed_values"] = []
        collections = await db.list_collections()
        all_folders_result = await db._conn.execute("SELECT * FROM folder ORDER BY name")
        all_folders = await all_folders_result.fetchall()
        context_types = await db.list_context_type_definitions()

        return _render(request, "upload.html",
            active_page="upload",
            document_types=doc_types,
            type_hierarchy=type_hierarchy,
            tag_definitions=tag_defs,
            collections=collections,
            all_folders=all_folders,
            context_types=context_types,
        )

    @router.post("/upload")
    async def handle_upload(
        request: Request,
        file: UploadFile = File(...),
        collection_id: str = Form(...),
        context_ref: str = Form(...),
        context_type: str = Form(None),
        uploaded_by: str = Form("manual_upload"),
        document_type: str = Form(None),
        folder_id: str = Form(None),
    ):
        """Handle file upload from the UI form. Collection determines the MinIO bucket."""
        import io

        # Resolve collection for bucket
        coll = await db.get_collection(UUID(collection_id))
        if not coll:
            return RedirectResponse("/ui/upload", status_code=303)
        bucket = coll["storage_container"]

        # Build tags from form fields
        form_data = await request.form()
        tags_dict = _extract_tags_from_form(form_data)
        tag_errors = await db.validate_tags(tags_dict)
        if tag_errors:
            return RedirectResponse("/ui/upload", status_code=303)

        if document_type:
            type_error = await db.validate_document_type(document_type)
            if type_error:
                return RedirectResponse("/ui/upload", status_code=303)
        else:
            document_type = None

        content = await file.read()
        filename = file.filename or "unnamed"
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

        return RedirectResponse(f"/ui/documents/{doc['id']}", status_code=303)

    # ── DOCUMENT ACTIONS ──────────────────────────────────────

    @router.post("/documents/{document_id}/type")
    async def set_type(request: Request, document_id: UUID, document_type: str = Form(...)):
        """Update document classification from the detail page."""
        if document_type:
            type_error = await db.validate_document_type(document_type)
            if not type_error:
                await db.update_document_type(document_id, document_type)
        return RedirectResponse(f"/ui/documents/{document_id}", status_code=303)

    @router.post("/documents/{document_id}/tags")
    async def save_tags(request: Request, document_id: UUID):
        """Save tags from the detail page tag editor form."""
        form_data = await request.form()
        tags_dict = _extract_tags_from_form(form_data)

        tag_errors = await db.validate_tags(tags_dict)
        if not tag_errors:
            await db.update_document_tags(document_id, tags_dict)

        return RedirectResponse(f"/ui/documents/{document_id}", status_code=303)

    @router.post("/documents/{document_id}/extract")
    async def trigger_extraction(request: Request, document_id: UUID):
        """Trigger text extraction with task tracking.

        Creates a task record first (visible immediately), runs extraction,
        then updates the task with results or error. The document detail
        page shows the task history so the user can see what happened.
        """
        import time
        doc = await db.get_document(document_id)
        if not doc:
            return RedirectResponse(f"/ui/documents/{document_id}", status_code=303)

        # Create task record (shows up immediately in task history)
        task = await db.create_task(
            document_id=document_id,
            task_type="text_extraction",
            task_method="pymupdf_get_text",
            initiated_by="ui_manual",
        )
        await db.start_task(task["id"])
        start_ms = int(time.time() * 1000)

        try:
            bucket = await _get_bucket(doc["collection_id"])
            content = storage.download_bytes(bucket, doc["storage_key"])
            text = extract_text_from_bytes(content, doc["filename"])

            # Upload extracted text to MinIO
            text_key = f"{doc['storage_key']}.extracted.txt"
            text_size = storage.upload_text(bucket, text_key, text)

            # Create child document record
            child = await db.insert_document(
                collection_id=doc["collection_id"],
                folder_id=doc.get("folder_id"),
                context_ref=doc["context_ref"],
                context_type=doc.get("context_type"),
                filename=f"{doc['filename']}.extracted.txt",
                content_type="text/plain",
                file_size_bytes=text_size,
                storage_key=text_key,
                uploaded_by="edms:text_extraction",
                tags={"transformation": ["text_extraction"]},
            )

            # Create lineage record
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
                },
            )

            # Mark task complete
            duration_ms = int(time.time() * 1000) - start_ms
            await db.complete_task(
                task_id=task["id"],
                result_document_id=child["id"],
                result_summary=f"Extracted {char_count:,} chars from {doc['filename']}",
                duration_ms=duration_ms,
                task_metadata={"char_count": char_count, "includes_form_fields": includes_form_fields},
            )

        except Exception as e:
            duration_ms = int(time.time() * 1000) - start_ms
            await db.fail_task(task["id"], f"Extraction failed: {str(e)}")

        return RedirectResponse(f"/ui/documents/{document_id}", status_code=303)

    @router.post("/documents/{document_id}/re-extract")
    async def re_extract(request: Request, document_id: UUID):
        """Force re-extraction. Creates a new task + new child document."""
        return await trigger_extraction(request, document_id)

    @router.post("/documents/{document_id}/delete")
    async def delete_document(request: Request, document_id: UUID):
        """Delete a document from the detail page."""
        doc = await db.get_document(document_id)
        if doc:
            # Delete from MinIO
            try:
                del_bucket = await _get_bucket(doc["collection_id"])
                storage.client.remove_object(del_bucket, doc["storage_key"])
            except Exception:
                pass
            await db.delete_document(document_id)

        return RedirectResponse("/ui/", status_code=303)

    # ── TAG MANAGEMENT ────────────────────────────────────────

    @router.get("/tags", response_class=HTMLResponse)
    async def tags_page(request: Request):
        """Tag definitions management page."""
        tag_defs = await db.list_tag_definitions(active_only=False)
        for td in tag_defs:
            if td["value_mode"] == "restricted":
                td["allowed_values"] = await db.list_tag_allowed_values(td["tag_key"])
            else:
                td["allowed_values"] = []

        return _render(request, "tags.html",
            active_page="tags",
            tag_definitions=tag_defs,
        )

    @router.post("/tags")
    async def create_tag(
        tag_key: str = Form(...),
        display_name: str = Form(...),
        value_mode: str = Form("restricted"),
        is_required: str = Form("false"),
        description: str = Form(None),
    ):
        """Create a new tag definition from the tags page form."""
        await db.insert_tag_definition(
            tag_key=tag_key,
            display_name=display_name,
            value_mode=value_mode,
            description=description,
            is_required=(is_required == "true"),
        )
        return RedirectResponse("/ui/tags", status_code=303)

    @router.post("/tags/{tag_key}/delete")
    async def delete_tag(tag_key: str):
        """Delete a tag definition from the tags page."""
        await db.delete_tag_definition(tag_key)
        return RedirectResponse("/ui/tags", status_code=303)

    @router.post("/tags/{tag_key}/values")
    async def add_tag_value(
        tag_key: str,
        value: str = Form(...),
        display_name: str = Form(...),
    ):
        """Add an allowed value to a restricted tag key."""
        await db.insert_tag_allowed_value(tag_key, value, display_name)
        return RedirectResponse("/ui/tags", status_code=303)

    @router.post("/tags/{tag_key}/values/{value}/delete")
    async def delete_tag_value(tag_key: str, value: str):
        """Delete an allowed value from a tag key."""
        await db.delete_tag_allowed_value(tag_key, value)
        return RedirectResponse("/ui/tags", status_code=303)

    # ── DOCUMENT TYPE MANAGEMENT ──────────────────────────────

    @router.get("/document-types", response_class=HTMLResponse)
    async def document_types_page(request: Request):
        """Document type definitions management page with two-level hierarchy."""
        # Get hierarchy: top-level types with nested subtypes
        type_hierarchy = await db.get_type_hierarchy()
        # Also get all types (flat) for the parent dropdown in the add form
        all_types = await db.list_document_type_definitions(active_only=False)
        top_level_types = [t for t in all_types if not t.get("parent_type_id")]
        return _render(request, "document_types.html",
            active_page="document_types",
            type_hierarchy=type_hierarchy,
            top_level_types=top_level_types,
            document_types=all_types,
        )

    @router.post("/document-types")
    async def create_document_type(
        type_key: str = Form(...),
        display_name: str = Form(...),
        description: str = Form(None),
        parent_type_id: str = Form(None),
    ):
        """Create a new document type definition (top-level or subtype)."""
        # insert_document_type_definition needs to support parent_type_id
        result = await db._conn.execute(
            """
            INSERT INTO document_type_definition (type_key, display_name, description, parent_type_id)
            VALUES (%(key)s, %(display)s, %(desc)s, %(parent)s)
            RETURNING *
            """,
            {"key": type_key, "display": display_name, "desc": description,
             "parent": parent_type_id if parent_type_id else None},
        )
        await result.fetchone()
        return RedirectResponse("/ui/document-types", status_code=303)

    @router.post("/document-types/{type_key}/delete")
    async def delete_doc_type(type_key: str):
        """Delete a document type definition."""
        await db.delete_document_type_definition(type_key)
        return RedirectResponse("/ui/document-types", status_code=303)

    # ── FOLDER MANAGEMENT ─────────────────────────────────────

    # ── COLLECTION MANAGEMENT ─────────────────────────────────

    @router.get("/collections", response_class=HTMLResponse)
    async def collections_page(request: Request):
        """Collection management page."""
        collections = await db.list_collections()
        return _render(request, "collections.html",
            active_page="collections",
            collections=collections,
        )

    @router.post("/collections")
    async def create_collection(
        name: str = Form(...), display_name: str = Form(...),
        storage_container: str = Form(...), owner_name: str = Form(...),
        description: str = Form(None),
    ):
        await db.insert_collection(
            name=name, display_name=display_name, storage_container=storage_container,
            owner_name=owner_name, created_by="ui_admin", description=description,
        )
        return RedirectResponse("/ui/collections", status_code=303)

    @router.post("/collections/{collection_id}/delete")
    async def delete_collection_ui(collection_id: UUID):
        await db.delete_collection(collection_id)
        return RedirectResponse("/ui/collections", status_code=303)

    # ── FOLDER MANAGEMENT (collection-first) ──────────────────

    @router.get("/folders", response_class=HTMLResponse)
    async def folders_page(request: Request, collection_id: Optional[str] = None):
        """Folder management. Must select a collection first."""
        collections = await db.list_collections()
        selected_collection = None
        folder_tree = []
        flat_folders = []

        if collection_id:
            selected_collection = await db.get_collection(UUID(collection_id))
            if selected_collection:
                folder_tree = await db.get_folder_tree(UUID(collection_id))
                # Build flat list with indentation for the parent dropdown
                flat_folders = _flatten_tree(folder_tree)

        return _render(request, "folders.html",
            active_page="folders",
            collections=collections,
            selected_collection=selected_collection,
            folder_tree=folder_tree,
            flat_folders=flat_folders,
        )

    @router.post("/folders")
    async def create_folder(
        collection_id: str = Form(...), name: str = Form(...),
        parent_folder_id: str = Form(None), description: str = Form(None),
    ):
        pid = UUID(parent_folder_id) if parent_folder_id else None
        await db.insert_folder(
            collection_id=UUID(collection_id), name=name,
            parent_folder_id=pid, description=description or None,
        )
        return RedirectResponse(f"/ui/folders?collection_id={collection_id}", status_code=303)

    @router.post("/folders/{folder_id}/delete")
    async def delete_folder(request: Request, folder_id: UUID):
        folder = await db.get_folder(folder_id)
        cid = str(folder["collection_id"]) if folder else ""
        await db.delete_folder(folder_id)
        return RedirectResponse(f"/ui/folders?collection_id={cid}", status_code=303)

    # ── TASK MONITOR ──────────────────────────────────────────

    @router.get("/tasks", response_class=HTMLResponse)
    async def tasks_page(
        request: Request,
        status: Optional[str] = None,
        task_type: Optional[str] = None,
    ):
        """Task monitor page - all tasks across all documents."""
        tasks = await db.list_all_tasks(status=status, task_type=task_type)
        return _render(request, "tasks.html",
            active_page="tasks",
            tasks=tasks,
            filter_status=status,
            filter_type=task_type,
        )

    # ── FOLDER ASSIGNMENT (from document detail) ──────────────

    @router.post("/documents/{document_id}/folder")
    async def assign_folder(request: Request, document_id: UUID, folder_id: str = Form(None)):
        """Move a document to a folder (or remove from folder)."""
        fid = UUID(folder_id) if folder_id else None
        await db.move_document_to_folder(document_id, fid)
        return RedirectResponse(f"/ui/documents/{document_id}", status_code=303)

    # ── BULK DELETE (from document browser) ───────────────────

    @router.post("/bulk-delete")
    async def bulk_delete(request: Request):
        """Delete multiple documents selected from the browse page."""
        form_data = await request.form()
        doc_ids = form_data.getlist("doc_ids")
        for doc_id in doc_ids:
            doc = await db.get_document(UUID(doc_id))
            if doc:
                try:
                    del_bucket = await _get_bucket(doc["collection_id"])
                    storage.client.remove_object(del_bucket, doc["storage_key"])
                except Exception:
                    pass
                await db.delete_document(UUID(doc_id))
        return RedirectResponse("/ui/", status_code=303)

    return router


def _flatten_tree(tree: list, depth: int = 0) -> list[dict]:
    """Flatten a folder tree into a list with indent strings for dropdowns."""
    result = []
    for node in tree:
        result.append({"id": node["id"], "name": node["name"], "indent": "-- " * depth})
        if node.get("children"):
            result.extend(_flatten_tree(node["children"], depth + 1))
    return result


def _extract_tags_from_form(form_data) -> dict:
    """Extract tags from form fields named tag_{key}.

    For restricted tags: multiple checkbox values → list
    For freetext tags: comma-separated string → list
    """
    tags = {}
    for key in form_data:
        if key.startswith("tag_"):
            tag_key = key[4:]  # strip "tag_" prefix
            values = form_data.getlist(key)
            # Filter empty values
            values = [v.strip() for v in values if v.strip()]
            # For freetext: split comma-separated values
            expanded = []
            for v in values:
                if "," in v:
                    expanded.extend([part.strip() for part in v.split(",") if part.strip()])
                else:
                    expanded.append(v)
            if expanded:
                tags[tag_key] = expanded
    return tags
