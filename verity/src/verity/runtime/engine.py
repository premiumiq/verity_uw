"""Verity Execution Engine — run agents and tasks with full governance.

ARCHITECTURE:
This engine calls Claude's Messages API directly (anthropic.AsyncAnthropic)
and runs the agentic loop in-process. Two gateways mediate external calls:

  - _gateway_llm_call: one Claude API call per turn. Transient errors
    (429/500/502/503/529) retry with exponential backoff.
  - _gateway_tool_call: one tool dispatch per Claude-requested tool use.
    Checks MockContext.tool_responses first, then the tool's DB-registered
    mock_mode_enabled flag, then dispatches the registered Python callable.

EXECUTION MODES:
  1. Fully live (mock=None)                       — LLM + tools both real
  2. Live LLM + caller-supplied tool mocks        — MockContext(tool_responses={...})
  3. Live LLM + all tools from DB mock registry  — MockContext(mock_all_tools=True)
  4. Step-level short-circuit (zero LLM, zero IO) — MockContext(step_responses={...})
     The matching value IS the structured output; sources/targets are
     skipped; a decision_log row is still written with mock_mode=True.

All modes write a DecisionLogCreate row with the same 31-column shape.
mock_mode=True is set whenever any caller-supplied mocking was active.
"""

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Callable, Literal, Optional
from uuid import UUID, uuid4

import anthropic

logger = logging.getLogger(__name__)


# ── CONSTANTS ────────────────────────────────────────────────────
# Maximum nesting depth of sub-agent delegation. Parent calls are at
# depth 0, direct sub-agents at 1, their sub-agents at 2, etc. Once
# decision_depth reaches this value, run_agent refuses to proceed and
# _dispatch_builtin_tool refuses to spawn a further delegation. Keeps
# recursive A->B->A->... loops from running away even if two agents
# have mutual delegation authorizations.
MAX_DECISION_DEPTH = 5

# Result types (ExecutionResult, ExecutionEvent, ExecutionEventType) live in
# verity.contracts.decision. Re-exported here so code that did
# `from verity.runtime.engine import ExecutionResult` keeps working.
from verity.contracts.decision import (  # noqa: F401
    ExecutionEvent,
    ExecutionEventType,
    ExecutionResult,
)
# MockContext lives in verity.contracts.mock — runtime-side boundary control.
from verity.contracts.mock import MockContext
# Governance-side dependency: the runtime reads configs from the registry.
# This is the version-pinning seam — the engine cannot execute without
# resolving a config through the governance plane.
from verity.governance.registry import Registry
# Decisions writer: the single write the runtime makes to the audit table.
# After Phase 2e, we no longer take the unified Decisions class here;
# DecisionsWriter is all the engine needs (it only calls .log_decision()).
from verity.runtime.decisions_writer import DecisionsWriter
# MCP client for tools registered with transport='mcp_*'. Optional — the
# engine only needs it when such tools are actually authorized for a run.
from verity.runtime.mcp_client import MCPClient
from verity.models.decision import DecisionLogCreate
from verity.models.lifecycle import DeploymentChannel, EntityType, RunPurpose
from verity.models.mcp import MCPServer
from verity.models.prompt import PromptAssignment


# ── EXECUTION ENGINE ──────────────────────────────────────────

