"""EDMS data models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class DocumentRecord(BaseModel):
    """One document in the EDMS registry."""
    id: UUID
    context_ref: str
    context_type: Optional[str] = None
    filename: str
    content_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    storage_provider: str = "minio"
    storage_container: str
    storage_key: str
    document_type: Optional[str] = None
    tags: dict[str, Any] = {}
    uploaded_by: str
    uploaded_at: Optional[datetime] = None
    notes: Optional[str] = None


class DocumentLineage(BaseModel):
    """A parent-child transformation relationship between two documents."""
    id: UUID
    parent_document_id: UUID
    child_document_id: UUID
    transformation_type: str
    transformation_method: Optional[str] = None
    transformation_status: str = "complete"
    transformation_error: Optional[str] = None
    transformation_metadata: dict[str, Any] = {}
    created_at: Optional[datetime] = None
