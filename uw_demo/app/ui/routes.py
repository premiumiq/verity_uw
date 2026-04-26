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

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

import httpx
import psycopg

logger = logging.getLogger(__name__)

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from uw_demo.app.config import settings
from uw_demo.app.workflows import run_doc_processing, run_risk_assessment


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
    """Read all submissions from uw_db, with the count of associated
    documents joined in. The doc_count is read directly from uw_db's
    `document` table — once UW has discovered docs for a submission,
    the count is local and a single SQL query gives us every row's
    count without any per-row EDMS round trip."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """SELECT s.*, COALESCE(d.doc_count, 0) AS doc_count
                FROM submission s
                LEFT JOIN (
                    SELECT submission_id, COUNT(*) AS doc_count
                    FROM document
                    GROUP BY submission_id
                ) d ON d.submission_id = s.id
                ORDER BY s.created_at"""
            )
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
                                  workflow_run_id=None, completed_by=None):
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
                        completed_by = %s, workflow_run_id = %s
                    WHERE submission_id = %s AND step_name = %s""",
                    (status, now, completed_by, workflow_run_id, submission_id, step_name),
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


def _humanize_age(timestamp) -> str:
    """Convert a past timestamp into a short relative age string,
    e.g. 'just now', '12m', '3h', '2d'. Returns '—' for None."""
    if not timestamp:
        return "—"
    delta = datetime.now(timezone.utc) - timestamp
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    return f"{secs // 86400}d"


def _compute_current_stage(workflow_steps: list[dict]) -> tuple[str, object]:
    """Find the workflow's current stage (first running step, else first
    pending step, else 'Complete'). Returns (label, since_timestamp).

    For a running step we use its `started_at`. For a pending step there
    is no entry timestamp on the step itself, so the caller should fall
    back to `submission.updated_at` to get a sensible "since when" age."""
    for s in workflow_steps:
        if s.get("status") == "running":
            return (
                s["step_name"].replace("_", " ").title(),
                s.get("started_at"),
            )
    for s in workflow_steps:
        if s.get("status") == "pending":
            return (
                "Awaiting " + s["step_name"].replace("_", " ").title(),
                None,
            )
    return ("Complete", None)


def _compute_next_action(sub: dict, submission_id: str) -> dict | None:
    """Compute the contextual next action based on submission status.

    The workflow has two ingestion steps before extraction:
      1. discover-documents — UW fetches the EDMS index and records
         one document row per file in uw_db. Status: intake → documents_received.
      2. process-documents — UW classifies + extracts fields from the
         already-discovered docs. Status: documents_received → documents_processed.
    Splitting these two means the Documents tab can render after step 1
    even before extraction is run."""
    status = sub["status"]
    sid = str(submission_id)
    if status == "intake":
        return {"label": "Discover Documents",
                "url": f"/submissions/{sid}/discover-documents", "method": "POST"}
    elif status == "documents_received":
        return {"label": "Process Documents",
                "url": f"/submissions/{sid}/process-documents", "method": "POST"}
    elif status == "review":
        return {"label": "Review & Approve Fields", "tab": "extraction"}
    elif status in ("approved", "documents_processed"):
        return {"label": "Assess Risk",
                "url": f"/submissions/{sid}/assess-risk", "method": "POST"}
    return None  # assessed, triaged = complete


# ══════════════════════════════════════════════════════════════
# EDMS HELPERS
# ══════════════════════════════════════════════════════════════

async def _fetch_document_index(submission_id: str) -> list[dict]:
    """Fetch the document INDEX (metadata only — no content) for a
    submission from EDMS. UW passes this list as `documents` in the
    Verity input_data; tasks declare what to fetch per reference via
    source_binding so the runtime — not UW — owns content retrieval.

    Returns a list of dicts with: id, filename, content_type, document_type.
    Empty list when EDMS has no docs (or returns an error).
    """
    context_ref = f"submission:{submission_id}"
    async with httpx.AsyncClient(base_url=settings.EDMS_URL, timeout=30.0) as http:
        resp = await http.get("/documents", params={"context_ref": context_ref})
        if resp.status_code != 200:
            return []
        return resp.json().get("documents", [])