class ExecutionEngine:
    """Execute agents, tasks, and tools with governance and mock support."""

    def __init__(
        self,
        registry: Registry,
        decisions: DecisionsWriter,
        anthropic_api_key: str,
        tool_implementations: Optional[dict[str, Callable]] = None,
        application: str = "default",
        mcp_client: Optional[MCPClient] = None,
        models=None,
    ):
        self.registry = registry
        self.decisions = decisions
        # Use AsyncAnthropic so Claude API calls don't block the event loop.
        # Without this, a 45-second pipeline run blocks ALL other HTTP requests.
        self.client = anthropic.AsyncAnthropic(api_key=anthropic_api_key) if anthropic_api_key else None
        self.tool_implementations = tool_implementations or {}
        self.application = application
        # Optional MCP client for tools with transport='mcp_*'. If None and
        # an MCP tool is dispatched, we return an error result rather than
        # crash — the error is fed back to Claude and logged to the audit trail.
        self.mcp_client = mcp_client
        # Governance "models" facade — writes a model_invocation_log row
        # after each agent/task decision so usage + spend are trackable
        # by agent / task / application / time. None disables logging
        # silently (e.g. in unit tests that don't need it).
        self.models = models

    def register_tool_implementation(self, tool_name: str, func: Callable):
        """Register a Python function as a tool implementation."""
        self.tool_implementations[tool_name] = func

    # ══════════════════════════════════════════════════════════
    # GATEWAY FUNCTIONS — all external calls pass through these
    # ══════════════════════════════════════════════════════════

    async def _gateway_llm_call(
        self, api_params: dict, mock: Optional[MockContext]
    ) -> Any:
        """Gateway for the single Claude API call this engine makes per turn.

        There is no LLM-level mocking path here. Callers that want
        deterministic no-LLM execution pass `MockContext(step_responses={...})`
        — the engine short-circuits before reaching this gateway and uses
        the supplied dict as the structured output verbatim.

        The `mock` parameter is still accepted and forwarded to
        `_gateway_tool_call` for tool-level mocking. It has no effect on
        the LLM call itself.

        Uses AsyncAnthropic so the event loop stays free while waiting
        for Claude's response (~5-15 seconds per call). Retries on
        transient errors (429/500/502/503/529) with exponential backoff.
        """
        if not self.client:
            raise RuntimeError(
                "No Anthropic API key configured. Set ANTHROPIC_API_KEY to run "
                "via this engine, or pass MockContext(step_responses={...}) for "
                "deterministic no-LLM execution."
            )

        max_retries = 3
        base_delay = 2.0  # seconds

        for attempt in range(max_retries + 1):
            try:
                return await self.client.messages.create(**api_params)
            except anthropic.APIStatusError as e:
                # Retry on transient errors (429, 529, 500, 502, 503)
                retryable = e.status_code in (429, 500, 502, 503, 529)
                if retryable and attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Claude API error {e.status_code} (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {e.message}"
                    )
                    await asyncio.sleep(delay)
                    continue
                # Non-retryable or exhausted retries
                logger.error(
                    f"Claude API error {e.status_code} after {attempt + 1} attempts: {e.message}"
                )
                raise
            except anthropic.APIConnectionError as e:
                # Network error — always retry
                if attempt < max_retries:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Claude API connection error (attempt {attempt + 1}/{max_retries + 1}), "
                        f"retrying in {delay:.1f}s: {e}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.error(f"Claude API connection error after {attempt + 1} attempts: {e}")
                raise

    async def _gateway_tool_call(
        self,
        tool_name: str,
        tool_input: dict,
        authorized_tools: list,
        mock: Optional[MockContext],
        call_order: int,
        parent_agent_version_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        workflow_run_id: Optional[UUID] = None,
        execution_context_id: Optional[UUID] = None,
        channel: str = "production",
    ) -> dict[str, Any]:
        """Gateway for all tool calls.

        The extra kwargs (parent_agent_version_id, parent_decision_id,
        decision_depth, workflow_run_id, execution_context_id, channel)
        exist for FC-1's delegate_to_agent meta-tool — they flow down
        into _dispatch_builtin_tool so a spawned sub-agent inherits the
        parent's correlation ids and the correct depth. All other tool
        transports ignore them.

        When MockContext IS provided (explicit mock control):
          1. Check MockContext.tool_responses for this specific tool
          2. Check MockContext.mock_all_tools flag
          3. If neither matches → REAL call (DB flag ignored — caller is in control)

        When MockContext is NOT provided (no explicit mock control):
          1. Check per-tool DB flag (tool.mock_mode_enabled)
          2. If not flagged → REAL call

        This ensures that when you pass a MockContext, you have full
        control over which tools are mocked. The DB flag only applies
        as a default when no MockContext is present.
        """
        # Look up the authorized tool definition once — we need it for
        # transport routing, DB-mock-flag fallback, and better error messages.
        tool_def = next((t for t in authorized_tools if t.name == tool_name), None)

        if mock:
            # Explicit mock control — caller decides what's mocked

            # 1. Check runtime tool_responses for this specific tool
            runtime_response = mock.get_tool_response(tool_name)
            if runtime_response is not None:
                return {
                    "tool_name": tool_name,
                    "call_order": call_order,
                    "input_data": tool_input,
                    "output_data": runtime_response,
                    "mock_mode": True,
                    "mock_source": "runtime",
                }

            # 2. Check mock_all_tools flag
            if mock.mock_all_tools:
                db_response = _get_db_mock_response(tool_name, authorized_tools)
                return {
                    "tool_name": tool_name,
                    "call_order": call_order,
                    "input_data": tool_input,
                    "output_data": db_response,
                    "mock_mode": True,
                    "mock_source": "db_all",
                }

            # 3. Not in tool_responses, not mock_all → REAL CALL
            #    (DB flag intentionally skipped — caller is in control)

        else:
            # No MockContext — use DB flag as default behavior
            if tool_def and tool_def.mock_mode_enabled:
                db_response = _get_db_mock_response(tool_name, authorized_tools)
                return {
                    "tool_name": tool_name,
                    "call_order": call_order,
                    "input_data": tool_input,
                    "output_data": db_response,
                    "mock_mode": True,
                    "mock_source": "db_flag",
                }

        # Real tool implementation — dispatch based on tool_def.transport
        return await self._execute_real_tool(
            tool_name, tool_input, call_order, tool_def,
            parent_agent_version_id=parent_agent_version_id,
            parent_decision_id=parent_decision_id,
            decision_depth=decision_depth,
            workflow_run_id=workflow_run_id,
            execution_context_id=execution_context_id,
            channel=channel,
        )

    async def _execute_real_tool(
        self, tool_name: str, tool_input: dict, call_order: int, tool_def,
        parent_agent_version_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        workflow_run_id: Optional[UUID] = None,
        execution_context_id: Optional[UUID] = None,
        channel: str = "production",
    ) -> dict[str, Any]:
        """Dispatch a real (non-mocked) tool call.

        Routes based on tool_def.transport:
          - 'python_inprocess' (default) — look up `tool_name` in the
            runtime's tool_implementations dict and call the Python callable.
          - 'mcp_stdio' | 'mcp_sse' | 'mcp_http' — forward through MCPClient
            to the server identified by tool_def.mcp_server_name, addressing
            the remote tool as tool_def.mcp_tool_name (falling back to
            tool_name if the remote name matches Verity's name).
          - 'verity_builtin' — engine-internal meta-tools (FC-1: delegate_to_agent).
            Dispatched via _dispatch_builtin_tool; receives the parent
            context kwargs so delegation works correctly.

        All error paths return a dict with `error=True` and an error message
        in output_data — they never raise, because the caller (the agentic
        loop) feeds the result back to Claude as a tool_result with
        is_error=True and lets Claude decide how to proceed.
        """
        transport = getattr(tool_def, "transport", "python_inprocess")

        if transport == "python_inprocess":
            return await self._dispatch_python_tool(tool_name, tool_input, call_order)

        if transport in ("mcp_stdio", "mcp_sse", "mcp_http"):
            return await self._dispatch_mcp_tool(
                tool_name, tool_input, call_order, tool_def,
            )

        if transport == "verity_builtin":
            return await self._dispatch_builtin_tool(
                tool_name, tool_input, call_order, tool_def,
                parent_agent_version_id=parent_agent_version_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth,
                workflow_run_id=workflow_run_id,
                execution_context_id=execution_context_id,
                channel=channel,
            )

        return {
            "tool_name": tool_name,
            "call_order": call_order,
            "input_data": tool_input,
            "output_data": {
                "error": f"Unknown tool transport {transport!r} on '{tool_name}'. "
                         f"Expected python_inprocess, mcp_stdio, mcp_sse, mcp_http, "
                         f"or verity_builtin."
            },
            "error": True,
            "transport": transport,
        }

    async def _dispatch_python_tool(
        self, tool_name: str, tool_input: dict, call_order: int,
    ) -> dict[str, Any]:
        """Current path: in-process Python callable via tool_implementations dict."""
        impl = self.tool_implementations.get(tool_name)
        if not impl:
            return {
                "tool_name": tool_name,
                "call_order": call_order,
                "input_data": tool_input,
                "output_data": {"error": f"No implementation registered for tool '{tool_name}'"},
                "error": True,
                "transport": "python_inprocess",
            }
        try:
            logger.info("Tool call starting: %s (call_order=%d, transport=python)", tool_name, call_order)
            tool_start = _now_ms()
            if asyncio.iscoroutinefunction(impl):
                result = await impl(**tool_input)
            else:
                result = impl(**tool_input)
            logger.info("Tool call complete: %s (%dms)", tool_name, _now_ms() - tool_start)
            return {
                "tool_name": tool_name,
                "call_order": call_order,
                "input_data": tool_input,
                "output_data": result,
                "transport": "python_inprocess",
            }
        except Exception as e:
            logger.error("Tool execution failed: %s", tool_name, exc_info=True)
            return {
                "tool_name": tool_name,
                "call_order": call_order,
                "input_data": tool_input,
                "output_data": {"error": f"Tool execution failed: {str(e)}"},
                "error": True,
                "transport": "python_inprocess",
            }

    async def _dispatch_mcp_tool(
        self, tool_name: str, tool_input: dict, call_order: int, tool_def,
    ) -> dict[str, Any]:
        """New path (Phase 4c): dispatch via MCPClient to a registered MCP server.

        On first use of a server, lazy-opens the connection (stdio subprocess
        or sse/http endpoint per the mcp_server config). Subsequent calls
        reuse the open session. Errors at any stage (no MCPClient configured,
        server not registered, server fails to open, MCP call raises, MCP
        returns isError=True) come back as error result dicts the agentic
        loop can feed to Claude.
        """
        transport = tool_def.transport
        server_name = getattr(tool_def, "mcp_server_name", None)

        if self.mcp_client is None:
            return _mcp_error(
                tool_name, tool_input, call_order, transport, server_name,
                "No MCPClient configured on this ExecutionEngine. Wire one "
                "through the Runtime facade before dispatching MCP tools.",
            )
        if not server_name:
            return _mcp_error(
                tool_name, tool_input, call_order, transport, server_name,
                f"Tool '{tool_name}' has transport={transport!r} but no "
                "mcp_server_name on the ToolAuthorization. Check the tool's "
                "registration in the mcp_server + tool tables.",
            )

        # Lazy-open the server on first use.
        try:
            if not self.mcp_client.is_open(server_name):
                server_row = await self.registry.get_mcp_server_by_name(server_name)
                if not server_row:
                    return _mcp_error(
                        tool_name, tool_input, call_order, transport, server_name,
                        f"MCP server {server_name!r} is not registered in "
                        "mcp_server. Register it before binding a tool to it.",
                    )
                await self.mcp_client.open(MCPServer(**server_row))
        except Exception as e:
            logger.error("MCP server open failed: %s", server_name, exc_info=True)
            return _mcp_error(
                tool_name, tool_input, call_order, transport, server_name,
                f"Failed to open MCP server {server_name!r}: {e}",
            )

        remote_name = tool_def.mcp_tool_name or tool_name
        try:
            logger.info(
                "Tool call starting: %s (call_order=%d, transport=%s, server=%s, remote=%s)",
                tool_name, call_order, transport, server_name, remote_name,
            )
            tool_start = _now_ms()
            mcp_result = await self.mcp_client.call_tool(
                server_name, remote_name, tool_input,
            )
            logger.info(
                "Tool call complete: %s (%dms, is_error=%s)",
                tool_name, _now_ms() - tool_start, mcp_result.get("is_error", False),
            )
            return {
                "tool_name": tool_name,
                "call_order": call_order,
                "input_data": tool_input,
                "output_data": mcp_result,
                "transport": transport,
                "mcp_server_name": server_name,
                "mcp_tool_name": remote_name,
                "error": bool(mcp_result.get("is_error", False)),
            }
        except Exception as e:
            logger.error("MCP tool dispatch failed: %s on %s", tool_name, server_name, exc_info=True)
            return _mcp_error(
                tool_name, tool_input, call_order, transport, server_name,
                f"MCP tool execution failed: {e}",
            )

    # ══════════════════════════════════════════════════════════
    # BUILTIN META-TOOLS (FC-1: sub-agent delegation)
    # ══════════════════════════════════════════════════════════

    async def _dispatch_builtin_tool(
        self,
        tool_name: str,
        tool_input: dict,
        call_order: int,
        tool_def,
        parent_agent_version_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        workflow_run_id: Optional[UUID] = None,
        execution_context_id: Optional[UUID] = None,
        channel: str = "production",
    ) -> dict[str, Any]:
        """Dispatch a Verity-internal meta-tool (transport='verity_builtin').

        Router: the only meta-tool today is delegate_to_agent. Future
        additions (e.g., fork_session, replay_decision) branch off the
        same method. Unknown builtin names come back as a tool_result
        error listing the known meta-tools — same pattern as unknown
        transport and unknown MCP tool.
        """
        if tool_name == "delegate_to_agent":
            return await self._delegate_to_agent(
                tool_input, call_order,
                parent_agent_version_id=parent_agent_version_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth,
                workflow_run_id=workflow_run_id,
                execution_context_id=execution_context_id,
                channel=channel,
            )
        return {
            "tool_name": tool_name,
            "call_order": call_order,
            "input_data": tool_input,
            "output_data": {
                "error": f"Unknown builtin meta-tool {tool_name!r}. "
                         f"Known: ['delegate_to_agent']."
            },
            "error": True,
            "transport": "verity_builtin",
        }

    async def _delegate_to_agent(
        self,
        tool_input: dict,
        call_order: int,
        parent_agent_version_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        workflow_run_id: Optional[UUID] = None,
        execution_context_id: Optional[UUID] = None,
        channel: str = "production",
    ) -> dict[str, Any]:
        """Spawn a sub-agent as a fully governed nested run.

        Flow:
          1. Validate input has agent_name + context.
          2. Refuse if decision_depth + 1 > MAX_DECISION_DEPTH.
          3. Require parent_agent_version_id (internal programming error
             otherwise — _gateway_tool_call must thread this in for
             verity_builtin tools).
          4. Check registry.check_delegation_authorized(parent, child_name).
             Unauthorized -> error tool_result listing the authorized targets.
          5. Call self.run_agent with parent_decision_id + incremented depth,
             pinning to resolved_child_version_id if the delegation row
             specifies it (version-pinned) or using the champion otherwise.
          6. Build a tool_record from the sub-agent's ExecutionResult.

        The sub-run writes its own row to agent_decision_log with
        parent_decision_id set to the caller's pre-generated self_decision_id.
        The caller's tool_calls_made gets this tool_record summary with the
        sub-decision's id for easy drill-through in the audit UI.
        """
        transport = "verity_builtin"

        # Validate shape
        child_name = tool_input.get("agent_name")
        child_context = tool_input.get("context")
        reason = tool_input.get("reason")

        if not isinstance(child_name, str) or not child_name.strip():
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                "Missing or invalid 'agent_name': must be a non-empty string.",
            )
        if child_context is None:
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                "Missing 'context': pass a dict with the sub-agent's input context.",
            )
        if not isinstance(child_context, dict):
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                f"'context' must be a dict; got {type(child_context).__name__}.",
            )

        # Depth guard
        next_depth = decision_depth + 1
        if next_depth >= MAX_DECISION_DEPTH:
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                f"Delegation refused: sub-agent would run at depth {next_depth}, "
                f"at or past the limit MAX_DECISION_DEPTH={MAX_DECISION_DEPTH}. "
                "Redesign the agent graph to reduce nesting.",
            )

        if parent_agent_version_id is None:
            # Programming error — the gateway threading is broken.
            # Surface it as a tool error so the loop can continue.
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                "Internal error: parent_agent_version_id not propagated to "
                "_delegate_to_agent. The engine's gateway threading is broken.",
            )

        # Governance gate
        authorization = await self.registry.check_delegation_authorized(
            parent_agent_version_id=parent_agent_version_id,
            child_agent_name=child_name,
        )
        if not authorization:
            # Pull the authorized targets list for a helpful error.
            authorized = await self.registry.list_delegations_for_parent(
                parent_agent_version_id=parent_agent_version_id,
            )
            allowed = sorted({
                row.get("effective_child_name") for row in authorized
                if row.get("authorized") and row.get("effective_child_name")
            })
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                f"Not authorized to delegate to {child_name!r}. "
                f"Authorized delegation targets for this agent version: {allowed or 'none'}. "
                "Register an agent_version_delegation row if this is intentional.",
            )

        resolved_version_id = authorization.get("resolved_child_version_id")
        if resolved_version_id is None:
            # Could happen if the child agent has no current champion yet
            # (champion-tracking row, no champion promoted). Refuse cleanly.
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                f"Delegation row found for {child_name!r} but it resolves to no "
                "runnable version (the child agent has no current champion). "
                "Promote a champion or pin the delegation to a specific version.",
            )

        # Spawn the sub-agent run.
        logger.info(
            "Delegating: parent_av=%s -> child=%s (depth %d -> %d, reason=%r)",
            parent_agent_version_id, child_name, decision_depth, next_depth, reason,
        )
        try:
            sub_result = await self.run_agent(
                agent_name=child_name,
                context=child_context,
                channel=channel,
                workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=next_depth,
                step_name=f"delegated_from_depth_{decision_depth}",
                mock=None,  # sub-agent runs live; mocks don't flow through delegation boundary
                execution_context_id=execution_context_id,
            )
        except Exception as e:
            logger.exception(
                "Sub-agent run raised during delegation: %s -> %s",
                parent_agent_version_id, child_name,
            )
            return _builtin_error(
                "delegate_to_agent", tool_input, call_order,
                f"Sub-agent {child_name!r} raised during delegation: "
                f"{type(e).__name__}: {e}",
            )

        # Success-or-failure tool_record. status=='failed' still flows back
        # so the caller's Claude sees the sub-agent's error and can decide.
        return {
            "tool_name": "delegate_to_agent",
            "call_order": call_order,
            "input_data": tool_input,
            "output_data": {
                "sub_decision_log_id": str(sub_result.decision_log_id),
                "sub_entity_name": sub_result.entity_name,
                "sub_version_label": sub_result.version_label,
                "sub_status": sub_result.status,
                "output": sub_result.output,
                "reasoning_text": sub_result.reasoning_text,
                "sub_input_tokens": sub_result.input_tokens,
                "sub_output_tokens": sub_result.output_tokens,
                "sub_duration_ms": sub_result.duration_ms,
                "sub_error_message": sub_result.error_message,
            },
            "error": sub_result.status != "complete",
            "transport": transport,
            "delegation_id": str(authorization["delegation_id"]),
            "resolved_child_version_id": str(resolved_version_id),
        }

    # ══════════════════════════════════════════════════════════
    # AGENT EXECUTION (multi-turn tool loop)
    # ══════════════════════════════════════════════════════════

    async def run_agent(
        self,
        agent_name: str,
        context: dict[str, Any],

        channel: str = "production",
        workflow_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        step_name: Optional[str] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = None,
        # Same write_mode gate as run_task — controls whether declared
        # targets actually fire after the agent's terminal turn. "auto"
        # is channel-gated (champion only), "log_only" forces dry run,
        # "write" forces. MockContext.target_blocks always wins.
        write_mode: Literal["auto", "log_only", "write"] = "auto",
        # When True and the agent's declared output_schema is set, the
        # engine injects a synthetic `submit_output` tool whose input
        # is the agent's output_schema, and forces a `tool_choice` on
        # the terminal turn so the final output is structurally
        # guaranteed. Off by default — agents emit free-form text and
        # `output` is best-effort-parsed (current behavior).
        enforce_output_schema: bool = False,
        # Live-state pointer back to execution_run for runs dispatched
        # by the async worker. Threaded through to the decision log.
        execution_run_id: Optional[UUID] = None,
    ) -> ExecutionResult:
        """Execute an agent: resolve config, assemble prompts, run the agentic loop.

        `mock` controls tool/source/target mocking and step-level
        short-circuit (see MockContext). When `mock.step_responses`
        names this agent or step, the engine returns the supplied dict
        as the output without calling Claude.

        FC-1 additions:
          - Pre-generates this run's decision log id (self_decision_id)
            at entry so that sub-agent calls made during the loop can set
            their parent_decision_id to this value BEFORE the parent's
            decision row is written.
          - Refuses to run if decision_depth >= MAX_DECISION_DEPTH. Each
            sub-agent call increments depth; this caps runaway recursion.
        """
        start_ms = _now_ms()
        logger.info(
            "Agent execution starting: %s (step=%s, tool_mocks=%s, depth=%d)",
            agent_name, step_name or "standalone", mock is not None, decision_depth,
        )

        # Pre-generated decision id — threaded into tool dispatch so a
        # delegate_to_agent call can set its spawned sub-agent's
        # parent_decision_id to this value before we've written our row.
        self_decision_id = uuid4()

        # Runaway-recursion guard. MAX_DECISION_DEPTH gates the call BEFORE
        # any config resolution happens; the error log does include the
        # agent name so it's clear which call was refused.
        if decision_depth >= MAX_DECISION_DEPTH:
            logger.error(
                "Agent execution refused — decision_depth %d >= MAX_DECISION_DEPTH %d (agent=%s)",
                decision_depth, MAX_DECISION_DEPTH, agent_name,
            )
            return ExecutionResult(
                decision_log_id=self_decision_id,
                entity_type="agent",
                entity_name=agent_name,
                version_label="",
                output={},
                duration_ms=_now_ms() - start_ms,
                status="failed",
                error_message=(
                    f"Refused to run {agent_name!r}: decision_depth={decision_depth} "
                    f"exceeds MAX_DECISION_DEPTH={MAX_DECISION_DEPTH}. Delegation chain "
                    "too deep."
                ),
            )

        config = await self.registry.get_agent_config(agent_name)

        # ── SYNC-PATH SELF-TRACKING ────────────────────────────
        # Same rationale as run_task: surface this call in /admin/runs
        # alongside worker-dispatched runs. Worker callers supply
        # execution_run_id and have already written the request row;
        # sync callers (UW workflows, validation runner, sub-agent
        # delegation) get an execution_run row written here.
        self_tracked_run_id: Optional[UUID] = None
        if execution_run_id is None:
            self_tracked_run_id = uuid4()
            await self._open_self_tracked_run(
                run_id=self_tracked_run_id,
                entity_kind="agent",
                entity_version_id=config.agent_version_id,
                entity_name=agent_name,
                channel=channel,
                input_data=context,
                execution_context_id=execution_context_id,
                workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                application=application or self.application,
                mock_mode=(mock is not None),
                write_mode=write_mode,
                enforce_output_schema=enforce_output_schema,
            )
            execution_run_id = self_tracked_run_id

        # ── STEP-LEVEL MOCK SHORT-CIRCUIT ──────────────────────
        # See the matching block in run_task. Skips the agentic loop
        # entirely (no Claude, no tool dispatch, no source/target work)
        # when the caller supplied a canned answer for this step or
        # entity name. Decision_log + run-tracking writes still happen
        # so audit shape is identical to a real run.
        is_step_mocked, step_mock_output = (False, None)
        if mock is not None:
            is_step_mocked, step_mock_output = mock.get_step_response(step_name, agent_name)

        if is_step_mocked:
            output = step_mock_output if isinstance(step_mock_output, dict) else {}
            output_text = json.dumps(output, default=str)
            duration_ms = _now_ms() - start_ms
            log_result = await self._log_decision(
                id=self_decision_id,
                entity_type=EntityType.AGENT, config=config, context=context,
                output=output, output_text=output_text,
                tool_calls_made=[], message_history=[],
                total_input_tokens=0, total_output_tokens=0,
                duration_ms=duration_ms,
                channel=channel, workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="complete", mock_mode=True,
                execution_context_id=execution_context_id,
                application=application,
                source_resolutions=None, target_writes=None,
                execution_run_id=execution_run_id,
            )
            if self_tracked_run_id is not None:
                await self._close_self_tracked_run_complete(
                    run_id=self_tracked_run_id,
                    decision_log_id=log_result["decision_log_id"],
                    duration_ms=duration_ms,
                )
            logger.info(
                "Agent execution complete (step-mocked): %s (step=%s, %dms, depth=%d)",
                agent_name, step_name or "standalone", duration_ms, decision_depth,
            )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="agent", entity_name=agent_name,
                version_label=config.version_label,
                output=output, output_summary=output_text[:500],
                reasoning_text=output.get("reasoning", "") if isinstance(output, dict) else "",
                confidence_score=output.get("confidence") if isinstance(output, dict) else None,
                risk_factors=output.get("risk_factors") if isinstance(output, dict) else None,
                tool_calls=[],
                input_tokens=0, output_tokens=0,
                duration_ms=duration_ms, status="complete",
            )

        # ── SOURCE RESOLUTION ──────────────────────────────────
        # Resolve any declared source_binding rows for this agent
        # version before the loop starts. Same helper run_task uses;
        # template_context overlays the resolved values onto a copy of
        # the caller-supplied context so prompt assembly sees both.
        # Failures here are hard fails — the loop never starts.
        template_context, source_resolutions = await self._resolve_sources(
            version_id=config.agent_version_id,
            owner_kind="agent_version",
            entity_name=agent_name,
            input_data=context,
            mock=mock,
        )
        system_prompt, user_messages = _assemble_prompts(config.prompts, template_context)
        tools = _build_tool_definitions(config.tools)
        # Initialised early so the failure handler can record partial
        # writes if a connector explosion happens mid-target loop.
        target_writes: list[dict[str, Any]] = []

        # ── OUTPUT-SCHEMA ENFORCEMENT ──────────────────────────
        # When the caller opts in via enforce_output_schema=True AND
        # the agent's declared output_schema is a valid JSON-Schema
        # properties dict, inject a synthetic `submit_output` tool that
        # the agent can call to terminate with a structurally-valid
        # answer. If the agent's loop ends naturally without calling
        # submit_output, an extra forced call is issued post-loop.
        # Off by default — agents continue emitting free-form text.
        submit_output_tool_def: Optional[dict] = None
        if enforce_output_schema:
            if not config.output_schema or not isinstance(config.output_schema, dict):
                logger.warning(
                    "enforce_output_schema=True for agent %s but no "
                    "output_schema is declared on the version; falling back "
                    "to free-form output.", agent_name,
                )
            elif not _is_valid_json_schema(config.output_schema):
                # Shorthand schemas like {'field': 'string'} aren't accepted
                # by the Claude tool input_schema validator. Fail-soft: log
                # and run without enforcement rather than abort the run.
                logger.warning(
                    "enforce_output_schema=True for agent %s but the "
                    "declared output_schema is not in valid JSON-Schema "
                    "shape (e.g. shorthand types like 'string' instead of "
                    "{'type': 'string'}); falling back to free-form output.",
                    agent_name,
                )
            else:
                submit_output_tool_def = {
                    "name": "submit_output",
                    "description": (
                        "Submit your final structured output for this run. "
                        "Calling this tool terminates the agent — there is no "
                        "tool result; the call itself is the answer."
                    ),
                    "input_schema": {
                        "type": "object",
                        "properties": config.output_schema,
                    },
                }
                tools = [*(tools or []), submit_output_tool_def]
        # When the agent calls submit_output (or we force it post-loop),
        # this captures the structured answer that becomes the run's
        # output dict.
        submit_output_input: Optional[dict] = None

        try:
            messages = [{"role": "user", "content": msg} for msg in user_messages]
            total_input_tokens = 0
            total_output_tokens = 0
            # Prompt-cache tokens are per-turn on the Anthropic response
            # (`.usage.cache_creation_input_tokens`, `.cache_read_input_tokens`).
            # Summed across the agentic loop and written to the
            # model_invocation_log row so spend analytics can see cache
            # savings at a glance.
            total_cache_write_tokens = 0
            total_cache_read_tokens = 0
            # One entry per real (non-mock) turn — used as the per_turn_metadata
            # JSONB on the invocation row for drill-through.
            per_turn_usage: list[dict] = []
            real_api_turns = 0
            last_stop_reason: Optional[str] = None
            invocation_started_at = datetime.now(timezone.utc)
            tool_calls_made = []
            # Track full message history for audit / future replay tooling.
            message_history = []

            # Multi-turn agentic loop — Claude may request tools up to max_turns times.
            max_turns = 10
            response = None
            for turn in range(max_turns):
                api_params = _build_api_params(config.inference_config, system_prompt, messages, tools)

                # ── LLM GATEWAY (async — won't block event loop) ──
                response = await self._gateway_llm_call(api_params, mock)

                # Track tokens (0 for mock responses). Mock responses don't
                # carry a `.usage` attribute, which is how we distinguish
                # real API turns from mocked ones for the invocation log.
                if hasattr(response, 'usage'):
                    in_tok = response.usage.input_tokens
                    out_tok = response.usage.output_tokens
                    cw_tok = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
                    cr_tok = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
                    total_cache_write_tokens += cw_tok
                    total_cache_read_tokens += cr_tok
                    real_api_turns += 1
                    last_stop_reason = getattr(response, 'stop_reason', None)
                    per_turn_usage.append({
                        "turn": turn,
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cache_write_tokens": cw_tok,
                        "cache_read_tokens": cr_tok,
                        "stop_reason": last_stop_reason,
                        "request_id": getattr(response, 'id', None),
                    })

                # Store assistant response in message history
                if hasattr(response, 'content'):
                    message_history.append({
                        "role": "assistant",
                        "content": _serialize_content_blocks(response.content),
                    })

                if response.stop_reason == "tool_use":
                    # First pass: scan for submit_output. If present, it
                    # terminates the run — capture the structured answer
                    # and exit the loop. We don't dispatch other tools in
                    # the same response (Claude shouldn't pair a final
                    # answer with a tool call; if it does, the answer wins).
                    if submit_output_tool_def is not None:
                        for block in response.content:
                            if (block.type == "tool_use"
                                    and block.name == "submit_output"):
                                submit_output_input = block.input or {}
                                break
                        if submit_output_input is not None:
                            messages.append({"role": "assistant", "content": response.content})
                            break

                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            # Check authorization. submit_output is the
                            # one synthetic tool that bypasses the
                            # registered-tools list (handled above; this
                            # branch only runs if there was no submit_output
                            # block).
                            authorized_names = {t.name for t in config.tools}
                            if block.name not in authorized_names:
                                tool_results.append({
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": json.dumps({"error": f"Tool '{block.name}' not authorized"}),
                                    "is_error": True,
                                })
                                continue

                            # ── TOOL GATEWAY ──
                            # parent_agent_version_id + parent_decision_id +
                            # decision_depth are threaded here so a
                            # delegate_to_agent meta-tool can (a) check the
                            # agent_version_delegation table with the right
                            # parent version, (b) set the spawned sub-agent's
                            # parent_decision_id to this run's pre-generated
                            # self_decision_id, and (c) increment depth.
                            tool_record = await self._gateway_tool_call(
                                block.name, block.input, config.tools,
                                mock, len(tool_calls_made) + 1,
                                parent_agent_version_id=config.agent_version_id,
                                parent_decision_id=self_decision_id,
                                decision_depth=decision_depth,
                                workflow_run_id=workflow_run_id,
                                execution_context_id=execution_context_id,
                                channel=channel,
                            )
                            tool_calls_made.append(tool_record)

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps(tool_record["output_data"], default=str),
                                "is_error": tool_record.get("error", False),
                            })

                    messages.append({"role": "assistant", "content": response.content})
                    messages.append({"role": "user", "content": tool_results})
                    message_history.append({"role": "user", "content": tool_results})
                else:
                    break

            # ── POST-LOOP FORCED submit_output (if enforcement on) ─
            # If output enforcement is active and the agent ended its
            # loop without calling submit_output (it stopped naturally
            # with text, or it never produced text either), issue ONE
            # more API call with tool_choice forcing submit_output. The
            # agent must produce a structured answer in the schema's
            # shape; that becomes the run's output.
            if (
                submit_output_tool_def is not None
                and submit_output_input is None
            ):
                # Append the agent's last response so the forced call
                # has full context to summarise.
                if response is not None and hasattr(response, "content"):
                    messages.append({"role": "assistant", "content": response.content})
                forced_params = _build_api_params(
                    config.inference_config,
                    system_prompt,
                    messages,
                    tools=[submit_output_tool_def],
                    tool_choice={"type": "tool", "name": "submit_output"},
                )
                forced_response = await self._gateway_llm_call(forced_params, mock)
                # Token accounting for this extra turn — keeps the
                # invocation log honest about what the run cost.
                if hasattr(forced_response, "usage"):
                    in_tok = forced_response.usage.input_tokens
                    out_tok = forced_response.usage.output_tokens
                    cw_tok = getattr(forced_response.usage, "cache_creation_input_tokens", 0) or 0
                    cr_tok = getattr(forced_response.usage, "cache_read_input_tokens", 0) or 0
                    total_input_tokens += in_tok
                    total_output_tokens += out_tok
                    total_cache_write_tokens += cw_tok
                    total_cache_read_tokens += cr_tok
                    real_api_turns += 1
                    last_stop_reason = getattr(forced_response, "stop_reason", None)
                    per_turn_usage.append({
                        "turn": "forced_submit_output",
                        "input_tokens": in_tok,
                        "output_tokens": out_tok,
                        "cache_write_tokens": cw_tok,
                        "cache_read_tokens": cr_tok,
                        "stop_reason": last_stop_reason,
                        "request_id": getattr(forced_response, "id", None),
                    })
                if hasattr(forced_response, "content"):
                    message_history.append({
                        "role": "assistant",
                        "content": _serialize_content_blocks(forced_response.content),
                    })
                    for block in forced_response.content:
                        if (
                            getattr(block, "type", None) == "tool_use"
                            and getattr(block, "name", None) == "submit_output"
                        ):
                            submit_output_input = block.input or {}
                            break
                # Treat this as the response of record for downstream
                # text extraction; an empty submit_output_input falls
                # through to the legacy text-parse path below.
                response = forced_response

            # ── FINAL OUTPUT ────────────────────────────────
            # When submit_output was called (organically or forced),
            # its tool input IS the structured output. Otherwise fall
            # back to the legacy best-effort text parse so agents
            # without enforcement keep working.
            if submit_output_input is not None:
                output = submit_output_input
                output_text = json.dumps(output, default=str)
            else:
                output_text = _extract_text(response)
                output = _try_parse_json(output_text)

            # ── TARGET WRITES ────────────────────────────────
            # Fire any declared write_targets now that we have the
            # parsed output. Same helper run_task uses; gate logic
            # honors channel × write_mode × MockContext.target_blocks.
            # Failures on required targets raise TargetWriteError; the
            # except branch below preserves partial_writes for audit.
            target_writes = await self._write_targets(
                version_id=config.agent_version_id,
                owner_kind="agent_version",
                entity_name=agent_name,
                input_data=context,
                output=output if isinstance(output, dict) else {},
                channel=channel,
                write_mode=write_mode,
                mock=mock,
            )

            duration_ms = _now_ms() - start_ms
            # With LLM mocking removed, mock_mode in the log reflects
            # "any form of caller-supplied mocking was active" — which
            # today means tool_responses or mock_all_tools.
            is_mocked = mock is not None

            log_result = await self._log_decision(
                id=self_decision_id,  # FC-1: pre-generated so sub-agents link correctly
                entity_type=EntityType.AGENT, config=config, context=context,
                output=output, output_text=output_text,
                tool_calls_made=tool_calls_made, message_history=message_history,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                duration_ms=duration_ms,
                channel=channel, workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="complete", mock_mode=is_mocked,
                execution_context_id=execution_context_id,
                application=application,
                source_resolutions=source_resolutions or None,
                target_writes=target_writes or None,
                execution_run_id=execution_run_id,
            )

            # Model invocation log — one row per decision, tokens summed
            # across agentic-loop turns. Silently skipped for fully-
            # mocked runs (no real provider usage to record).
            await self._log_model_invocation(
                decision_log_id=log_result["decision_log_id"],
                config=config,
                started_at=invocation_started_at,
                completed_at=datetime.now(timezone.utc),
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_write_tokens=total_cache_write_tokens,
                cache_read_tokens=total_cache_read_tokens,
                api_call_count=real_api_turns,
                stop_reason=last_stop_reason,
                status="complete",
                error_message=None,
                per_turn_metadata=per_turn_usage or None,
            )

            logger.info("Agent execution complete: %s (%dms, %d tool calls, %d+%d tokens, depth=%d)",
                         agent_name, duration_ms, len(tool_calls_made),
                         total_input_tokens, total_output_tokens, decision_depth)
            if self_tracked_run_id is not None:
                await self._close_self_tracked_run_complete(
                    run_id=self_tracked_run_id,
                    decision_log_id=log_result["decision_log_id"],
                    duration_ms=duration_ms,
                )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="agent", entity_name=agent_name,
                version_label=config.version_label,
                output=output, output_summary=output_text[:500],
                reasoning_text=output.get("reasoning", "") if isinstance(output, dict) else "",
                confidence_score=output.get("confidence") if isinstance(output, dict) else None,
                risk_factors=output.get("risk_factors") if isinstance(output, dict) else None,
                tool_calls=tool_calls_made,
                input_tokens=total_input_tokens, output_tokens=total_output_tokens,
                duration_ms=duration_ms, status="complete",
            )

        except Exception as e:
            duration_ms = _now_ms() - start_ms
            logger.error("Agent execution failed: %s (%dms)", agent_name, duration_ms, exc_info=True)
            # Even on error we log with self_decision_id — sub-agents spawned
            # during the (failed) loop already wrote rows referencing this id
            # as their parent_decision_id. Writing the parent's row with the
            # pre-generated id keeps the audit graph intact.
            log_result = await self._log_decision(
                id=self_decision_id,
                entity_type=EntityType.AGENT, config=config, context=context,
                output={}, output_text="", tool_calls_made=[], message_history=[],
                total_input_tokens=0, total_output_tokens=0,
                duration_ms=duration_ms,
                channel=channel, workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="failed", error_message=str(e),
                execution_context_id=execution_context_id,
                application=application,
                # Preserve partial audit if the failure happened mid-resolution
                # or mid-target-write. SourceResolutionError /
                # TargetWriteError carry partial_resolutions /
                # partial_writes; otherwise fall back to whatever the loop
                # had collected before raising.
                source_resolutions=(
                    getattr(e, "partial_resolutions", None)
                    or locals().get("source_resolutions")
                    or None
                ),
                target_writes=(
                    getattr(e, "partial_writes", None)
                    or locals().get("target_writes")
                    or None
                ),
                execution_run_id=execution_run_id,
            )
            # Record partial token usage on failed runs too — the loop
            # may have completed N turns before raising, and that token
            # spend is still real. Helper skips if totals are all zero.
            await self._log_model_invocation(
                decision_log_id=log_result["decision_log_id"],
                config=config,
                started_at=invocation_started_at,
                completed_at=datetime.now(timezone.utc),
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cache_write_tokens=total_cache_write_tokens,
                cache_read_tokens=total_cache_read_tokens,
                api_call_count=real_api_turns,
                stop_reason=last_stop_reason,
                status="failed",
                error_message=str(e),
                per_turn_metadata=per_turn_usage or None,
            )
            if self_tracked_run_id is not None:
                await self._close_self_tracked_run_error(
                    run_id=self_tracked_run_id,
                    error_code=type(e).__name__,
                    error_message=str(e)[:1000],
                    decision_log_id=log_result.get("decision_log_id"),
                )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="agent", entity_name=agent_name,
                version_label=config.version_label,
                output={}, duration_ms=duration_ms,
                status="failed", error_message=str(e),
            )

    # ══════════════════════════════════════════════════════════
    # TASK EXECUTION (single-turn, structured output)
    # ══════════════════════════════════════════════════════════

    async def run_task(
        self,
        task_name: str,
        input_data: dict[str, Any],

        channel: str = "production",
        workflow_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        step_name: Optional[str] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = None,
        # Governs declared-target writes after the LLM call succeeds.
        #   "auto"     — channel-gated: only `champion` writes for real,
        #                every other channel is log-only. Default.
        #   "log_only" — forced dry run regardless of channel. Used by
        #                replay, debugging, shadow comparisons.
        #   "write"    — forced write regardless of channel. Caller must
        #                have authority (production callers only).
        # MockContext.target_blocks still takes precedence: any field in
        # that set is log-only even under write_mode="write".
        write_mode: Literal["auto", "log_only", "write"] = "auto",
        # Live-state pointer back to execution_run for runs dispatched by
        # the async worker. The decision_log row carries this so audit
        # tooling can navigate from a decision back to its run record.
        execution_run_id: Optional[UUID] = None,
    ) -> ExecutionResult:
        """Execute a task with single-turn structured output and mock support."""
        logger.info("Task execution starting: %s (step=%s, mock=%s)",
                     task_name, step_name or "standalone", mock is not None)
        start_ms = _now_ms()
        invocation_started_at = datetime.now(timezone.utc)
        config = await self.registry.get_task_config(task_name)

        # ── SYNC-PATH SELF-TRACKING ────────────────────────────────────
        # Worker dispatch supplies execution_run_id (and has already
        # written the request + status ledger). Sync callers don't —
        # we write the execution_run row ourselves so this call shows
        # up in /admin/runs alongside worker-dispatched runs. See the
        # _open_self_tracked_run docstring for the rationale.
        self_tracked_run_id: Optional[UUID] = None
        if execution_run_id is None:
            self_tracked_run_id = uuid4()
            await self._open_self_tracked_run(
                run_id=self_tracked_run_id,
                entity_kind="task",
                entity_version_id=config.task_version_id,
                entity_name=task_name,
                channel=channel,
                input_data=input_data,
                execution_context_id=execution_context_id,
                workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                application=application or self.application,
                mock_mode=(mock is not None),
                write_mode=write_mode,
            )
            execution_run_id = self_tracked_run_id

        # ── STEP-LEVEL MOCK SHORT-CIRCUIT ──────────────────────────────
        # If the caller supplied a step-level mock for this run (matched
        # by step_name first, then task_name), the engine returns the
        # canned answer without calling Claude, resolving sources, or
        # firing targets. This is the path UW's mock mode takes — fast,
        # deterministic, zero-token. The decision_log row + execution_run
        # tracking still happen below, so /admin/runs and /admin/decisions
        # show the same shape as a real run.
        is_step_mocked, step_mock_output = (False, None)
        if mock is not None:
            is_step_mocked, step_mock_output = mock.get_step_response(step_name, task_name)

        if is_step_mocked:
            output = step_mock_output if isinstance(step_mock_output, dict) else {}
            output_text = json.dumps(output, default=str)
            duration_ms = _now_ms() - start_ms
            log_result = await self._log_decision(
                entity_type=EntityType.TASK, config=config, context=input_data,
                output=output, output_text=output_text,
                tool_calls_made=[], message_history=[],
                total_input_tokens=0, total_output_tokens=0,
                duration_ms=duration_ms,
                channel=channel, workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="complete", mock_mode=True,
                execution_context_id=execution_context_id,
                application=application,
                source_resolutions=None, target_writes=None,
                execution_run_id=execution_run_id,
            )
            if self_tracked_run_id is not None:
                await self._close_self_tracked_run_complete(
                    run_id=self_tracked_run_id,
                    decision_log_id=log_result["decision_log_id"],
                    duration_ms=duration_ms,
                )
            logger.info(
                "Task execution complete (step-mocked): %s (step=%s, %dms)",
                task_name, step_name or "standalone", duration_ms,
            )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="task", entity_name=task_name,
                version_label=config.version_label,
                output=output, output_summary=output_text[:500],
                input_tokens=0, output_tokens=0,
                duration_ms=duration_ms, status="complete",
            )

        # ── SOURCE RESOLUTION ──────────────────────────────────────────
        # Before prompt assembly, resolve any declared data sources for
        # this TaskVersion. Each source maps a caller-supplied reference
        # (e.g. input_data["document_ref"]) to a template variable
        # (e.g. {{document_text}}) via a registered connector. Mocks are
        # checked first, then the connector fetch is invoked. Resolution
        # is eager; failures are hard failures. See
        # verity.runtime.connectors for the provider contract.
        template_context, source_resolutions = await self._resolve_sources(
            version_id=config.task_version_id,
            owner_kind="task_version",
            entity_name=task_name,
            input_data=input_data,
            mock=mock,
        )
        system_prompt, user_messages = _assemble_prompts(config.prompts, template_context)

        try:
            messages = [{"role": "user", "content": msg} for msg in user_messages]

            # For tasks with output_schema in valid JSON Schema format,
            # use tool_choice to force Claude to return structured JSON.
            # The schema must have proper JSON Schema property definitions
            # (e.g., {"field": {"type": "string"}}) not informal ones
            # (e.g., {"field": "string"}).
            tools_for_task = None
            tool_choice = None
            output_schema = config.task_output_schema
            if output_schema and isinstance(output_schema, dict) and _is_valid_json_schema(output_schema):
                tools_for_task = [{
                    "name": "structured_output",
                    "description": f"Return the structured output for {task_name}",
                    "input_schema": {"type": "object", "properties": output_schema},
                }]
                tool_choice = {"type": "tool", "name": "structured_output"}

            api_params = _build_api_params(
                config.inference_config, system_prompt, messages,
                tools=tools_for_task, tool_choice=tool_choice,
            )

            # ── LLM GATEWAY (async) ──
            # `mock` is passed through for symmetry with run_agent, but has
            # no effect: the gateway doesn't mock LLM calls after Phase 3d,
            # and tasks use a synthetic `structured_output` tool (not a
            # registered one) so tool-level mocking doesn't apply either.
            response = await self._gateway_llm_call(api_params, mock=mock)

            # Walk the response content blocks once. Claude's response is a
            # list of typed pieces: `thinking` blocks (extended thinking
            # mode), `text` blocks (narrative / chain-of-thought), and
            # `tool_use` blocks (the structured answer when we forced
            # structured_output via tool_choice).
            #
            # Reasoning is captured unconditionally from thinking + text
            # blocks — a task either has a structured answer alongside
            # the narrative (tool_choice path) or the narrative IS the
            # answer (non-tool_choice path). We separate them below.
            thinking_parts: list[str] = []
            text_parts: list[str] = []
            tool_output: dict = {}
            for block in (response.content or []):
                btype = getattr(block, "type", None)
                if btype == "thinking":
                    thinking_parts.append(getattr(block, "thinking", "") or "")
                elif btype == "text":
                    text_parts.append(getattr(block, "text", "") or "")
                elif btype == "tool_use" and getattr(block, "name", None) == "structured_output":
                    tool_output = getattr(block, "input", {}) or {}

            if tool_choice:
                # Structured output path: tool_use carries the answer,
                # narrative text blocks (and any thinking blocks) are the
                # reasoning alongside it.
                output = tool_output
                output_text = json.dumps(output)
                reasoning_parts = thinking_parts + text_parts
            else:
                # Free-form path: the concatenated text IS the answer.
                # Only thinking blocks count as separate reasoning.
                output_text = "\n\n".join(text_parts)
                output = _try_parse_json(output_text) if output_text else {}
                reasoning_parts = thinking_parts

            reasoning_text: Optional[str] = (
                "\n\n".join(p for p in reasoning_parts if p).strip() or None
            )

            # ── TARGET WRITES ───────────────────────────────────────────
            # Fire any declared output targets now that we have a valid
            # output dict. Each target maps an output field to a connector
            # write. The write gate (channel × write_mode × mock.target_blocks)
            # decides whether to actually call the connector or just record
            # a log-only intent. Per-target failures on required targets
            # raise TargetWriteError and abort the task; partial writes
            # already made are preserved on the raised exception so the
            # decision log still captures them.
            target_writes = await self._write_targets(
                version_id=config.task_version_id,
                owner_kind="task_version",
                entity_name=task_name,
                input_data=input_data,
                output=output if isinstance(output, dict) else {},
                channel=channel,
                write_mode=write_mode,
                mock=mock,
            )

            duration_ms = _now_ms() - start_ms

            log_result = await self._log_decision(
                entity_type=EntityType.TASK, config=config, context=input_data,
                output=output, output_text=output_text,
                reasoning_text=reasoning_text,
                tool_calls_made=[], message_history=[],
                total_input_tokens=response.usage.input_tokens,
                total_output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms,
                channel=channel, workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="complete",
                execution_context_id=execution_context_id,
                application=application,
                source_resolutions=source_resolutions or None,
                target_writes=target_writes or None,
                execution_run_id=execution_run_id,
            )

            # Single-turn task — one API call, so per_turn_metadata is
            # omitted (the invocation row's top-level fields already have
            # everything for a one-turn call).
            cache_write_tok = getattr(response.usage, 'cache_creation_input_tokens', 0) or 0
            cache_read_tok  = getattr(response.usage, 'cache_read_input_tokens', 0) or 0
            await self._log_model_invocation(
                decision_log_id=log_result["decision_log_id"],
                config=config,
                started_at=invocation_started_at,
                completed_at=datetime.now(timezone.utc),
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cache_write_tokens=cache_write_tok,
                cache_read_tokens=cache_read_tok,
                api_call_count=1,
                stop_reason=getattr(response, 'stop_reason', None),
                status="complete",
                error_message=None,
                per_turn_metadata=None,
            )

            logger.info("Task execution complete: %s (%dms, %d+%d tokens)",
                         task_name, duration_ms,
                         response.usage.input_tokens, response.usage.output_tokens)
            # Close the self-tracked run (no-op if the worker is the
            # caller, since execution_run_id was supplied externally).
            if self_tracked_run_id is not None:
                await self._close_self_tracked_run_complete(
                    run_id=self_tracked_run_id,
                    decision_log_id=log_result["decision_log_id"],
                    duration_ms=duration_ms,
                )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="task", entity_name=task_name,
                version_label=config.version_label,
                output=output, output_summary=output_text[:500],
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms, status="complete",
            )

        except Exception as e:
            duration_ms = _now_ms() - start_ms
            logger.error("Task execution failed: %s (%dms)", task_name, duration_ms, exc_info=True)
            log_result = await self._log_decision(
                entity_type=EntityType.TASK, config=config, context=input_data,
                output={}, output_text="", tool_calls_made=[], message_history=[],
                total_input_tokens=0, total_output_tokens=0,
                duration_ms=duration_ms,
                channel=channel, workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="failed", error_message=str(e),
                execution_context_id=execution_context_id,
                application=application,
                source_resolutions=(
                    getattr(e, "partial_resolutions", None)
                    or locals().get("source_resolutions")
                    or None
                ),
                target_writes=(
                    getattr(e, "partial_writes", None)
                    or locals().get("target_writes")
                    or None
                ),
                execution_run_id=execution_run_id,
            )
            if self_tracked_run_id is not None:
                await self._close_self_tracked_run_error(
                    run_id=self_tracked_run_id,
                    error_code=type(e).__name__,
                    error_message=str(e)[:1000],
                    decision_log_id=log_result.get("decision_log_id"),
                )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="task", entity_name=task_name,
                version_label=config.version_label,
                output={}, duration_ms=duration_ms,
                status="failed", error_message=str(e),
            )

    # ══════════════════════════════════════════════════════════
    # TASK SOURCE RESOLUTION (pre-prompt, declarative I/O for Tasks)
    # ══════════════════════════════════════════════════════════

    async def _resolve_sources(
        self,
        version_id: UUID,
        owner_kind: str,   # 'task_version' | 'agent_version'
        entity_name: str,
        input_data: dict[str, Any],
        mock: Optional[MockContext],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Resolve declared source bindings for a task or agent version.

        Reads source_binding rows for (owner_kind, version_id), parses
        each `reference` string in the wiring DSL, and assembles a
        template context by overlaying the resolved values onto a copy
        of input_data. Connector-fetch references hit the registered
        provider; input./const: references are pure data lookups.

        Returns (template_context, resolutions):
          - template_context — input_data with resolved template_vars merged in.
          - resolutions      — audit list, one entry per binding, with
                                shape suitable for the decision log's
                                source_resolutions JSONB column.

        Mocking semantics: for `fetch:` references, the binding's input
        field name (the part inside `input.<...>`) is used as the
        MockContext key, preserving the existing per-source mock
        registration shape.

        Raises:
          - SourceResolutionError: a required binding could not be
            resolved (missing input value, connector failure, malformed
            reference).
          - ConnectorNotRegistered: the binding's connector isn't
            registered.

        Entities with zero declared bindings short-circuit to
        (input_data, []) with no DB or audit noise.
        """
        rows = await self.registry.db.fetch_all(
            "list_source_bindings",
            {"owner_kind": owner_kind, "owner_id": str(version_id)},
        )
        if not rows:
            return dict(input_data), []

        from verity.runtime.connectors import (
            get_provider,
            ConnectorNotRegistered,
            SourceResolutionError,
        )

        async def _connector_fetch(connector_name: str, method: str, ref_value: Any) -> Any:
            provider = get_provider(connector_name)
            return await provider.fetch(method, ref_value)

        template_context = dict(input_data)
        resolutions: list[dict[str, Any]] = []
        scopes = {"input": input_data}

        for row in rows:
            template_var = row["template_var"]
            reference_str = row["reference"]
            required = row["required"]

            # Parse upfront — a bad reference is registration-level data,
            # so a failure here is structural and must abort.
            try:
                parsed = _parse_reference(reference_str)
            except ValueError as exc:
                resolutions.append({
                    "template_var": template_var,
                    "reference": reference_str,
                    "kind": "unknown",
                    "status": "failed",
                    "mocked": False,
                    "failure_reason": f"parse_error: {exc}",
                })
                raise SourceResolutionError(
                    f"{owner_kind} '{entity_name}' has a malformed source "
                    f"reference for template_var={template_var!r}: {exc}",
                    partial_resolutions=resolutions,
                ) from exc

            # Build a base record. Fetch-kind records carry the connector
            # info so audit views can show 'edms.get_document_text' at a
            # glance; input/const records carry just the kind.
            base: dict[str, Any] = {
                "template_var": template_var,
                "reference": reference_str,
                "kind": parsed.kind,
            }
            if parsed.kind == "fetch":
                base["input_field"] = parsed.arg_path
                base["connector"] = parsed.connector
                base["method"] = parsed.method
                # MockContext keys per-source mocks by the input field
                # name; preserve that for backward compat.
                if mock is not None:
                    is_mocked, mock_payload = mock.get_source_response(parsed.arg_path)
                    if is_mocked:
                        template_context[template_var] = mock_payload
                        size = _payload_size(mock_payload)
                        resolutions.append({
                            **base,
                            "ref_summary": _ref_summary(input_data.get(parsed.arg_path)),
                            "status": "resolved",
                            "mocked": True,
                            "payload_size": size,
                        })
                        logger.info(
                            "source_resolved entity=%s template_var=%s "
                            "kind=fetch connector=%s method=%s mocked=True size=%s",
                            entity_name, template_var, parsed.connector,
                            parsed.method, size,
                        )
                        continue

            # Real resolution.
            try:
                value = await _resolve_reference(parsed, scopes, _connector_fetch)
            except ConnectorNotRegistered:
                resolutions.append({
                    **base,
                    "ref_summary": _ref_summary(
                        input_data.get(parsed.arg_path) if parsed.kind == "fetch" else None
                    ),
                    "status": "failed",
                    "mocked": False,
                    "failure_reason": "connector_not_registered",
                })
                raise
            except Exception as exc:
                resolutions.append({
                    **base,
                    "ref_summary": _ref_summary(
                        input_data.get(parsed.arg_path) if parsed.kind == "fetch" else None
                    ),
                    "status": "failed",
                    "mocked": False,
                    "failure_reason": str(exc)[:200],
                })
                raise SourceResolutionError(
                    f"{owner_kind} '{entity_name}' failed to resolve source "
                    f"'{template_var}' via {reference_str!r}: {exc}",
                    partial_resolutions=resolutions,
                ) from exc

            # Missing input/fetch arg path. Required → fail; optional → skip.
            if value is _MISSING:
                if required:
                    resolutions.append({
                        **base, "status": "failed", "mocked": False,
                        "failure_reason": "missing_value",
                    })
                    raise SourceResolutionError(
                        f"{owner_kind} '{entity_name}' declares required "
                        f"source '{template_var}' (reference={reference_str!r}) "
                        f"but the caller did not provide a resolvable value.",
                        partial_resolutions=resolutions,
                    )
                resolutions.append({
                    **base, "status": "skipped_no_ref", "mocked": False,
                })
                continue

            template_context[template_var] = value
            size = _payload_size(value)
            resolution: dict[str, Any] = {
                **base, "status": "resolved", "mocked": False,
                "payload_size": size,
            }
            if parsed.kind == "fetch":
                resolution["ref_summary"] = _ref_summary(
                    input_data.get(parsed.arg_path)
                )
            resolutions.append(resolution)
            logger.info(
                "source_resolved entity=%s template_var=%s kind=%s size=%s",
                entity_name, template_var, parsed.kind, size,
            )

        return template_context, resolutions

    async def _write_targets(
        self,
        version_id: UUID,
        owner_kind: str,   # 'task_version' | 'agent_version'
        entity_name: str,
        input_data: dict[str, Any],
        output: dict[str, Any],
        channel: str,
        write_mode: Literal["auto", "log_only", "write"],
        mock: Optional[MockContext],
    ) -> list[dict[str, Any]]:
        """Fire declared output targets for a task or agent version.

        For each write_target (in execution_order):
          1. Compute the effective write mode (channel × write_mode ×
             MockContext.target_blocks). See `_effective_write_mode`.
          2. Load the per-field target_payload_field rows and assemble
             the payload dict via `_build_target_payload` (resolves
             references against {input, output}).
          3. If effective mode is 'write', call the registered
             connector's write(). If 'log_only', record the intended
             write without calling the connector.

        Connector exceptions on required targets raise TargetWriteError
        carrying partial_writes so the caller's decision log still
        captures the audit trail. Optional-target failures are recorded
        but do not abort.

        Returns a list of write records suitable for the decision log's
        target_writes JSONB column. Entities with zero declared targets
        short-circuit to [] with no DB round-trip.
        """
        target_rows = await self.registry.db.fetch_all(
            "list_write_targets",
            {"owner_kind": owner_kind, "owner_id": str(version_id)},
        )
        if not target_rows:
            return []

        from verity.runtime.connectors import (
            get_provider,
            ConnectorNotRegistered,
            TargetWriteError,
        )

        writes: list[dict[str, Any]] = []

        # Sort by execution_order so the audit list reflects declared
        # ordering. The SQL already orders, but a defensive sort keeps
        # the semantics if the query shape changes.
        for row in sorted(target_rows, key=lambda r: r.get("execution_order", 1)):
            target_id = row["id"]
            target_name = row["name"]
            connector_name = row["connector_name"]
            write_method = row["write_method"]
            container = row["container"]
            required = row["required"]

            mock_blocked = bool(mock and mock.is_target_blocked(target_name))
            effective, reason = _effective_write_mode(
                write_mode=write_mode, channel=channel, mock_blocked=mock_blocked,
            )

            base = {
                "target_name": target_name,
                "connector": connector_name,
                "method": write_method,
                "container": container,
                "mode": effective,
                "mode_reason": reason,
                "mocked": mock_blocked,
            }

            # Assemble the payload by walking target_payload_field rows.
            field_rows = await self.registry.db.fetch_all(
                "list_target_payload_fields",
                {"write_target_id": str(target_id)},
            )
            try:
                payload = _build_target_payload(field_rows, input_data, output)
            except ValueError as exc:
                writes.append({
                    **base, "status": "failed",
                    "failure_reason": f"payload_assembly: {exc}",
                })
                if required:
                    raise TargetWriteError(
                        f"{owner_kind} '{entity_name}' failed to assemble payload "
                        f"for target '{target_name}': {exc}",
                        partial_writes=writes,
                    ) from exc
                logger.info(
                    "target_skipped entity=%s target=%s reason=%s",
                    entity_name, target_name, exc,
                )
                continue

            size = _payload_size(payload)

            # Log-only path — record the intended write but skip the
            # connector. Validation runs and non-champion channels land
            # here.
            if effective == "log_only":
                writes.append({**base, "status": "logged", "payload_size": size})
                logger.info(
                    "target_logged entity=%s target=%s connector=%s method=%s size=%s reason=%s",
                    entity_name, target_name, connector_name, write_method, size, reason,
                )
                continue

            # Real write.
            try:
                provider = get_provider(connector_name)
                handle = await provider.write(write_method, container, payload)
            except ConnectorNotRegistered:
                writes.append({
                    **base, "status": "failed",
                    "payload_size": size,
                    "failure_reason": "connector_not_registered",
                })
                if required:
                    raise
                continue
            except Exception as exc:
                writes.append({
                    **base, "status": "failed",
                    "payload_size": size,
                    "failure_reason": str(exc)[:200],
                })
                if required:
                    raise TargetWriteError(
                        f"{owner_kind} '{entity_name}' failed to write target "
                        f"'{target_name}' via {connector_name}.{write_method}: {exc}",
                        partial_writes=writes,
                    ) from exc
                continue

            writes.append({
                **base, "status": "wrote",
                "payload_size": size,
                "handle": handle,
            })
            logger.info(
                "target_wrote entity=%s target=%s connector=%s method=%s size=%s handle=%s",
                entity_name, target_name, connector_name, write_method, size, handle,
            )

        return writes

    # ══════════════════════════════════════════════════════════
    # TOOL EXECUTION (standalone, no LLM — for pipeline steps)
    # ══════════════════════════════════════════════════════════

    async def run_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],

        channel: str = "production",
        workflow_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        step_name: Optional[str] = None,
        mock: Optional[MockContext] = None,
        execution_context_id: Optional[UUID] = None,
        application: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a tool directly — no LLM call.

        Used for deterministic pipeline steps (clearance checks, data lookups).
        Goes through the tool gateway (respects mock context).
        Logs a decision for audit completeness.
        """
        start_ms = _now_ms()

        # Resolve tool from registry
        tool_rows = await self.registry.db.fetch_all("list_tools")
        tool_def = next((t for t in tool_rows if t["name"] == tool_name), None)
        if not tool_def:
            raise ValueError(f"Tool '{tool_name}' not found in registry")

        # Build a minimal authorized_tools list for the gateway
        from verity.models.tool import ToolAuthorization
        auth_tool = ToolAuthorization(
            tool_id=tool_def["id"], name=tool_def["name"],
            display_name=tool_def["display_name"],
            description=tool_def["description"],
            input_schema=tool_def["input_schema"],
            output_schema=tool_def["output_schema"],
            implementation_path=tool_def["implementation_path"],
            mock_mode_enabled=tool_def["mock_mode_enabled"],
            mock_response_key=tool_def.get("mock_response_key"),
        )

        try:
            # ── TOOL GATEWAY ──
            tool_record = await self._gateway_tool_call(
                tool_name, input_data, [auth_tool], mock, 1,
            )

            output = tool_record.get("output_data", {})
            duration_ms = _now_ms() - start_ms

            # Log decision (entity_type='tool' for audit)
            snapshot = {"tool_name": tool_name, "mock_mode": tool_record.get("mock_mode", False)}
            log_result = await self.decisions.log_decision(DecisionLogCreate(
                entity_type=EntityType.TOOL,
                entity_version_id=tool_def["id"],  # Use tool ID as version ID
                prompt_version_ids=[],
                inference_config_snapshot=snapshot,
                
                channel=DeploymentChannel(channel),
                workflow_run_id=workflow_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth,
                step_name=step_name,
                execution_context_id=execution_context_id,
                input_summary=str(input_data)[:500],
                input_json=input_data,
                output_json=output if isinstance(output, dict) else {"result": output},
                output_summary=str(output)[:500],
                model_used=None,
                input_tokens=0, output_tokens=0,
                duration_ms=duration_ms,
                tool_calls_made=[tool_record],
                application=application or self.application,
                status="complete" if not tool_record.get("error") else "failed",
                mock_mode=tool_record.get("mock_mode", False),
            ))

            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="tool", entity_name=tool_name,
                version_label="n/a",
                output=output if isinstance(output, dict) else {"result": output},
                output_summary=str(output)[:500],
                duration_ms=duration_ms,
                status="complete" if not tool_record.get("error") else "failed",
                error_message=output.get("error") if isinstance(output, dict) and "error" in output else None,
            )

        except Exception as e:
            duration_ms = _now_ms() - start_ms
            return ExecutionResult(
                decision_log_id=UUID(int=0),  # No decision logged on exception
                entity_type="tool", entity_name=tool_name,
                version_label="n/a", output={},
                duration_ms=duration_ms,
                status="failed", error_message=str(e),
            )

    # ══════════════════════════════════════════════════════════
    # DECISION LOGGING (shared by agents, tasks, and tools)
    # ══════════════════════════════════════════════════════════

    async def _log_model_invocation(
        self,
        *,
        decision_log_id: UUID,
        config,
        started_at: datetime,
        completed_at: datetime,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int,
        cache_read_tokens: int,
        api_call_count: int,
        stop_reason: Optional[str],
        status: str,
        error_message: Optional[str],
        per_turn_metadata: Optional[list[dict]],
    ) -> None:
        """Write a model_invocation_log row alongside the decision.

        Silent no-op paths:
          - `self.models` is None (unit tests / pre-FC instances).
          - The run was fully mocked (input_tokens + output_tokens == 0
            AND cache tokens == 0). Mock runs carry no real provider
            usage; writing rows would corrupt spend analytics.
          - The model isn't in the catalog (e.g. someone just added a
            new Claude model but hasn't run the seed). Logs a warning
            rather than crashing the decision path — the decision row
            itself is already safely written at this point.
        """
        if self.models is None:
            return
        if (input_tokens + output_tokens + cache_write_tokens + cache_read_tokens) == 0:
            return

        model_name = (
            config.inference_config.model_name
            if hasattr(config, "inference_config") else None
        )
        if not model_name:
            return

        # Anthropic is the only provider the engine currently calls;
        # Bedrock / OpenAI paths will override this when they land.
        provider = "anthropic"
        model_row = await self.models.get_model_by_name(provider, model_name)
        if not model_row:
            logger.warning(
                "Model '%s/%s' not in catalog — invocation log skipped for "
                "decision %s. Register the model (and a price row) and "
                "re-run.", provider, model_name, decision_log_id,
            )
            return

        try:
            await self.models.log_invocation(
                decision_log_id=decision_log_id,
                model_id=model_row["id"],
                provider=provider,
                model_name=model_name,
                started_at=started_at,
                completed_at=completed_at,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_creation_input_tokens=cache_write_tokens,
                cache_read_input_tokens=cache_read_tokens,
                api_call_count=api_call_count,
                stop_reason=stop_reason,
                status=status,
                error_message=error_message,
                per_turn_metadata=per_turn_metadata,
            )
        except Exception:
            # Never fail a decision because invocation logging failed —
            # the decision row is the audit-critical record; the
            # invocation row is observability data.
            logger.exception(
                "Failed to write model_invocation_log for decision %s",
                decision_log_id,
            )

    # ── SYNC-PATH RUN TRACKING ─────────────────────────────────
    # Worker-dispatched runs already have an execution_run row written
    # by the API (see web/api/runs.py + RunsWriter.submit) and a full
    # status ledger written by the worker. Sync callers — UW workflows,
    # validation runner, notebooks calling verity.execution.* directly —
    # bypass that path entirely. The helpers below make every sync call
    # leave the same minimum trail in the run-tracking tables so the
    # /admin/runs page is the canonical "what happened" view regardless
    # of how the call was kicked off.
    #
    # Sync runs get exactly two rows:
    #   1. execution_run                  — the request, written at entry
    #   2. execution_run_completion or _error — the terminal outcome
    #
    # No execution_run_status entries: a sync call has no claim queue,
    # so 'submitted'/'claimed'/'heartbeat' events would be invented
    # noise. The execution_run_current view resolves current_status from
    # the terminal row (or falls back to 'submitted' until the terminal
    # row lands), which is exactly what we want.

    async def _open_self_tracked_run(
        self,
        *,
        run_id: UUID,
        entity_kind: str,                          # 'task' | 'agent'
        entity_version_id: UUID,
        entity_name: str,
        channel: str,
        input_data: Optional[dict],
        execution_context_id: Optional[UUID],
        workflow_run_id: Optional[UUID],
        parent_decision_id: Optional[UUID],
        application: str,
        mock_mode: bool,
        write_mode: Optional[str] = None,
        enforce_output_schema: Optional[bool] = None,
    ) -> None:
        """INSERT the execution_run request row for a sync call."""
        await self.registry.db.execute_returning(
            "insert_execution_run",
            {
                "id": str(run_id),
                "entity_kind": entity_kind,
                "entity_version_id": str(entity_version_id),
                "entity_name": entity_name,
                "channel": channel,
                "input_json": (
                    json.dumps(input_data, default=str) if input_data else None
                ),
                "execution_context_id": (
                    str(execution_context_id) if execution_context_id else None
                ),
                "workflow_run_id": (
                    str(workflow_run_id) if workflow_run_id else None
                ),
                "parent_decision_id": (
                    str(parent_decision_id) if parent_decision_id else None
                ),
                "application": application,
                "mock_mode": mock_mode,
                "write_mode": write_mode,
                "enforce_output_schema": enforce_output_schema,
                # Distinguish sync calls in audit views from worker-
                # dispatched ones without inventing fake worker ids.
                "submitted_by": "inproc",
            },
        )

    async def _close_self_tracked_run_complete(
        self,
        run_id: UUID,
        decision_log_id: Optional[UUID],
        duration_ms: Optional[int],
    ) -> None:
        """INSERT the terminal-success row for a self-tracked sync run.

        Failures here are logged but never raise — the run already
        completed; failing to record the terminal row leaves the
        execution_run_current view showing 'submitted' until somebody
        notices, which is mildly confusing but not load-bearing.
        Better than throwing on top of a successful call.
        """
        try:
            await self.registry.db.execute_returning(
                "insert_execution_run_completion",
                {
                    "execution_run_id": str(run_id),
                    "final_status": "complete",
                    "decision_log_id": (
                        str(decision_log_id) if decision_log_id else None
                    ),
                    "duration_ms": duration_ms,
                    "worker_id": None,
                },
            )
        except Exception:
            logger.exception(
                "Failed to write execution_run_completion for self-tracked run %s",
                run_id,
            )

    async def _close_self_tracked_run_error(
        self,
        run_id: UUID,
        error_code: Optional[str],
        error_message: str,
        decision_log_id: Optional[UUID] = None,
    ) -> None:
        """INSERT the terminal-failure row for a self-tracked sync run."""
        try:
            await self.registry.db.execute_returning(
                "insert_execution_run_error",
                {
                    "execution_run_id": str(run_id),
                    "error_code": error_code,
                    "error_message": error_message,
                    "error_trace": None,
                    "worker_id": None,
                    "decision_log_id": (
                        str(decision_log_id) if decision_log_id else None
                    ),
                },
            )
        except Exception:
            logger.exception(
                "Failed to write execution_run_error for self-tracked run %s",
                run_id,
            )

    async def _log_decision(
        self,
        entity_type: EntityType,
        config,
        context: dict,
        output: dict | str,
        output_text: str,
        tool_calls_made: list,
        message_history: list,
        total_input_tokens: int,
        total_output_tokens: int,
        duration_ms: int,
        channel: str,
        workflow_run_id: Optional[UUID],
        parent_decision_id: Optional[UUID],
        decision_depth: int,
        step_name: Optional[str],
        status: str,
        error_message: Optional[str] = None,
        mock_mode: bool = False,
        execution_context_id: Optional[UUID] = None,
        run_purpose: str = "production",
        reproduced_from_decision_id: Optional[UUID] = None,
        id: Optional[UUID] = None,
        # `application` overrides self.application for this one decision.
        # Used by the REST runtime endpoints so that decisions produced on
        # behalf of a caller (e.g. ds_workbench) get logged with the
        # caller's app name rather than the Verity server's default
        # identity. None → fall back to self.application (the SDK-client
        # identity the engine was constructed with).
        application: Optional[str] = None,
        # Declarative I/O audit trail — source resolutions and target
        # writes produced during this execution. Persisted as JSONB on
        # agent_decision_log for later querying and replay.
        source_resolutions: Optional[list[dict]] = None,
        target_writes: Optional[list[dict]] = None,
        # Explicit reasoning text captured by the caller. For tasks with
        # structured output via tool_choice this is Claude's chain-of-thought
        # text block emitted before the forced tool_use. For agents emitting
        # a prose final turn this is that text. None means the model did
        # not produce any narrative alongside the structured answer.
        reasoning_text: Optional[str] = None,
        # Live-state pointer back to execution_run when this decision was
        # produced via the async run-submission path (worker-driven).
        # None for legacy synchronous calls that bypass the worker.
        execution_run_id: Optional[UUID] = None,
    ) -> dict:
        """Create a decision log entry with full snapshot.

        FC-1: `id` is an optional caller-supplied UUID. When provided,
        it's used as the decision log row's primary key (via COALESCE
        in the SQL); otherwise the SQL column default uuid_generate_v4()
        generates one. The runtime pre-generates the id at the start of
        run_agent so sub-agent calls made during the loop can set their
        parent_decision_id correctly before this row is written.
        """
        snapshot = config.get_inference_snapshot() if hasattr(config, 'get_inference_snapshot') else {}

        # Determine version_id based on entity type
        if entity_type == EntityType.AGENT:
            version_id = config.agent_version_id
        elif entity_type == EntityType.TASK:
            version_id = config.task_version_id
        else:
            version_id = getattr(config, 'id', None) or UUID(int=0)

        # Strip bulky fields (e.g. base64 PDF bytes under `_documents`)
        # from the logged input before it hits the DB. The original
        # `context` is still used upstream for prompt assembly and tool
        # calls — only the audit representation is trimmed.
        sanitized_context, redaction_summary = _redact_input_for_log(
            context if isinstance(context, dict) else None
        )
        summary_source = sanitized_context if sanitized_context is not None else context

        return await self.decisions.log_decision(DecisionLogCreate(
            id=id,
            entity_type=entity_type,
            entity_version_id=version_id,
            prompt_version_ids=[p.prompt_version_id for p in config.prompts] if hasattr(config, 'prompts') else [],
            inference_config_snapshot=snapshot.model_dump() if hasattr(snapshot, 'model_dump') else snapshot,
            channel=DeploymentChannel(channel),
            mock_mode=mock_mode,
            workflow_run_id=workflow_run_id,
            parent_decision_id=parent_decision_id,
            decision_depth=decision_depth,
            step_name=step_name,
            execution_context_id=execution_context_id,
            run_purpose=RunPurpose(run_purpose),
            reproduced_from_decision_id=reproduced_from_decision_id,
            input_summary=str(summary_source)[:500],
            input_json=sanitized_context,
            output_json=output if isinstance(output, dict) else None,
            output_summary=output_text[:500] if output_text else None,
            # Reasoning precedence: explicit reasoning_text from the caller
            # (captured from Claude's text block before a forced tool_use)
            # wins; otherwise fall back to a `reasoning` field the structured
            # output dict might carry. No silent fallback to output_text —
            # that produced a duplicate of output_summary for tasks whose
            # output had no reasoning field.
            reasoning_text=(
                reasoning_text
                or (output.get("reasoning") if isinstance(output, dict) else None)
            ),
            risk_factors=output.get("risk_factors") if isinstance(output, dict) else None,
            confidence_score=output.get("confidence") if isinstance(output, dict) else None,
            model_used=config.inference_config.model_name if hasattr(config, 'inference_config') else None,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            duration_ms=duration_ms,
            tool_calls_made=tool_calls_made if tool_calls_made else None,
            message_history=message_history if message_history else None,
            application=application or self.application,
            status=status,
            error_message=error_message,
            source_resolutions=source_resolutions,
            target_writes=target_writes,
            redaction_applied=redaction_summary,
            execution_run_id=execution_run_id,
        ))


# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def _assemble_prompts(
    prompts: list[PromptAssignment], context: dict[str, Any]
) -> tuple[str, list]:
    """Assemble prompts into system prompt and user messages.

    Validates that all declared template variables are present in the
    context dict. Raises ValueError if any are missing, so the caller
    gets a clear error instead of {{placeholder}} being sent to Claude.

    If the context contains a "_documents" key (list of dicts with
    "data" and "media_type"), document content blocks are prepended
    to the first user message. This enables sending PDFs to Claude
    for native document understanding (form layout, checkboxes, etc.).

    Returns:
        (system_prompt, user_messages) where each user message is either
        a string (text-only) or a list of content blocks (documents + text).
    """
    system_parts = []
    user_messages = []
    sorted_prompts = sorted(prompts, key=lambda p: p.execution_order)

    for prompt in sorted_prompts:
        if not prompt.is_required and prompt.condition_logic:
            if not _evaluate_condition(prompt.condition_logic, context):
                continue

        # Validate: check that all declared template variables are in context
        # Skip keys starting with "_" — those are internal (e.g., _documents)
        if prompt.template_variables:
            missing = [v for v in prompt.template_variables
                       if v not in context and not v.startswith("_")]
            if missing:
                raise ValueError(
                    f"Prompt '{prompt.prompt_name}' requires template variables "
                    f"{missing} but they are not in the execution context. "
                    f"Available context keys: {sorted(context.keys())}"
                )

        content = _substitute_variables(prompt.content, context)
        if prompt.api_role == "system":
            system_parts.append(content)
        elif prompt.api_role == "user":
            user_messages.append(content)

    system_prompt = "\n\n".join(system_parts) if system_parts else ""
    if not user_messages:
        user_messages = [json.dumps(context, default=str)]

    # If context includes _documents, prepend document content blocks
    # to the first user message. This sends PDFs/images to Claude as
    # native document content blocks alongside the text prompt.
    if "_documents" in context and context["_documents"]:
        doc_blocks = []
        for doc in context["_documents"]:
            doc_blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": doc.get("media_type", "application/pdf"),
                    "data": doc["data"],
                },
            })
        # Convert first user message from string to content block array
        first_msg = user_messages[0] if user_messages else ""
        user_messages[0] = doc_blocks + [{"type": "text", "text": first_msg}]

    return system_prompt, user_messages


