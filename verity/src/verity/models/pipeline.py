"""Pipeline models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import EntityType, LifecycleState


class PipelineStep(BaseModel):
    step_order: int
    step_name: str
    entity_type: EntityType
    entity_name: str
    entity_version_id: Optional[UUID] = None  # None = use champion
    depends_on: list[str] = []
    parallel_group: Optional[str] = None
    error_policy: str = "fail_pipeline"
    output_key: Optional[str] = None
    condition: Optional[dict[str, Any]] = None


class Pipeline(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: Optional[str] = None
    current_champion_version_id: Optional[UUID] = None
    created_at: Optional[datetime] = None


class PipelineVersion(BaseModel):
    id: UUID
    pipeline_id: UUID
    version_number: int
    lifecycle_state: LifecycleState = LifecycleState.DRAFT
    steps: list[PipelineStep]
    change_summary: Optional[str] = None
    developer_name: Optional[str] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    created_at: Optional[datetime] = None
