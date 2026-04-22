"""SDK-backed execution engine — scaffold.

This module is the Phase 3 replacement for runtime.engine.ExecutionEngine's
custom agentic loop. It delegates the loop, tool dispatch, and message
management to Anthropic's official Claude Agent SDK (`claude-agent-sdk`),
while preserving Verity's governance wrappers:
  - prompt assembly from registry prompt_version records
  - decision logging (31-column DecisionLogCreate)
  - version-pinning (registry stays the source of configs)
  - tool mocking via MockContext.tool_responses

What it does NOT support, by design:
  - MockContext.llm_responses (LLM-level replay).
    The SDK does not expose a monkey-patchable LLM hook; replicating that
    capability would require writing a custom Transport subclass. Instead,
    the FixtureEngine (runtime/fixture_backend.py, Phase 3d) provides
    deterministic no-LLM execution for demos and tests; live and real-LLM
    test paths go through this SDK engine. Legacy MockContext.llm_responses
    plumbing is removed wholesale in Phase 3e.

Scaffolding only at this stage — every public method raises
NotImplementedError. Phase 3b fills in run_agent; Phase 3c fills in run_task.
"""

from __future__ import annotations

from typing import Any, Callable, Optional
from uuid import UUID

from verity.contracts.decision import ExecutionResult
from verity.contracts.mock import MockContext
from verity.governance.registry import Registry
from verity.runtime.decisions_writer import DecisionsWriter


class SdkEngine:
    """Claude Agent SDK-backed execution engine.

    Same constructor shape as runtime.engine.ExecutionEngine so the Runtime
    facade can swap between them without other wiring changes. Same public
    method names so callers don't change.
    """

    def __init__(
        self,
        registry: Registry,
        decisions: DecisionsWriter,
        anthropic_api_key: str,
        tool_implementations: Optional[dict[str, Callable]] = None,
        application: str = "default",
    ):
        self.registry = registry
        self.decisions = decisions
        self.anthropic_api_key = anthropic_api_key
        self.application = application
        # Same dict ExecutionEngine uses. UW's register_tool_implementation()
        # populates this at app startup; both engines read from the same dict
        # if they share a reference.
        self.tool_implementations: dict[str, Callable] = (
            tool_implementations if tool_implementations is not None else {}
        )

    # ── TOOL REGISTRATION ────────────────────────────────────────

    def register_tool_implementation(self, tool_name: str, func: Callable) -> None:
        """Register a Python callable as the implementation of a named tool.

        Same semantics as ExecutionEngine.register_tool_implementation(). The
        tool's input_schema / output_schema / mock settings come from the
        registry at execution time; this just provides the Python body to
        dispatch when the agent calls the tool by name.
        """
        self.tool_implementations[tool_name] = func

    # ── PUBLIC EXECUTION API ─────────────────────────────────────

    async def run_agent(
        self,
        agent_name: str,
        context: dict[str, Any],
        channel: str = "production",
        pipeline_run_id: Optional[UUID] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
        step_name: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute an agent via Claude Agent SDK. Implemented in Phase 3b."""
        raise NotImplementedError(
            "SdkEngine.run_agent is scaffolded in Phase 3a and implemented in Phase 3b. "
            "Use runtime.engine.ExecutionEngine for now."
        )

    async def run_task(
        self,
        task_name: str,
        input_data: dict[str, Any],
        channel: str = "production",
        pipeline_run_id: Optional[UUID] = None,
        mock: Optional[MockContext] = None,
        stream: bool = False,
        execution_context_id: Optional[UUID] = None,
        step_name: Optional[str] = None,
    ) -> ExecutionResult:
        """Execute a task via Claude Agent SDK. Implemented in Phase 3c."""
        raise NotImplementedError(
            "SdkEngine.run_task is scaffolded in Phase 3a and implemented in Phase 3c. "
            "Use runtime.engine.ExecutionEngine for now."
        )


__all__ = ["SdkEngine"]
