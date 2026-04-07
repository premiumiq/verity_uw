"""UW Demo Routes — Business workflow pages.

These routes serve the underwriter-facing UI:
- Submission list at /uw/
- Submission detail at /uw/submissions/{id}
- Pipeline runner at /uw/submissions/{id}/pipeline

AI results come from Verity's decision log.
Submission metadata comes from the static SUBMISSIONS list in pipeline.py.

MOCK vs LIVE:
- Mock: builds MockContext from pre-built outputs → goes through Verity
  execution engine → skips Claude → logs decisions normally
- Live: no MockContext → execution engine calls Claude for real

Both paths produce identical governance trails in Verity.
"""

from enum import Enum
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from uw_demo.app.pipeline import (
    SUBMISSIONS,
    SUBMISSIONS_BY_ID,
    get_mock_context,
)


TEMPLATES_DIR = Path(__file__).parent / "templates"


def _enum_value(value):
    """Same enum filter used by Verity web."""
    if isinstance(value, Enum):
        return value.value
    return value


def create_uw_routes(verity) -> APIRouter:
    """Create all UW business workflow routes."""
    router = APIRouter()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.finalize = _enum_value

    # ── SUBMISSIONS LIST ──────────────────────────────────────

    @router.get("/", response_class=HTMLResponse)
    async def submissions_list(request: Request):
        """Show all submissions with status badges."""
        return templates.TemplateResponse(request, "submissions.html", {
            "active_page": "submissions",
            "submissions": SUBMISSIONS,
        })

    # ── SUBMISSION DETAIL ─────────────────────────────────────

    @router.get("/submissions/{submission_id}", response_class=HTMLResponse)
    async def submission_detail(request: Request, submission_id: str):
        """Show one submission with all AI results from Verity decision log."""
        await verity.ensure_connected()

        sub = SUBMISSIONS_BY_ID.get(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # Get audit trail using Verity-owned IDs (never business keys)
        trail = []
        if sub.get("last_pipeline_run_id"):
            trail = await verity.get_audit_trail_by_run(sub["last_pipeline_run_id"])
        elif sub.get("last_execution_context_id"):
            trail = await verity.get_audit_trail(sub["last_execution_context_id"])

        # Get any overrides linked to decisions for this submission's pipeline run
        overrides = []
        if sub.get("last_pipeline_run_id"):
            override_rows = await verity.db.fetch_all_raw(
                "SELECT ol.* FROM override_log ol "
                "JOIN agent_decision_log adl ON adl.id = ol.decision_log_id "
                "WHERE adl.pipeline_run_id = %(run_id)s::uuid",
                {"run_id": sub["last_pipeline_run_id"]},
            )
            if override_rows:
                overrides = override_rows

        return templates.TemplateResponse(request, "submission_detail.html", {
            "active_page": "submissions",
            "sub": sub,
            "trail": trail,
            "overrides": overrides,
        })

    # ── PIPELINE RUNNER ───────────────────────────────────────

    @router.get("/submissions/{submission_id}/pipeline", response_class=HTMLResponse)
    async def pipeline_page(request: Request, submission_id: str):
        """Show pipeline runner page (before execution)."""
        sub = SUBMISSIONS_BY_ID.get(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        return templates.TemplateResponse(request, "pipeline_runner.html", {
            "active_page": "submissions",
            "sub": sub,
            "result": None,
            "mode": None,
        })

    @router.post("/submissions/{submission_id}/pipeline", response_class=HTMLResponse)
    async def run_pipeline(request: Request, submission_id: str, mode: str = "mock"):
        """Execute the pipeline and show results.

        mode=mock: Builds MockContext → goes through execution engine →
                   skips Claude → logs decisions. Instant, free.
        mode=live: No MockContext → execution engine calls Claude.
                   Costs ~$0.05, takes ~15-30 seconds.

        Both paths produce identical governance trails in Verity.
        """
        await verity.ensure_connected()

        sub = SUBMISSIONS_BY_ID.get(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # Create or get execution context for this submission
        try:
            ctx = await verity.create_execution_context(
                context_ref=f"submission:{submission_id}",
                context_type="submission",
                metadata={"named_insured": sub["named_insured"], "lob": sub["lob"]},
            )
            exec_ctx_id = ctx["id"]
        except Exception:
            exec_ctx_id = None  # Graceful fallback if app not registered yet

        pipeline_context = {
            "submission_id": submission_id,
            "lob": sub["lob"],
            "named_insured": sub["named_insured"],
        }

        if mode == "live":
            result = await verity.execute_pipeline(
                pipeline_name="uw_submission_pipeline",
                context=pipeline_context,
                execution_context_id=exec_ctx_id,
            )
        else:
            mock = get_mock_context(submission_id)
            result = await verity.execute_pipeline(
                pipeline_name="uw_submission_pipeline",
                context=pipeline_context,
                mock=mock,
                execution_context_id=exec_ctx_id,
            )

        # Store Verity IDs on the submission so "View in Verity" links work
        sub["last_pipeline_run_id"] = str(result.pipeline_run_id)
        sub["last_execution_context_id"] = str(exec_ctx_id) if exec_ctx_id else None

        return templates.TemplateResponse(request, "pipeline_runner.html", {
            "active_page": "submissions",
            "sub": sub,
            "result": result,
            "mode": mode,
        })

    return router
