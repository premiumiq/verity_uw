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
    to validate the call (input_schema), route the dispatch (transport
    + optional mcp_server_name + mcp_tool_name), and decide mock
    behaviour (mock_mode_enabled, mock_response_key).

    Dispatch routing (used by the runtime's `_gateway_tool_call`):
      - transport='python_inprocess' (default) — look up `name` in the
        runtime's `tool_implementations` dict and call the Python callable.
      - transport='mcp_stdio'|'mcp_sse'|'mcp_http' — forward the call
        through the MCP client to the server identified by `mcp_server_name`,
        addressing the remote tool as `mcp_tool_name` (or `name` if the
        remote tool name matches Verity's name).
    """
    authorization_id: Optional[UUID] = None
    tool_id: UUID
    name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]

    # Dispatch transport. See class docstring for routing semantics.
    transport: str = "python_inprocess"
    mcp_server_name: Optional[str] = None
    mcp_tool_name: Optional[str] = None

    implementation_path: str
    mock_mode_enabled: bool = True
    mock_response_key: Optional[str] = None
    data_classification_max: str = "tier3_confidential"
    is_write_operation: bool = False
    requires_confirmation: bool = False
    authorized: bool = True
    notes: Optional[str] = None
