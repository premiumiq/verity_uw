"""UW Demo Routes — Underwriting workbench workflow pages.

Two pages:
1. Submissions list (/) — KPI cards + submissions table
2. Submission detail (/submissions/{id}) — stepper, cards, tabs, action buttons

Tab content is loaded via HTMX (no full page reload):
- /submissions/{id}/tab/details
- /submissions/{id}/tab/extraction
- /submissions/{id}/tab/assessment
- /submissions/{id}/tab/loss-history
- /submissions/{id}/tab/audit-trail

Pipeline actions (POST, returns HTMX partials):
- /submissions/{id}/process-documents — Pipeline 1 (classify + extract)
- /submissions/{id}/approve-extraction — HITL approval
- /submissions/{id}/assess-risk — Pipeline 2 (triage + appetite)

No mock/live toggle in the UI. Use APP_ENV=demo for mock, APP_ENV=live for real.
"""

import base64
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import httpx
import psycopg

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from uw_demo.app.config import settings
from uw_demo.app.pipeline import (
    get_mock_context_doc_processing,
    get_mock_context_risk_assessment,
)


TEMPLATES_DIR = Path(__file__).parent / "templates"


def _enum_value(value):
    """Jinja2 filter: extract .value from enums."""
    if isinstance(value, Enum):
        return value.value
    return value


# ══════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ══════════════════════════════════════════════════════════════

async def _get_conn():
    """Get an async connection to uw_db."""
    return await psycopg.AsyncConnection.connect(settings.UW_DB_URL)


async def _get_setting(key: str, default: str = "") -> str:
    """Read a setting from app_settings table. No restart needed to change."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT value FROM app_settings WHERE key = %s", (key,))
            row = await cur.fetchone()
            return row[0] if row else default


async def _use_mock() -> bool:
    """Check if pipelines should use mock mode. Reads from DB on every call."""
    mode = await _get_setting("pipeline_mode", "mock")
    return mode != "live"


async def _get_submissions():
    """Read all submissions from uw_db."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM submission ORDER BY created_at")
            cols = [d.name for d in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def _get_submission(submission_id: str):
    """Read a single submission."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM submission WHERE id = %s", (submission_id,))
            row = await cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))


async def _get_extractions(submission_id: str):
    """Read extraction records for a submission."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM submission_extraction WHERE submission_id = %s ORDER BY field_name",
                (submission_id,),
            )
            cols = [d.name for d in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def _get_assessments(submission_id: str):
    """Read assessments for a submission. Returns {assessment_type: row}."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM submission_assessment WHERE submission_id = %s",
                (submission_id,),
            )
            cols = [d.name for d in cur.description]
            rows = await cur.fetchall()
            return {r["assessment_type"]: r for r in [dict(zip(cols, row)) for row in rows]}


async def _get_workflow_steps(submission_id: str):
    """Read workflow steps ordered by step_order."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM workflow_step WHERE submission_id = %s ORDER BY step_order",
                (submission_id,),
            )
            cols = [d.name for d in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def _get_loss_history(submission_id: str):
    """Read loss history for a submission."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM loss_history WHERE submission_id = %s ORDER BY policy_year",
                (submission_id,),
            )
            cols = [d.name for d in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


async def _update_workflow_step(submission_id: str, step_name: str, status: str,
                                  pipeline_run_id=None, completed_by=None):
    """Update a workflow step's status."""
    now = datetime.now(timezone.utc)
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            if status == "running":
                await cur.execute(
                    """UPDATE workflow_step SET status = %s, started_at = %s
                    WHERE submission_id = %s AND step_name = %s""",
                    (status, now, submission_id, step_name),
                )
            elif status in ("complete", "failed", "skipped"):
                await cur.execute(
                    """UPDATE workflow_step SET status = %s, completed_at = %s,
                        completed_by = %s, pipeline_run_id = %s
                    WHERE submission_id = %s AND step_name = %s""",
                    (status, now, completed_by, pipeline_run_id, submission_id, step_name),
                )
            else:
                await cur.execute(
                    "UPDATE workflow_step SET status = %s WHERE submission_id = %s AND step_name = %s",
                    (status, submission_id, step_name),
                )
        await conn.commit()


async def _update_submission_status(submission_id: str, status: str, **kwargs):
    """Update submission status and optional fields."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            # Build dynamic SET clause for extra fields
            sets = ["status = %s", "updated_at = NOW()"]
            params = [status]
            for key, val in kwargs.items():
                sets.append(f"{key} = %s")
                params.append(val)
            params.append(submission_id)
            await cur.execute(
                f"UPDATE submission SET {', '.join(sets)} WHERE id = %s",
                params,
            )
        await conn.commit()


async def _get_status_counts():
    """Count submissions grouped by status for KPI cards."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT status, COUNT(*) FROM submission GROUP BY status")
            rows = await cur.fetchall()
            return {row[0]: row[1] for row in rows}


