"""Request/response Pydantic models for the REST API.

These models sit at the HTTP boundary. They mirror the keyword arguments
of the SDK methods they wrap, but are explicit about field types so
FastAPI can document them in OpenAPI and validate incoming payloads.

Response shapes mostly reuse existing Pydantic models from
`verity.contracts.*` / `verity.models.*`. The request models below are
new and specific to the API layer.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── Runtime execution requests ────────────────────────────────

class RunAgentRequest(BaseModel):
    """Body for POST /api/v1/runtime/agents/{name}/run."""

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Context variables passed to the agent — merged into "
                    "prompt template placeholders and available in tool calls.",
    )
    channel: str = Field(
        "production",
        description="Deployment channel to resolve version against. "
                    "Default 'production' resolves the current champion.",
    )
    execution_context_id: Optional[UUID] = Field(
        None,
        description="Link this run's decision log row to a pre-created "
                    "execution_context (business-level grouping).",
    )
    workflow_run_id: Optional[UUID] = Field(
        None,
        description="Link this run to a parent pipeline run (normally "
                    "left null when calling the agent directly).",
    )
    application: Optional[str] = Field(
        None,
        description="Attribution override for the decision log's "
                    "`application` column. When omitted, decisions are "
                    "tagged with the Verity server process's default "
                    "client identity ('default'). External callers "
                    "(e.g. the DS Workbench) pass their own app name "
                    "here so cleanup-by-application queries work.",
    )


class RunTaskRequest(BaseModel):
    """Body for POST /api/v1/runtime/tasks/{name}/run."""

    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured input to the task. Shape must satisfy "
                    "the task's registered input_schema.",
    )
    channel: str = "production"
    execution_context_id: Optional[UUID] = None
    workflow_run_id: Optional[UUID] = None
    application: Optional[str] = Field(
        None,
        description="Attribution override for the decision log's "
                    "`application` column (see RunAgentRequest.application).",
    )


class RunPipelineRequest(BaseModel):
    """Body for POST /api/v1/runtime/pipelines/{name}/run."""

    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Top-level context shared across all pipeline steps.",
    )
    channel: str = "production"
    execution_context_id: Optional[UUID] = None
    application: Optional[str] = Field(
        None,
        description="Attribution override for every decision log row "
                    "produced by this pipeline run "
                    "(see RunAgentRequest.application).",
    )
