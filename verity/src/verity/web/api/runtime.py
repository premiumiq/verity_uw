"""Runtime execution endpoints — run_agent / run_task / run_pipeline.

Thin JSON wrappers over `verity.execution.*` and
`verity.pipeline_executor.*`. Each endpoint awaits the full execution
synchronously and returns the ExecutionResult / PipelineResult on
completion. No streaming or background-job semantics in the first pass
— notebooks that want real-time tokens can call Verity's admin-side
streaming endpoints directly, or we'll add an SSE variant later when
a specific use case needs it.

Results are @dataclass instances in the SDK. FastAPI / Pydantic v2
serializes dataclasses via `jsonable_encoder`, so returning them
directly from a route produces correct JSON (UUIDs as strings, nested
dataclasses recursed into) without any manual conversion.
"""

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException

from verity.web.api.schemas import RunAgentRequest, RunPipelineRequest, RunTaskRequest


def build_runtime_router(verity) -> APIRouter:
    """Build the /runtime/* execution endpoints."""
    router = APIRouter(prefix="/runtime", tags=["runtime"])

    @router.post("/agents/{name}/run")
    async def run_agent(name: str, req: RunAgentRequest) -> dict[str, Any]:
        """Execute an agent end-to-end and return the full ExecutionResult.

        Decision logs are written synchronously before the response returns
        — the `decision_log_id` in the response is ready for immediate
        audit-trail lookup.
        """
        try:
            result = await verity.execute_agent(
                agent_name=name,
                context=req.context,
                channel=req.channel,
                workflow_run_id=req.workflow_run_id,
                execution_context_id=req.execution_context_id,
                application=req.application,
            )
        except ValueError as exc:
            # Unknown agent name or version — surface as 404 rather than 500.
            raise HTTPException(status_code=404, detail=str(exc))
        return asdict(result)

    @router.post("/tasks/{name}/run")
    async def run_task(name: str, req: RunTaskRequest) -> dict[str, Any]:
        try:
            result = await verity.execute_task(
                task_name=name,
                input_data=req.input_data,
                channel=req.channel,
                workflow_run_id=req.workflow_run_id,
                execution_context_id=req.execution_context_id,
                application=req.application,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return asdict(result)

    @router.post("/pipelines/{name}/run")
    async def run_pipeline(name: str, req: RunPipelineRequest) -> dict[str, Any]:
        """Execute a pipeline from its champion version.

        Returns the PipelineResult with all step outcomes inline —
        each step's ExecutionResult, status, duration, and any error.
        """
        try:
            result = await verity.execute_pipeline(
                pipeline_name=name,
                context=req.context,
                channel=req.channel,
                execution_context_id=req.execution_context_id,
                application=req.application,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        return asdict(result)

    return router