# Module-level cache for collection name → UUID. Vault's /upload
# endpoint takes a collection_id (UUID), not a name; the lookup is
# stable for the life of the process.
_COLLECTION_ID_CACHE: dict[str, str] = {}


async def _get_collection_id(name: str) -> str | None:
    """Resolve a Vault collection name (e.g. 'underwriting') to its
    UUID. Cached per process — Vault collections rarely change."""
    if name in _COLLECTION_ID_CACHE:
        return _COLLECTION_ID_CACHE[name]
    async with httpx.AsyncClient(base_url=settings.EDMS_URL, timeout=10.0) as http:
        resp = await http.get("/collections")
        if resp.status_code != 200:
            return None
        for c in resp.json().get("collections", []):
            if c.get("name") == name:
                _COLLECTION_ID_CACHE[name] = c["id"]
                return c["id"]
    return None


# ══════════════════════════════════════════════════════════════
# DOCUMENT REFERENCES (uw_db)
# ══════════════════════════════════════════════════════════════
#
# Discovery is the act of writing one row per EDMS document into
# uw_db's `document` table. Once persisted, every downstream surface
# (submissions list count, Documents tab, extraction pipeline) reads
# from uw_db — the EDMS lookup happens once at discovery time, not
# on every page load.

async def _persist_documents(submission_id: str, edms_docs: list[dict]) -> int:
    """Upsert EDMS document references into uw_db `document`.

    The EDMS index dicts carry: id, filename, content_type, document_type
    (and possibly more). We mirror only the metadata UW needs to display
    and route on; content stays in EDMS, addressed by edms_document_id.

    UPSERT semantics: re-running discovery for a submission is a no-op
    when EDMS hasn't changed; if a doc has new metadata (e.g. a fresher
    classification from EDMS), the row updates in place.

    Returns the number of rows written.
    """
    if not edms_docs:
        return 0

    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            for d in edms_docs:
                await cur.execute(
                    """INSERT INTO document (
                        submission_id, edms_document_id, filename,
                        content_type, file_size_bytes, page_count,
                        document_type, discovery_status, extraction_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'received', 'pending')
                    ON CONFLICT (submission_id, edms_document_id) DO UPDATE SET
                        filename = EXCLUDED.filename,
                        content_type = EXCLUDED.content_type,
                        file_size_bytes = COALESCE(EXCLUDED.file_size_bytes, document.file_size_bytes),
                        page_count = COALESCE(EXCLUDED.page_count, document.page_count),
                        -- Don't clobber a UW-side classification with an
                        -- EDMS-side null — only update document_type when
                        -- EDMS actually has a value.
                        document_type = COALESCE(EXCLUDED.document_type, document.document_type),
                        discovery_status = 'received'
                    """,
                    (
                        submission_id,
                        d.get("id"),
                        d.get("filename") or "(unnamed)",
                        d.get("content_type"),
                        d.get("file_size_bytes"),
                        d.get("page_count"),
                        d.get("document_type"),
                    ),
                )
        await conn.commit()
    return len(edms_docs)


async def _get_documents(submission_id: str) -> list[dict]:
    """Read all `document` rows for a submission from uw_db, ordered
    by received_at. Returns dicts keyed by column name."""
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM document WHERE submission_id = %s "
                "ORDER BY received_at",
                (submission_id,),
            )
            cols = [c.name for c in cur.description]
            rows = await cur.fetchall()
            return [dict(zip(cols, row)) for row in rows]


