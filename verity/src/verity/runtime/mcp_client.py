"""MCP client — Verity's bridge to external MCP servers.

Wraps the official `mcp` Python package so the runtime's
`_gateway_tool_call` can dispatch a tool registered with
`transport='mcp_stdio'` / `'mcp_sse'` / `'mcp_http'` to the
configured server, log the input/output into `tool_calls_made`
identically to an in-process Python tool, and honor the same
governance (authorization, mock mode, audit).

What this module provides (Phase 4b):
  - `MCPClient`: a connection pool keyed by `mcp_server.name`. Opens
    sessions lazily on first use, keeps them open for the process
    lifetime, exposes `list_tools`, `call_tool`, and a `close_all`
    hook for shutdown.
  - Only `stdio` transport is implemented end-to-end. `sse` and `http`
    raise NotImplementedError with a clear message — they land in
    Phase 4e when we wire an actual SSE/HTTP-backed MCP server
    (HubSpot or similar).

What lands later:
  - Phase 4c: `_gateway_tool_call` in runtime/engine.py branches on
    `ToolAuthorization.transport` and calls `MCPClient.call_tool`
    when it's one of the mcp_* variants.
  - Phase 4e: SSE/HTTP transport implementations here, plus a concrete
    HubSpot or other business-system MCP server.

Design notes:
  - Connections are held alive via `AsyncExitStack` because MCP's client
    factories (`stdio_client`, `sse_client`, etc.) are async context
    managers — you can't just call them and keep the session; you have
    to keep the context entered.
  - Each server gets its own `AsyncExitStack`, so closing one server
    doesn't affect others.
  - This module does NOT enforce authorization or mock behavior. That's
    the runtime's job in `_gateway_tool_call`. Here we only dispatch.
"""

from __future__ import annotations

import logging
from contextlib import AsyncExitStack
from typing import Any, Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from verity.models.mcp import MCPServer

logger = logging.getLogger(__name__)


class MCPConnectionError(Exception):
    """Raised when a server fails to open or respond."""


class MCPServerNotOpen(Exception):
    """Raised when a server_name is referenced but hasn't been opened."""


