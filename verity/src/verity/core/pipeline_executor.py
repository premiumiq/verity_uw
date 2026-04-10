"""Verity Pipeline Executor — orchestrate multi-step agent/task pipelines.

Resolves pipeline steps, executes in dependency order with parallel group
support via asyncio.gather. Each step is a governed Verity execution
(agent or task) sharing a pipeline_run_id for audit trail grouping.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID, uuid4

from verity.core.execution import ExecutionEngine, ExecutionResult
from verity.core.registry import Registry
from verity.utils.logging import pipeline_run_id_var, step_name_var
from verity.models.pipeline import PipelineStep

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result of a single pipeline step."""
    step_name: str
    entity_type: str
    entity_name: str
    status: str  # "complete", "failed", "skipped"
    execution_result: Optional[ExecutionResult] = None
    error_message: Optional[str] = None
    duration_ms: int = 0


@dataclass
class PipelineResult:
    """Result of a full pipeline execution."""
    pipeline_run_id: UUID
    pipeline_name: str
    version_number: int
    steps_completed: list[StepResult] = field(default_factory=list)
    steps_failed: list[StepResult] = field(default_factory=list)
    steps_skipped: list[StepResult] = field(default_factory=list)
    all_steps: list[StepResult] = field(default_factory=list)
    status: str = "complete"  # "complete", "partial", "failed"
    duration_ms: int = 0