# Any top-level string value larger than this many bytes is replaced in
# the logged input with a stub {elided, bytes, preview}. Sized to hold
# a generous prompt/template but catch anything PDF-sized.
_LARGE_FIELD_BYTES = 8192


def _effective_write_mode(
    write_mode: Literal["auto", "log_only", "write"],
    channel: str,
    mock_blocked: bool,
) -> tuple[Literal["write", "log_only"], str]:
    """Resolve the write gate to a concrete (mode, reason) pair.

    Precedence, from strongest to weakest:
      1. MockContext.target_blocks — an explicit block always wins. Used
         by validation/test runs to guarantee no side effects regardless
         of channel or explicit write_mode.
      2. Caller-supplied `write_mode`: "log_only" and "write" are both
         explicit overrides with well-defined reasons.
      3. "auto" mode: write iff channel is champion (the only production
         channel), log-only for every other channel.

    The returned reason string is stashed in the target_writes audit
    record so operators can answer "why didn't this write?" without
    re-deriving the logic.
    """
    if mock_blocked:
        return "log_only", "mock_target_block"
    if write_mode == "log_only":
        return "log_only", "write_mode=log_only"
    if write_mode == "write":
        return "write", "write_mode=write"
    # write_mode == "auto" — channel-gated.
    if channel == "champion":
        return "write", "auto_channel=champion"
    return "log_only", f"auto_channel={channel}"


