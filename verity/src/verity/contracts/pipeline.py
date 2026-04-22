"""Pipeline step — one step definition within a pipeline version.

Only PipelineStep lives in contracts: the pipeline executor (runtime)
iterates over these to orchestrate step execution. The governance-internal
Pipeline and PipelineVersion DB models stay in verity.models.pipeline.
"""

from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.contracts.enums import EntityType


class PipelineStep(BaseModel):
    """One step in a pipeline's execution plan.

    Steps with the same step_order form an execution group that runs in
    parallel. depends_on names prior step_names that must complete before
    this step starts. condition is an optional dict that gets evaluated
    against the pipeline context to decide whether this step runs.
    """
    step_order: int
    step_name: str
    entity_type: EntityType
    entity_name: str
    # None = resolve champion at runtime
    entity_version_id: Optional[UUID] = None
    depends_on: list[str] = []
    parallel_group: Optional[str] = None
    error_policy: str = "fail_pipeline"
    output_key: Optional[str] = None
    condition: Optional[dict[str, Any]] = None
