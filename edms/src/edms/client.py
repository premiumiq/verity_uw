"""EDMS HTTP Client — for consuming applications.

This is NOT the service. This is a lightweight HTTP client that calls
the EDMS service's REST APIs. Consuming apps (UW demo, Claims app, etc.)
import this to interact with the EDMS service.

The EDMS service runs in its own container at http://edms:8002.
This client makes HTTP requests to it. No direct database or MinIO access.

Usage:
    from edms import EdmsClient

    client = EdmsClient(base_url="http://edms:8002")

    # List documents for a business context
    docs = await client.list_documents("submission:SUB-001")

    # Get extracted text for a document
    text = await client.get_document_text(document_id)

    # Upload a document (standard multipart upload)
    doc = await client.upload("/path/to/form.pdf", collection_id, "submission:SUB-001")

    # Trigger text extraction
    result = await client.extract_text(document_id)
"""

from typing import Any, Optional
from uuid import UUID

import httpx


class EdmsClient:
    """HTTP client for the EDMS service.

    All methods make HTTP requests to the EDMS REST API.
    No direct database or storage access.
    """

    def __init__(self, base_url: str = "http://edms:8002"):
        """Initialize the client.

        Args:
            base_url: URL of the EDMS service (e.g., "http://edms:8002"
                      inside Docker, or "http://localhost:8002" from host)
        """
        self.base_url = base_url.rstrip("/")

    async def list_documents(self, context_ref: str) -> list[dict]:
        """List all documents for a business context.

        Args:
            context_ref: Business context (e.g., "submission:SUB-001")

        Returns:
            List of document metadata dicts.
        """
        async with httpx.AsyncClient() as http:
            resp = await http.get(
                f"{self.base_url}/documents",
                params={"context_ref": context_ref},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("documents", [])

    async def get_document_text(self, document_id: str | UUID) -> str:
        """Get extracted text for a document.

        This is the method that Verity tool implementations wrap.
        An agent calls "get_document_text" tool → Verity calls this method
        → this method calls the EDMS service → returns text to the agent.

        Args:
            document_id: UUID of the document (as string or UUID)

        Returns:
            Extracted text as a string.
        """
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{self.base_url}/documents/{document_id}/text")
            resp.raise_for_status()
            data = resp.json()
            return data.get("text", "")

    async def get_metadata(self, document_id: str | UUID) -> dict:
        """Get document metadata by ID."""
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{self.base_url}/documents/{document_id}")
            resp.raise_for_status()
            return resp.json()

    async def get_children(self, document_id: str | UUID) -> list[dict]:
        """Get all documents derived from a parent."""
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{self.base_url}/documents/{document_id}/children")
            resp.raise_for_status()
            data = resp.json()
            return data.get("children", [])

    async def upload(
        self,
        file_path: str,
        collection_id: str,
        context_ref: str,
        context_type: Optional[str] = None,
        uploaded_by: str = "system",
        document_type: Optional[str] = None,
    ) -> dict:
        """Upload a document via standard multipart POST.

        Reads file bytes from local disk and sends as multipart form
        data to the EDMS service. This is how any client uploads — no
        shared filesystem required.

        Args:
            file_path: Local path to the file to upload.
            collection_id: UUID of the EDMS collection.
            context_ref: Business context (e.g., "submission:uuid").
            context_type: Optional context type (submission, policy, etc.).
            uploaded_by: Who is uploading (default: "system").
            document_type: Optional pre-classification.

        Returns:
            Document metadata dict from EDMS.
        """
        from pathlib import Path as _Path

        path = _Path(file_path)
        # Guess content type from extension
        suffix = path.suffix.lower()
        content_type = {
            ".pdf": "application/pdf",
            ".txt": "text/plain",
            ".json": "application/json",
            ".csv": "text/csv",
        }.get(suffix, "application/octet-stream")

        form_data = {
            "collection_id": collection_id,
            "context_ref": context_ref,
            "uploaded_by": uploaded_by,
        }
        if context_type:
            form_data["context_type"] = context_type
        if document_type:
            form_data["document_type"] = document_type

        with open(file_path, "rb") as f:
            files = {"file": (path.name, f, content_type)}
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.post(
                    f"{self.base_url}/documents/upload",
                    data=form_data,
                    files=files,
                )
                resp.raise_for_status()
                return resp.json()

    async def extract_text(self, document_id: str | UUID) -> dict:
        """Trigger text extraction for a document.

        Creates a child document with the extracted text.
        Idempotent — returns existing extraction if already done.

        Returns:
            Dict with text, char_count, text_document_id, already_extracted.
        """
        async with httpx.AsyncClient() as http:
            resp = await http.post(f"{self.base_url}/documents/{document_id}/extract")
            resp.raise_for_status()
            return resp.json()

    async def set_document_type(self, document_id: str | UUID, document_type: str) -> dict:
        """Update a document's classified type."""
        async with httpx.AsyncClient() as http:
            resp = await http.put(
                f"{self.base_url}/documents/{document_id}/type",
                data={"document_type": document_type},
            )
            resp.raise_for_status()
            return resp.json()

    async def list_collections(self) -> list[dict]:
        """List all collections in EDMS.

        Used by seed scripts to find the 'general' collection UUID.
        """
        async with httpx.AsyncClient() as http:
            resp = await http.get(f"{self.base_url}/collections")
            resp.raise_for_status()
            data = resp.json()
            return data.get("collections", [])