# ══════════════════════════════════════════════════════════════
# WIRING DSL — reference parsing and resolution
# ══════════════════════════════════════════════════════════════
# A wiring reference is a string that describes how one field in a
# source binding (input resolution) or target payload field (output
# write) gets its value. Four kinds:
#
#   input.<dotted.path[i]>
#       Pull a value from the unit's own input dict.
#   output.<dotted.path[i]>
#       Pull a value from the unit's own structured output (target
#       payload only — sources are resolved before output exists).
#   const:<literal>
#       Bake a literal in. The value is the part after the colon.
#   fetch:<connector>/<method>(input.<field>)
#       Resolve via a registered connector. Sources only — payloads
#       can't fetch.
#
# Path grammar: dotted keys + bracketed integer indices,
# e.g. `documents[0].kind`. No JSONPath, no arithmetic, no conditionals.

# Sentinel for "the path didn't resolve in the supplied scope." Distinct
# from None (which is a legitimate value a path can resolve to).
_MISSING = object()


@dataclass(frozen=True)
class _ParsedReference:
    """Typed result of parsing a wiring DSL reference string.

    Only the fields relevant to `kind` are populated:
      kind='input' | 'output' → path
      kind='const'            → value
      kind='fetch'            → connector, method, arg_path
                                (arg_path is the dotted path inside input.*)
    """
    kind: str  # 'input' | 'output' | 'const' | 'fetch'
    raw: str
    path: Optional[str] = None
    value: Optional[str] = None
    connector: Optional[str] = None
    method: Optional[str] = None
    arg_path: Optional[str] = None


