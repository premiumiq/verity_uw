"""Pydantic models for the governance intake layer.

These mirror the columns of the `governance.intake*`, `approval_request`,
and `approval_signoff` tables defined in
``verity/src/verity/db/schema_intake.sql``. They are read-shapes — used
for typed return values from the service layer and for inbound JSON
validation in the API and Studio layers.

See docs/architecture/governance-intake.md for the design contract.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── ENUMS ─────────────────────────────────────────────────────
# Mirror the Postgres enum values exactly. Mismatch surfaces at parse
# time rather than at SQL execution time.


class IntakeStatus(str, Enum):
    PROPOSED = "proposed"
    IN_REVIEW = "in_review"
    IMPACT_ASSESSMENT = "impact_assessment"
    APPROVED = "approved"
    IN_BUILD = "in_build"
    LIVE = "live"
    REJECTED = "rejected"
    RETIRED = "retired"


class AIRiskTier(str, Enum):
    MINIMAL = "minimal"
    LIMITED = "limited"
    HIGH = "high"
    UNACCEPTABLE = "unacceptable"


class NAICMateriality(str, Enum):
    MATERIAL = "material"
    NON_MATERIAL = "non_material"


class RequirementKind(str, Enum):
    BUSINESS = "business"
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"
    COMPLIANCE = "compliance"


class RequirementStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    DEPRECATED = "deprecated"


class RequirementRelationship(str, Enum):
    IMPLEMENTS = "implements"
    TESTS = "tests"
    MONITORS = "monitors"
    INFORMS = "informs"


class StudioRole(str, Enum):
    BUSINESS_OWNER = "business_owner"
    COMPLIANCE = "compliance"
    LEGAL = "legal"
    MODEL_RISK = "model_risk"
    AI_GOVERNANCE = "ai_governance"
    SECURITY = "security"
    PRIVACY = "privacy"
    ENGINEER = "engineer"
    AUDITOR = "auditor"
    VIEWER = "viewer"


class ApprovalRole(str, Enum):
    """Subset of StudioRole that can sign off on an approval_request."""
    BUSINESS_OWNER = "business_owner"
    COMPLIANCE = "compliance"
    LEGAL = "legal"
    MODEL_RISK = "model_risk"
    AI_GOVERNANCE = "ai_governance"
    SECURITY = "security"
    PRIVACY = "privacy"


class ApprovalDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    REQUESTED_CHANGES = "requested_changes"
    ABSTAINED = "abstained"


class ApprovalRequestKind(str, Enum):
    INTAKE = "intake"
    RISK_RECLASSIFICATION = "risk_reclassification"
    PROMOTE_CANDIDATE = "promote_candidate"
    PROMOTE_CHAMPION = "promote_champion"
    RETIRE = "retire"


class ArtifactPlanStatus(str, Enum):
    PROPOSED = "proposed"
    IN_PROGRESS = "in_progress"
    REALIZED = "realized"
    CANCELLED = "cancelled"


class LinkedEntityKind(str, Enum):
    """Subset of governance.entity_type relevant to intake links.

    Mirrors the values added to the existing entity_type enum by
    schema_intake.sql plus the original four (agent/task/prompt/tool).
    """
    AGENT = "agent"
    TASK = "task"
    PROMPT = "prompt"
    TOOL = "tool"
    TEST_SUITE = "test_suite"
    GROUND_TRUTH_DATASET = "ground_truth_dataset"


# ── ROLE × RISK-TIER POLICY ────────────────────────────────────
# Which approval roles are required for an intake of a given risk
# tier. Driven by § 4.2 of governance-intake.md and § 4.3 of the
# NAIC Model Bulletin / EU AI Act mapping. Centralised here so the
# service layer and the API layer agree without copy-paste.


REQUIRED_ROLES_BY_RISK_TIER: dict[AIRiskTier, list[ApprovalRole]] = {
    AIRiskTier.UNACCEPTABLE: [],  # auto-rejected; no approvals possible
    AIRiskTier.HIGH: [
        ApprovalRole.BUSINESS_OWNER,
        ApprovalRole.COMPLIANCE,
        ApprovalRole.LEGAL,
        ApprovalRole.MODEL_RISK,
        ApprovalRole.AI_GOVERNANCE,
    ],
    AIRiskTier.LIMITED: [
        ApprovalRole.BUSINESS_OWNER,
        ApprovalRole.COMPLIANCE,
        ApprovalRole.AI_GOVERNANCE,
    ],
    AIRiskTier.MINIMAL: [
        ApprovalRole.BUSINESS_OWNER,
    ],
}


# ── RECORD MODELS ─────────────────────────────────────────────


class Intake(BaseModel):
    """The intake header — one row per business-approved AI use case."""
    id: UUID
    # Owning application — every intake is scoped to a registered
    # application (the consuming product the AI use case is for).
    # `application_id` is the FK; `application_code`/`application_name`
    # are populated by the service-layer JOIN for convenience.
    application_id: Optional[UUID] = None
    application_code: Optional[str] = None
    application_name: Optional[str] = None
    code: str
    title: str
    problem_statement: str
    expected_benefit: str
    in_scope_decisions: Optional[str] = None
    out_of_scope_decisions: Optional[str] = None
    affected_populations: list[str] = Field(default_factory=list)
    business_owner_name: str
    business_owner_email: Optional[str] = None
    requesting_team: Optional[str] = None
    ai_risk_tier: AIRiskTier
    risk_classification_rationale: str
    naic_materiality: NAICMateriality
    status: IntakeStatus = IntakeStatus.PROPOSED
    intake_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    retired_at: Optional[datetime] = None
    effective_date: Optional[date] = None
    next_recertification_due: Optional[date] = None
    created_by: str
    acting_as_role: Optional[StudioRole] = None
    updated_at: Optional[datetime] = None
    notes: Optional[str] = None
    # HITL (human-in-the-loop) strategy captured at intake. Free-text
    # description of how humans review or override AI output, plus the
    # trigger condition (always / confidence < X / sample / exception).
    # Surfaced in compliance reports for canonicals like
    # human_oversight_intervention and use_user_authorization_controls.
    hitl_strategy: Optional[str] = None
    hitl_review_threshold: Optional[str] = None


class IntakeImpactAssessment(BaseModel):
    """Required for intakes with risk tier in (limited, high)."""
    id: UUID
    intake_id: UUID
    version: int = 1
    data_sources: list[dict[str, Any]] = Field(default_factory=list)
    potential_harms: list[dict[str, Any]] = Field(default_factory=list)
    mitigations: list[dict[str, Any]] = Field(default_factory=list)
    fairness_considerations: Optional[str] = None
    privacy_considerations: Optional[str] = None
    human_oversight_plan: Optional[str] = None
    completed_at: Optional[datetime] = None
    completed_by: Optional[str] = None
    notes: Optional[str] = None


class IntakeRequirement(BaseModel):
    """A BR/FR/NFR/compliance requirement under an intake.

    Embeddings (vector(384) BGE-small) and embedding_input_hash exist
    on the row but are not exposed here directly — services emit them
    via update_embedding(). The ``has_embedding`` boolean is a
    convenience for UI rendering.
    """
    id: UUID
    intake_id: UUID
    code: str
    kind: RequirementKind
    statement: str
    acceptance_criteria: Optional[str] = None
    source: Optional[str] = None
    status: RequirementStatus = RequirementStatus.DRAFT
    parent_requirement_id: Optional[UUID] = None
    has_embedding: bool = False
    created_by: str
    acting_as_role: Optional[StudioRole] = None
    updated_at: Optional[datetime] = None


class IntakeEntityLink(BaseModel):
    """A bridge row from an intake (and optionally a requirement) to a registry entity."""
    id: UUID
    intake_id: UUID
    requirement_id: Optional[UUID] = None
    entity_type: LinkedEntityKind
    entity_id: UUID
    relationship: RequirementRelationship = RequirementRelationship.IMPLEMENTS
    created_by: str
    acting_as_role: Optional[StudioRole] = None
    created_at: Optional[datetime] = None


class IntakeArtifactPlan(BaseModel):
    """A proposed registry entity to be built for this intake.

    Auto-generated on intake approval (§ 6 of governance-intake.md);
    engineers may add, edit, or remove rows. ``realized_entity_id``
    is set when an engineer realises this plan into a concrete
    registry row; until then, no registry entity exists for it.
    """
    id: UUID
    intake_id: UUID
    requirement_id: Optional[UUID] = None
    proposed_kind: LinkedEntityKind
    proposed_name: str
    proposed_display_name: str
    proposed_description: Optional[str] = None
    proposed_purpose: Optional[str] = None
    proposed_inputs: dict[str, Any] = Field(default_factory=dict)
    proposed_outputs: dict[str, Any] = Field(default_factory=dict)
    proposed_capability_type: Optional[str] = None  # ``governance.capability_type``; only for tasks
    proposed_materiality_tier: str  # ``governance.materiality_tier`` — high/medium/low
    realized_entity_id: Optional[UUID] = None
    status: ArtifactPlanStatus = ArtifactPlanStatus.PROPOSED
    auto_generated: bool = False
    created_by: str
    acting_as_role: Optional[StudioRole] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ApprovalRequest(BaseModel):
    """One gating event on an intake (intake approval, promotion, retire)."""
    id: UUID
    intake_id: UUID
    kind: ApprovalRequestKind
    target_entity_type: Optional[LinkedEntityKind] = None
    target_entity_id: Optional[UUID] = None
    required_roles: list[ApprovalRole]
    status: str = "pending"  # pending | approved | rejected | withdrawn
    opened_at: Optional[datetime] = None
    opened_by: str
    opened_by_role: Optional[StudioRole] = None
    decided_at: Optional[datetime] = None
    summary: str
    notes: Optional[str] = None


class ApprovalSignoff(BaseModel):
    """One signoff on an approval_request from one approver in one role."""
    id: UUID
    approval_request_id: UUID
    role: ApprovalRole
    approver_name: str
    approver_email: Optional[str] = None
    decision: ApprovalDecision
    comment: Optional[str] = None
    evidence_url: Optional[str] = None
    signed_at: Optional[datetime] = None


# ── REQUEST / RESPONSE SHAPES ─────────────────────────────────


class IntakeCreate(BaseModel):
    """Inbound payload for creating an intake.

    The owning application is required — only registered applications
    can submit intakes. Pass either ``application_code`` (preferred,
    looked up at create time) or ``application_id`` directly.
    """
    application_code: Optional[str] = None
    application_id: Optional[UUID] = None
    code: str
    title: str
    problem_statement: str
    expected_benefit: str
    in_scope_decisions: Optional[str] = None
    out_of_scope_decisions: Optional[str] = None
    affected_populations: list[str] = Field(default_factory=list)
    business_owner_name: str
    business_owner_email: Optional[str] = None
    requesting_team: Optional[str] = None
    # Initial proposed risk tier (final tier set at triage); defaults to
    # 'limited' so the form has a safe non-trivial value at submit time.
    ai_risk_tier: AIRiskTier = AIRiskTier.LIMITED
    risk_classification_rationale: str = "(pending triage)"
    naic_materiality: NAICMateriality = NAICMateriality.NON_MATERIAL
    notes: Optional[str] = None
    hitl_strategy: Optional[str] = None
    hitl_review_threshold: Optional[str] = None


class IntakeTriage(BaseModel):
    """Inbound payload for triaging an intake (AI-Governance action)."""
    ai_risk_tier: AIRiskTier
    naic_materiality: NAICMateriality
    risk_classification_rationale: str


class RequirementCreate(BaseModel):
    code: str
    kind: RequirementKind
    statement: str
    acceptance_criteria: Optional[str] = None
    source: Optional[str] = None
    parent_requirement_id: Optional[UUID] = None


class EntityLinkCreate(BaseModel):
    entity_type: LinkedEntityKind
    entity_id: UUID
    requirement_id: Optional[UUID] = None
    relationship: RequirementRelationship = RequirementRelationship.IMPLEMENTS


class ImpactAssessmentUpdate(BaseModel):
    data_sources: list[dict[str, Any]] = Field(default_factory=list)
    potential_harms: list[dict[str, Any]] = Field(default_factory=list)
    mitigations: list[dict[str, Any]] = Field(default_factory=list)
    fairness_considerations: Optional[str] = None
    privacy_considerations: Optional[str] = None
    human_oversight_plan: Optional[str] = None
    notes: Optional[str] = None
    completed: bool = False  # if True, sets completed_at/by


class ApprovalSignoffCreate(BaseModel):
    role: ApprovalRole
    approver_name: str
    approver_email: Optional[str] = None
    decision: ApprovalDecision
    comment: Optional[str] = None
    evidence_url: Optional[str] = None


class PromotionGateResult(BaseModel):
    """Returned by IntakeService.check_promotion_gate.

    ``allowed=False`` means the lifecycle service must block the
    promotion and surface ``reasons`` in the 409 response.
    """
    allowed: bool
    reasons: list[str] = Field(default_factory=list)
    linked_intakes: list[UUID] = Field(default_factory=list)
