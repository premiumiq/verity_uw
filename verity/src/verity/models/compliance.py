"""Pydantic models for the L3 compliance metamodel.

Mirrors `verity/src/verity/db/schema_compliance.sql`.

Architecture: docs/architecture/compliance-stack.md
Build plan:   docs/plans/compliance-build-plan.md
"""

from datetime import date, datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


# ── EMBEDDING MODEL IDENTITY ─────────────────────────────────


class EmbeddingConfig(BaseModel):
    id: UUID
    model_name: str
    model_version: str
    dim: int
    runtime: str = "fastembed"
    is_current: bool = True
    created_at: Optional[datetime] = None


# ── LEFT AXIS: REGULATORS ────────────────────────────────────


class RegulatoryFramework(BaseModel):
    id: UUID
    code: str
    name: str
    jurisdiction: str
    version: Optional[str] = None
    effective_date: Optional[date] = None
    valid_from: date
    valid_to: date
    source_url: Optional[str] = None
    description: Optional[str] = None
    sort_seq: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RegulatoryProvision(BaseModel):
    id: UUID
    framework_id: UUID
    citation: str
    title: str
    text: Optional[str] = None
    effective_date: Optional[date] = None
    valid_from: date
    valid_to: date
    sort_seq: int = 0
    embedding: Optional[list[float]] = None
    embedding_model_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── CENTER AXIS: RATIONALIZED REQUIREMENTS ───────────────────


class CanonicalRequirementTheme(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    sort_seq: int = 0
    created_at: Optional[datetime] = None


class CanonicalRequirement(BaseModel):
    id: UUID
    theme_id: UUID
    code: str
    title: str
    description: Optional[str] = None
    sort_seq: int = 0
    embedding: Optional[list[float]] = None
    embedding_model_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── BRIDGE: PROVISION ↔ CANONICAL REQUIREMENT ────────────────


class ProvisionRequirementMap(BaseModel):
    """Many-to-many between regulatory_provision and canonical_requirement.

    `match_strength` captures semantic alignment of the provision to the
    canonical requirement (0..1). It is NOT coverage. Coverage of the
    canonical requirement lives in RequirementCoverage.coverage_level.
    """

    id: UUID
    provision_id: UUID
    canonical_requirement_id: UUID
    match_strength: float = Field(default=1.0, gt=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    mapping_source: str = "manual"  # 'manual' | 'semantic_recommended' | 'human_validated'
    validated_by: Optional[str] = None
    validated_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── RIGHT AXIS: VERITY FEATURES HIERARCHY ────────────────────


class FeaturePlane(BaseModel):
    id: UUID
    code: str
    name: str
    description: Optional[str] = None
    sort_seq: int = 0
    created_at: Optional[datetime] = None


class FeatureCapability(BaseModel):
    id: UUID
    plane_id: UUID
    code: str
    name: str
    description: Optional[str] = None
    sort_seq: int = 0
    created_at: Optional[datetime] = None


class Feature(BaseModel):
    id: UUID
    capability_id: UUID
    code: str
    name: str
    description: Optional[str] = None
    status: str = "shipped"  # 'shipped' | 'planned' | 'partial' | 'deprecated'
    sort_seq: int = 0
    embedding: Optional[list[float]] = None
    embedding_model_id: Optional[UUID] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ── BRIDGE: CANONICAL REQUIREMENT ↔ FEATURE ──────────────────


class RequirementFeatureLink(BaseModel):
    id: UUID
    canonical_requirement_id: UUID
    feature_id: UUID
    role: str = "primary"  # 'primary' | 'supporting'
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ── COVERAGE ─────────────────────────────────────────────────


class RequirementCoverage(BaseModel):
    id: UUID
    canonical_requirement_id: UUID
    coverage_level: str  # 'full' | 'substantial' | 'partial' | 'gap'
    rationale: Optional[str] = None
    customer_actions: Optional[str] = None
    last_reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