def _compute_next_action(sub: dict, submission_id: str) -> dict | None:
    """Compute the contextual next action based on submission status."""
    status = sub["status"]
    sid = str(submission_id)
    if status == "intake":
        return {"label": "Process Documents", "url": f"/submissions/{sid}/process-documents", "method": "POST"}
    elif status == "review":
        return {"label": "Review & Approve Fields", "tab": "extraction"}
    elif status in ("approved", "documents_processed"):
        return {"label": "Assess Risk", "url": f"/submissions/{sid}/assess-risk", "method": "POST"}
    return None  # assessed, triaged = complete


# ══════════════════════════════════════════════════════════════
# EDMS HELPERS
# ══════════════════════════════════════════════════════════════

async def _fetch_documents_from_edms(submission_id: str):
    """Fetch documents from EDMS with content and text for pipeline input."""
    context_ref = f"submission:{submission_id}"
    documents = []

    async with httpx.AsyncClient(base_url=settings.EDMS_URL, timeout=30.0) as http:
        resp = await http.get("/documents", params={"context_ref": context_ref})
        if resp.status_code != 200:
            return []
        docs = resp.json().get("documents", [])

        for doc in docs:
            doc_id = doc["id"]
            # Get PDF bytes for classifier (base64 for Claude content blocks)
            try:
                resp = await http.get(f"/documents/{doc_id}/content")
                resp.raise_for_status()
                doc["content_base64"] = base64.b64encode(resp.content).decode()
            except Exception:
                doc["content_base64"] = None

            # Get extracted text for field extractor
            try:
                resp = await http.get(f"/documents/{doc_id}/text")
                resp.raise_for_status()
                doc["extracted_text"] = resp.json().get("text", "")
            except Exception:
                doc["extracted_text"] = ""

            documents.append(doc)
    return documents


# ══════════════════════════════════════════════════════════════
# ROUTE FACTORY
# ══════════════════════════════════════════════════════════════

