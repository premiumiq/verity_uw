"""Tool models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class Tool(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    implementation_path: str
    mock_mode_enabled: bool = True
    mock_response_key: Optional[str] = None
    data_classification_max: str = "tier3_confidential"
    is_write_operation: bool = False
    requires_confirmation: bool = False
    tags: list[str] = []
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ToolAuthorization(BaseModel):
    """A tool authorized for use by an agent_version or task_version."""
    authorization_id: Optional[UUID] = None
    tool_id: UUID
    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    implementation_path: str
    mock_mode_enabled: bool = True
    mock_response_key: Optional[str] = None
    data_classification_max: str = "tier3_confidential"
    is_write_operation: bool = False
    requires_confirmation: bool = False
    authorized: bool = True
    notes: Optional[str] = None
