"""FixtureEngine — deterministic, zero-LLM execution for demos and cheap tests.

Purpose
-------
When running the UW demo with Claude credits turned off, or running a test
suite on a laptop that can't reach api.anthropic.com, we still want:
  - The full governance trail (a row in agent_decision_log per run)
  - Real config resolution (so version_ids in the log are correct)
  - Real pipeline orchestration (step ordering, parallel groups)
  - Honest identification in the log that "this wasn't a real LLM call"

FixtureEngine provides that. It has the same public shape as
runtime.engine.ExecutionEngine (same constructor, same run_agent / run_task /
register_tool_implementation signatures), so `PipelineExecutor` or any
caller can drive it without caring which engine it received.

How it works
------------
Each run_agent / run_task call:
  1. Resolves the entity's config through the governance registry. This
     is the version-pinning seam — even fixture runs go through it so
     the decision log's entity_version_id and prompt_version_ids are real.
  2. Looks up a `Fixture` in the engine's fixtures dict, keyed first by
     step_name (pipeline mode) then by entity_name. Raises loudly if
     neither key is present.
  3. Writes a DecisionLogCreate row shaped like a real run — same 31
     columns populated, but `mock_mode=True` and tokens/duration either
     zero or whatever the fixture declares.
  4. Returns an ExecutionResult built from the fixture.

What it does NOT do
-------------------
  - Call Claude. Ever. That's the point.
  - Dispatch registered tool_implementations. Fixtures provide canned
    outputs directly; tool_calls listed in the fixture go into the
    decision log for audit but are never executed.
  - Run an agentic loop. There's no loop to run.

Replaces the now-removed `MockContext.llm_responses` pattern from the
original custom engine (see runtime/engine.py pre-Phase-3d). That pattern
pretended mock LLM responses were real LLM responses; FixtureEngine is
honest: it's a separate engine that logs mock_mode=True and doesn't
pretend to be anything else.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from verity.contracts.decision import (
    DecisionLogCreate,
    ExecutionResult,
)
from verity.contracts.enums import DeploymentChannel, EntityType, RunPurpose
from verity.contracts.mock import MockContext
from verity.governance.registry import Registry
from verity.runtime.decisions_writer import DecisionsWriter


@dataclass
class Fixture:
    """Pre-built result for a single agent or task invocation.

    Every field is optional except `output`. The engine fills the
    DecisionLogCreate row by combining the fixture's values with
    metadata from the resolved config (entity_version_id,
    prompt_version_ids, inference_config_snapshot).
    """

    # The structured output the agent/task "returned". Goes into
    # decision_log.output_json and into ExecutionResult.output.
    output: dict[str, Any]

    # Optional: a short text summary of the output (first 500 chars of
    # the output JSON if not provided).
    output_summary: Optional[str] = None

    # Optional: reasoning_text for the decision log. Useful if the
    # fixture wants to show "the agent would have said: ..." text.
    reasoning_text: str = ""

    # Optional extraction-style metadata that gets lifted into the
    # decision log's dedicated columns if the caller wants them visible
    # without diving into output_json.
    confidence_score: Optional[float] = None
    risk_factors: Optional[Any] = None

    # Optional: fake tool calls to record. Each entry should look like
    # {tool_name, call_order, input_data, output_data, mock_mode}.
    # The tools are NOT actually dispatched — this is display-only.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    # Optional: fake message history for audit-trail completeness.
    # Usually empty for fixtures; the governance UI will just show
    # "(fixture — no LLM conversation captured)" when empty.
    message_history: list[dict[str, Any]] = field(default_factory=list)

    # Optional: how long to claim the "execution" took. Default 0.
    duration_ms: int = 0

    # Optional: token counts to claim. Default 0/0 since no LLM ran.
    input_tokens: int = 0
    output_tokens: int = 0


class FixtureNotFound(Exception):
    """Raised when FixtureEngine is asked to run an entity/step without a matching fixture.

    Loud failure by design: if you wire FixtureEngine into a run, every
    run_agent / run_task call it receives must have a fixture, otherwise
    you've probably made a wiring mistake.
    """

    pass


class FixtureEngine:
    """Zero-LLM execution engine that returns pre-built fixtures.

    Constructor shape matches ExecutionEngine so the Runtime facade or
    PipelineExecutor can swap them without any other rewiring:

        FixtureEngine(registry, decisions, fixtures, application="uw_demo")
        ExecutionEngine(registry, decisions, anthropic_api_key, application="uw_demo")

    The `fixtures` arg is a dict keyed by step_name OR entity_name
    (tried in that order). Values are Fixture instances or plain dicts
    with the same fields (auto-coerced).
    """

    def __init__(
        self,
        registry: Registry,
        decisions: DecisionsWriter,
        fixtures: dict[str, Fixture | dict[str, Any]],
        application: str = "default",
    ):
        self.registry = registry
        self.decisions = decisions
        self.application = application
        # Normalize: accept dicts or Fixture instances interchangeably.
        self.fixtures: dict[str, Fixture] = {
            key: value if isinstance(value, Fixture) else Fixture(**value)
            for key, value in fixtures.items()
        }
        # Kept for interface compatibility with ExecutionEngine. Tools
        # registered here are never dispatched by FixtureEngine — the
        # fixture's output is returned directly — but callers that
        # register_tool_implementation on any engine (e.g., UW's startup
        # code) shouldn't have to know which engine they have.
        self.tool_implementations: dict[str, Callable] = {}

    # ── TOOL REGISTRATION (no-op for fixtures) ────────────────────

    def register_tool_implementation(self, tool_name: str, func: Callable) -> None:
        """Accept tool registrations for interface compatibility — but never dispatch them.

        Fixtures provide their outputs directly; there are no live tool
        calls to dispatch. This method exists so callers (e.g., the UW
        startup code that registers ~10 tool implementations) work
        regardless of which engine is active.
        """
        self.tool_implementations[tool_name] = func

    # ── PUBLIC EXECUTION API ─────────────────────────────────────

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
        application: Optional[str] = None,
    ) -> ExecutionResult:
        """Return the fixture for this agent as an ExecutionResult and log the decision.

        Args have the same meaning as ExecutionEngine.run_agent. The
        `mock` and `stream` args are accepted for interface compatibility
        but ignored — fixtures don't need mocking and can't be streamed.
        """
        start_ms = _now_ms()
        config = await self.registry.get_agent_config(agent_name)
        fixture = self._resolve_fixture(step_name, agent_name)
        duration_ms = fixture.duration_ms or (_now_ms() - start_ms)

        log_result = await self._log_decision(
            entity_type=EntityType.AGENT,
            config=config,
            entity_version_id=config.agent_version_id,
            context=context,
            fixture=fixture,
            duration_ms=duration_ms,
            channel=channel,
            pipeline_run_id=pipeline_run_id,
            parent_decision_id=parent_decision_id,
            decision_depth=decision_depth,
            step_name=step_name,
            execution_context_id=execution_context_id,
            application=application,
        )

        return ExecutionResult(
            decision_log_id=log_result["decision_log_id"],
            entity_type="agent",
            entity_name=agent_name,
            version_label=config.version_label,
            output=fixture.output,
            output_summary=_summarize_output(fixture),
            reasoning_text=fixture.reasoning_text,
            confidence_score=fixture.confidence_score,
            risk_factors=fixture.risk_factors,
            tool_calls=fixture.tool_calls,
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            duration_ms=duration_ms,
            status="complete",
        )

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
        application: Optional[str] = None,
    ) -> ExecutionResult:
        """Return the fixture for this task as an ExecutionResult and log the decision."""
        start_ms = _now_ms()
        config = await self.registry.get_task_config(task_name)
        fixture = self._resolve_fixture(step_name, task_name)
        duration_ms = fixture.duration_ms or (_now_ms() - start_ms)

        log_result = await self._log_decision(
            entity_type=EntityType.TASK,
            config=config,
            entity_version_id=config.task_version_id,
            context=input_data,
            fixture=fixture,
            duration_ms=duration_ms,
            channel=channel,
            pipeline_run_id=pipeline_run_id,
            parent_decision_id=parent_decision_id,
            decision_depth=decision_depth,
            step_name=step_name,
            execution_context_id=execution_context_id,
            application=application,
        )

        return ExecutionResult(
            decision_log_id=log_result["decision_log_id"],
            entity_type="task",
            entity_name=task_name,
            version_label=config.version_label,
            output=fixture.output,
            output_summary=_summarize_output(fixture),
            reasoning_text=fixture.reasoning_text,
            confidence_score=fixture.confidence_score,
            risk_factors=fixture.risk_factors,
            tool_calls=fixture.tool_calls,
            input_tokens=fixture.input_tokens,
            output_tokens=fixture.output_tokens,
            duration_ms=duration_ms,
            status="complete",
        )

    # ── INTERNAL HELPERS ─────────────────────────────────────────

    def _resolve_fixture(self, step_name: Optional[str], entity_name: str) -> Fixture:
        """Pick the matching fixture: step_name first (pipeline mode), then entity_name.

        Raises FixtureNotFound if neither key matches. This is a loud
        failure on purpose — if you're running with the FixtureEngine you
        should have provided fixtures for every step/entity that will run.
        """
        if step_name and step_name in self.fixtures:
            return self.fixtures[step_name]
        if entity_name in self.fixtures:
            return self.fixtures[entity_name]
        available = sorted(self.fixtures.keys())
        raise FixtureNotFound(
            f"No fixture found for step_name={step_name!r} or entity_name={entity_name!r}. "
            f"Available fixtures: {available}"
        )

    async def _log_decision(
        self,
        entity_type: EntityType,
        config: Any,
        entity_version_id: UUID,
        context: dict[str, Any],
        fixture: Fixture,
        duration_ms: int,
        channel: str,
        pipeline_run_id: Optional[UUID],
        parent_decision_id: Optional[UUID],
        decision_depth: int,
        step_name: Optional[str],
        execution_context_id: Optional[UUID],
        application: Optional[str] = None,
    ) -> dict:
        """Write a DecisionLogCreate row shaped like a real run but flagged mock_mode=True.

        inference_config_snapshot still reflects the config that *would*
        have been applied (same as a real run). prompt_version_ids are
        still pulled from the resolved config. model_used is the model
        that would have been invoked. Tokens and duration come from the
        fixture (usually zero/zero/small).
        """
        snapshot = (
            config.get_inference_snapshot()
            if hasattr(config, "get_inference_snapshot")
            else {}
        )
        output = fixture.output
        output_summary = _summarize_output(fixture)

        return await self.decisions.log_decision(
            DecisionLogCreate(
                entity_type=entity_type,
                entity_version_id=entity_version_id,
                prompt_version_ids=[p.prompt_version_id for p in config.prompts]
                if hasattr(config, "prompts")
                else [],
                inference_config_snapshot=snapshot.model_dump()
                if hasattr(snapshot, "model_dump")
                else snapshot,
                channel=DeploymentChannel(channel),
                mock_mode=True,
                pipeline_run_id=pipeline_run_id,
                parent_decision_id=parent_decision_id,
                decision_depth=decision_depth,
                step_name=step_name,
                execution_context_id=execution_context_id,
                run_purpose=RunPurpose.PRODUCTION,
                input_summary=str(context)[:500],
                input_json=context if isinstance(context, dict) else None,
                output_json=output if isinstance(output, dict) else None,
                output_summary=output_summary[:500] if output_summary else None,
                reasoning_text=fixture.reasoning_text[:1000]
                if fixture.reasoning_text
                else None,
                risk_factors=fixture.risk_factors,
                confidence_score=fixture.confidence_score,
                model_used=config.inference_config.model_name
                if hasattr(config, "inference_config")
                else None,
                input_tokens=fixture.input_tokens,
                output_tokens=fixture.output_tokens,
                duration_ms=duration_ms,
                tool_calls_made=fixture.tool_calls if fixture.tool_calls else None,
                message_history=fixture.message_history
                if fixture.message_history
                else None,
                application=application or self.application,
                status="complete",
            )
        )


# ── MODULE HELPERS ──────────────────────────────────────────────

def _now_ms() -> int:
    """Current time in milliseconds since the epoch."""
    return int(time.time() * 1000)


def _summarize_output(fixture: Fixture) -> str:
    """Produce a one-line summary of the fixture's output for display."""
    if fixture.output_summary:
        return fixture.output_summary
    try:
        return json.dumps(fixture.output, default=str)
    except (TypeError, ValueError):
        return str(fixture.output)


__all__ = ["Fixture", "FixtureEngine", "FixtureNotFound"]