class PipelineExecutor:
    """Execute pipelines with dependency resolution and parallel groups."""

    def __init__(self, registry: Registry, execution_engine: ExecutionEngine):
        self.registry = registry
        self.engine = execution_engine

    async def run_pipeline(
        self,
        pipeline_name: str,
        context: dict[str, Any],

        channel: str = "production",
        mock=None,  # Optional MockContext
        execution_context_id=None,  # Optional UUID — links decisions to a business context
    ) -> PipelineResult:
        """Execute a pipeline from its champion version.

        1. Load pipeline champion config
        2. Parse steps into dependency graph
        3. Execute in topological order, with parallel groups via asyncio.gather
        4. Pass accumulated results to downstream steps
        5. Handle error policies per step
        """
        start_ms = _now_ms()
        pipeline_run_id = uuid4()
        pipeline_run_id_var.set(str(pipeline_run_id))

        # Load pipeline config
        pipeline = await self.registry.get_pipeline_by_name(pipeline_name)
        if not pipeline:
            raise ValueError(f"Pipeline '{pipeline_name}' not found")
        if not pipeline.get("steps"):
            raise ValueError(f"Pipeline '{pipeline_name}' has no steps defined")

        steps_json = pipeline["steps"]
        if isinstance(steps_json, str):
            import json
            steps_json = json.loads(steps_json)

        steps = [PipelineStep(**s) if isinstance(s, dict) else s for s in steps_json]
        version_number = pipeline.get("champion_version_number", 1)

        step_names = [s.step_name if isinstance(s, PipelineStep) else s.get("step_name", "?") for s in steps]
        logger.info("Pipeline run starting: %s (run_id=%s, steps=%s, mock=%s)",
                     pipeline_name, str(pipeline_run_id)[:8], step_names, mock is not None)

        # Build execution plan: group by step_order, resolve dependencies
        execution_groups = _build_execution_groups(steps)

        # Accumulated results from completed steps (keyed by step_name)
        accumulated_results: dict[str, StepResult] = {}
        all_steps: list[StepResult] = []
        pipeline_failed = False

        for group in execution_groups:
            if pipeline_failed:
                # Skip remaining groups
                for step in group:
                    result = StepResult(
                        step_name=step.step_name,
                        entity_type=step.entity_type.value,
                        entity_name=step.entity_name,
                        status="skipped",
                        error_message="Pipeline failed at earlier step",
                    )
                    all_steps.append(result)
                continue

            # Check which steps in this group can run (dependencies met, conditions pass)
            runnable = []
            for step in group:
                # Check dependencies
                deps_met = all(
                    dep in accumulated_results and accumulated_results[dep].status == "complete"
                    for dep in step.depends_on
                    if dep not in _get_parallel_groups(steps)  # parallel groups resolve as a unit
                )
                # Check parallel group dependencies
                for dep in step.depends_on:
                    if dep in _get_parallel_groups(steps):
                        group_steps = [s.step_name for s in steps if s.parallel_group == dep]
                        deps_met = deps_met and all(
                            sn in accumulated_results and accumulated_results[sn].status in ("complete", "skipped")
                            for sn in group_steps
                        )

                if not deps_met:
                    result = StepResult(
                        step_name=step.step_name,
                        entity_type=step.entity_type.value,
                        entity_name=step.entity_name,
                        status="skipped",
                        error_message="Dependencies not met",
                    )
                    accumulated_results[step.step_name] = result
                    all_steps.append(result)
                    continue

                # Check condition
                if step.condition and not _evaluate_step_condition(step.condition, accumulated_results, context):
                    result = StepResult(
                        step_name=step.step_name,
                        entity_type=step.entity_type.value,
                        entity_name=step.entity_name,
                        status="skipped",
                        error_message="Condition not met",
                    )
                    accumulated_results[step.step_name] = result
                    all_steps.append(result)
                    continue

                runnable.append(step)

            if not runnable:
                continue

            # Execute group: if multiple steps, run in parallel
            if len(runnable) == 1:
                result = await self._execute_step(
                    runnable[0], context, accumulated_results,
                    channel, pipeline_run_id, mock, execution_context_id,
                )
                accumulated_results[runnable[0].step_name] = result
                all_steps.append(result)

                if result.status == "failed" and runnable[0].error_policy == "fail_pipeline":
                    pipeline_failed = True
            else:
                # Parallel execution
                tasks = [
                    self._execute_step(
                        step, context, accumulated_results,
                        channel, pipeline_run_id, mock,
                    )
                    for step in runnable
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                for step, result in zip(runnable, results):
                    if isinstance(result, Exception):
                        step_result = StepResult(
                            step_name=step.step_name,
                            entity_type=step.entity_type.value,
                            entity_name=step.entity_name,
                            status="failed",
                            error_message=str(result),
                        )
                    else:
                        step_result = result

                    accumulated_results[step.step_name] = step_result
                    all_steps.append(step_result)

                    if step_result.status == "failed" and step.error_policy == "fail_pipeline":
                        pipeline_failed = True

        # Determine overall status
        duration_ms = _now_ms() - start_ms
        completed = [s for s in all_steps if s.status == "complete"]
        failed = [s for s in all_steps if s.status == "failed"]
        skipped = [s for s in all_steps if s.status == "skipped"]

        if pipeline_failed:
            overall_status = "failed"
        elif failed:
            overall_status = "partial"
        else:
            overall_status = "complete"

        logger.info("Pipeline run complete: %s (run_id=%s, status=%s, %dms, "
                     "completed=%d, failed=%d, skipped=%d)",
                     pipeline_name, str(pipeline_run_id)[:8], overall_status,
                     duration_ms, len(completed), len(failed), len(skipped))

        return PipelineResult(
            pipeline_run_id=pipeline_run_id,
            pipeline_name=pipeline_name,
            version_number=version_number,
            steps_completed=completed,
            steps_failed=failed,
            steps_skipped=skipped,
            all_steps=all_steps,
            status=overall_status,
            duration_ms=duration_ms,
        )

    async def _execute_step(
        self,
        step: PipelineStep,
        context: dict[str, Any],
        accumulated_results: dict[str, StepResult],
        channel: str,
        pipeline_run_id: UUID,
        mock=None,
        execution_context_id=None,
    ) -> StepResult:
        """Execute a single pipeline step (agent, task, or tool)."""
        start_ms = _now_ms()
        step_name_var.set(step.step_name)
        logger.info("Step starting: %s (%s: %s)", step.step_name, step.entity_type, step.entity_name)

        # Build step context: original context + accumulated outputs from prior steps
        step_context = dict(context)
        for dep_name, dep_result in accumulated_results.items():
            if dep_result.execution_result and dep_result.execution_result.output:
                step_context[dep_name] = dep_result.execution_result.output

        try:
            entity_type = step.entity_type.value if hasattr(step.entity_type, 'value') else str(step.entity_type)

            if entity_type == "agent":
                exec_result = await self.engine.run_agent(
                    agent_name=step.entity_name,
                    context=step_context,

                    channel=channel,
                    pipeline_run_id=pipeline_run_id,
                    step_name=step.step_name,
                    mock=mock,
                    execution_context_id=execution_context_id,
                )
            elif entity_type == "task":
                exec_result = await self.engine.run_task(
                    task_name=step.entity_name,
                    input_data=step_context,

                    channel=channel,
                    pipeline_run_id=pipeline_run_id,
                    step_name=step.step_name,
                    mock=mock,
                    execution_context_id=execution_context_id,
                )
            elif entity_type == "tool":
                exec_result = await self.engine.run_tool(
                    tool_name=step.entity_name,
                    input_data=step_context,

                    channel=channel,
                    pipeline_run_id=pipeline_run_id,
                    step_name=step.step_name,
                    mock=mock,
                    execution_context_id=execution_context_id,
                )
            else:
                return StepResult(
                    step_name=step.step_name,
                    entity_type=entity_type,
                    entity_name=step.entity_name,
                    status="skipped",
                    error_message=f"Unsupported entity type: {entity_type}",
                    duration_ms=_now_ms() - start_ms,
                )

            duration_ms = _now_ms() - start_ms
            status = "complete" if exec_result.status == "complete" else "failed"
            if status == "complete":
                logger.info("Step complete: %s (%dms)", step.step_name, duration_ms)
            else:
                logger.error("Step failed: %s (%dms) — %s",
                              step.step_name, duration_ms, exec_result.error_message)
            return StepResult(
                step_name=step.step_name,
                entity_type=entity_type,
                entity_name=step.entity_name,
                status=status,
                execution_result=exec_result,
                error_message=exec_result.error_message,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = _now_ms() - start_ms
            logger.error("Step exception: %s (%dms)", step.step_name, duration_ms, exc_info=True)
            return StepResult(
                step_name=step.step_name,
                entity_type=step.entity_type.value,
                entity_name=step.entity_name,
                status="failed",
                error_message=str(e),
                duration_ms=duration_ms,
            )


# ── HELPER FUNCTIONS ──────────────────────────────────────────

def _build_execution_groups(steps: list[PipelineStep]) -> list[list[PipelineStep]]:
    """Group steps by step_order for sequential execution.

    Steps with the same step_order and same parallel_group run concurrently.
    Steps with different step_orders run sequentially.
    """
    order_map: dict[int, list[PipelineStep]] = {}
    for step in steps:
        order_map.setdefault(step.step_order, []).append(step)

    return [order_map[k] for k in sorted(order_map.keys())]


def _get_parallel_groups(steps: list[PipelineStep]) -> set[str]:
    """Get all parallel group names."""
    return {s.parallel_group for s in steps if s.parallel_group}


def _evaluate_step_condition(
    condition: dict[str, Any],
    accumulated_results: dict[str, StepResult],
    context: dict[str, Any],
) -> bool:
    """Evaluate a step's condition against accumulated results and context.

    Example conditions:
    - {"if_doc_type_present": "do_application"} — checks if doc type is in prior outputs
    """
    for key, expected_value in condition.items():
        if key == "if_doc_type_present":
            # Check if any prior step's output contains this doc type
            for step_result in accumulated_results.values():
                if step_result.execution_result and step_result.execution_result.output:
                    output = step_result.execution_result.output
                    if isinstance(output, dict):
                        doc_type = output.get("document_type", "")
                        if doc_type == expected_value:
                            return True
                        docs = output.get("documents_found", [])
                        if expected_value in docs:
                            return True
            return False

        # Generic key-value check against context
        if key.startswith("if_"):
            ctx_key = key[3:]
            if ctx_key in context and context[ctx_key] != expected_value:
                return False

    return True


def _now_ms() -> int:
    return int(time.time() * 1000)
