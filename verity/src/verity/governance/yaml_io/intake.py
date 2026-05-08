"""YAML import / export for governance intakes.

Each intake round-trips as a single YAML document that includes its
requirements, impact assessment, plan rows, entity links, and approvals.
This is intentionally a single-doc shape (not the full bundle/dep-graph
machinery in exporter.py) — intakes live above the registry, so their
"transitive deps" are just their child rows.

YAML shape::

    apiVersion: verity.intake/v1
    code: uw-bop-eligibility
    title: BOP Submission Eligibility Classification
    problem_statement: ...
    expected_benefit: ...
    in_scope_decisions: ...
    out_of_scope_decisions: ...
    affected_populations: [applicants, brokers, underwriters]
    business_owner_name: ...
    business_owner_email: ...
    requesting_team: ...
    ai_risk_tier: high
    naic_materiality: material
    risk_classification_rationale: ...
    requirements:
      - code: BR-1
        kind: business
        statement: ...
        acceptance_criteria: ...
        source: ...
        status: approved
    impact_assessment:
      data_sources: [...]
      potential_harms: [...]
      mitigations: [...]
      fairness_considerations: ...
      privacy_considerations: ...
      human_oversight_plan: ...
    plan:
      - proposed_kind: task
        proposed_name: ...
        proposed_display_name: ...
        proposed_capability_type: classification
        proposed_materiality_tier: high
"""

from __future__ import annotations

from typing import Any

import yaml

from verity.governance.intake import IntakeService
from verity.models.intake import (
    AIRiskTier,
    LinkedEntityKind,
    NAICMateriality,
    RequirementKind,
    RequirementStatus,
)