# Pre-compiled to keep the parse hot path cheap.
_FETCH_RE = re.compile(
    r"^fetch:(?P<connector>[A-Za-z0-9_\-]+)/(?P<method>[A-Za-z0-9_]+)"
    r"\(input\.(?P<arg>[A-Za-z0-9_.\[\]]+)\)$"
)
_BRACKET_INDEX_RE = re.compile(r"\[(\d+)\]")


def _parse_reference(ref: str) -> _ParsedReference:
    """Parse a wiring DSL reference string. Raises ValueError on malformed input."""
    if not isinstance(ref, str):
        raise ValueError(f"reference must be a string, got {type(ref).__name__}")
    if ref.startswith("input."):
        return _ParsedReference(kind="input", raw=ref, path=ref[len("input."):])
    if ref.startswith("output."):
        return _ParsedReference(kind="output", raw=ref, path=ref[len("output."):])
    if ref.startswith("const:"):
        return _ParsedReference(kind="const", raw=ref, value=ref[len("const:"):])
    m = _FETCH_RE.match(ref)
    if m:
        return _ParsedReference(
            kind="fetch", raw=ref,
            connector=m.group("connector"),
            method=m.group("method"),
            arg_path=m.group("arg"),
        )
    raise ValueError(
        f"Unknown reference shape: {ref!r}. Expected one of: "
        "'input.<path>', 'output.<path>', 'const:<value>', "
        "'fetch:<connector>/<method>(input.<field>)'."
    )


