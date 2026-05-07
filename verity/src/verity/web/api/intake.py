"""JSON API for the governance intake layer.

All routes are mounted under ``/api/v1/governance/intake/...``. Same
shape as the rest of the API: a ``build_intake_router(verity)`` factory
that returns an ``APIRouter``. Mounted from
``verity/src/verity/web/api/router.py``.

See docs/architecture/governance-intake.md § 8 for the full surface.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from psycopg.errors import Error as PsycopgError

from verity.models.intake import (
    AIRiskTier,
    ApprovalDecision,
    ApprovalRole,
    ApprovalRequestKind,
    ApprovalSignoffCreate,
    EntityLinkCreate,
    ImpactAssessmentUpdate,
    IntakeCreate,
    IntakeStatus,
    IntakeTriage,
    LinkedEntityKind,
    NAICMateriality,
    RequirementCreate,
    RequirementKind,
    RequirementStatus,
    StudioRole,
)


def _as_400(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


async def _require_intake(verity, app_code: str, intake_code: str) -> dict:
    """Resolve an intake by (application_code, code) or raise 404.

    Path-scoped lookup — both segments are required because two
    applications may each have an intake with the same code slug.
    """
    row = await verity.intake.get_intake_by_code(app_code, intake_code)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Intake '{app_code}/{intake_code}' not found",
        )
    return row


def build_intake_router(verity) -> APIRouter:
    """All ``/api/v1/governance/intake/*`` and related endpoints."""
    router = APIRouter(prefix="/governance", tags=["governance-intake"])

    # ── INTAKE CRUD ────────────────────────────────────────────

    @router.post("/intake")
    async def create_intake(body: IntakeCreate) -> dict:
        try:
            return await verity.intake.create_intake(
                code=body.code,
                title=body.title,
                problem_statement=body.problem_statement,
                expected_benefit=body.expected_benefit,
                business_owner_name=body.business_owner_name,
                business_owner_email=body.business_owner_email,
                requesting_team=body.requesting_team,
                in_scope_decisions=body.in_scope_decisions,
                out_of_scope_decisions=body.out_of_scope_decisions,
                affected_populations=body.affected_populations,
                ai_risk_tier=body.ai_risk_tier,
                risk_classification_rationale=body.risk_classification_rationale,
                naic_materiality=body.naic_materiality.value,
                notes=body.notes,
                # API caller identity is not yet populated (no auth);
                # default to the application name.
                created_by=getattr(verity, "application", "api"),
                acting_as_role=None,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/intake")
    async def list_intakes(
        status: Optional[IntakeStatus] = Query(default=None),
        ai_risk_tier: Optional[AIRiskTier] = Query(default=None),
        owner_email: Optional[str] = Query(default=None),
    ) -> list[dict]:
        return await verity.intake.list_intakes(
            status=status,
            ai_risk_tier=ai_risk_tier,
            business_owner_email=owner_email,
        )

    @router.get("/intake/{app_code}/{intake_code}")
    async def get_intake(app_code: str, intake_code: str) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        # Bundle the deep-detail rows in one response for the UI.
        intake_id = intake["id"]
        requirements = await verity.intake.list_requirements(intake_id)
        links = await verity.intake.list_entity_links(intake_id)
        plan = await verity.intake.list_plan_rows(intake_id)
        impact = await verity.intake.get_impact_assessment(intake_id)
        approvals = await verity.intake.list_approval_requests(intake_id)
        return {
            "intake": intake,
            "requirements": requirements,
            "entity_links": links,
            "artifact_plan": plan,
            "impact_assessment": impact,
            "approvals": approvals,
        }

    @router.patch("/intake/{app_code}/{intake_code}")
    async def patch_intake(app_code: str, intake_code: str, body: dict[str, Any]) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            updated = await verity.intake.update_intake(intake["id"], **body)
            return updated or intake
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/intake/{app_code}/{intake_code}/triage")
    async def triage_intake(app_code: str, intake_code: str, body: IntakeTriage) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            return await verity.intake.triage_intake(
                intake["id"],
                ai_risk_tier=body.ai_risk_tier,
                naic_materiality=body.naic_materiality.value,
                risk_classification_rationale=body.risk_classification_rationale,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/intake/{app_code}/{intake_code}/retire")
    async def retire_intake(app_code: str, intake_code: str) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        result = await verity.intake.retire_intake(intake["id"])
        return result or intake

    # ── REQUIREMENTS ───────────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/requirements")
    async def add_requirement(app_code: str, intake_code: str, body: RequirementCreate) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            return await verity.intake.add_requirement(
                intake["id"],
                code=body.code,
                kind=body.kind,
                statement=body.statement,
                acceptance_criteria=body.acceptance_criteria,
                source=body.source,
                parent_requirement_id=body.parent_requirement_id,
                created_by=getattr(verity, "application", "api"),
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/intake/{app_code}/{intake_code}/requirements")
    async def list_requirements(app_code: str, intake_code: str) -> list[dict]:
        intake = await _require_intake(verity, app_code, intake_code)
        return await verity.intake.list_requirements(intake["id"])

    @router.patch("/intake/{app_code}/{intake_code}/requirements/{req_code}")
    async def update_requirement(app_code: str, intake_code: str, req_code: str, body: dict[str, Any]) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        # Resolve req by (intake_id, req_code)
        all_reqs = await verity.intake.list_requirements(intake["id"])
        req = next((r for r in all_reqs if r["code"] == req_code), None)
        if not req:
            raise HTTPException(404, f"Requirement '{req_code}' not found")
        try:
            return await verity.intake.update_requirement(req["id"], **body) or req
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/intake/{app_code}/{intake_code}/requirements/redundancy-check")
    async def redundancy_check(app_code: str, intake_code: str, body: dict[str, Any]) -> list[dict]:
        """Embed the supplied text and return the top-N similar requirements."""
        statement = body.get("statement") or ""
        acceptance = body.get("acceptance_criteria")
        return await verity.intake.search_similar_requirements(
            statement=statement,
            acceptance_criteria=acceptance,
            top_n=int(body.get("top_n", 5)),
            min_similarity=float(body.get("min_similarity", 0.85)),
        )

    # ── ENTITY LINKS ───────────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/links")
    async def create_link(app_code: str, intake_code: str, body: EntityLinkCreate) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            row = await verity.intake.link_entity(
                intake["id"],
                entity_type=body.entity_type,
                entity_id=body.entity_id,
                requirement_id=body.requirement_id,
                relationship=body.relationship,
                created_by=getattr(verity, "application", "api"),
            )
            return row or {"status": "exists"}
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.delete("/intake/{app_code}/{intake_code}/links/{link_id}")
    async def delete_link(app_code: str, intake_code: str, link_id: UUID) -> dict:
        deleted = await verity.intake.delete_entity_link(link_id)
        if not deleted:
            raise HTTPException(404, "Link not found")
        return deleted

    # ── ARTIFACT PLAN ──────────────────────────────────────────

    @router.get("/intake/{app_code}/{intake_code}/plan")
    async def list_plan(app_code: str, intake_code: str) -> list[dict]:
        intake = await _require_intake(verity, app_code, intake_code)
        return await verity.intake.list_plan_rows(intake["id"])

    @router.post("/intake/{app_code}/{intake_code}/plan/generate")
    async def generate_plan(app_code: str, intake_code: str) -> list[dict]:
        """Re-run the rule-based plan generator over this intake."""
        from verity.governance.plan_generator import generate_plan as gen
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            return await gen(verity.intake, intake["id"])
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.patch("/intake/{app_code}/{intake_code}/plan/{plan_id}")
    async def patch_plan(app_code: str, intake_code: str, plan_id: UUID, body: dict[str, Any]) -> dict:
        await _require_intake(verity, app_code, intake_code)
        updated = await verity.intake.update_plan_row(plan_id, **body)
        if not updated:
            raise HTTPException(404, "Plan row not found")
        return updated

    @router.post("/intake/{app_code}/{intake_code}/plan/{plan_id}/realize")
    async def realize_plan(app_code: str, intake_code: str, plan_id: UUID, body: dict[str, Any]) -> dict:
        """Mark a plan row as realised, pointing at a registry entity."""
        await _require_intake(verity, app_code, intake_code)
        eid = body.get("realized_entity_id")
        if not eid:
            raise HTTPException(400, "realized_entity_id required")
        row = await verity.intake.realize_plan_row(plan_id, UUID(str(eid)))
        if not row:
            raise HTTPException(404, "Plan row not found")
        return row

    # ── IMPACT ASSESSMENT ──────────────────────────────────────

    @router.get("/intake/{app_code}/{intake_code}/impact")
    async def get_impact(app_code: str, intake_code: str) -> Optional[dict]:
        intake = await _require_intake(verity, app_code, intake_code)
        return await verity.intake.get_impact_assessment(intake["id"])

    @router.post("/intake/{app_code}/{intake_code}/impact")
    async def upsert_impact(app_code: str, intake_code: str, body: ImpactAssessmentUpdate) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            return await verity.intake.upsert_impact_assessment(
                intake["id"],
                completed=body.completed,
                completed_by=getattr(verity, "application", "api"),
                data_sources=body.data_sources,
                potential_harms=body.potential_harms,
                mitigations=body.mitigations,
                fairness_considerations=body.fairness_considerations,
                privacy_considerations=body.privacy_considerations,
                human_oversight_plan=body.human_oversight_plan,
                notes=body.notes,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    # ── APPROVALS ──────────────────────────────────────────────

    @router.get("/intake/{app_code}/{intake_code}/approvals")
    async def list_approvals(app_code: str, intake_code: str) -> list[dict]:
        intake = await _require_intake(verity, app_code, intake_code)
        return await verity.intake.list_approval_requests(intake["id"])

    @router.post("/intake/{app_code}/{intake_code}/approvals")
    async def open_approval(app_code: str, intake_code: str, body: dict[str, Any]) -> dict:
        intake = await _require_intake(verity, app_code, intake_code)
        try:
            return await verity.intake.open_approval_request(
                intake["id"],
                kind=ApprovalRequestKind(body["kind"]),
                opened_by=body.get("opened_by") or getattr(verity, "application", "api"),
                summary=body["summary"],
                required_roles=[ApprovalRole(r) for r in body.get("required_roles", [])],
                target_entity_type=(
                    LinkedEntityKind(body["target_entity_type"])
                    if body.get("target_entity_type") else None
                ),
                target_entity_id=UUID(str(body["target_entity_id"]))
                    if body.get("target_entity_id") else None,
                notes=body.get("notes"),
            )
        except (KeyError, ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.post("/approvals/{request_id}/signoff")
    async def signoff(request_id: UUID, body: ApprovalSignoffCreate) -> dict:
        try:
            return await verity.intake.signoff(
                request_id,
                role=body.role,
                approver_name=body.approver_name,
                approver_email=body.approver_email,
                decision=body.decision,
                comment=body.comment,
                evidence_url=body.evidence_url,
            )
        except (ValueError, PsycopgError) as exc:
            raise _as_400(exc)

    @router.get("/approvals/{request_id}")
    async def get_approval(request_id: UUID) -> dict:
        request = await verity.intake.db.fetch_one(
            "get_approval_request", {"id": str(request_id)},
        )
        if not request:
            raise HTTPException(404, "Approval request not found")
        signoffs = await verity.intake.list_signoffs(request_id)
        return {"request": request, "signoffs": signoffs}

    # ── DASHBOARD ──────────────────────────────────────────────

    @router.get("/dashboard")
    async def dashboard() -> dict:
        return await verity.intake.dashboard_counts()

    return router
