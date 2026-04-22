"""Tool models.

ToolAuthorization was moved to verity.contracts.tool as of Phase 1 of the
Registry/Runtime split. It is re-exported here for backward compatibility.

What stays here (governance-internal DB read shape):
- Tool — the full tool registry row (metadata + schemas + mock settings)
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

# Re-export boundary model from contracts for backward compatibility.
from verity.contracts.tool import ToolAuthorization  # noqa: F401


class Tool(BaseModel):
    """Tool registry row — the canonical definition of a callable tool."""
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
