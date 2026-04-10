"""EDMS tools — call EDMS REST API via httpx.

NO edms package dependency. The UW app calls EDMS over HTTP, just like
any other external service. In production these run on separate servers.

These functions are registered as Verity tool implementations so agents
can call them. They're also used directly by the pipeline runner to
pre-fetch documents before passing them to tasks.

Usage:
    # As Verity tool (called by agents via execution engine):
    verity.register_tool_implementation("list_documents", list_documents)

    # Direct call from pipeline runner:
    docs = await list_documents("submission:00000001-...")
    content = await get_document_content(doc_id)
"""

import httpx

from uw_demo.app.config import settings


# Timeout for EDMS calls — PDFs can be large, extraction can be slow
_TIMEOUT = 30.0


async def list_documents(
    context_ref: str,
    document_type: str = None,
    context_type: str = None,
) -> list[dict]:
    """List all documents in EDMS for a business context.

    Args:
        context_ref: Business context, e.g. 'submission:00000001-...'
        document_type: Optional filter (do_application, loss_run, etc.)
        context_type: Optional filter (submission, policy, claim)

    Returns:
        List of document metadata dicts.
    """
    params = {"context_ref": context_ref}
    if document_type:
        params["document_type"] = document_type
    if context_type:
        params["context_type"] = context_type

    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        resp = await http.get(f"{settings.EDMS_URL}/documents", params=params)
        resp.raise_for_status()
        return resp.json().get("documents", [])


async def get_document_text(document_id: str) -> str:
    """Get extracted text for a document.

    Args:
        document_id: UUID of the document.

    Returns:
        Extracted text as a string.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        resp = await http.get(f"{settings.EDMS_URL}/documents/{document_id}/text")
        resp.raise_for_status()
        return resp.json().get("text", "")


async def get_document_content(document_id: str) -> bytes:
    """Download original file bytes from EDMS.

    Used to send PDFs to Claude for classification — Claude's native
    document understanding sees the actual form layout, checkboxes,
    headers, and tables.

    Args:
        document_id: UUID of the document.

    Returns:
        Raw file bytes (PDF, text, etc.)
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        resp = await http.get(f"{settings.EDMS_URL}/documents/{document_id}/content")
        resp.raise_for_status()
        return resp.content


async def get_document_metadata(document_id: str) -> dict:
    """Get document metadata (filename, type, size, etc.)

    Args:
        document_id: UUID of the document.

    Returns:
        Document metadata dict.
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as http:
        resp = await http.get(f"{settings.EDMS_URL}/documents/{document_id}")
        resp.raise_for_status()
        return resp.json()
