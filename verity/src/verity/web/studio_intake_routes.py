"""Verity Studio routes for the governance intake layer.

Mounted by ``studio_routes.create_studio_routes`` so the persona
middleware on the Studio sub-app applies. All routes render Jinja
templates from ``templates/studio/`` and use HTMX for partial updates
where it earns its keep (redundancy check, persona switch).

Adds the ``/studio/intake/...`` page tree plus the persona-switcher
HTMX endpoint and the governance dashboard. See
docs/architecture/governance-intake.md § 7.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from verity.governance.plan_generator import generate_plan as _generate_plan
from verity.models.intake import (
    AIRiskTier,
    ApprovalDecision,
    ApprovalRequestKind,
    ApprovalRole,
    ArtifactPlanStatus,
    LinkedEntityKind,
    NAICMateriality,
    REQUIRED_ROLES_BY_RISK_TIER,
    RequirementKind,
    RequirementRelationship,
    RequirementStatus,
    StudioRole,
)
from verity.web.middleware.persona import (
    ACTION_AUTHOR_REGISTRY,
    ACTION_CREATE_INTAKE,
    ACTION_EDIT_IMPACT_ASSESSMENT,
    ACTION_EDIT_INTAKE,
    ACTION_EDIT_PLAN,
    ACTION_EDIT_REQUIREMENT,
    ACTION_GENERATE_PLAN,
    ACTION_REALIZE_PLAN,
    ACTION_SIGNOFF,
    ACTION_TRIAGE_INTAKE,
    PERSONA_COOKIE_NAME,
    get_persona,
    is_action_allowed,
    persona_cookie_response,
)


logger = logging.getLogger(__name__)


def _render(
    templates: Jinja2Templates, request: Request, template: str, **ctx: Any,
):
    """Convenience wrapper around TemplateResponse that always passes the
    persona to templates and the action-permission helper."""
    ctx.setdefault("persona", get_persona(request))
    ctx.setdefault("is_action_allowed", is_action_allowed)
    ctx.setdefault("StudioRole", StudioRole)
    ctx.setdefault("AIRiskTier", AIRiskTier)
    ctx.setdefault("ApprovalRole", ApprovalRole)
    ctx.setdefault("ApprovalDecision", ApprovalDecision)
    ctx.setdefault("ApprovalRequestKind", ApprovalRequestKind)
    ctx.setdefault("ArtifactPlanStatus", ArtifactPlanStatus)
    ctx.setdefault("LinkedEntityKind", LinkedEntityKind)
    ctx.setdefault("NAICMateriality", NAICMateriality)
    ctx.setdefault("RequirementKind", RequirementKind)
    ctx.setdefault("RequirementRelationship", RequirementRelationship)
    ctx.setdefault("RequirementStatus", RequirementStatus)
    return templates.TemplateResponse(request, template, ctx)


def _persona_or_default(request: Request) -> StudioRole:
    p = get_persona(request)
    return p or StudioRole.VIEWER


# ── INTAKE LIFECYCLE STEPPER ─────────────────────────────────
# The intake's lifecycle is presented as 6 main stages on the
# detail page, mirroring uw_demo's submission stepper. Two
# terminal states (rejected, retired) are surfaced via badges
# rather than as additional stops on the rail.

# Ordered main flow. impact_assessment is always shown but
# marked 'skipped' for minimal-tier intakes that bypass it.
_INTAKE_FLOW = [
    ("proposed",          "Proposed"),
    ("in_review",         "In Review"),
    ("impact_assessment", "Impact Assessment"),
    ("approved",          "Approved"),
    ("in_build",          "In Build"),
    ("live",              "Live"),
]
_INTAKE_FLOW_INDEX = {code: i for i, (code, _) in enumerate(_INTAKE_FLOW)}


def _intake_workflow_steps(intake: dict) -> list[dict]:
    """Compute stepper rows for an intake.

    Each row matches the shape uw_demo's _stepper.html partial expects:
        {step_order, step_name, status, completed_at}

    Status values:
        complete  — the intake has progressed past this stage
        active    — the intake is currently at this stage
        pending   — not yet reached
        skipped   — minimal-tier intakes bypass impact_assessment
        failed    — set on the rejection point when status='rejected'

    For terminal states (rejected, retired) we mark the corresponding
    step appropriately and let the rest fall back to skipped/complete.
    """
    current_status = intake.get("status") or "proposed"
    risk_tier = intake.get("ai_risk_tier")

    # 'rejected' bookkeeping: the intake was rejected at whichever
    # stage it had reached; we don't know exactly when, so we mark
    # `proposed` as failed and the rest skipped. (Auto-rejection of
    # 'unacceptable' tier happens at triage, so 'in_review' is the
    # natural stop; flag it on the in_review step in that case.)
    rejected = current_status == "rejected"
    retired = current_status == "retired"

    # 'retired' = the intake completed its useful life; treat all
    # main stages as complete.
    if retired:
        steps = []
        for i, (code, label) in enumerate(_INTAKE_FLOW, start=1):
            steps.append({
                "step_order": i,
                "step_name":  label,
                "status":     "complete",
                "completed_at": None,
            })
        return steps

    # Determine which step is "active" (or the closest equivalent
    # for impact_assessment when tier is minimal).
    current_index = _INTAKE_FLOW_INDEX.get(current_status, 0)

    steps: list[dict] = []
    for i, (code, label) in enumerate(_INTAKE_FLOW, start=1):
        idx = i - 1
        if rejected:
            # If we know triage hadn't happened yet (only proposed) we
            # mark proposed as failed; otherwise we mark the stage at
            # current_index as failed.
            if idx == current_index:
                status = "failed"
            elif idx < current_index:
                status = "complete"
            else:
                status = "skipped"
        elif idx < current_index:
            status = "complete"
        elif idx == current_index:
            status = "active"
        else:
            status = "pending"

        # Minimal-tier intakes skip impact_assessment.
        if (
            code == "impact_assessment"
            and risk_tier == "minimal"
            and status != "active"
        ):
            status = "skipped"

        steps.append({
            "step_order":   i,
            "step_name":    label,
            "status":       status,
            "completed_at": None,
        })
    return steps


def _check_action(request: Request, action: str) -> None:
    """Raise 403 when current persona may not perform the action."""
    persona = get_persona(request)
    if not is_action_allowed(persona, action):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Persona '{persona.value if persona else 'viewer'}' "
                f"may not perform action '{action}'."
            ),
        )


def register_intake_studio_routes(router: APIRouter, verity, templates: Jinja2Templates) -> None:
    """Attach all intake-mode routes to the supplied router.

    Called from create_studio_routes() so we share the same router /
    templates instance and persona middleware.
    """

    # ── PERSONA SWITCHER ───────────────────────────────────────

    @router.post("/persona", response_class=HTMLResponse)
    async def switch_persona(
        request: Request, persona: str = Form(...), redirect_to: str = Form("/studio/intake"),
    ):
        """HTMX endpoint that sets the persona cookie and redirects."""
        try:
            role = StudioRole(persona)
        except ValueError:
            role = StudioRole.VIEWER
        # Use a 303 so the browser issues a fresh GET, picking up the
        # new cookie on the redirect target.
        response = RedirectResponse(url=redirect_to, status_code=303)
        return persona_cookie_response(response, role)

    # ── INTAKE LIST + DETAIL ───────────────────────────────────

    @router.get("/intake", response_class=HTMLResponse)
    async def intake_list(
        request: Request,
        application_code: str = "",
    ):
        """Intake inventory, optionally filtered by application.

        The application picker on the page submits a GET with
        ``?application_code=...`` — empty string means "all apps".
        """
        await verity.ensure_connected()
        rows = await verity.intake.list_intakes(
            business_owner_email=None,
            status=None,
            ai_risk_tier=None,
            application_code=(application_code or None),
        )
        counts = await verity.intake.dashboard_counts()
        applications = await verity.registry.list_applications()
        return _render(
            templates, request, "studio/intake_list.html",
            active_mode="intake",
            intakes=rows,
            counts=counts,
            applications=applications,
            filter_app=application_code or "",
        )

    @router.get("/intake/new", response_class=HTMLResponse)
    async def intake_new(request: Request):
        _check_action(request, ACTION_CREATE_INTAKE)
        await verity.ensure_connected()
        # Load registered applications so the form can show a picker.
        # Only registered applications can intake use cases — the form
        # offers exactly the set in governance.application, no free text.
        applications = await verity.registry.list_applications()
        return _render(
            templates, request, "studio/intake_new.html",
            active_mode="intake",
            applications=applications,
        )

    @router.post("/intake/new", response_class=HTMLResponse)
    async def intake_create(
        request: Request,
        application_code: str = Form(...),
        code: str = Form(...),
        title: str = Form(...),
        problem_statement: str = Form(...),
        expected_benefit: str = Form(...),
        business_owner_name: str = Form(...),
        business_owner_email: str = Form(""),
        requesting_team: str = Form(""),
        in_scope_decisions: str = Form(""),
        out_of_scope_decisions: str = Form(""),
        affected_populations: str = Form(""),
        ai_risk_tier: str = Form("limited"),
        risk_classification_rationale: str = Form("(pending triage)"),
        naic_materiality: str = Form("non_material"),
        notes: str = Form(""),
        hitl_strategy: str = Form(""),
        hitl_review_threshold: str = Form(""),
    ):
        _check_action(request, ACTION_CREATE_INTAKE)
        await verity.ensure_connected()
        persona = _persona_or_default(request)
        pops = [p.strip() for p in affected_populations.split(",") if p.strip()]
        try:
            row = await verity.intake.create_intake(
                application_code=application_code,
                code=code, title=title,
                problem_statement=problem_statement,
                expected_benefit=expected_benefit,
                business_owner_name=business_owner_name,
                business_owner_email=business_owner_email or None,
                requesting_team=requesting_team or None,
                in_scope_decisions=in_scope_decisions or None,
                out_of_scope_decisions=out_of_scope_decisions or None,
                affected_populations=pops,
                ai_risk_tier=AIRiskTier(ai_risk_tier),
                risk_classification_rationale=risk_classification_rationale,
                naic_materiality=naic_materiality,
                notes=notes or None,
                hitl_strategy=hitl_strategy or None,
                hitl_review_threshold=hitl_review_threshold or None,
                created_by=persona.value,
                acting_as_role=persona,
            )
        except Exception as exc:
            logger.exception("intake create failed")
            applications = await verity.registry.list_applications()
            return _render(
                templates, request, "studio/intake_new.html",
                active_mode="intake", error=str(exc),
                applications=applications,
            )
        return RedirectResponse(
            url=f"/studio/intake/{application_code}/{row['code']}",
            status_code=303,
        )

    @router.get("/intake/{app_code}/{intake_code}", response_class=HTMLResponse)
    async def intake_detail(
        request: Request,
        app_code: str,
        intake_code: str,
        tab: str = "overview",
        # Edit-mode query params. Each tab supports an in-place edit
        # branch toggled by these params; permission is checked at
        # render time so a user without the right persona never sees
        # the edit form.
        edit: str = "",            # "1" → overview tab in edit mode
        edit_req: str = "",        # "{req_code}" → that requirement row in edit mode
        edit_plan: str = "",       # "{plan_id}" → that plan row in edit mode
    ):
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, f"Intake '{app_code}/{intake_code}' not found")
        intake_id = intake["id"]
        return _render(
            templates, request, "studio/intake_detail.html",
            active_mode="intake",
            intake=intake,
            active_tab=tab,
            edit_overview=(edit == "1"),
            edit_req_code=edit_req or "",
            edit_plan_id=edit_plan or "",
            requirements=await verity.intake.list_requirements(intake_id),
            entity_links=await verity.intake.list_entity_links(intake_id),
            plan=await verity.intake.list_plan_rows(intake_id),
            impact=await verity.intake.get_impact_assessment(intake_id),
            approvals=await verity.intake.list_approval_requests(intake_id),
            REQUIRED_ROLES_BY_RISK_TIER=REQUIRED_ROLES_BY_RISK_TIER,
            workflow_steps=_intake_workflow_steps(intake),
        )

    # ── EDIT POSTS ────────────────────────────────────────────
    # Each editable tab has a single POST endpoint. Persona is checked
    # via _check_action; the underlying IntakeService methods do the
    # actual writes. All redirect back to the same tab in read-only
    # mode (303) so a refresh doesn't re-submit.

    @router.post("/intake/{app_code}/{intake_code}/edit", response_class=HTMLResponse)
    async def edit_intake_overview(
        request: Request, app_code: str, intake_code: str,
        title: str = Form(...),
        problem_statement: str = Form(...),
        expected_benefit: str = Form(...),
        in_scope_decisions: str = Form(""),
        out_of_scope_decisions: str = Form(""),
        affected_populations: str = Form(""),
        business_owner_name: str = Form(...),
        business_owner_email: str = Form(""),
        requesting_team: str = Form(""),
        notes: str = Form(""),
        hitl_strategy: str = Form(""),
        hitl_review_threshold: str = Form(""),
    ):
        _check_action(request, ACTION_EDIT_INTAKE)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        # affected_populations stays a comma-separated list — same as
        # the new-intake form, parsed into a list of strings.
        pops = [p.strip() for p in affected_populations.split(",") if p.strip()]
        try:
            await verity.intake.update_intake(
                intake["id"],
                title=title,
                problem_statement=problem_statement,
                expected_benefit=expected_benefit,
                in_scope_decisions=in_scope_decisions or None,
                out_of_scope_decisions=out_of_scope_decisions or None,
                affected_populations=pops,
                business_owner_name=business_owner_name,
                business_owner_email=business_owner_email or None,
                requesting_team=requesting_team or None,
                notes=notes or None,
                hitl_strategy=hitl_strategy or None,
                hitl_review_threshold=hitl_review_threshold or None,
            )
        except Exception as exc:
            logger.exception("intake overview edit failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=overview", status_code=303)

    @router.post("/intake/{app_code}/{intake_code}/requirements/{req_code}/update", response_class=HTMLResponse)
    async def update_requirement(
        request: Request, app_code: str, intake_code: str, req_code: str,
        kind: str = Form(...),
        statement: str = Form(...),
        acceptance_criteria: str = Form(""),
        source: str = Form(""),
        status: str = Form("draft"),
    ):
        _check_action(request, ACTION_EDIT_REQUIREMENT)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        # Resolve req by (intake_id, req_code) — the public key from the URL.
        all_reqs = await verity.intake.list_requirements(intake["id"])
        req = next((r for r in all_reqs if r["code"] == req_code), None)
        if not req:
            raise HTTPException(404, f"Requirement '{req_code}' not found")
        try:
            await verity.intake.update_requirement(
                req["id"],
                statement=statement,
                acceptance_criteria=acceptance_criteria or None,
                source=source or None,
                status=RequirementStatus(status),
            )
            # Kind is updated separately because update_requirement above
            # doesn't take a `kind` param (kind is mostly stable). Use a
            # narrow inline path: skip if unchanged.
            if req["kind"] != kind:
                # update_requirement does take parent_requirement_id and
                # status via COALESCE, but not kind — go direct via the
                # raw query to avoid extending the public service API
                # for a rare edit case.
                await verity.intake.db.execute_raw(
                    "UPDATE governance.intake_requirement "
                    "SET kind = %(kind)s::governance.requirement_kind, "
                    "    updated_at = now() "
                    "WHERE id = %(id)s",
                    {"kind": kind, "id": str(req["id"])},
                )
        except Exception as exc:
            logger.exception("requirement edit failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=requirements", status_code=303)

    @router.post("/intake/{app_code}/{intake_code}/plan/{plan_id}/update", response_class=HTMLResponse)
    async def update_plan_row(
        request: Request, app_code: str, intake_code: str, plan_id: UUID,
        proposed_name: str = Form(...),
        proposed_display_name: str = Form(...),
        proposed_description: str = Form(""),
        proposed_purpose: str = Form(""),
        status: str = Form("proposed"),
    ):
        _check_action(request, ACTION_EDIT_PLAN)
        await verity.ensure_connected()
        try:
            await verity.intake.update_plan_row(
                plan_id,
                proposed_name=proposed_name,
                proposed_display_name=proposed_display_name,
                proposed_description=proposed_description or None,
                proposed_purpose=proposed_purpose or None,
                status=ArtifactPlanStatus(status),
            )
        except Exception as exc:
            logger.exception("plan row edit failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=plan", status_code=303)

    # ── TRIAGE / RECLASSIFY ────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/triage", response_class=HTMLResponse)
    async def intake_triage(
        request: Request, app_code: str, intake_code: str,
        ai_risk_tier: str = Form(...),
        naic_materiality: str = Form(...),
        risk_classification_rationale: str = Form(...),
    ):
        _check_action(request, ACTION_TRIAGE_INTAKE)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        try:
            await verity.intake.triage_intake(
                intake["id"],
                ai_risk_tier=AIRiskTier(ai_risk_tier),
                naic_materiality=naic_materiality,
                risk_classification_rationale=risk_classification_rationale,
            )
        except Exception as exc:
            logger.exception("triage failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=overview", status_code=303)

    # ── REQUIREMENTS ───────────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/requirements/add", response_class=HTMLResponse)
    async def add_requirement(
        request: Request, app_code: str, intake_code: str,
        req_code: str = Form(...),
        kind: str = Form(...),
        statement: str = Form(...),
        acceptance_criteria: str = Form(""),
        source: str = Form(""),
    ):
        _check_action(request, ACTION_EDIT_REQUIREMENT)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        persona = _persona_or_default(request)
        try:
            await verity.intake.add_requirement(
                intake["id"],
                code=req_code,
                kind=RequirementKind(kind),
                statement=statement,
                acceptance_criteria=acceptance_criteria or None,
                source=source or None,
                created_by=persona.value,
                acting_as_role=persona,
            )
        except Exception as exc:
            logger.exception("add_requirement failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=requirements", status_code=303)

    @router.post("/intake/{app_code}/{intake_code}/requirements/redundancy-check", response_class=HTMLResponse)
    async def redundancy_check_partial(
        request: Request, app_code: str, intake_code: str,
        statement: str = Form(""),
    ):
        await verity.ensure_connected()
        if not statement.strip():
            return HTMLResponse("")
        try:
            hits = await verity.intake.search_similar_requirements(
                statement=statement, top_n=5, min_similarity=0.78,
            )
        except Exception as exc:
            logger.warning("redundancy_check failed: %s", exc)
            return HTMLResponse("")
        return _render(
            templates, request, "studio/_partials/redundancy_hint.html",
            hits=hits,
        )

    # ── IMPACT ASSESSMENT ──────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/impact", response_class=HTMLResponse)
    async def upsert_impact(
        request: Request, app_code: str, intake_code: str,
        fairness_considerations: str = Form(""),
        privacy_considerations: str = Form(""),
        human_oversight_plan: str = Form(""),
        notes: str = Form(""),
        completed: str = Form(""),
        # Structured-array fields surfaced as JSON textareas. Empty
        # value → reset to []; malformed JSON → 400 (handled below).
        data_sources_json: str = Form(""),
        potential_harms_json: str = Form(""),
        mitigations_json: str = Form(""),
    ):
        _check_action(request, ACTION_EDIT_IMPACT_ASSESSMENT)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        persona = _persona_or_default(request)

        # Parse JSON textareas. Empty stays empty; bad JSON returns 400
        # with a clear pointer rather than letting psycopg surface a
        # cryptic JSONB cast error.
        import json as _json

        def _parse_jsonb_array(label: str, raw: str) -> list:
            raw = (raw or "").strip()
            if not raw:
                return []
            try:
                parsed = _json.loads(raw)
            except _json.JSONDecodeError as exc:
                raise HTTPException(
                    400,
                    f"{label} is not valid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno}).",
                )
            if not isinstance(parsed, list):
                raise HTTPException(400, f"{label} must be a JSON array.")
            return parsed

        try:
            await verity.intake.upsert_impact_assessment(
                intake["id"],
                completed_by=persona.value,
                completed=bool(completed),
                data_sources=_parse_jsonb_array("Data sources", data_sources_json),
                potential_harms=_parse_jsonb_array("Potential harms", potential_harms_json),
                mitigations=_parse_jsonb_array("Mitigations", mitigations_json),
                fairness_considerations=fairness_considerations or None,
                privacy_considerations=privacy_considerations or None,
                human_oversight_plan=human_oversight_plan or None,
                notes=notes or None,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("upsert_impact failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=impact", status_code=303)

    # ── APPROVALS ──────────────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/approvals/{request_id}/signoff", response_class=HTMLResponse)
    async def signoff(
        request: Request, app_code: str, intake_code: str, request_id: UUID,
        approver_name: str = Form(...),
        approver_email: str = Form(""),
        decision: str = Form(...),
        comment: str = Form(""),
        evidence_url: str = Form(""),
    ):
        """Record an approval signoff.

        The signoff *role* is derived from the current persona — never
        accepted from form input — so a user acting as one role cannot
        sign as another. Server-side checks:

          1. Persona must be one of the approval-eligible roles
             (engineer / auditor / viewer cannot sign).
          2. Persona's role must be in the approval request's
             required_roles list. Otherwise the signoff is rejected.

        Identity (approver_name, approver_email) remains free-text for
        the demo — there is no real auth yet — but role spoofing is
        eliminated.
        """
        _check_action(request, ACTION_SIGNOFF)
        await verity.ensure_connected()

        persona = get_persona(request)
        if persona is None:
            raise HTTPException(403, "No persona selected; cannot sign off.")

        # Persona → ApprovalRole. Engineer/auditor/viewer don't have
        # a corresponding ApprovalRole — fail closed.
        try:
            signing_role = ApprovalRole(persona.value)
        except ValueError:
            raise HTTPException(
                403,
                f"Persona '{persona.value}' is not an approver role; "
                f"switch to a role allowed to sign approvals.",
            )

        # Verify the role is required on this specific request.
        # Reject impostor signoffs (e.g. compliance signing as legal).
        approval_request = await verity.intake.db.fetch_one(
            "get_approval_request", {"id": str(request_id)},
        )
        if not approval_request:
            raise HTTPException(404, "Approval request not found.")
        required = approval_request.get("required_roles") or []
        # required_roles is JSONB — psycopg may surface as list or str.
        if isinstance(required, str):
            import json as _json
            required = _json.loads(required)
        if signing_role.value not in required:
            raise HTTPException(
                403,
                f"Persona '{persona.value}' is not in this request's "
                f"required roles ({', '.join(required)}). Switch persona "
                f"to one of those roles to sign.",
            )

        try:
            await verity.intake.signoff(
                request_id,
                role=signing_role,
                approver_name=approver_name,
                approver_email=approver_email or None,
                decision=ApprovalDecision(decision),
                comment=comment or None,
                evidence_url=evidence_url or None,
            )
        except Exception as exc:
            logger.exception("signoff failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=approvals", status_code=303)

    # ── ARTIFACT PLAN ──────────────────────────────────────────

    @router.post("/intake/{app_code}/{intake_code}/plan/generate", response_class=HTMLResponse)
    async def generate_plan(request: Request, app_code: str, intake_code: str):
        _check_action(request, ACTION_GENERATE_PLAN)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        try:
            await _generate_plan(verity.intake, intake["id"])
        except Exception as exc:
            logger.exception("plan generation failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(url=f"/studio/intake/{app_code}/{intake_code}?tab=plan", status_code=303)

    @router.post("/intake/{app_code}/{intake_code}/plan/{plan_id}/delete", response_class=HTMLResponse)
    async def plan_delete(request: Request, app_code: str, intake_code: str, plan_id: UUID):
        """Hard-delete a plan row.

        Cleaner than soft-cancelling: the (intake_id, kind, name) tuple
        is unique, so a soft-delete row would block a future re-run of
        the plan generator from re-creating that artifact. Hard delete
        means re-running naturally restores rows the requirements still
        warrant.

        Realized rows are NOT deletable through this endpoint — once a
        plan row maps to a registered registry entity, the engineer
        should retire/deprecate the entity properly rather than orphan
        the link by deleting the plan row underneath. Returns 409 if a
        caller hits this on a realized row.
        """
        _check_action(request, ACTION_EDIT_PLAN)
        await verity.ensure_connected()
        existing = await verity.intake.db.fetch_one(
            "get_artifact_plan_row", {"id": str(plan_id)},
        )
        if existing and existing.get("status") == "realized":
            raise HTTPException(
                409,
                "Plan row is realized to a registry entity; "
                "deprecate the entity rather than deleting the plan row.",
            )
        await verity.intake.delete_plan_row(plan_id)
        return RedirectResponse(
            url=f"/studio/intake/{app_code}/{intake_code}?tab=plan",
            status_code=303,
        )

    @router.post("/intake/{app_code}/{intake_code}/plan/add", response_class=HTMLResponse)
    async def plan_add(
        request: Request, app_code: str, intake_code: str,
        proposed_kind: str = Form(...),
        proposed_name: str = Form(...),
        proposed_display_name: str = Form(...),
        proposed_materiality_tier: str = Form(...),
        proposed_capability_type: str = Form(""),
        proposed_purpose: str = Form(""),
        proposed_description: str = Form(""),
    ):
        """Add a plan row manually — for artifacts the rule-based
        generator didn't catch, or that an engineer wants to plan
        ahead of intake approval."""
        _check_action(request, ACTION_EDIT_PLAN)
        await verity.ensure_connected()
        intake = await verity.intake.get_intake_by_code(app_code, intake_code)
        if not intake:
            raise HTTPException(404, "Intake not found")
        persona = _persona_or_default(request)
        try:
            await verity.intake.add_plan_row(
                intake["id"],
                proposed_kind=LinkedEntityKind(proposed_kind),
                proposed_name=proposed_name,
                proposed_display_name=proposed_display_name,
                proposed_materiality_tier=proposed_materiality_tier,
                proposed_capability_type=proposed_capability_type or None,
                proposed_purpose=proposed_purpose or None,
                proposed_description=proposed_description or None,
                auto_generated=False,
                created_by=persona.value,
                acting_as_role=persona,
            )
        except Exception as exc:
            logger.exception("plan_add failed")
            raise HTTPException(400, str(exc))
        return RedirectResponse(
            url=f"/studio/intake/{app_code}/{intake_code}?tab=plan", status_code=303,
        )

    # ── GOVERNANCE DASHBOARD ───────────────────────────────────

    @router.get("/governance/dashboard", response_class=HTMLResponse)
    async def governance_dashboard(request: Request):
        await verity.ensure_connected()
        return _render(
            templates, request, "studio/governance_dashboard.html",
            active_mode="intake",
            counts=await verity.intake.dashboard_counts(),
        )
