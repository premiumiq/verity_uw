"""Tool authorization — a tool allowed for use by an agent/task version.

Only ToolAuthorization lives in contracts: it's what the runtime needs
to decide whether (and how) a tool call can be dispatched. The
governance-internal Tool DB model stays in verity.models.tool.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class ToolAuthorization(BaseModel):
    """A tool authorized for use by an agent_version or task_version.

    This is the runtime's view of an authorized tool: enough metadata
    to validate the call (input_schema), dispatch the implementation
    (name, implementation_path), and decide mock behaviour
    (mock_mode_enabled, mock_response_key).
    """
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
