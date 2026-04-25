"""Shared enums used across governance and runtime.

These enums are the common vocabulary that lets governance (definitions,
lifecycle, audit) and runtime (execution) speak about the same things
without one depending on the other. They live in `contracts/` because
they cross the boundary — every decision log references an EntityType,
every config resolution carries a LifecycleState, every execution has
a DeploymentChannel and RunPurpose.

Note: The governance-internal machine state lives elsewhere:
- PromotionRequest, ApprovalRecord — in verity.models.lifecycle
- VALID_TRANSITIONS, STATE_TO_CHANNEL — in verity.models.lifecycle
"""

from enum import Enum


class LifecycleState(str, Enum):
    """The 7-state lifecycle applied to every agent/task/prompt/pipeline version."""
    DRAFT = "draft"
    CANDIDATE = "candidate"
    STAGING = "staging"
    SHADOW = "shadow"
    CHALLENGER = "challenger"
    CHAMPION = "champion"
    DEPRECATED = "deprecated"


class DeploymentChannel(str, Enum):
    """Where a given execution is happening: dev, staging, shadow, evaluation, or production."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    SHADOW = "shadow"
    EVALUATION = "evaluation"
    PRODUCTION = "production"


class MaterialityTier(str, Enum):
    """How material a given AI component is to business decisions."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CapabilityType(str, Enum):
    """What kind of work a task performs."""
    CLASSIFICATION = "classification"
    EXTRACTION = "extraction"
    GENERATION = "generation"
    SUMMARISATION = "summarisation"
    MATCHING = "matching"
    VALIDATION = "validation"


class EntityType(str, Enum):
    """The four first-class entity types Verity governs."""
    AGENT = "agent"
    TASK = "task"
    PROMPT = "prompt"
    TOOL = "tool"


class GovernanceTier(str, Enum):
    """How strictly a prompt is governed (behavioural = full lifecycle, formatting = minimal)."""
    BEHAVIOURAL = "behavioural"
    CONTEXTUAL = "contextual"
    FORMATTING = "formatting"


class ApiRole(str, Enum):
    """Where a prompt slots into the Claude messages API (system, user, or prefill)."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT_PREFILL = "assistant_prefill"


class MetricType(str, Enum):
    """How a test case or validation record is scored."""
    EXACT_MATCH = "exact_match"
    SCHEMA_VALID = "schema_valid"
    FIELD_ACCURACY = "field_accuracy"
    CLASSIFICATION_F1 = "classification_f1"
    SEMANTIC_SIMILARITY = "semantic_similarity"
    HUMAN_RUBRIC = "human_rubric"


class RunPurpose(str, Enum):
    """Why an execution happened. Independent of channel and mock_mode."""
    PRODUCTION = "production"       # Normal business execution
    TEST = "test"                   # Test suite run
    VALIDATION = "validation"       # Ground truth validation
    AUDIT_RERUN = "audit_rerun"     # Historical reproduction


class GtDatasetStatus(str, Enum):
    """Ground truth dataset lifecycle status."""
    COLLECTING = "collecting"
    LABELING = "labeling"
    ADJUDICATING = "adjudicating"
    READY = "ready"
    DEPRECATED = "deprecated"


class GtQualityTier(str, Enum):
    """Ground truth quality classification."""
    SILVER = "silver"   # Single annotator, no independent review
    GOLD = "gold"       # Multi-annotator with IAA check


class GtSourceType(str, Enum):
    """Ground truth record source type."""
    DOCUMENT = "document"
    SUBMISSION = "submission"
    SYNTHETIC = "synthetic"


class GtAnnotatorType(str, Enum):
    """Ground truth annotator type."""
    HUMAN_SME = "human_sme"
    LLM_JUDGE = "llm_judge"
    ADJUDICATOR = "adjudicator"
