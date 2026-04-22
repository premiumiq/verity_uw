"""MCP (Model Context Protocol) server registry models.

These are governance-internal DB read/write shapes for the `mcp_server`
table. They describe how Verity knows about an MCP server — where it
lives, how to connect, what auth it needs. They do NOT describe how to
dispatch a single tool call through it — that's the runtime's MCP
client concern in Phase 4b.

Added in Phase 4a / FC-14 (MCP tool integration).

Stay in verity.models (not verity.contracts) because only the governance
plane reads/writes the mcp_server table directly. The runtime learns
about MCP servers indirectly through ToolAuthorization.mcp_server_name
and hydrates connection details via governance.registry.get_mcp_server_by_name
at dispatch time.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class MCPServer(BaseModel):
    """Registered MCP server — read shape from the `mcp_server` DB row.

    Transport values:
      - 'stdio' — Verity spawns the server as a subprocess via
                  `command` + `args`, speaks MCP over the pipes.
      - 'sse'   — Verity connects to `url` as a Server-Sent Events endpoint.
      - 'http'  — Verity POSTs JSON-RPC MCP messages to `url`.

    Which fields matter depends on transport:
      - stdio: command + args are required, url is unused
      - sse/http: url is required, command + args are unused
      - env and auth_config apply to all transports
    """
    id: UUID
    name: str
    display_name: str
    description: Optional[str] = None
    transport: str

    # stdio-only
    command: Optional[str] = None
    args: list[str] = []

    # sse/http-only
    url: Optional[str] = None

    # Environment variables (stdio) or request headers (sse/http)
    env: dict[str, Any] = {}
    # API keys, bearer tokens, OAuth config — free-form JSONB
    auth_config: dict[str, Any] = {}

    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class MCPServerCreate(BaseModel):
    """Input for register_mcp_server() — no id/timestamps, active defaults True."""
    name: str
    display_name: str
    description: Optional[str] = None
    transport: str

    command: Optional[str] = None
    args: list[str] = []

    url: Optional[str] = None

    env: dict[str, Any] = {}
    auth_config: dict[str, Any] = {}

    active: bool = True
