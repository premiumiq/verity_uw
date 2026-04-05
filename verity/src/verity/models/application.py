"""Application and Execution Context models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import EntityType


class Application(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None


class ApplicationEntity(BaseModel):
    id: UUID
    application_id: UUID
    entity_type: EntityType
    entity_id: UUID
    created_at: Optional[datetime] = None


class ExecutionContext(BaseModel):
    id: UUID
    application_id: UUID
    context_ref: str
    context_type: Optional[str] = None
    metadata: dict[str, Any] = {}
    created_at: Optional[datetime] = None
