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
  1. Fully live (mock=None)                      — LLM + tools both real
  2. Live LLM + caller-supplied tool mocks       — MockContext(tool_responses={...})
  3. Live LLM + all tools from DB mock registry — MockContext(mock_all_tools=True)

For deterministic no-LLM execution (demos, cheap tests), use the separate
FixtureEngine in runtime/fixture_backend.py — it's not a mode of this
engine. LLM-level mocking was retired in Phase 3d; see the FixtureEngine
docstring for the replacement story.

All modes write a DecisionLogCreate row with the same 31-column shape.
mock_mode=True is set whenever any caller-supplied mocking was active.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Optional
from uuid import UUID

import anthropic

logger = logging.getLogger(__name__)

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

        LLM-level mocking was retired in Phase 3d — there is no longer a
        "canned LLM response" path in this engine. Callers that want
        deterministic no-LLM execution use FixtureEngine, which is a
        separate class entirely (see runtime/fixture_backend.py).

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
                "via this engine, or use FixtureEngine (runtime/fixture_backend.py) "
                "for deterministic no-LLM execution with pre-built fixtures."
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
    ) -> dict[str, Any]:
        """Gateway for all tool calls.

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
        return await self._execute_real_tool(tool_name, tool_input, call_order, tool_def)

    async def _execute_real_tool(
        self, tool_name: str, tool_input: dict, call_order: int, tool_def
    ) -> dict[str, Any]:
        """Dispatch a real (non-mocked) tool call.

        Routes based on tool_def.transport:
          - 'python_inprocess' (default) — look up `tool_name` in the
            runtime's tool_implementations dict and call the Python callable.
          - 'mcp_stdio' | 'mcp_sse' | 'mcp_http' — forward through MCPClient
            to the server identified by tool_def.mcp_server_name, addressing
            the remote tool as tool_def.mcp_tool_name (falling back to
            tool_name if the remote name matches Verity's name).

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

        return {
            "tool_name": tool_name,
            "call_order": call_order,
            "input_data": tool_input,
            "output_data": {
                "error": f"Unknown tool transport {transport!r} on '{tool_name}'. "
                         f"Expected python_inprocess, mcp_stdio, mcp_sse, or mcp_http."
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
    # AGENT EXECUTION (multi-turn tool loop)
    # ══════════════════════════════════════════════════════════

    async def run_agent(
        self,
        agent_name: str,
        context: dict[str, Any],

        channel: str = "production",
        pipeline_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        step_name: Optional[str] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
    ) -> ExecutionResult:
        """Execute an agent: resolve config, assemble prompts, run the agentic loop.

        `mock` controls tool-level mocking only (see MockContext).
        LLM-level mocking was retired in Phase 3d — use FixtureEngine
        for deterministic no-LLM execution.
        """
        start_ms = _now_ms()
        logger.info("Agent execution starting: %s (step=%s, tool_mocks=%s)",
                     agent_name, step_name or "standalone", mock is not None)
        config = await self.registry.get_agent_config(agent_name)
        system_prompt, user_messages = _assemble_prompts(config.prompts, context)
        tools = _build_tool_definitions(config.tools)

        try:
            messages = [{"role": "user", "content": msg} for msg in user_messages]
            total_input_tokens = 0
            total_output_tokens = 0
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

                # Track tokens (0 for mock responses)
                if hasattr(response, 'usage'):
                    total_input_tokens += response.usage.input_tokens
                    total_output_tokens += response.usage.output_tokens

                # Store assistant response in message history
                if hasattr(response, 'content'):
                    message_history.append({
                        "role": "assistant",
                        "content": _serialize_content_blocks(response.content),
                    })

                if response.stop_reason == "tool_use":
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            # Check authorization
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
                            tool_record = await self._gateway_tool_call(
                                block.name, block.input, config.tools,
                                mock, len(tool_calls_made) + 1,
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

            output_text = _extract_text(response)
            output = _try_parse_json(output_text)
            duration_ms = _now_ms() - start_ms
            # With LLM mocking removed, mock_mode in the log reflects
            # "any form of caller-supplied mocking was active" — which
            # today means tool_responses or mock_all_tools.
            is_mocked = mock is not None

            log_result = await self._log_decision(
                entity_type=EntityType.AGENT, config=config, context=context,
                output=output, output_text=output_text,
                tool_calls_made=tool_calls_made, message_history=message_history,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                duration_ms=duration_ms, 
                channel=channel, pipeline_run_id=pipeline_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="complete", mock_mode=is_mocked,
                execution_context_id=execution_context_id,
            )

            logger.info("Agent execution complete: %s (%dms, %d tool calls, %d+%d tokens)",
                         agent_name, duration_ms, len(tool_calls_made),
                         total_input_tokens, total_output_tokens)
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
            log_result = await self._log_decision(
                entity_type=EntityType.AGENT, config=config, context=context,
                output={}, output_text="", tool_calls_made=[], message_history=[],
                total_input_tokens=0, total_output_tokens=0,
                duration_ms=duration_ms, 
                channel=channel, pipeline_run_id=pipeline_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="failed", error_message=str(e),
                execution_context_id=execution_context_id,
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
        pipeline_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        step_name: Optional[str] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
    ) -> ExecutionResult:
        """Execute a task with single-turn structured output and mock support."""
        logger.info("Task execution starting: %s (step=%s, mock=%s)",
                     task_name, step_name or "standalone", mock is not None)
        start_ms = _now_ms()
        config = await self.registry.get_task_config(task_name)
        system_prompt, user_messages = _assemble_prompts(config.prompts, input_data)

        try:
            # Build messages — tasks are single-turn structured output via Claude.
            # LLM-level mocking was retired in Phase 3d; use FixtureEngine for
            # deterministic no-LLM task execution.
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

            # Extract output
            if tool_choice and response.content:
                output = {}
                for block in response.content:
                    if block.type == "tool_use" and block.name == "structured_output":
                        output = block.input
                        break
                output_text = json.dumps(output)
            else:
                output_text = _extract_text(response)
                output = _try_parse_json(output_text)

            duration_ms = _now_ms() - start_ms

            log_result = await self._log_decision(
                entity_type=EntityType.TASK, config=config, context=input_data,
                output=output, output_text=output_text,
                tool_calls_made=[], message_history=[],
                total_input_tokens=response.usage.input_tokens,
                total_output_tokens=response.usage.output_tokens,
                duration_ms=duration_ms, 
                channel=channel, pipeline_run_id=pipeline_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="complete",
                execution_context_id=execution_context_id,
            )

            logger.info("Task execution complete: %s (%dms, %d+%d tokens)",
                         task_name, duration_ms,
                         response.usage.input_tokens, response.usage.output_tokens)
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
                channel=channel, pipeline_run_id=pipeline_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth, step_name=step_name,
                status="failed", error_message=str(e),
                execution_context_id=execution_context_id,
            )
            return ExecutionResult(
                decision_log_id=log_result["decision_log_id"],
                entity_type="task", entity_name=task_name,
                version_label=config.version_label,
                output={}, duration_ms=duration_ms,
                status="failed", error_message=str(e),
            )

    # ══════════════════════════════════════════════════════════
    # TOOL EXECUTION (standalone, no LLM — for pipeline steps)
    # ══════════════════════════════════════════════════════════

    async def run_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],

        channel: str = "production",
        pipeline_run_id: Optional[UUID] = None,
        parent_decision_id: Optional[UUID] = None,
        decision_depth: int = 0,
        step_name: Optional[str] = None,
        mock: Optional[MockContext] = None,
        execution_context_id: Optional[UUID] = None,
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
                pipeline_run_id=pipeline_run_id,
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
                application=self.application,
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
        pipeline_run_id: Optional[UUID],
        parent_decision_id: Optional[UUID],
        decision_depth: int,
        step_name: Optional[str],
        status: str,
        error_message: Optional[str] = None,
        mock_mode: bool = False,
        execution_context_id: Optional[UUID] = None,
        run_purpose: str = "production",
        reproduced_from_decision_id: Optional[UUID] = None,
    ) -> dict:
        """Create a decision log entry with full snapshot."""
        snapshot = config.get_inference_snapshot() if hasattr(config, 'get_inference_snapshot') else {}

        # Determine version_id based on entity type
        if entity_type == EntityType.AGENT:
            version_id = config.agent_version_id
        elif entity_type == EntityType.TASK:
            version_id = config.task_version_id
        else:
            version_id = getattr(config, 'id', None) or UUID(int=0)

        return await self.decisions.log_decision(DecisionLogCreate(
            entity_type=entity_type,
            entity_version_id=version_id,
            prompt_version_ids=[p.prompt_version_id for p in config.prompts] if hasattr(config, 'prompts') else [],
            inference_config_snapshot=snapshot.model_dump() if hasattr(snapshot, 'model_dump') else snapshot,
            channel=DeploymentChannel(channel),
            mock_mode=mock_mode,
            pipeline_run_id=pipeline_run_id,
            parent_decision_id=parent_decision_id,
            decision_depth=decision_depth,
            step_name=step_name,
            execution_context_id=execution_context_id,
            run_purpose=RunPurpose(run_purpose),
            reproduced_from_decision_id=reproduced_from_decision_id,
            input_summary=str(context)[:500],
            input_json=context if isinstance(context, dict) else None,
            output_json=output if isinstance(output, dict) else None,
            output_summary=output_text[:500] if output_text else None,
            reasoning_text=(output.get("reasoning", output_text[:1000]) if isinstance(output, dict) else output_text[:1000]) if output_text else None,
            risk_factors=output.get("risk_factors") if isinstance(output, dict) else None,
            confidence_score=output.get("confidence") if isinstance(output, dict) else None,
            model_used=config.inference_config.model_name if hasattr(config, 'inference_config') else None,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            duration_ms=duration_ms,
            tool_calls_made=tool_calls_made if tool_calls_made else None,
            message_history=message_history if message_history else None,
            application=self.application,
            status=status,
            error_message=error_message,
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