def _walk_path(obj: Any, path: str) -> Any:
    """Walk a dotted+indexed path into a dict/list. Returns _MISSING if any segment is absent.

    Examples:
      _walk_path({"a": {"b": 1}}, "a.b") -> 1
      _walk_path({"docs": [{"k": "x"}]}, "docs[0].k") -> "x"
      _walk_path({}, "a.b") -> _MISSING
    """
    if not path:
        return obj
    # Normalize bracketed indices into dotted segments.
    norm = _BRACKET_INDEX_RE.sub(r".\1", path)
    cursor = obj
    for part in norm.split("."):
        if part == "":
            continue
        if isinstance(cursor, dict):
            if part in cursor:
                cursor = cursor[part]
            else:
                return _MISSING
        elif isinstance(cursor, list):
            try:
                idx = int(part)
            except ValueError:
                return _MISSING
            if 0 <= idx < len(cursor):
                cursor = cursor[idx]
            else:
                return _MISSING
        else:
            # Hit a leaf before the path ended.
            return _MISSING
    return cursor


async def _resolve_reference(
    parsed: _ParsedReference,
    scopes: dict[str, Any],
    connector_fetch: Optional[Callable[..., Any]] = None,
) -> Any:
    """Resolve a parsed reference against the supplied scopes.

    `scopes` is a bag like `{"input": <input_data>, "output": <output_data>}`.
    Either key may be absent; missing scope is treated like a missing
    path. Returns the resolved value, or _MISSING if the path didn't
    resolve.

    For `fetch:` references, the caller must pass `connector_fetch` —
    an async callable `(connector_name, method, ref_value) -> payload`.
    Source resolution wires this up to the registered ConnectorProvider;
    target payload assembly never passes one (payloads can't fetch).
    """
    if parsed.kind == "const":
        return parsed.value
    if parsed.kind == "input":
        return _walk_path(scopes.get("input", {}), parsed.path)
    if parsed.kind == "output":
        return _walk_path(scopes.get("output", {}), parsed.path)
    if parsed.kind == "fetch":
        if connector_fetch is None:
            raise ValueError(
                f"fetch: reference {parsed.raw!r} requires a connector_fetch "
                "callable (only valid in source resolution, not target payloads)."
            )
        arg_value = _walk_path(scopes.get("input", {}), parsed.arg_path)
        if arg_value is _MISSING:
            return _MISSING
        return await connector_fetch(parsed.connector, parsed.method, arg_value)
    raise ValueError(f"Unsupported reference kind: {parsed.kind!r}")