def _docs_for_workflow(docs: list[dict]) -> list[dict]:
    """Translate uw_db `document` rows into the dict shape the
    Verity workflow expects — same keys as `_fetch_document_index`
    returned previously, so workflow code is unchanged. The id passed
    is the EDMS document id (the runtime's source_binding fetches
    against EDMS, not against uw_db)."""
    return [
        {
            "id": str(d["edms_document_id"]),
            "filename": d.get("filename"),
            "content_type": d.get("content_type"),
            "document_type": d.get("document_type"),
        }
        for d in docs
    ]


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
        # doc_count drives the badge on the Documents tab (mirrors the
        # review_count badge on Extracted Fields). 0 is a real value —
        # we render the badge even at zero so the empty state is loud.
        documents = await _get_documents(submission_id)
        doc_count = len(documents)
        next_action = _compute_next_action(sub, submission_id)
        run_id = str(sub.get("last_risk_workflow_run_id") or sub.get("last_doc_workflow_run_id") or "")

        # Current-stage label + humanized age — used by the new
        # stepper context strip. For pending stages we use
        # sub.updated_at as the "since when" anchor.
        current_stage_label, stage_since = _compute_current_stage(workflow_steps)
        current_stage_age = _humanize_age(stage_since or sub.get("updated_at"))

        pipeline_mode = await _get_setting("pipeline_mode", "mock")
        return templates.TemplateResponse(request, "submission_detail.html", {
            "active_page": "submissions",
            "sub": sub,
            "workflow_steps": workflow_steps,
            "assessments": assessments,
            "next_action": next_action,
            "review_count": review_count,
            "doc_count": doc_count,
            "current_stage_label": current_stage_label,
            "current_stage_age": current_stage_age,
            "run_id": run_id if run_id else None,
            # execution_context_id scopes the "View in Verity" link to
            # ALL decisions for the submission (every workflow_run_id),
            # not just the most recent workflow's audit trail.
            "execution_context_id": str(sub.get("execution_context_id")) if sub.get("execution_context_id") else None,
            "pipeline_mode": pipeline_mode,
        })

    # ── TAB PARTIALS (HTMX) ──────────────────────────────────

    @router.get("/submissions/{submission_id}/tab/details", response_class=HTMLResponse)
    async def tab_details(request: Request, submission_id: str):
        sub = await _get_submission(submission_id)
        return templates.TemplateResponse(request, "partials/_tab_details.html", {"sub": sub})

    @router.get("/submissions/{submission_id}/tab/documents", response_class=HTMLResponse)
    async def tab_documents(request: Request, submission_id: str):
        """Render the Documents tab — one card per uw_db `document` row.
        No EDMS round-trip; data was mirrored at discovery time."""
        documents = await _get_documents(submission_id)
        # Pass submission_id so the empty-state Discover button and the
        # Upload modal know which submission to POST against.
        return templates.TemplateResponse(request, "partials/_tab_documents.html",
                                           {"documents": documents,
                                            "submission_id": submission_id})

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
        """Submission-scoped audit trail.

        Queries by `execution_context_id` so every workflow invocation
        for the submission shows up — doc-processing classifies/extracts
        AND risk-assessment triage/appetite, across however many
        workflow runs the submission has gone through. The previous
        version picked one workflow_run_id and silently hid every
        decision from the OTHER workflow.
        """
        await verity.ensure_connected()
        sub = await _get_submission(submission_id)
        trail = []
        ctx_id = sub.get("execution_context_id")
        if ctx_id:
            trail = await verity.get_audit_trail(str(ctx_id))
        return templates.TemplateResponse(request, "partials/_tab_audit_trail.html", {
            "trail": trail,
            "execution_context_id": str(ctx_id) if ctx_id else None,
        })

    # ── DOCUMENT DISCOVERY ───────────────────────────────────
    #
    # Discovery is the first step UW takes on a fresh submission:
    # ask EDMS what documents arrived for this submission, then
    # persist a row per document into uw_db's `document` table.
    # Once persisted, the Documents tab and the # Docs column on
    # the list page can render from uw_db without any EDMS round
    # trip per page load.
    #
    # This endpoint is separate from /process-documents (which now
    # only runs classify+extract on already-discovered docs). Splitting
    # the two lets UW track which submissions have docs but haven't
    # been processed yet — a real status, not an implicit one.

    @router.post("/submissions/{submission_id}/discover-documents",
                  response_class=HTMLResponse)
    async def run_document_discovery(request: Request, submission_id: str):
        """Pull the document index from EDMS for this submission and
        write one row per document into uw_db `document`. Idempotent
        — re-running on the same submission is a no-op (UPSERT)."""
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # Fetch from EDMS using the existing helper. Returns [] on error
        # or empty submission; we still persist (zero rows) and continue.
        edms_docs = await _fetch_document_index(submission_id)
        await _persist_documents(submission_id, edms_docs)

        # Status transition: intake → documents_received. The state
        # machine helper that guards transitions is added in a later
        # phase; for now we update the column directly.
        await _update_submission_status(submission_id, "documents_received")

        return RedirectResponse(url=f"/submissions/{submission_id}",
                                 status_code=303)

    # ── DOCUMENT UPLOAD (manual, via the UI modal) ───────────
    #
    # Lets a user push a file straight into Vault from the Documents
    # tab without going through Vault's own UI. The user picks the
    # file, document type, sensitivity, and category; the rest
    # (collection, context_ref, context_type, lob, uploaded_by) is
    # auto-populated server-side from the submission.
    #
    # User-picked document_type is authoritative — when the AI
    # classifier later runs, the value already on the row should be
    # respected. (Workflow change to actually skip the classifier
    # step for already-classified docs is deferred to Phase 4.)

    @router.post("/submissions/{submission_id}/upload-document",
                  response_class=HTMLResponse)
    async def upload_document_to_vault(
        request: Request, submission_id: str,
        file: UploadFile = File(...),
        document_type: str = Form(...),
        sensitivity: str = Form(...),
        category: str = Form(...),
    ):
        """Forward a user-selected file to Vault, then mirror the
        new document reference into uw_db so the Documents tab
        shows it immediately."""
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # Resolve underwriting collection UUID (cached after first call).
        coll_id = await _get_collection_id("underwriting")
        if not coll_id:
            return HTMLResponse("Vault 'underwriting' collection not found",
                                 status_code=500)

        # Map UW LOB code (DO/GL) to Vault's lob tag value (do/gl).
        # The lob tag is added automatically; the user does not pick it.
        lob_tag = (sub.get("lob") or "").lower()
        tags = {
            "sensitivity": sensitivity,
            "category": category,
            "lob": lob_tag,
        }

        # Read the upload into memory once. The file is small (insurance
        # docs); streaming is overkill for the demo.
        content = await file.read()

        # POST multipart/form-data to Vault. httpx handles the boundary
        # encoding when we pass `files` and `data` separately.
        files = {
            "file": (
                file.filename or "uploaded.bin",
                content,
                file.content_type or "application/octet-stream",
            ),
        }
        data = {
            "collection_id": coll_id,
            "context_ref": f"submission:{submission_id}",
            "context_type": "submission",
            "document_type": document_type,
            "tags": json.dumps(tags),
            "uploaded_by": "uw_user",
        }
        async with httpx.AsyncClient(base_url=settings.EDMS_URL,
                                       timeout=60.0) as http:
            resp = await http.post("/upload", files=files, data=data)
            if resp.status_code != 200:
                logger.error(
                    "Vault upload failed for submission=%s status=%s body=%s",
                    submission_id, resp.status_code, resp.text[:500],
                )
                return HTMLResponse(
                    f"Vault upload failed: {resp.status_code}",
                    status_code=502,
                )
            new_doc = resp.json()

        # Mirror the new doc into uw_db. Build the same dict shape
        # _persist_documents expects, including file_size_bytes so the
        # Documents tab can render the size column right away.
        await _persist_documents(submission_id, [{
            "id": new_doc.get("id"),
            "filename": new_doc.get("filename"),
            "content_type": new_doc.get("content_type"),
            "file_size_bytes": new_doc.get("file_size_bytes") or len(content),
            "page_count": None,
            # User-picked document_type is authoritative — pass it through
            # so the classifier step can be short-circuited later.
            "document_type": document_type,
        }])

        return RedirectResponse(url=f"/submissions/{submission_id}",
                                 status_code=303)

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

        # UW passes only the document INDEX to Verity — pure references
        # plus metadata. Each task version's source_binding declares what
        # to fetch from each reference (text, bytes, image — modality is
        # the task's choice, not UW's). The runtime calls EDMS via the
        # connector at execution time, so the audit input_json carries
        # exactly the references that were considered, with no inlined
        # content of any kind.
        #
        # Source of truth: uw_db `document` table (populated by
        # /discover-documents). The Verity workflow shape is unchanged —
        # _docs_for_workflow translates rows back into the same
        # {id, filename, content_type, document_type} dicts the workflow
        # used to receive directly from EDMS.
        uw_docs = await _get_documents(submission_id)
        documents = _docs_for_workflow(uw_docs)

        pipeline_context = {
            "submission_id": submission_id,
            "lob": sub["lob"],
            "named_insured": sub["named_insured"],
            "document_count": str(len(documents)),
            "documents": documents,
        }

        # Execute pipeline
        # json and logger already imported at module level

        try:
            use_mock = await _use_mock()
            result = await run_doc_processing(
                verity,
                submission_id=submission_id,
                pipeline_context=pipeline_context,
                execution_context_id=exec_ctx_id,
                use_mock=use_mock,
            )
        except Exception as e:
            logger.error(f"Doc-processing workflow failed for {submission_id}: {e}")
            await _update_workflow_step(submission_id, "document_processing", "failed",
                                         completed_by=f"error: {str(e)[:200]}")
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        run_id = str(result.workflow_run_id)

        # Check pipeline result — handle failure
        if result.status == "failed":
            error_msg = ""
            for step in result.all_steps:
                if step.status == "failed":
                    error_msg = step.error_message or "Unknown error"
                    break
            logger.error(f"Pipeline 1 failed for {submission_id}: {error_msg}")
            await _update_workflow_step(submission_id, "document_processing", "failed",
                                         workflow_run_id=run_id,
                                         completed_by=f"error: {error_msg[:200]}")
            await _update_submission_status(submission_id, "intake",
                                             last_doc_workflow_run_id=run_id)
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        # Surface the "classified but nothing was extractable" outcome
        # honestly. Don't pretend the workflow completed — there are
        # zero extracted fields and risk-assessment can't run.
        if result.status == "no_extractable_documents":
            logger.info(
                "doc_processing produced no extractable documents for %s: %s",
                submission_id, result.error_message,
            )
            await _update_workflow_step(
                submission_id, "document_processing", "no_extractable_documents",
                workflow_run_id=run_id,
                completed_by=result.error_message or "no documents matched a registered extractor",
            )
            await _update_submission_status(
                submission_id, "intake",
                last_doc_workflow_run_id=run_id,
                execution_context_id=str(exec_ctx_id) if exec_ctx_id else None,
            )
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        # Pipeline succeeded (or partial — at least one extract worked) —
        # update workflow.
        await _update_workflow_step(submission_id, "document_processing", "complete",
                                     workflow_run_id=run_id, completed_by="system")
        await _update_submission_status(submission_id, "documents_processed",
                                         last_doc_workflow_run_id=run_id,
                                         execution_context_id=str(exec_ctx_id) if exec_ctx_id else None)

        # Write extraction results to uw_db from every per-doc extract
        # step that succeeded. Per-doc workflow generates step_names
        # like 'extract_fields:do_app_acme.pdf' — the original
        # `step_name == "extract_fields"` lookup never matched anything,
        # so this used to silently no-op for every submission.
        from uw_demo.app.tools.submission_tools import store_extraction_result
        extract_steps = [
            s for s in result.all_steps
            if s.step_name and s.step_name.startswith("extract_fields:")
            and s.status == "complete"
            and s.execution_result and s.execution_result.output
        ]
        for s in extract_steps:
            output = s.execution_result.output
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

    await _update_workflow_step(submission_id, "triage", "running")

    # Resolve the execution context: reuse the submission's existing
    # one if it already has one (created during doc-processing or a
    # prior risk-assessment), otherwise mint a new one and persist
    # it below so future runs and the "View in Verity" link find it.
    exec_ctx_id = sub.get("execution_context_id")
    if not exec_ctx_id:
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

    # Execute workflow
    try:
        use_mock = await _use_mock()
        result = await run_risk_assessment(
            verity,
            submission_id=submission_id,
            pipeline_context=pipeline_context,
            execution_context_id=exec_ctx_id,
            use_mock=use_mock,
        )
    except Exception as e:
        logger.error(f"Risk-assessment workflow failed for {submission_id}: {e}")
        await _update_workflow_step(submission_id, "triage", "failed",
                                     completed_by=f"error: {str(e)[:200]}")
        await _update_submission_status(submission_id, "approved",
                                         execution_context_id=str(exec_ctx_id) if exec_ctx_id else None)
        return

    # Check pipeline result status
    run_id = str(result.workflow_run_id)

    if result.status == "failed":
        # Pipeline ran but steps failed (e.g., Claude API overloaded)
        error_msg = ""
        for step in result.all_steps:
            if step.status == "failed":
                error_msg = step.error_message or "Unknown error"
                break
        logger.error(f"Pipeline 2 failed for {submission_id}: {error_msg}")
        await _update_workflow_step(submission_id, "triage", "failed",
                                     workflow_run_id=run_id, completed_by=f"error: {error_msg[:200]}")
        await _update_submission_status(submission_id, "approved",
                                         last_risk_workflow_run_id=run_id,
                                         execution_context_id=str(exec_ctx_id) if exec_ctx_id else None)
        return

    # Pipeline succeeded — update workflow steps per actual step status
    for step in result.all_steps:
        if step.step_name in ("triage_submission", "assess_appetite"):
            wf_name = "triage" if step.step_name == "triage_submission" else "appetite"
            if step.status == "complete":
                await _update_workflow_step(submission_id, wf_name, "complete",
                                             workflow_run_id=run_id, completed_by="system")
            elif step.status == "failed":
                await _update_workflow_step(submission_id, wf_name, "failed",
                                             workflow_run_id=run_id,
                                             completed_by=f"error: {step.error_message or 'unknown'}"[:200])
            elif step.status == "skipped":
                await _update_workflow_step(submission_id, wf_name, "skipped",
                                             workflow_run_id=run_id, completed_by="system")

    # Write assessment results to uw_db from pipeline output
    triage_step = next((s for s in result.all_steps if s.step_name == "triage_submission"), None)
    appetite_step = next((s for s in result.all_steps if s.step_name == "assess_appetite"), None)

    # Both agents run with enforce_output_schema=True (see workflows.py),
    # so their `execution_result.output` is guaranteed to be structured
    # JSON conforming to the agent_version's output_schema. That
    # structured dict IS the canonical conclusion — there's a single
    # persistence path: read agent_decision_log.output_json and upsert
    # into submission_assessment. The previous tool-based mid-loop
    # writes (`store_triage_result` / `update_appetite_status`) were
    # retired 2026-04-25.
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            if (triage_step and triage_step.status == "complete"
                    and triage_step.execution_result and triage_step.execution_result.output):
                t = triage_step.execution_result.output
                await cur.execute(
                    """INSERT INTO submission_assessment (
                        submission_id, assessment_type, result,
                        risk_score, routing, confidence, reasoning, workflow_run_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, assessment_type) DO UPDATE SET
                        result = EXCLUDED.result, risk_score = EXCLUDED.risk_score,
                        routing = EXCLUDED.routing, confidence = EXCLUDED.confidence,
                        reasoning = EXCLUDED.reasoning, workflow_run_id = EXCLUDED.workflow_run_id,
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
                        determination, confidence, reasoning, workflow_run_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (submission_id, assessment_type) DO UPDATE SET
                        result = EXCLUDED.result, determination = EXCLUDED.determination,
                        confidence = EXCLUDED.confidence, reasoning = EXCLUDED.reasoning,
                        workflow_run_id = EXCLUDED.workflow_run_id, created_at = NOW()
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
                                         last_risk_workflow_run_id=run_id,
                                         execution_context_id=str(exec_ctx_id) if exec_ctx_id else None)
    else:
        await _update_submission_status(submission_id, "approved",
                                         last_risk_workflow_run_id=run_id,
                                         execution_context_id=str(exec_ctx_id) if exec_ctx_id else None)
