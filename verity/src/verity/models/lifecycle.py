"""Lifecycle enums and approval models."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class LifecycleState(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    STAGING = "staging"
    SHADOW = "shadow"
    CHALLENGER = "challenger"
    CHAMPION = "champion"
    DEPRECATED = "deprecated"


class DeploymentChannel(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    SHADOW = "shadow"
    EVALUATION = "evaluation"
    PRODUCTION = "production"


class MaterialityTier(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CapabilityType(str, Enum):
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    GENERATION = "generation"
    SUMMARISATION = "summarisation"
    MATCHING = "matching"
    VALIDATION = "validation"


class EntityType(str, Enum):
    AGENT = "agent"
    TASK = "task"
    PROMPT = "prompt"
    PIPELINE = "pipeline"
    TOOL = "tool"


class GovernanceTier(str, Enum):
    BEHAVIOURAL = "behavioural"
    CONTEXTUAL = "contextual"
    FORMATTING = "formatting"


class ApiRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT_PREFILL = "assistant_prefill"


class MetricType(str, Enum):
    EXACT_MATCH = "exact_match"
    SCHEMA_VALID = "schema_valid"
    FIELD_ACCURACY = "field_accuracy"
    CLASSIFICATION_F1 = "classification_f1"
    SEMANTIC_SIMILARITY = "semantic_similarity"
    HUMAN_RUBRIC = "human_rubric"


# Valid lifecycle transitions per the 7-state model
VALID_TRANSITIONS: dict[LifecycleState, list[LifecycleState]] = {
    LifecycleState.DRAFT: [LifecycleState.CANDIDATE],
    LifecycleState.CANDIDATE: [LifecycleState.STAGING, LifecycleState.CHAMPION, LifecycleState.DEPRECATED],
    LifecycleState.STAGING: [LifecycleState.SHADOW, LifecycleState.DEPRECATED],
    LifecycleState.SHADOW: [LifecycleState.CHALLENGER, LifecycleState.DEPRECATED],
    LifecycleState.CHALLENGER: [LifecycleState.CHAMPION, LifecycleState.DEPRECATED],
    LifecycleState.CHAMPION: [LifecycleState.DEPRECATED],
    LifecycleState.DEPRECATED: [],
}

# Channel mapping for each lifecycle state
STATE_TO_CHANNEL: dict[LifecycleState, DeploymentChannel] = {
    LifecycleState.DRAFT: DeploymentChannel.DEVELOPMENT,
    LifecycleState.CANDIDATE: DeploymentChannel.DEVELOPMENT,
    LifecycleState.STAGING: DeploymentChannel.STAGING,
    LifecycleState.SHADOW: DeploymentChannel.SHADOW,
    LifecycleState.CHALLENGER: DeploymentChannel.EVALUATION,
    LifecycleState.CHAMPION: DeploymentChannel.PRODUCTION,
    LifecycleState.DEPRECATED: DeploymentChannel.PRODUCTION,
}


class PromotionRequest(BaseModel):
    target_state: LifecycleState
    approver_name: str
    approver_role: Optional[str] = None
    rationale: str
    staging_results_reviewed: bool = False
    ground_truth_reviewed: bool = False
    fairness_analysis_reviewed: bool = False
    shadow_metrics_reviewed: bool = False
    challenger_metrics_reviewed: bool = False
    model_card_reviewed: bool = False
    similarity_flags_reviewed: bool = False


class ApprovalRecord(BaseModel):
    id: UUID
    entity_type: EntityType
    entity_version_id: UUID
    gate_type: str
    from_state: Optional[LifecycleState] = None
    to_state: Optional[LifecycleState] = None
    approver_name: str
    approver_role: Optional[str] = None
    approved_at: datetime
    rationale: str