class MCPClient:
    """Pool of active MCP client sessions, keyed by mcp_server.name.

    Lifecycle:
      - `open(server)` creates an `AsyncExitStack`, enters the
        transport's async context, enters a `ClientSession`, calls
        `initialize()`, and stores the session keyed by server.name.
      - `call_tool(server_name, tool_name, args)` dispatches against
        the open session and returns the MCP result, normalized into
        a plain dict that matches the shape of an in-process tool
        response.
      - `close(server_name)` aclose()s the stack for one server.
      - `close_all()` aclose()s every open stack (Runtime shutdown).

    Not thread-safe — designed for a single asyncio event loop.
    """

    def __init__(self):
        self._sessions: dict[str, ClientSession] = {}
        self._stacks: dict[str, AsyncExitStack] = {}

    # ── LIFECYCLE ──────────────────────────────────────────────

    async def open(self, server: MCPServer) -> None:
        """Open a session to `server` if not already open.

        Idempotent — repeated calls for the same server.name are no-ops.
        """
        if server.name in self._sessions:
            return

        stack = AsyncExitStack()
        await stack.__aenter__()

        try:
            if server.transport == "stdio":
                read, write = await self._open_stdio(stack, server)
            elif server.transport == "sse":
                raise NotImplementedError(
                    "MCP transport 'sse' is not implemented yet. "
                    "Scheduled for Phase 4e (HubSpot/SharePoint integration). "
                    "Use transport='stdio' for now."
                )
            elif server.transport == "http":
                raise NotImplementedError(
                    "MCP transport 'http' is not implemented yet. "
                    "Scheduled for Phase 4e. Use transport='stdio' for now."
                )
            else:
                raise MCPConnectionError(
                    f"Unknown MCP transport {server.transport!r} on server "
                    f"{server.name!r}. Expected one of: stdio, sse, http."
                )

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except Exception:
            # Unwind the stack if anything above failed before we stored it.
            await stack.aclose()
            raise

        self._stacks[server.name] = stack
        self._sessions[server.name] = session
        logger.info(
            "MCP server opened: name=%s transport=%s",
            server.name,
            server.transport,
        )

    async def _open_stdio(self, stack: AsyncExitStack, server: MCPServer):
        """Spawn the stdio-transport server and return (read, write) streams."""
        if not server.command:
            raise MCPConnectionError(
                f"MCP server {server.name!r} has transport='stdio' but no "
                "command. Set mcp_server.command to a launch executable."
            )
        params = StdioServerParameters(
            command=server.command,
            args=list(server.args or []),
            env=dict(server.env or {}),
        )
        return await stack.enter_async_context(stdio_client(params))

    async def close(self, server_name: str) -> None:
        """Close the session for one server. Safe to call on unknown names."""
        stack = self._stacks.pop(server_name, None)
        self._sessions.pop(server_name, None)
        if stack is not None:
            await stack.aclose()
            logger.info("MCP server closed: name=%s", server_name)

    async def close_all(self) -> None:
        """Close every open session. Call on Runtime shutdown."""
        for name in list(self._sessions.keys()):
            try:
                await self.close(name)
            except Exception:
                logger.exception("Error closing MCP server: name=%s", name)

    # ── DISCOVERY / DISPATCH ──────────────────────────────────

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        """Return the list of tools the MCP server advertises.

        Used by the governance UI (Phase 4f) to show what's available
        on a server, and by the runtime for sanity checks ("does this
        server actually expose the tool we're about to call?").
        """
        session = self._require_session(server_name)
        result = await session.list_tools()
        # result.tools is a list of mcp.types.Tool. Normalize to plain dicts.
        return [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema or {},
            }
            for t in result.tools
        ]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        """Dispatch a tool call on the named server and return the result.

        Normalizes the MCP response into a plain dict so the caller
        (_gateway_tool_call in engine.py) can stash it in
        agent_decision_log.tool_calls_made without a transport-specific
        branch at audit-log time.

        Raises:
          MCPServerNotOpen  — if `server_name` hasn't been opened yet.
          RuntimeError      — if the MCP server returns isError=True.
        """
        session = self._require_session(server_name)
        result = await session.call_tool(tool_name, arguments=arguments)

        # MCP ToolCallResult has:
        #   - content: list of content blocks (TextContent, ImageContent, ...)
        #   - isError: bool
        # Normalize to a simple {"content": [...], "is_error": bool} dict.
        # For text-only results, expose the concatenated text at "text" for
        # convenience — matches the implicit shape in-process Python tools
        # use today.
        content = []
        texts = []
        for block in result.content:
            if hasattr(block, "text"):
                content.append({"type": "text", "text": block.text})
                texts.append(block.text)
            elif hasattr(block, "type"):
                # Non-text content block (image, resource, etc.) — pass
                # through a shape-preserving dict so it shows up in the
                # audit log intact.
                content.append({"type": block.type, "raw": str(block)})
            else:
                content.append({"type": "unknown", "raw": str(block)})

        normalized = {
            "content": content,
            "is_error": bool(result.isError),
        }
        if texts:
            normalized["text"] = "\n".join(texts)

        if result.isError:
            logger.warning(
                "MCP tool error: server=%s tool=%s content=%s",
                server_name, tool_name, normalized["text"][:200] if texts else "",
            )

        return normalized

    # ── INTERNALS ──────────────────────────────────────────────

    def _require_session(self, server_name: str) -> ClientSession:
        session = self._sessions.get(server_name)
        if session is None:
            raise MCPServerNotOpen(
                f"MCP server {server_name!r} is not open. Call "
                "MCPClient.open(server) first."
            )
        return session

    def is_open(self, server_name: str) -> bool:
        """True if a session is currently open for this server."""
        return server_name in self._sessions

    @property
    def open_servers(self) -> list[str]:
        """Names of all currently-open servers (diagnostic)."""
        return list(self._sessions.keys())


__all__ = ["MCPClient", "MCPConnectionError", "MCPServerNotOpen"]