def _safe_iso(value: Any) -> Any:
    """Coerce datetime/UUID values to ISO/string for YAML serialisation."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value) if hasattr(value, "hex") else value


async def export_intake_to_yaml(
    intake_service: IntakeService, code: str,
) -> str:
    """Return a single YAML document for the named intake."""
    intake = await intake_service.get_intake_by_code(code)
    if not intake:
        raise ValueError(f"Intake '{code}' not found")
    intake_id = intake["id"]

    requirements = await intake_service.list_requirements(intake_id)
    plan = await intake_service.list_plan_rows(intake_id)
    links = await intake_service.list_entity_links(intake_id)
    impact = await intake_service.get_impact_assessment(intake_id)
    approvals = await intake_service.list_approval_requests(intake_id)

    # Sign-offs are nested under their parent approval_request.
    approvals_payload = []
    for a in approvals:
        signoffs = await intake_service.list_signoffs(a["id"])
        approvals_payload.append({
            "kind": a["kind"],
            "status": a["status"],
            "summary": a["summary"],
            "required_roles": a["required_roles"],
            "opened_by": a["opened_by"],
            "opened_at": _safe_iso(a["opened_at"]),
            "decided_at": _safe_iso(a["decided_at"]),
            "signoffs": [
                {
                    "role": s["role"],
                    "approver_name": s["approver_name"],
                    "approver_email": s.get("approver_email"),
                    "decision": s["decision"],
                    "comment": s.get("comment"),
                    "evidence_url": s.get("evidence_url"),
                    "signed_at": _safe_iso(s.get("signed_at")),
                }
                for s in signoffs
            ],
        })

    payload = {
        "apiVersion": "verity.intake/v1",
        "code": intake["code"],
        "title": intake["title"],
        "problem_statement": intake["problem_statement"],
        "expected_benefit": intake["expected_benefit"],
        "in_scope_decisions": intake.get("in_scope_decisions"),
        "out_of_scope_decisions": intake.get("out_of_scope_decisions"),
        "affected_populations": intake.get("affected_populations") or [],
        "business_owner_name": intake["business_owner_name"],
        "business_owner_email": intake.get("business_owner_email"),
        "requesting_team": intake.get("requesting_team"),
        "ai_risk_tier": intake["ai_risk_tier"],
        "naic_materiality": intake["naic_materiality"],
        "risk_classification_rationale": intake["risk_classification_rationale"],
        "status": intake["status"],
        "requirements": [
            {
                "code": r["code"],
                "kind": r["kind"],
                "statement": r["statement"],
                "acceptance_criteria": r.get("acceptance_criteria"),
                "source": r.get("source"),
                "status": r["status"],
            }
            for r in requirements
        ],
        "impact_assessment": (
            {
                "data_sources": impact.get("data_sources") or [],
                "potential_harms": impact.get("potential_harms") or [],
                "mitigations": impact.get("mitigations") or [],
                "fairness_considerations": impact.get("fairness_considerations"),
                "privacy_considerations": impact.get("privacy_considerations"),
                "human_oversight_plan": impact.get("human_oversight_plan"),
                "completed_at": _safe_iso(impact.get("completed_at")),
                "completed_by": impact.get("completed_by"),
            }
            if impact else None
        ),
        "plan": [
            {
                "proposed_kind": p["proposed_kind"],
                "proposed_name": p["proposed_name"],
                "proposed_display_name": p["proposed_display_name"],
                "proposed_description": p.get("proposed_description"),
                "proposed_purpose": p.get("proposed_purpose"),
                "proposed_capability_type": p.get("proposed_capability_type"),
                "proposed_materiality_tier": p["proposed_materiality_tier"],
                "status": p["status"],
                "auto_generated": p.get("auto_generated", False),
            }
            for p in plan
        ],
        "links": [
            {
                "entity_type": l["entity_type"],
                "entity_id": str(l["entity_id"]),
                "relationship": l["relationship"],
            }
            for l in links
        ],
        "approvals": approvals_payload,
    }
    # default_flow_style=False → block style; sort_keys=False → preserve order.
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, width=100)


async def import_intake_from_yaml(
    intake_service: IntakeService, yaml_text: str,
    *,
    created_by: str = "yaml-import",
) -> dict:
    """Idempotent import of a single intake YAML.

    If an intake with the same code already exists, this is a no-op
    (returns the existing row). Otherwise creates it with all child
    rows. Approval signoffs in the YAML are recorded as-is — the import
    does NOT trigger plan auto-generation, so the import faithfully
    reproduces the source state.
    """
    payload = yaml.safe_load(yaml_text)
    if not isinstance(payload, dict):
        raise ValueError("YAML root must be a mapping")
    if payload.get("apiVersion") != "verity.intake/v1":
        raise ValueError(
            f"Unknown apiVersion: {payload.get('apiVersion')!r}; "
            f"expected 'verity.intake/v1'"
        )

    code = payload["code"]
    existing = await intake_service.get_intake_by_code(code)
    if existing:
        return existing

    # Create the intake header. Marked with the supplied risk tier
    # already — import does NOT re-trigger triage logic.
    intake_row = await intake_service.create_intake(
        code=code,
        title=payload["title"],
        problem_statement=payload["problem_statement"],
        expected_benefit=payload["expected_benefit"],
        business_owner_name=payload["business_owner_name"],
        business_owner_email=payload.get("business_owner_email"),
        requesting_team=payload.get("requesting_team"),
        in_scope_decisions=payload.get("in_scope_decisions"),
        out_of_scope_decisions=payload.get("out_of_scope_decisions"),
        affected_populations=payload.get("affected_populations") or [],
        ai_risk_tier=AIRiskTier(payload.get("ai_risk_tier", "limited")),
        risk_classification_rationale=payload.get(
            "risk_classification_rationale", "(imported)",
        ),
        naic_materiality=payload.get("naic_materiality", "non_material"),
        notes=payload.get("notes"),
        created_by=created_by,
    )

    # Requirements (preserve order to keep the BR-1 → FR-1 → ... shape).
    for req in payload.get("requirements") or []:
        await intake_service.add_requirement(
            intake_row["id"],
            code=req["code"],
            kind=RequirementKind(req["kind"]),
            statement=req["statement"],
            acceptance_criteria=req.get("acceptance_criteria"),
            source=req.get("source"),
            status=RequirementStatus(req.get("status", "draft")),
            created_by=created_by,
            embed_now=True,
        )

    # Impact assessment.
    ia = payload.get("impact_assessment")
    if ia:
        await intake_service.upsert_impact_assessment(
            intake_row["id"],
            completed=bool(ia.get("completed_at")),
            completed_by=ia.get("completed_by") or created_by,
            data_sources=ia.get("data_sources") or [],
            potential_harms=ia.get("potential_harms") or [],
            mitigations=ia.get("mitigations") or [],
            fairness_considerations=ia.get("fairness_considerations"),
            privacy_considerations=ia.get("privacy_considerations"),
            human_oversight_plan=ia.get("human_oversight_plan"),
        )

    # Plan rows (auto_generated=False on import — they're explicit input).
    for p in payload.get("plan") or []:
        await intake_service.add_plan_row(
            intake_row["id"],
            proposed_kind=LinkedEntityKind(p["proposed_kind"]),
            proposed_name=p["proposed_name"],
            proposed_display_name=p["proposed_display_name"],
            proposed_description=p.get("proposed_description"),
            proposed_purpose=p.get("proposed_purpose"),
            proposed_capability_type=p.get("proposed_capability_type"),
            proposed_materiality_tier=p.get("proposed_materiality_tier", "medium"),
            auto_generated=p.get("auto_generated", False),
            created_by=created_by,
        )

    # Approval requests + signoffs are NOT replayed on import: they are
    # historical artifacts whose timestamps and approver identities
    # belong to the source environment. The fresh import lands with a
    # clean kind='intake' approval request (auto-opened by create_intake)
    # so the importing site can re-collect signoffs locally.

    return intake_row
