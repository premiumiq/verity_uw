"""Reporting models — model inventory, compliance, model cards."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel

from verity.models.lifecycle import EntityType, MaterialityTier


class ModelInventoryAgent(BaseModel):
    id: UUID
    name: str
    display_name: str
    materiality_tier: MaterialityTier
    domain: str
    champion_version: Optional[str] = None
    champion_since: Optional[datetime] = None
    inference_config_name: Optional[str] = None
    model_name: Optional[str] = None
    last_validation_date: Optional[datetime] = None
    last_validation_passed: Optional[bool] = None
    f1_score: Optional[float] = None
    cohens_kappa: Optional[float] = None
    model_card_status: Optional[str] = None
    model_card_approved_by: Optional[str] = None
    override_count_30d: int = 0
    decision_count_30d: int = 0
    active_incidents: int = 0


class ModelInventoryTask(BaseModel):
    id: UUID
    name: str
    display_name: str
    capability_type: str
    materiality_tier: MaterialityTier
    domain: str
    champion_version: Optional[str] = None
    champion_since: Optional[datetime] = None
    inference_config_name: Optional[str] = None
    model_name: Optional[str] = None
    last_validation_date: Optional[datetime] = None
    last_validation_passed: Optional[bool] = None
    f1_score: Optional[float] = None
    field_accuracy: Optional[dict[str, Any]] = None
    model_card_status: Optional[str] = None
    decision_count_30d: int = 0


class ModelCard(BaseModel):
    id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    card_version: int = 1
    purpose: str
    design_rationale: str
    inputs_description: str
    outputs_description: str
    known_limitations: str
    conditions_of_use: str
    lm_specific_limitations: Optional[str] = None
    prompt_sensitivity_notes: Optional[str] = None
    validated_by: Optional[str] = None
    validation_run_id: Optional[UUID] = None
    validation_notes: Optional[str] = None
    regulatory_notes: Optional[str] = None
    materiality_classification: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    lifecycle_state: str = "draft"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DashboardCounts(BaseModel):
    agent_count: int = 0
    task_count: int = 0
    prompt_count: int = 0
    config_count: int = 0
    tool_count: int = 0
    pipeline_count: int = 0
    total_decisions: int = 0
    total_overrides: int = 0
    open_incidents: int = 0