def _build_target_payload(
    field_rows: list[dict[str, Any]],
    input_data: dict[str, Any],
    output: dict[str, Any],
) -> dict[str, Any]:
    """Assemble a write_target's payload dict from its target_payload_field rows.

    Each row contributes one key to the returned dict. References may
    be `input.*`, `output.*`, or `const:*` — `fetch:` is rejected
    (payloads can't fetch). Missing-value handling per row:
      required=True  → raise ValueError (caller turns into TargetWriteError)
      required=False → omit the field

    Synchronous: target payloads never need async work.
    """
    payload: dict[str, Any] = {}
    sorted_rows = sorted(field_rows, key=lambda r: r.get("execution_order", 1))
    for row in sorted_rows:
        payload_field = row["payload_field"]
        reference = row["reference"]
        required = row.get("required", True)
        parsed = _parse_reference(reference)
        if parsed.kind == "fetch":
            raise ValueError(
                f"target_payload_field '{payload_field}' has fetch: reference "
                f"{reference!r}; only input.*, output.*, const:* are allowed."
            )
        if parsed.kind == "const":
            payload[payload_field] = parsed.value
            continue
        if parsed.kind == "input":
            value = _walk_path(input_data, parsed.path)
        else:  # 'output'
            value = _walk_path(output, parsed.path)
        if value is _MISSING:
            if required:
                raise ValueError(
                    f"target_payload_field '{payload_field}' (reference="
                    f"{reference!r}) could not be resolved against the "
                    f"unit's input/output."
                )
            continue
        payload[payload_field] = value
    return payload


def _redact_input_for_log(
    context: Optional[dict],
) -> tuple[Optional[dict], Optional[dict]]:
    """Strip bulky fields from a logged context so the decision row stays
    readable. Returns (sanitized_context, redaction_summary).

    Two patterns are handled:
      1. `_documents` — Verity protocol key (see _assemble_prompts) whose
         entries carry base64 PDF/image bytes. Each entry with a `data`
         field is replaced by a reference stub
         {filename, media_type, bytes, elided}.
      2. Any other top-level string value over _LARGE_FIELD_BYTES is
         replaced with {elided, bytes, preview}.

    When nothing is elided the original dict is returned unchanged and
    the summary is None.
    """
    if not isinstance(context, dict):
        return context, None

    total_bytes = 0
    fields: list[str] = []
    sanitized = dict(context)  # shallow copy, top-level mutation only

    # _documents protocol key — strip per-entry base64 bytes.
    docs = sanitized.get("_documents")
    if isinstance(docs, list) and docs:
        new_docs = []
        doc_elided = False
        for doc in docs:
            if isinstance(doc, dict) and isinstance(doc.get("data"), str):
                size = len(doc["data"])
                total_bytes += size
                new_docs.append({
                    "filename": doc.get("filename") or doc.get("name"),
                    "media_type": doc.get("media_type"),
                    "bytes": size,
                    "elided": True,
                })
                doc_elided = True
            else:
                new_docs.append(doc)
        if doc_elided:
            sanitized["_documents"] = new_docs
            fields.append("_documents")

    # Oversized top-level strings.
    for k, v in list(sanitized.items()):
        if k == "_documents":
            continue
        if isinstance(v, str) and len(v) > _LARGE_FIELD_BYTES:
            total_bytes += len(v)
            sanitized[k] = {
                "elided": True,
                "bytes": len(v),
                "preview": v[:80],
            }
            fields.append(k)

    if not fields:
        return context, None

    summary: dict[str, Any] = {
        "fields": fields,
        "total_bytes_elided": total_bytes,
    }
    if "_documents" in fields and isinstance(sanitized.get("_documents"), list):
        summary["documents_elided"] = sum(
            1 for d in sanitized["_documents"]
            if isinstance(d, dict) and d.get("elided")
        )
    return sanitized, summary


def _substitute_variables(template: str, context: dict[str, Any]) -> str:
    """Replace {{variable}} placeholders with context values."""
    result = template
    for key, value in context.items():
        placeholder = "{{" + key + "}}"
        if placeholder in result:
            if isinstance(value, (dict, list)):
                result = result.replace(placeholder, json.dumps(value, default=str, indent=2))
            else:
                result = result.replace(placeholder, str(value))
    return result


def _evaluate_condition(condition: dict, context: dict) -> bool:
    """Evaluate a condition_logic dict against context."""
    for key, value in condition.items():
        if key == "include":
            continue
        ctx_key = key.replace("if_", "")
        if ctx_key in context and context[ctx_key] != value:
            return False
    return True


def _build_tool_definitions(tools) -> list[dict] | None:
    """Convert ToolAuthorization list into Claude API tool format."""
    if not tools:
        return None
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in tools
    ]


def _build_api_params(
    inference_config, system_prompt, messages, tools=None, tool_choice=None,
) -> dict:
    """Build kwargs for anthropic client.messages.create().
    Passes through extended_params for thinking, caching, etc.
    """
    params = {
        "model": inference_config.model_name,
        "messages": messages,
        "max_tokens": inference_config.max_tokens or 4096,
    }
    if system_prompt:
        params["system"] = system_prompt
    if inference_config.temperature is not None:
        params["temperature"] = float(inference_config.temperature)
    if inference_config.top_p is not None:
        params["top_p"] = float(inference_config.top_p)
    if inference_config.top_k is not None:
        params["top_k"] = int(inference_config.top_k)
    if inference_config.stop_sequences:
        params["stop_sequences"] = inference_config.stop_sequences
    if tools:
        params["tools"] = tools
    if tool_choice:
        params["tool_choice"] = tool_choice
    if inference_config.extended_params:
        for key, value in inference_config.extended_params.items():
            if key not in params:
                params[key] = value
    return params


def _serialize_content_blocks(content) -> list[dict]:
    """Serialize Claude response content blocks for message_history storage."""
    result = []
    for block in content:
        if hasattr(block, 'text'):
            result.append({"type": "text", "text": block.text})
        elif hasattr(block, 'type') and block.type == "tool_use":
            result.append({
                "type": "tool_use", "id": block.id,
                "name": block.name, "input": block.input,
            })
    return result


def _get_db_mock_response(tool_name: str, authorized_tools: list) -> dict:
    """Get mock response from a tool's DB-registered mock_responses."""
    tool_def = next((t for t in authorized_tools if t.name == tool_name), None)
    if tool_def and hasattr(tool_def, 'mock_responses') and tool_def.mock_responses:
        # Return the 'default' scenario response
        if isinstance(tool_def.mock_responses, dict):
            return tool_def.mock_responses.get("default", {"mock": True, "tool": tool_name})
    return {"mock": True, "tool": tool_name, "message": "No mock response configured"}


def _extract_text(response) -> str:
    """Extract text content from a Claude response."""
    parts = []
    for block in response.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "\n".join(parts)


def _try_parse_json(text: str) -> dict | str:
    """Try to parse text as JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(json_lines).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return {"raw_output": text}


def _is_valid_json_schema(properties: dict) -> bool:
    """Check if output_schema properties are valid JSON Schema format.

    Valid:   {"field": {"type": "string"}} — each property is a dict with "type"
    Invalid: {"field": "string"} — shorthand, not valid JSON Schema

    We only use tool_choice structured output when the schema is valid,
    because the Claude API validates it against JSON Schema draft 2020-12.
    """
    if not properties:
        return False
    for key, value in properties.items():
        if not isinstance(value, dict):
            return False  # Value is a string like "number" — not valid JSON Schema
        if "type" not in value and "$ref" not in value and "anyOf" not in value:
            return False
    return True


def _now_ms() -> int:
    return int(time.time() * 1000)


def _payload_size(payload: Any) -> int:
    """Approximate size of a resolved source payload (bytes or characters).

    Used for decision log / telemetry. Cheap approximation — for strings
    returns character count; for bytes returns byte count; for anything
    else falls back to the length of its JSON representation.
    """
    if payload is None:
        return 0
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return len(payload)
    if isinstance(payload, str):
        return len(payload)
    try:
        return len(json.dumps(payload, default=str))
    except (TypeError, ValueError):
        return -1  # unmeasurable — recorded as such in the audit trail


def _ref_summary(ref: Any) -> str:
    """Compact string rep of a source reference for logs and audit rows.

    Refs are typically short strings (doc ids, URIs), but can be dicts
    (composite refs). Truncate to keep decision logs readable.
    """
    if isinstance(ref, str):
        return ref if len(ref) <= 120 else ref[:117] + "..."
    try:
        s = json.dumps(ref, default=str)
    except (TypeError, ValueError):
        s = str(ref)
    return s if len(s) <= 120 else s[:117] + "..."


def _mcp_error(
    tool_name: str,
    tool_input: dict,
    call_order: int,
    transport: str,
    server_name: Optional[str],
    message: str,
) -> dict[str, Any]:
    """Build an error-shaped tool_calls_made entry for an MCP dispatch failure.

    Same shape as successful MCP results so the decision log and audit UI
    don't need a special case for failed MCP calls. `error=True` and
    `output_data.error` both signal the failure; `transport` and
    `mcp_server_name` are preserved so the audit shows which server failed.
    """
    return {
        "tool_name": tool_name,
        "call_order": call_order,
        "input_data": tool_input,
        "output_data": {"error": message},
        "error": True,
        "transport": transport,
        "mcp_server_name": server_name,
    }


def _builtin_error(
    tool_name: str,
    tool_input: dict,
    call_order: int,
    message: str,
) -> dict[str, Any]:
    """Build an error-shaped tool_calls_made entry for a verity_builtin failure.

    Used for delegate_to_agent validation / authorization / depth / child-run
    errors. The error propagates back to Claude as an is_error=True
    tool_result; the agent decides whether to retry with different args,
    fall back to its own reasoning, or surface the issue.
    """
    return {
        "tool_name": tool_name,
        "call_order": call_order,
        "input_data": tool_input,
        "output_data": {"error": message},
        "error": True,
        "transport": "verity_builtin",
    }
