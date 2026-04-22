"""Pipeline models.

PipelineStep was moved to verity.contracts.pipeline as of Phase 1 of the
Registry/Runtime split. It is re-exported here for backward compatibility.

What stays here (governance-internal DB read shapes):
- Pipeline — the pipeline header row
- PipelineVersion — a versioned pipeline with steps (list[PipelineStep]) and lifecycle state
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import LifecycleState

# Re-export boundary model from contracts for backward compatibility.
from verity.contracts.pipeline import PipelineStep  # noqa: F401


class Pipeline(BaseModel):
    """Pipeline header — one row per named pipeline (N versions reference it)."""
    id: UUID
    name: str
    display_name: str
    description: Optional[str] = None
    current_champion_version_id: Optional[UUID] = None
    created_at: Optional[datetime] = None


class PipelineVersion(BaseModel):
    """One versioned pipeline: list of steps + lifecycle state."""
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