def create_uw_routes(verity) -> APIRouter:
    """Create all UW business workflow routes."""
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.finalize = _enum_value

    # ── SETTINGS TOGGLE ──────────────────────────────────────

    @router.post("/settings/pipeline-mode", response_class=HTMLResponse)
    async def toggle_pipeline_mode(request: Request):
        """Toggle pipeline_mode between mock and live. Returns HTMX partial for sidebar toggle."""
        form = await request.form()
        new_mode = form.get("mode", "mock")
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "UPDATE app_settings SET value = %s, updated_at = NOW() WHERE key = 'pipeline_mode'",
                    (new_mode,),
                )
            await conn.commit()

        # Return just the toggle button HTML (HTMX swaps it into the sidebar)
        if new_mode == "live":
            return HTMLResponse(
                '<div style="font-size: 0.6rem; text-transform: uppercase; color: rgba(255,255,255,0.4); letter-spacing: 0.3px; margin-bottom: 4px;">Pipeline Mode</div>'
                '<form hx-post="/settings/pipeline-mode" hx-target="#pipeline-mode-toggle" hx-swap="innerHTML">'
                '<button type="submit" name="mode" value="mock" class="verity-btn verity-btn-sm" '
                'style="background: var(--verity-green); color: white; border: none; width: 100%;">'
                'LIVE — Click for Mock</button></form>'
            )
        else:
            return HTMLResponse(
                '<div style="font-size: 0.6rem; text-transform: uppercase; color: rgba(255,255,255,0.4); letter-spacing: 0.3px; margin-bottom: 4px;">Pipeline Mode</div>'
                '<form hx-post="/settings/pipeline-mode" hx-target="#pipeline-mode-toggle" hx-swap="innerHTML">'
                '<button type="submit" name="mode" value="live" class="verity-btn verity-btn-sm" '
                'style="background: var(--verity-amber); color: white; border: none; width: 100%;">'
                'MOCK — Click for Live</button></form>'
            )

    # ── SUBMISSIONS LIST ──────────────────────────────────────

    @router.get("/", response_class=HTMLResponse)
    async def submissions_list(request: Request):
        """Dashboard: KPI cards + submissions table."""
        submissions = await _get_submissions()
        status_counts = await _get_status_counts()

        # Enrich with assessment results for display
        for sub in submissions:
            assessments = await _get_assessments(str(sub["id"]))
            triage = assessments.get("triage", {})
            appetite = assessments.get("appetite", {})
            sub["risk_score"] = triage.get("risk_score")
            sub["appetite"] = appetite.get("determination")

        pipeline_mode = await _get_setting("pipeline_mode", "mock")
        return templates.TemplateResponse(request, "submissions.html", {
            "active_page": "submissions",
            "submissions": submissions,
            "status_counts": status_counts,
            "pipeline_mode": pipeline_mode,
        })

    # ── SUBMISSION DETAIL ─────────────────────────────────────

    @router.get("/submissions/{submission_id}", response_class=HTMLResponse)
    async def submission_detail(request: Request, submission_id: str):
        """Main detail page with stepper, cards, tabs."""
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        workflow_steps = await _get_workflow_steps(submission_id)
        extractions = await _get_extractions(submission_id)
        assessments = await _get_assessments(submission_id)
        review_count = sum(1 for e in extractions if e.get("needs_review"))
        next_action = _compute_next_action(sub, submission_id)
        run_id = str(sub.get("last_risk_pipeline_run_id") or sub.get("last_doc_pipeline_run_id") or "")

        pipeline_mode = await _get_setting("pipeline_mode", "mock")
        return templates.TemplateResponse(request, "submission_detail.html", {
            "active_page": "submissions",
            "sub": sub,
            "workflow_steps": workflow_steps,
            "assessments": assessments,
            "next_action": next_action,
            "review_count": review_count,
            "run_id": run_id if run_id else None,
            "pipeline_mode": pipeline_mode,
        })

    # ── TAB PARTIALS (HTMX) ──────────────────────────────────

    @router.get("/submissions/{submission_id}/tab/details", response_class=HTMLResponse)
    async def tab_details(request: Request, submission_id: str):
        sub = await _get_submission(submission_id)
        return templates.TemplateResponse(request, "partials/_tab_details.html", {"sub": sub})

    @router.get("/submissions/{submission_id}/tab/extraction", response_class=HTMLResponse)
    async def tab_extraction(request: Request, submission_id: str):
        sub = await _get_submission(submission_id)
        extractions = await _get_extractions(submission_id)
        return templates.TemplateResponse(request, "partials/_tab_extraction.html", {
            "sub": sub,
            "extractions": extractions,
            "is_review_mode": sub["status"] == "review",
        })

    @router.get("/submissions/{submission_id}/tab/assessment", response_class=HTMLResponse)
    async def tab_assessment(request: Request, submission_id: str):
        assessments = await _get_assessments(submission_id)
        return templates.TemplateResponse(request, "partials/_tab_assessment.html", {
            "assessments": assessments,
        })

    @router.get("/submissions/{submission_id}/tab/loss-history", response_class=HTMLResponse)
    async def tab_loss_history(request: Request, submission_id: str):
        loss_history = await _get_loss_history(submission_id)
        total_claims = sum(l["claims_count"] for l in loss_history)
        total_incurred = sum(float(l["incurred"]) for l in loss_history)
        total_paid = sum(float(l["paid"]) for l in loss_history)
        total_reserves = sum(float(l["reserves"]) for l in loss_history)
        return templates.TemplateResponse(request, "partials/_tab_loss_history.html", {
            "loss_history": loss_history,
            "total_claims": total_claims,
            "total_incurred": total_incurred,
            "total_paid": total_paid,
            "total_reserves": total_reserves,
        })

    @router.get("/submissions/{submission_id}/tab/audit-trail", response_class=HTMLResponse)
    async def tab_audit_trail(request: Request, submission_id: str):
        await verity.ensure_connected()
        sub = await _get_submission(submission_id)
        trail = []
        run_id = sub.get("last_risk_pipeline_run_id") or sub.get("last_doc_pipeline_run_id")
        if run_id:
            trail = await verity.get_audit_trail_by_run(str(run_id))
        return templates.TemplateResponse(request, "partials/_tab_audit_trail.html", {
            "trail": trail,
            "run_id": str(run_id) if run_id else None,
        })

    # ── PIPELINE 1: DOCUMENT PROCESSING ──────────────────────

    @router.post("/submissions/{submission_id}/process-documents", response_class=HTMLResponse)
    async def run_document_processing(request: Request, submission_id: str):
        """Run Pipeline 1: classify documents + extract fields.

        Pre-fetches documents from EDMS, sends PDFs to classifier as
        content blocks, sends extracted text to field extractor.
        No mock/live toggle — controlled by APP_ENV.
        """
        await verity.ensure_connected()

        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # Update workflow step
        await _update_workflow_step(submission_id, "document_processing", "running")

        # Create Verity execution context
        try:
            ctx = await verity.create_execution_context(
                context_ref=f"submission:{submission_id}",
                context_type="submission",
                metadata={"named_insured": sub["named_insured"], "lob": sub["lob"]},
            )
            exec_ctx_id = ctx["id"]
        except Exception:
            exec_ctx_id = None

        # Fetch documents from EDMS
        documents = await _fetch_documents_from_edms(submission_id)

        # Build pipeline context with document content
        doc_blocks = []
        all_extracted_text = []
        for doc in documents:
            if doc.get("content_base64") and doc.get("content_type", "").startswith("application/pdf"):
                doc_blocks.append({
                    "data": doc["content_base64"],
                    "media_type": "application/pdf",
                })
            if doc.get("extracted_text"):
                all_extracted_text.append(doc["extracted_text"])

        pipeline_context = {
            "submission_id": submission_id,
            "lob": sub["lob"],
            "named_insured": sub["named_insured"],
            "document_count": str(len(documents)),
            "_documents": doc_blocks,
            "document_text": "\n\n---\n\n".join(all_extracted_text) if all_extracted_text else "(no documents found)",
        }

        # Execute pipeline
        import json
        import logging
        logger = logging.getLogger("uw_demo.pipeline")

        try:
            use_mock = await _use_mock()
            if use_mock:
                mock = get_mock_context_doc_processing(submission_id)
                result = await verity.execute_pipeline(
                    pipeline_name="uw_document_processing",
                    context=pipeline_context,
                    mock=mock,
                    execution_context_id=exec_ctx_id,
                )
            else:
                result = await verity.execute_pipeline(
                    pipeline_name="uw_document_processing",
                    context=pipeline_context,
                    execution_context_id=exec_ctx_id,
                )
        except Exception as e:
            logger.error(f"Pipeline 1 execution failed for {submission_id}: {e}")
            await _update_workflow_step(submission_id, "document_processing", "failed",
                                         completed_by=f"error: {str(e)[:200]}")
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        run_id = str(result.pipeline_run_id)

        # Check pipeline result — handle failure
        if result.status == "failed":
            error_msg = ""
            for step in result.all_steps:
                if step.status == "failed":
                    error_msg = step.error_message or "Unknown error"
                    break
            logger.error(f"Pipeline 1 failed for {submission_id}: {error_msg}")
            await _update_workflow_step(submission_id, "document_processing", "failed",
                                         pipeline_run_id=run_id,
                                         completed_by=f"error: {error_msg[:200]}")
            await _update_submission_status(submission_id, "intake",
                                             last_doc_pipeline_run_id=run_id)
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        # Pipeline succeeded — update workflow
        await _update_workflow_step(submission_id, "document_processing", "complete",
                                     pipeline_run_id=run_id, completed_by="system")
        await _update_submission_status(submission_id, "documents_processed",
                                         last_doc_pipeline_run_id=run_id,
                                         execution_context_id=str(exec_ctx_id) if exec_ctx_id else None)

        # Write extraction results to uw_db from pipeline output.
        # Read directly from result.all_steps (works for both mock and live mode).
        from uw_demo.app.tools.submission_tools import store_extraction_result
        extract_step = next((s for s in result.all_steps if s.step_name == "extract_fields"), None)
        if (extract_step and extract_step.status == "complete"
                and extract_step.execution_result and extract_step.execution_result.output):
            output = extract_step.execution_result.output
            await store_extraction_result(
                submission_id=submission_id,
                fields=output.get("fields", {}),
                low_confidence_fields=output.get("low_confidence_fields", []),
                unextractable_fields=output.get("unextractable_fields", []),
            )

        # Check if HITL review is needed
        extractions = await _get_extractions(submission_id)
        needs_review = any(e.get("needs_review") for e in extractions)

        if needs_review:
            # Hold for human review
            await _update_workflow_step(submission_id, "extraction_review", "running")
            await _update_submission_status(submission_id, "review")
        else:
            # No flags — skip review and auto-trigger Pipeline 2
            await _update_workflow_step(submission_id, "extraction_review", "skipped",
                                         completed_by="auto (no flags)")
            await _update_submission_status(submission_id, "approved")

            # Auto-trigger Pipeline 2 (risk assessment)
            await _run_risk_assessment_internal(verity, submission_id, sub, templates)

        # Redirect back to detail page
        return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

    # ── HITL EXTRACTION APPROVAL ─────────────────────────────

    @router.post("/submissions/{submission_id}/approve-extraction", response_class=HTMLResponse)
    async def approve_extraction(request: Request, submission_id: str):
        """Process HITL overrides and advance workflow."""
        form = await request.form()

        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                for key, value in form.items():
                    if key.startswith("override_") and value:
                        field_name = key.replace("override_", "")
                        reason = form.get(f"reason_{field_name}", "Manual correction")
                        reviewer = form.get("reviewer_name", "Underwriter")

                        await cur.execute(
                            """UPDATE submission_extraction SET
                                overridden = TRUE, override_value = %s,
                                overridden_by = %s, override_reason = %s,
                                override_at = NOW(), needs_review = FALSE
                            WHERE submission_id = %s AND field_name = %s""",
                            (value, reviewer, reason, submission_id, field_name),
                        )

                # Clear remaining flags (accepted as-is)
                await cur.execute(
                    "UPDATE submission_extraction SET needs_review = FALSE WHERE submission_id = %s AND needs_review = TRUE",
                    (submission_id,),
                )
            await conn.commit()

        # Update workflow
        reviewer = form.get("reviewer_name", "Underwriter")
        await _update_workflow_step(submission_id, "extraction_review", "complete",
                                     completed_by=reviewer)
        await _update_submission_status(submission_id, "approved")

        # Auto-trigger Pipeline 2 after HITL approval
        await verity.ensure_connected()
        sub = await _get_submission(submission_id)
        await _run_risk_assessment_internal(verity, submission_id, sub, templates)

        # Redirect back to detail page
        return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

    # ── PIPELINE 2: RISK ASSESSMENT ──────────────────────────

    @router.post("/submissions/{submission_id}/assess-risk", response_class=HTMLResponse)
    async def run_risk_assessment(request: Request, submission_id: str):
        """Run Pipeline 2: triage + appetite using finalized fields from uw_db."""
        await verity.ensure_connected()
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        await _run_risk_assessment_internal(verity, submission_id, sub, templates)
        return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

    return router


# ══════════════════════════════════════════════════════════════
# INTERNAL: Risk assessment pipeline runner
# ══════════════════════════════════════════════════════════════
# Extracted so it can be called both from the manual "Assess Risk"
# button AND from the auto-trigger after clean extraction.

async def _run_risk_assessment_internal(verity, submission_id: str, sub: dict, templates):
    """Run Pipeline 2 and write results to uw_db.

    Handles pipeline failures gracefully — if the pipeline fails
    (e.g., Claude API overloaded), workflow steps are set to 'failed'
    and submission status reverts to 'approved' so the user can retry.
    """
    import json
    import logging

    logger = logging.getLogger("uw_demo.pipeline")

    await _update_workflow_step(submission_id, "triage", "running")

    # Create execution context
    try:
        ctx = await verity.create_execution_context(
            context_ref=f"submission:{submission_id}",
            context_type="submission",
            metadata={"named_insured": sub["named_insured"], "lob": sub["lob"]},
        )
        exec_ctx_id = ctx["id"]
    except Exception:
        exec_ctx_id = None

    pipeline_context = {
        "submission_id": submission_id,
        "lob": sub["lob"],
        "named_insured": sub["named_insured"],
    }

    # Execute pipeline
    try:
        use_mock = await _use_mock()
        if use_mock:
            mock = get_mock_context_risk_assessment(submission_id)
            result = await verity.execute_pipeline(
                pipeline_name="uw_risk_assessment",
                context=pipeline_context,
                mock=mock,
                execution_context_id=exec_ctx_id,
            )
        else:
            result = await verity.execute_pipeline(
                pipeline_name="uw_risk_assessment",
                context=pipeline_context,
                execution_context_id=exec_ctx_id,
            )
    except Exception as e:
        logger.error(f"Pipeline 2 execution failed for {submission_id}: {e}")
        await _update_workflow_step(submission_id, "triage", "failed",
                                     completed_by=f"error: {str(e)[:200]}")
        await _update_submission_status(submission_id, "approved")
        return

    # Check pipeline result status
    run_id = str(result.pipeline_run_id)

    if result.status == "failed":
        # Pipeline ran but steps failed (e.g., Claude API overloaded)
        error_msg = ""
        for step in result.all_steps:
            if step.status == "failed":
                error_msg = step.error_message or "Unknown error"
                break
        logger.error(f"Pipeline 2 failed for {submission_id}: {error_msg}")
        await _update_workflow_step(submission_id, "triage", "failed",
                                     pipeline_run_id=run_id, completed_by=f"error: {error_msg[:200]}")
        await _update_submission_status(submission_id, "approved",
                                         last_risk_pipeline_run_id=run_id)
        return

    # Pipeline succeeded — update workflow steps per actual step status
    for step in result.all_steps:
        if step.step_name in ("triage_submission", "assess_appetite"):
            wf_name = "triage" if step.step_name == "triage_submission" else "appetite"
            if step.status == "complete":
                await _update_workflow_step(submission_id, wf_name, "complete",
                                             pipeline_run_id=run_id, completed_by="system")
            elif step.status == "failed":
                await _update_workflow_step(submission_id, wf_name, "failed",
                                             pipeline_run_id=run_id,
                                             completed_by=f"error: {step.error_message or 'unknown'}"[:200])
            elif step.status == "skipped":
                await _update_workflow_step(submission_id, wf_name, "skipped",
                                             pipeline_run_id=run_id, completed_by="system")

    # Write assessment results to uw_db from pipeline output
    triage_step = next((s for s in result.all_steps if s.step_name == "triage_submission"), None)
    appetite_step = next((s for s in result.all_steps if s.step_name == "assess_appetite"), None)

    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            if (triage_step and triage_step.status == "complete"
                    and triage_step.execution_result and triage_step.execution_result.output):
                t = triage_step.execution_result.output
                await cur.execute(
                    """INSERT INTO submission_assessment (
                        submission_id, assessment_type, result,
                        risk_score, routing, confidence, reasoning, pipeline_run_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, assessment_type) DO UPDATE SET
                        result = EXCLUDED.result, risk_score = EXCLUDED.risk_score,
                        routing = EXCLUDED.routing, confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning, pipeline_run_id = EXCLUDED.pipeline_run_id,
                        created_at = NOW()
                    """,
                    (submission_id, "triage", json.dumps(t),
                     t.get("risk_score"), t.get("routing"),
                     t.get("confidence"), t.get("reasoning"), run_id),
                )

            if (appetite_step and appetite_step.status == "complete"
                    and appetite_step.execution_result and appetite_step.execution_result.output):
                a = appetite_step.execution_result.output
                await cur.execute(
                    """INSERT INTO submission_assessment (
                        submission_id, assessment_type, result,
                        determination, confidence, reasoning, pipeline_run_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, assessment_type) DO UPDATE SET
                        result = EXCLUDED.result, determination = EXCLUDED.determination,
                        confidence = EXCLUDED.confidence, reasoning = EXCLUDED.reasoning,
                        pipeline_run_id = EXCLUDED.pipeline_run_id, created_at = NOW()
                    """,
                    (submission_id, "appetite", json.dumps(a),
                     a.get("determination"), a.get("confidence"),
                     a.get("reasoning"), run_id),
                )
        await conn.commit()

    # Set final submission status based on what completed
    all_complete = all(
        s.status == "complete" for s in result.all_steps
    )
    if all_complete:
        await _update_submission_status(submission_id, "assessed",
                                         last_risk_pipeline_run_id=run_id)
    else:
        await _update_submission_status(submission_id, "approved",
                                         last_risk_pipeline_run_id=run_id)
