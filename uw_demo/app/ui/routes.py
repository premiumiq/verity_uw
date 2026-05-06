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
from uw_demo.app.db.state import (
    InvalidStageTransitionError,
    current_stage,
    ensure_stages,
    record_event,
    transition_stage,
)
from uw_demo.app.ui.field_layout import FIELD_GROUPS, format_value
from uw_demo.app.workflows import run_doc_processing, run_risk_assessment


TEMPLATES_DIR = Path(__file__).parent / "templates"


def _enum_value(value):
    """Jinja2 filter: extract .value from enums."""
    if isinstance(value, Enum):
        return value.value
    return value


# ══════════════════════════════════════════════════════════════
# HITL EDIT REASON PRESETS
# ══════════════════════════════════════════════════════════════
# Drives the dropdown on the inline-edit form (pen → save).
# Each entry is (id, label, send_feedback_default).
#
#   id                        — value submitted by the form select.
#   label                     — what the operator sees AND what
#                               gets stored as the audit reason.
#   send_feedback_default     — whether picking this preset should
#                               turn the "Send feedback to Verity"
#                               checkbox ON (True) or OFF (False).
#
# Why the flag default varies: not every HITL edit is feedback the
# Verity governance system should learn from. If the broker simply
# didn't include a piece of info on the documents, that's a data-
# completeness problem, not an extractor accuracy problem —
# forwarding it would muddy the extractor's training signal.
# Reasons that ARE about extractor accuracy (missed / wrong) flip
# the flag on by default. The operator can still override the
# checkbox manually after picking a preset.
#
# The 'other' entry is special-cased in the template: choosing it
# reveals a free-text input. Typed reasons default to flag ON
# because the typical reason an operator types something custom
# is "the AI got it wrong in a way the presets don't cover".

EDIT_REASONS = [
    # (id, label, send_feedback_default)
    ("not_extracted",
     "Field was not extracted at all",
     True),
    ("not_extracted_accurately",
     "Field was not extracted accurately",
     True),
    ("not_in_documents",
     "Information not received on documents",
     False),
    ("broker_correction",
     "Broker correction (email / phone)",
     False),
    ("uw_judgment",
     "Override per UW judgment",
     False),
    ("other",
     "Other (specify)",
     True),
]

# Lookup by id — used by the edit handler to translate the
# submitted preset id back into its (label, flag) pair without a
# linear scan.
EDIT_REASON_BY_ID = {r[0]: r for r in EDIT_REASONS}


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
    """Read all submissions from uw_db, enriched with:
      - doc_count   (LEFT JOIN on document table)
      - current_stage / current_stage_status — derived from
        submission_stage rows using the same priority rule as
        state.current_stage (lowest non-complete forward stage,
        with 'declined' as a short-circuit terminal). Computed
        in SQL so the list page is one round-trip."""
    from uw_demo.app.db.state import STAGE_ORDER
    order_expr = " ".join(
        f"WHEN '{s}' THEN {i}" for i, s in enumerate(STAGE_ORDER)
    )
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""SELECT
                    s.*,
                    COALESCE(d.doc_count, 0) AS doc_count,
                    COALESCE(stg.current_stage, 'intake') AS current_stage,
                    COALESCE(stg.current_status, 'pending') AS current_stage_status
                FROM submission s
                LEFT JOIN (
                    SELECT submission_id, COUNT(*) AS doc_count
                    FROM document GROUP BY submission_id
                ) d ON d.submission_id = s.id
                LEFT JOIN LATERAL (
                    SELECT
                      COALESCE(
                        (SELECT 'declined' FROM submission_stage dx
                         WHERE dx.submission_id = s.id
                           AND dx.stage = 'declined'
                           AND dx.status::text != 'pending'),
                        (SELECT stage::text FROM submission_stage f
                         WHERE f.submission_id = s.id
                           AND f.status::text != 'complete'
                           AND f.stage::text IN
                               ({", ".join(f"'{x}'" for x in STAGE_ORDER)})
                         ORDER BY CASE f.stage::text {order_expr} ELSE 99 END
                         LIMIT 1),
                        'appetite'
                      ) AS current_stage,
                      COALESCE(
                        (SELECT status::text FROM submission_stage cs
                         WHERE cs.submission_id = s.id
                           AND cs.stage::text = (
                              SELECT stage::text FROM submission_stage f2
                              WHERE f2.submission_id = s.id
                                AND f2.status::text != 'complete'
                                AND f2.stage::text IN
                                    ({", ".join(f"'{x}'" for x in STAGE_ORDER)})
                              ORDER BY CASE f2.stage::text {order_expr} ELSE 99 END
                              LIMIT 1
                           )),
                        'complete'
                      ) AS current_status
                ) stg ON TRUE
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


async def _get_submission_stages(submission_id: str) -> list[dict]:
    """Read all submission_stage rows for a submission, ordered by
    the canonical STAGE_ORDER (intake → ... → appetite, then declined).
    Drives the horizontal stepper on the detail page.

    Returns dicts keyed by column name; status is normalised to str
    so the templates can compare with literal string values."""
    # Build a CASE expression that imposes the canonical priority
    # order on the stage column. Stages outside the order list (none
    # currently — all are listed) sort last.
    from uw_demo.app.db.state import ALL_STAGES
    order_expr = " ".join(
        f"WHEN '{stage}' THEN {i}" for i, stage in enumerate(ALL_STAGES)
    )
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""SELECT
                    id, submission_id,
                    stage::text AS stage,
                    status::text AS status,
                    started_at, completed_at, blocked_reason,
                    last_run_id, enter_count
                FROM submission_stage
                WHERE submission_id = %s
                ORDER BY CASE stage::text {order_expr} ELSE 99 END""",
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


async def _get_stage_counts() -> dict[str, int]:
    """Count submissions grouped by their *current stage* for the
    KPI cards on the list page. Replaces the old _get_status_counts
    that grouped by submission.status (column dropped in 4.1).

    "Current stage" rule: the lowest-priority non-complete stage
    per submission. Same rule as state.current_stage().

    Returned keys are stage names ('intake', 'document_processing',
    'information_review', 'triage', 'appetite', 'declined') plus a
    derived 'all_complete' bucket for submissions whose forward
    stages are all complete."""
    from uw_demo.app.db.state import STAGE_ORDER
    # Build a single SQL that finds, per submission, the lowest-
    # priority stage that isn't complete (or the terminal 'declined'
    # if its status is non-pending). This mirrors state.current_stage.
    order_expr = " ".join(
        f"WHEN '{stage}' THEN {i}" for i, stage in enumerate(STAGE_ORDER)
    )
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""WITH per_sub AS (
                    SELECT
                      ss.submission_id,
                      -- declined short-circuit: if declined.status != pending,
                      -- that's the current stage regardless.
                      COALESCE(
                        (SELECT 'declined' FROM submission_stage d
                         WHERE d.submission_id = ss.submission_id
                           AND d.stage = 'declined'
                           AND d.status::text != 'pending'),
                        (SELECT stage::text FROM submission_stage f
                         WHERE f.submission_id = ss.submission_id
                           AND f.status::text != 'complete'
                           AND f.stage::text IN
                               ({", ".join(f"'{s}'" for s in STAGE_ORDER)})
                         ORDER BY CASE f.stage::text {order_expr} ELSE 99 END
                         LIMIT 1),
                        'all_complete'
                      ) AS current_stage
                    FROM submission_stage ss
                    GROUP BY ss.submission_id
                )
                SELECT current_stage, COUNT(*) FROM per_sub
                GROUP BY current_stage"""
            )
            rows = await cur.fetchall()
            return {row[0]: row[1] for row in rows}


def _build_field_sections(
    sub: dict,
    extractions: list[dict],
    documents: list[dict] | None = None,
) -> list[dict]:
    """Merge the submission row and its extraction rows into the
    sectioned form-view structure the Details tab template iterates.

    Called from two places:
      - tab_details (HTMX swap when the tab is clicked)
      - submission_detail (page-load include of _tab_details.html)
    Single helper so both surfaces show the same data without a
    second DB round-trip — extractions and documents are already
    loaded by the detail route, so this is pure computation.

    `documents` is optional but recommended: when provided, the
    function resolves each extraction's source_document_id into
    the actual filename so the sparkle tooltip can name the
    source doc without another query.
    """
    ext_by_name = {e["field_name"]: e for e in extractions}
    # Build a lookup from document.id (uw_db UUID) to (filename,
    # edms_document_id). Filename drives the modal's display;
    # edms_document_id builds the "Open in Vault" link.
    doc_lookup: dict[str, dict] = {}
    for d in (documents or []):
        if d.get("id"):
            doc_lookup[str(d["id"])] = {
                "filename": d.get("filename"),
                "edms_document_id": d.get("edms_document_id"),
            }
    sections: list[dict] = []

    for section_title, fields, lob_filter in FIELD_GROUPS:
        # LOB-gated sections (e.g. Board for D&O): skip when the
        # submission's LOB doesn't match.
        if lob_filter and sub.get("lob") != lob_filter:
            continue

        field_views: list[dict] = []
        for fname, label, formatter in fields:
            ext = ext_by_name.get(fname)
            # Displayed value precedence:
            #   1. HITL value (human-corrected)
            #   2. AI value (AI-extracted)
            #   3. Submission row value (broker-stated)
            if ext and ext.get("hitl_value") is not None:
                raw_value = ext["hitl_value"]
            elif ext and ext.get("ai_value") is not None:
                raw_value = ext["ai_value"]
            else:
                raw_value = sub.get(fname)
            # is_ai_authoritative drives the sparkle: AI produced
            # this value AND no human has overridden it.
            is_ai_authoritative = bool(
                ext and ext.get("ai_value") is not None
                and ext.get("hitl_value") is None
            )
            # ai_not_found is TRUE when the AI ran, had no value
            # to report, AND no human has supplied one since.
            # The first two conditions come from how
            # store_extraction_result writes the row:
            #   ai_found = field_name not in unextractable
            # so a row with ai_found=False AND ai_value IS NULL
            # means the AI explicitly listed this field as
            # unextractable. ai_value="" with ai_found=True can
            # also mean "extracted but empty".
            #
            # The hitl_value gate is the bug-fix: once a HITL
            # edit has supplied a value, the field is no longer
            # "AI never produced a value" — the user has filled
            # it in. Without this gate the cell would keep
            # rendering the "AI did not find this field" badge
            # in place of the human-entered value, even though
            # both the audit log and the hitl_value column
            # already carried the edit.
            ai_not_found = bool(
                ext is not None
                and ext.get("ai_value") in (None, "")
                and ext.get("hitl_value") is None
                and (ext.get("ai_found") is False
                     or ext.get("review_reason") == "missing")
            )
            # broker_stated_only: AI tried and didn't find, but the
            # row still has a value because the broker provided one
            # at intake (it's on the submission row directly).
            # Drives a small "Broker-stated" chip next to the value
            # so the user knows the source even when the AI gave up.
            broker_stated_only = bool(
                ai_not_found
                and sub.get(fname) not in (None, "")
            )
            # Resolve source document context (filename for display,
            # edms_document_id for the Vault link).
            source_filename = None
            source_edms_id  = None
            if ext and ext.get("source_document_id"):
                ref = doc_lookup.get(str(ext["source_document_id"]))
                if ref:
                    source_filename = ref["filename"]
                    source_edms_id  = ref["edms_document_id"]
            # Whether the "Send feedback to Verity" checkbox in the
            # edit modal should default to ON. The signal here is
            # "AI was involved in this field's value, either by
            # providing one or by being expected to and missing":
            #   - AI gave a value (is_ai_authoritative) → check
            #   - AI ran and missed (ai_not_found)      → check
            # Otherwise (broker filled in, AI never ran) → unchecked.
            # The macro hides the checkbox entirely when no
            # extraction row exists at all (nothing to forward).
            feedback_default = bool(is_ai_authoritative or ai_not_found)
            field_views.append({
                "field_name": fname,
                "label": label,
                "formatter": formatter,
                "raw_value": raw_value,
                "display_value": format_value(raw_value, formatter),
                "extraction": ext,
                "is_ai_authoritative": is_ai_authoritative,
                "ai_not_found": ai_not_found,
                "broker_stated_only": broker_stated_only,
                "feedback_default": feedback_default,
                "needs_review": bool(ext and ext.get("needs_review")),
                "source_filename": source_filename,
                "source_edms_id":  source_edms_id,
            })

        sections.append({"title": section_title, "fields": field_views})

    return sections


def _humanize_event(ev: dict) -> str:
    """Turn a submission_event row into a one-line audit
    description. Single chokepoint so the template stays free of
    branching logic and new event types only need a clause here."""
    typ = ev.get("event_type") or ""
    payload = ev.get("payload") or {}

    # State changes — payload carries from/to/stage.
    if typ == "stage_status_changed":
        stage = (payload.get("stage") or "").replace("_", " ").title()
        to    = (payload.get("to")    or "").replace("_", " ").title()
        return f"Stage '{stage}' → {to}"

    # Discovery & document handling.
    if typ == "discovery_triggered":
        return "Document discovery triggered"
    if typ == "discovery_completed":
        n = payload.get("doc_count", 0)
        return f"Discovery completed — {n} document{'' if n == 1 else 's'} found"
    if typ == "document_uploaded":
        f = payload.get("filename") or "(unnamed)"
        t = payload.get("document_type") or "document"
        return f"Uploaded '{f}' ({t.replace('_', ' ')})"

    # Pipeline lifecycle.
    if typ == "pipeline_triggered":
        kind = (payload.get("kind") or "pipeline").replace("_", " ")
        return f"User triggered {kind}"
    if typ == "started":
        kind = (payload.get("kind") or "pipeline").replace("_", " ").title()
        return f"{kind} started"
    if typ == "completed":
        kind = (payload.get("kind") or "pipeline").replace("_", " ").title()
        outcome = payload.get("outcome")
        return f"{kind} completed{' — ' + outcome if outcome else ''}"
    if typ == "failed":
        kind = (payload.get("kind") or "pipeline").replace("_", " ").title()
        err = (payload.get("error") or "")[:80]
        return f"{kind} failed{': ' + err if err else ''}"
    if typ == "blocked":
        kind = (payload.get("kind") or "pipeline").replace("_", " ").title()
        reason = payload.get("blocked_reason") or ""
        return f"{kind} blocked{': ' + reason if reason else ''}"

    # HITL actions.
    if typ == "extraction_approved":
        return "Extraction review approved"
    if typ == "field_edited":
        f = payload.get("field_name") or ev.get("field_name") or "?"
        old = (str(payload.get("old_value") or "")).strip()
        new = (str(payload.get("new_value") or "")).strip()
        if old and len(old) > 30: old = old[:30] + "…"
        if new and len(new) > 30: new = new[:30] + "…"
        return f"Field '{f}' edited: '{old}' → '{new}'"

    # Fallback — show the raw type so unmapped events are still
    # visible rather than silently swallowed.
    cat = ev.get("event_category") or "event"
    return f"{cat}: {typ}"


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


def _compute_next_action(
    submission_id: str,
    stage: str,
    stage_status: str,
    has_docs: bool,
) -> dict | None:
    """Compute the contextual next action from the current stage
    and its status. Returns None when the workflow is complete
    (or terminal, e.g. declined).

    Args:
      submission_id: UUID for URL building.
      stage:         current stage name (from state.current_stage()).
      stage_status:  status within that stage (pending / running /
                     blocked_on_input / complete / failed).
      has_docs:      whether at least one document is persisted in
                     uw_db. Lets us show "Discover Documents" rather
                     than "Process Documents" when the user hasn't
                     pulled the index from Vault yet.

    Decision table (covers the canonical happy path + the recovery
    cases). Re-entry is handled by the stage helper itself; this
    function just decides what UI button to show right now."""
    sid = str(submission_id)

    # Pretty stage labels — used both for "running" indicators and
    # any contextual messaging the action bar might show.
    stage_label = stage.replace("_", " ").title()

    # Document Processing stage covers both "discovery" (pull
    # references from Vault) and "processing" (classify + extract).
    # Discovery is implied by has_docs; processing is the next step
    # once docs are present.
    if stage == "document_processing":
        if not has_docs and stage_status in ("pending", "blocked_on_input"):
            return {"label": "Discover Documents",
                    "url": f"/submissions/{sid}/discover-documents",
                    "method": "POST"}
        if stage_status in ("pending", "blocked_on_input", "failed"):
            return {"label": "Process Documents",
                    "url": f"/submissions/{sid}/process-documents",
                    "method": "POST"}
        if stage_status == "running":
            # AI is processing documents server-side. There's
            # nothing for the user to click; the action bar
            # shows a "running" indicator so coming back to the
            # page mid-run doesn't read as "Workflow Complete".
            return {"label": f"{stage_label} in progress…",
                    "running": True}
        return None

    if stage == "information_review":
        # Information Review is HITL — `running` here means "user
        # is in the middle of reviewing", not "AI is running".
        # The action button shows in both running and
        # blocked_on_input so the user can complete the review.
        if stage_status in ("running", "blocked_on_input"):
            return {"label": "Complete Review",
                    "url": f"/submissions/{sid}/approve-extraction",
                    "method": "POST"}
        if stage_status == "failed":
            return {"label": "Re-run Extraction",
                    "url": f"/submissions/{sid}/process-documents",
                    "method": "POST"}
        return None

    if stage in ("triage", "appetite"):
        if stage_status in ("pending", "blocked_on_input", "failed"):
            return {"label": "Assess Risk",
                    "url": f"/submissions/{sid}/assess-risk",
                    "method": "POST"}
        if stage_status == "running":
            return {"label": f"{stage_label} in progress…",
                    "running": True}
        return None  # complete — handled by the all-done case below

    # intake / declined / unknown — no contextual action.
    return None


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
    # Make EDIT_REASONS available to every template without
    # having to thread it through each route's context dict.
    # The _field_row macro iterates this to build its dropdown.
    templates.env.globals["edit_reasons"] = EDIT_REASONS

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
        status_counts = await _get_stage_counts()

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

        # Per-stage rows drive the horizontal stepper. The `stages`
        # list is pre-ordered (intake → ... → declined) so the
        # template just iterates.
        stages = await _get_submission_stages(submission_id)

        # Resolve the current stage / status pair for the action bar
        # and the context strip. Done with the same helper any other
        # place that needs the answer would use.
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                cur_stage, cur_status = await current_stage(cur, submission_id)

        extractions = await _get_extractions(submission_id)
        assessments = await _get_assessments(submission_id)
        review_count = sum(1 for e in extractions if e.get("needs_review"))
        documents = await _get_documents(submission_id)
        doc_count = len(documents)

        # Submission Details is the default tab — its content is
        # included directly in submission_detail.html on first load
        # (not via HTMX), so the route has to pass `sections` along
        # for the include to render. The HTMX tab handler calls
        # the same helper. Documents are passed so the sparkle
        # tooltip can name the source file.
        sections = _build_field_sections(sub, extractions, documents)

        next_action = _compute_next_action(
            submission_id, cur_stage, cur_status, has_docs=doc_count > 0,
        )
        run_id = str(sub.get("last_risk_workflow_run_id")
                     or sub.get("last_doc_workflow_run_id") or "")

        # "In current stage: <age>" anchor — use the stage row's
        # started_at if present, else sub.updated_at as the
        # last-meaningful-touch fallback.
        stage_started_at = next(
            (s["started_at"] for s in stages
             if s["stage"] == cur_stage and s["started_at"]),
            None,
        )
        current_stage_age = _humanize_age(
            stage_started_at or sub.get("updated_at")
        )
        current_stage_label = (
            cur_stage.replace("_", " ").title()
            if cur_status != "complete"
            else "Complete"
        )

        pipeline_mode = await _get_setting("pipeline_mode", "mock")
        return templates.TemplateResponse(request, "submission_detail.html", {
            "active_page": "submissions",
            "sub": sub,
            "stages": stages,
            "current_stage_name": cur_stage,
            "current_stage_status": cur_status,
            "assessments": assessments,
            "next_action": next_action,
            "review_count": review_count,
            "doc_count": doc_count,
            "sections": sections,
            "current_stage_label": current_stage_label,
            "current_stage_age": current_stage_age,
            "run_id": run_id if run_id else None,
            "execution_context_id": str(sub.get("execution_context_id"))
                if sub.get("execution_context_id") else None,
            "pipeline_mode": pipeline_mode,
        })

    # ── TAB PARTIALS (HTMX) ──────────────────────────────────

    @router.get("/submissions/{submission_id}/tab/details", response_class=HTMLResponse)
    async def tab_details(request: Request, submission_id: str):
        """Render the Submission Details tab via HTMX swap. Same
        data shape as the page-load include — both routes call
        _build_field_sections so the two render paths can't drift."""
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)
        extractions = await _get_extractions(submission_id)
        # Same documents lookup as the page-load route so the
        # sparkle tooltip resolves source_document_id → filename.
        documents = await _get_documents(submission_id)
        sections = _build_field_sections(sub, extractions, documents)
        return templates.TemplateResponse(
            request, "partials/_tab_details.html",
            {"sub": sub, "sections": sections},
        )

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
        # "review mode" means the user is actively in Information Review
        # (some fields flagged) — derived from the stage row, not the
        # dropped submission.status column.
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                cur_stage, cur_status = await current_stage(cur, submission_id)
        is_review_mode = (
            cur_stage == "information_review"
            and cur_status in ("running", "blocked_on_input")
        )
        return templates.TemplateResponse(request, "partials/_tab_extraction.html", {
            "sub": sub,
            "extractions": extractions,
            "is_review_mode": is_review_mode,
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
        """Submission-scoped audit trail driven by `submission_event`.

        Renders the UW-side history of everything that's happened to
        this submission: state changes, user actions (uploads,
        approvals, field edits), pipeline lifecycle moments, and
        system events. Each row carries a `workflow_run_id` when
        relevant — those rows get a 'View in Verity' link straight
        to the run-level audit trail in Verity admin.

        A footer link to /admin/audit-trail/context/{exec_ctx_id}
        gives the user the cross-run view in Verity.
        """
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("Submission not found.", status_code=404)

        events: list[dict] = []
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT event_category, event_type, actor, occurred_at,
                              payload, workflow_run_id, document_id, field_name
                    FROM submission_event
                    WHERE submission_id = %s
                    ORDER BY occurred_at DESC""",
                    (submission_id,),
                )
                cols = [d.name for d in cur.description]
                events = [dict(zip(cols, row)) for row in await cur.fetchall()]

        # Pre-render each row's humanised description so the
        # template stays simple. Keeps rendering logic in Python
        # rather than spreading it across Jinja conditionals.
        for ev in events:
            ev["description"] = _humanize_event(ev)

        ctx_id = sub.get("execution_context_id")
        return templates.TemplateResponse(
            request, "partials/_tab_audit_trail.html",
            {
                "events": events,
                "execution_context_id": str(ctx_id) if ctx_id else None,
                "verity_admin_url": "http://localhost:8000",
            },
        )

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
        — re-running on the same submission is a no-op (UPSERT).

        Stage outcome:
          document_processing.status flips to 'blocked_on_input'
          (docs are persisted; waiting on the user to click
          "Process Documents" to actually classify + extract).
        """
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # Fetch from EDMS — returns [] on error or empty submission;
        # we still persist (zero rows) and continue so the user sees
        # an honest empty Documents tab rather than a stale state.
        edms_docs = await _fetch_document_index(submission_id)
        await _persist_documents(submission_id, edms_docs)

        # All state writes share one transaction so a failure
        # mid-way doesn't half-update the audit trail.
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                # Captured BEFORE the stage transition so the
                # audit-trail timeline shows: user clicked → state
                # changed → pipeline reported outcome.
                await record_event(
                    cur, submission_id,
                    event_category="user_action",
                    event_type="discovery_triggered",
                    actor="uw_user",
                )
                await transition_stage(
                    cur, submission_id, "document_processing",
                    "blocked_on_input",
                    changed_by="uw_user",
                    blocked_reason="awaiting_pipeline_trigger",
                    reason="Documents discovered from Vault",
                )
                await record_event(
                    cur, submission_id,
                    event_category="pipeline",
                    event_type="discovery_completed",
                    actor="system",
                    payload={"doc_count": len(edms_docs)},
                )
            await conn.commit()

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

        # Audit event for the upload — payload captures everything
        # the audit-trail UI needs to render the row without a join.
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await record_event(
                    cur, submission_id,
                    event_category="user_action",
                    event_type="document_uploaded",
                    actor="uw_user",
                    payload={
                        "filename": new_doc.get("filename"),
                        "document_type": document_type,
                        "sensitivity": sensitivity,
                        "category": category,
                        "size_bytes": new_doc.get("file_size_bytes") or len(content),
                    },
                    document_id=new_doc.get("id"),
                )
            await conn.commit()

        return RedirectResponse(url=f"/submissions/{submission_id}",
                                 status_code=303)

    # ── PIPELINE 1: DOCUMENT PROCESSING ──────────────────────

    @router.post("/submissions/{submission_id}/process-documents", response_class=HTMLResponse)
    async def run_document_processing(request: Request, submission_id: str):
        """Classify documents + extract fields. Stage-aware.

        Stage transitions written by this handler (in order, by path):
          on entry → document_processing.status = running
          exception → document_processing.status = failed
          pipeline 'failed' → document_processing.status = failed
          pipeline 'no_extractable_documents' →
             document_processing.status = blocked_on_input
             (blocked_reason='no_extractable_documents' so the user
              can upload a missing doc and re-trigger)
          pipeline succeeded →
             document_processing.status = complete
             then either:
               - some fields need HITL → information_review.running
               - all clean → information_review.complete + auto-trigger triage
        """
        await verity.ensure_connected()

        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("<h1>Submission not found</h1>", status_code=404)

        # ── Pre-flight: mark stage running, record user click ────
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await record_event(
                    cur, submission_id,
                    event_category="user_action",
                    event_type="pipeline_triggered",
                    actor="uw_user",
                    payload={"kind": "doc_processing"},
                )
                await transition_stage(
                    cur, submission_id, "document_processing", "running",
                    changed_by="uw_user",
                    reason="Process Documents triggered",
                )
            await conn.commit()

        # Resolve the execution context: reuse the submission's
        # existing one if any (set by an earlier doc-processing or
        # risk-assessment run), else mint a fresh one and persist it.
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

        # ── Run the pipeline (network/AI work, outside DB tx) ────
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
            async with await _get_conn() as conn:
                async with conn.cursor() as cur:
                    await transition_stage(
                        cur, submission_id, "document_processing", "failed",
                        changed_by="system",
                        reason=f"Workflow exception: {str(e)[:200]}",
                    )
                    await record_event(
                        cur, submission_id,
                        event_category="pipeline",
                        event_type="failed",
                        actor="system",
                        payload={"kind": "doc_processing",
                                 "error": str(e)[:200]},
                    )
                await conn.commit()
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        run_id = str(result.workflow_run_id)

        # ── Pipeline reported failure (steps failed) ─────────────
        if result.status == "failed":
            error_msg = ""
            for step in result.all_steps:
                if step.status == "failed":
                    error_msg = step.error_message or "Unknown error"
                    break
            logger.error(f"Pipeline 1 failed for {submission_id}: {error_msg}")
            async with await _get_conn() as conn:
                async with conn.cursor() as cur:
                    # Persist the run id and (if newly minted) ctx
                    # alongside the stage transition so the audit
                    # trail can deep-link to this specific run.
                    await cur.execute(
                        """UPDATE submission SET
                            last_doc_workflow_run_id = %s,
                            execution_context_id = COALESCE(execution_context_id, %s)
                        WHERE id = %s""",
                        (run_id, str(exec_ctx_id) if exec_ctx_id else None,
                         submission_id),
                    )
                    await transition_stage(
                        cur, submission_id, "document_processing", "failed",
                        changed_by="system",
                        run_id=run_id,
                        reason=error_msg[:200],
                    )
                    await record_event(
                        cur, submission_id,
                        event_category="pipeline",
                        event_type="failed",
                        actor="system",
                        payload={"kind": "doc_processing",
                                 "error": error_msg[:200]},
                        workflow_run_id=run_id,
                    )
                await conn.commit()
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        # ── Pipeline ran but no extractable documents present ────
        # Stage status is `blocked_on_input` rather than `failed` —
        # the underwriter can recover by uploading a missing
        # ACORD/GL application and re-triggering the pipeline.
        if result.status == "no_extractable_documents":
            logger.info(
                "doc_processing produced no extractable documents for %s: %s",
                submission_id, result.error_message,
            )
            async with await _get_conn() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """UPDATE submission SET
                            last_doc_workflow_run_id = %s,
                            execution_context_id = COALESCE(execution_context_id, %s)
                        WHERE id = %s""",
                        (run_id, str(exec_ctx_id) if exec_ctx_id else None,
                         submission_id),
                    )
                    await transition_stage(
                        cur, submission_id, "document_processing",
                        "blocked_on_input",
                        changed_by="system",
                        run_id=run_id,
                        blocked_reason="no_extractable_documents",
                        reason=result.error_message or
                               "no documents matched a registered extractor",
                    )
                    await record_event(
                        cur, submission_id,
                        event_category="pipeline",
                        event_type="blocked",
                        actor="system",
                        payload={"kind": "doc_processing",
                                 "blocked_reason": "no_extractable_documents",
                                 "detail": result.error_message},
                        workflow_run_id=run_id,
                    )
                await conn.commit()
            return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

        # ── Pipeline succeeded (or partial — at least one extract worked)
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE submission SET
                        last_doc_workflow_run_id = %s,
                        execution_context_id = COALESCE(execution_context_id, %s)
                    WHERE id = %s""",
                    (run_id, str(exec_ctx_id) if exec_ctx_id else None,
                     submission_id),
                )
                await transition_stage(
                    cur, submission_id, "document_processing", "complete",
                    changed_by="system",
                    run_id=run_id,
                    reason="Classification + extraction completed",
                )
                await record_event(
                    cur, submission_id,
                    event_category="pipeline",
                    event_type="completed",
                    actor="system",
                    payload={"kind": "doc_processing",
                             "outcome": result.status},
                    workflow_run_id=run_id,
                )
            await conn.commit()

        # Write extraction results to uw_db from every per-doc extract
        # step that succeeded. Per-doc workflow generates step_names
        # like 'extract_fields:do_app_acme.pdf'. The provenance
        # passed to store_extraction_result (decision_log_id,
        # extractor_id, output_path, workflow_run_id) drives the
        # sparkle tooltip and gives the override API the anchor it
        # needs to reach back to the specific run.
        from uw_demo.app.tools.submission_tools import store_extraction_result
        extract_steps = [
            s for s in result.all_steps
            if s.step_name and s.step_name.startswith("extract_fields:")
            and s.status == "complete"
            and s.execution_result and s.execution_result.output
        ]
        # Pre-load this submission's document index once so we can
        # resolve each step's filename to its uw_db document.id
        # without N round-trips. The step_name suffix carries the
        # filename — `extract_fields:do_app_acme.pdf` → `do_app_acme.pdf`.
        uw_docs_by_name = {
            d["filename"]: str(d["id"])
            for d in await _get_documents(submission_id)
            if d.get("filename")
        }
        for s in extract_steps:
            output = s.execution_result.output
            er = s.execution_result
            extractor_id = (
                f"{er.entity_name}@{er.version_label}"
                if er.entity_name and er.version_label else er.entity_name
            )
            # Resolve which document this step extracted from. The
            # source_document_id is what powers the sparkle modal's
            # 'Source: <filename>' line and 'Open in Vault' link.
            doc_filename = s.step_name.split(":", 1)[1] if ":" in s.step_name else None
            source_document_id = uw_docs_by_name.get(doc_filename)
            await store_extraction_result(
                submission_id=submission_id,
                fields=output.get("fields", {}),
                low_confidence_fields=output.get("low_confidence_fields", []),
                unextractable_fields=output.get("unextractable_fields", []),
                source_document_id=source_document_id,
                workflow_run_id=run_id,
                decision_log_id=str(er.decision_log_id) if er.decision_log_id else None,
                extractor_id=extractor_id,
            )

        # ── Decide whether HITL review is needed ─────────────────
        extractions = await _get_extractions(submission_id)
        needs_review = any(e.get("needs_review") for e in extractions)

        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                if needs_review:
                    await transition_stage(
                        cur, submission_id, "information_review", "running",
                        changed_by="system",
                        reason="At least one extracted field flagged for review",
                    )
                else:
                    # Auto-pass — no flagged fields to review.
                    await transition_stage(
                        cur, submission_id, "information_review", "complete",
                        changed_by="system",
                        reason="Auto-approved (no extraction flags)",
                    )
            await conn.commit()

        # Auto-trigger Pipeline 2 (risk assessment) ONLY when there
        # were no flagged fields. With flags, the workflow has to
        # wait on the underwriter's HITL review (triggered later
        # by approve_extraction).
        if not needs_review:
            await _run_risk_assessment_internal(verity, submission_id, sub, templates)

        return RedirectResponse(url=f"/submissions/{submission_id}", status_code=303)

    # ── PROVENANCE MODAL ─────────────────────────────────────
    #
    # Returns the provenance panel for one extracted field. The
    # sparkle icon's HTMX get hits this endpoint; the response
    # is swapped into the page-level <dialog>'s content slot,
    # then JS opens the dialog. Every link inside the modal
    # opens in a new tab — Vault doc, Verity decision page.

    @router.get("/submissions/{submission_id}/extraction/{field_name}/provenance",
                response_class=HTMLResponse)
    async def provenance_panel(request: Request,
                                submission_id: str,
                                field_name: str):
        sub = await _get_submission(submission_id)
        if not sub:
            return HTMLResponse("Submission not found.", status_code=404)
        extractions = await _get_extractions(submission_id)
        documents = await _get_documents(submission_id)
        sections = _build_field_sections(sub, extractions, documents)

        target = None
        for sec in sections:
            for f in sec["fields"]:
                if f["field_name"] == field_name:
                    target = f
                    break
            if target:
                break
        if not target:
            return HTMLResponse(
                f"<div style='padding:20px'>No layout entry for "
                f"<code>{field_name}</code>.</div>",
                status_code=404,
            )

        return templates.TemplateResponse(
            request, "partials/_provenance_modal.html",
            {
                "field": target,
                "sub": sub,
                # Hard-coded base URLs for the demo. Both services
                # are co-located at known ports; future deployments
                # would resolve these from settings.
                "verity_admin_url": "http://localhost:8000",
                "vault_url":        "http://localhost:8002",
            },
        )

    # ── PER-FIELD INLINE EDIT ────────────────────────────────
    #
    # Handles the HTMX POST from the pen/save flow on each field
    # in the Submission Details tab. Three writes in one transaction:
    #   1. submission_extraction_audit  (always, append-only)
    #   2. verity_db.hitl_override      (only on AI→HITL flip with
    #                                    a Verity decision anchor)
    #   3. submission_extraction        (updates hitl_* channel)
    # On success, re-renders the same field_row macro so HTMX can
    # swap it back into the page in 'readonly' state.

    @router.post("/submissions/{submission_id}/extraction/{field_name}/edit",
                  response_class=HTMLResponse)
    async def edit_extraction_field(
        request: Request,
        submission_id: str,
        field_name: str,
        hitl_value: str = Form(...),
        reason: str = Form(""),
        send_feedback: str = Form(""),
    ):
        # Treat any non-empty checkbox value as "on". HTML omits
        # unchecked checkboxes from the form body entirely.
        forward_to_verity = bool(send_feedback)
        # When the user opts in to forwarding, a reason is
        # mandatory — the governance signal needs context.
        if forward_to_verity and not reason.strip():
            return HTMLResponse(
                "Reason is required when 'Send feedback to Verity' "
                "is enabled.",
                status_code=400,
            )
        # Read the current extraction row. Have to know the prior
        # value, the prior origin (AI vs HITL), and the Verity
        # anchors before we can build the audit + override calls.
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """SELECT * FROM submission_extraction
                    WHERE submission_id = %s AND field_name = %s""",
                    (submission_id, field_name),
                )
                cols = [d.name for d in cur.description]
                row_tuple = await cur.fetchone()
                if not row_tuple:
                    return HTMLResponse(
                        f"No extraction row for field '{field_name}'.",
                        status_code=404,
                    )
                ext = dict(zip(cols, row_tuple))

                # was_ai_authoritative drives whether we need to
                # call Verity. AI-authoritative means: AI produced
                # a value AND no human has overridden it yet.
                was_ai_authoritative = (
                    ext.get("ai_value") is not None
                    and ext.get("hitl_value") is None
                )
                old_value = (
                    ext.get("hitl_value")
                    if ext.get("hitl_value") is not None
                    else ext.get("ai_value")
                )
                actor = "uw_user"  # auth not yet wired

                # Forward to Verity only when the user opted in
                # via the Send-feedback checkbox AND we have a
                # decision-log anchor to attach the override to.
                # The semantic broadens beyond strict AI→HITL
                # flips: if the AI ran and missed (ai_not_found)
                # AND the user opts in, we forward that too —
                # the pen modal default-checks the box for those.
                hitl_override_id: object = None
                anchor = ext.get("verity_execution_run_id")
                if forward_to_verity and anchor:
                    try:
                        ov = await verity.record_hitl_override(
                            decision_log_id  = anchor,
                            output_path      = ext.get("output_path") or
                                                f"$.fields.{field_name}.value",
                            ai_value         = ext.get("ai_value"),
                            ai_found         = bool(ext.get("ai_found")),
                            hitl_value       = hitl_value,
                            application      = "uw_demo",
                            entity_type      = "submission",
                            entity_reference = str(submission_id),
                            fact_type        = field_name,
                            created_by       = actor,
                            reason           = reason or None,
                        )
                        hitl_override_id = ov.get("id")
                    except Exception as e:
                        # Don't block the local edit if Verity is
                        # unreachable / the run was wiped — log
                        # and continue. The audit row still
                        # records the change locally.
                        logger.warning(
                            "record_hitl_override failed for "
                            "submission=%s field=%s: %s",
                            submission_id, field_name, e,
                        )
                elif forward_to_verity and not anchor:
                    # User wanted to forward but no Verity decision
                    # is anchored to this row (seeded data, or AI
                    # never ran on this submission). Log so it's
                    # visible in app logs; the audit row still
                    # captures the local edit.
                    logger.info(
                        "send_feedback requested but no Verity anchor "
                        "for submission=%s field=%s; saving locally "
                        "without forwarding.",
                        submission_id, field_name,
                    )

                # 1) Audit row (always). Carries the prior origin
                # so reports can answer "how many AI→HITL flips
                # happened on field X?".
                await cur.execute(
                    """INSERT INTO submission_extraction_audit (
                        submission_id, field_name,
                        old_value, new_value,
                        was_ai_authoritative,
                        actor, hitl_override_id,
                        workflow_run_id
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (
                        submission_id, field_name,
                        old_value, hitl_value,
                        was_ai_authoritative,
                        actor, hitl_override_id,
                        ext.get("workflow_run_id"),
                    ),
                )

                # 2) Update the submission_extraction row's HITL
                # channel. ai_* columns stay untouched — they
                # remain the immutable record of what the AI
                # produced on this run.
                await cur.execute(
                    """UPDATE submission_extraction SET
                        hitl_value = %s,
                        hitl_at    = NOW(),
                        hitl_by    = %s,
                        needs_review = FALSE
                    WHERE submission_id = %s AND field_name = %s""",
                    (hitl_value, actor, submission_id, field_name),
                )

                # 3) submission_event row for the audit-trail tab.
                # Categorised as a user_action (not state_change)
                # since it doesn't move a stage — it just records
                # the human edit.
                await record_event(
                    cur, submission_id,
                    event_category="user_action",
                    event_type="field_edited",
                    actor=actor,
                    payload={
                        "field_name": field_name,
                        "old_value":  old_value,
                        "new_value":  hitl_value,
                        "was_ai_authoritative": was_ai_authoritative,
                        "reason":     reason or None,
                        "hitl_override_id":
                            str(hitl_override_id) if hitl_override_id else None,
                    },
                    field_name=field_name,
                )
            await conn.commit()

        # Re-fetch the row + supporting context and rebuild ONE
        # field-view dict so we can re-render the macro. HTMX swaps
        # the outer .verity-field with this fresh markup.
        sub = await _get_submission(submission_id)
        extractions = await _get_extractions(submission_id)
        documents = await _get_documents(submission_id)
        sections = _build_field_sections(sub, extractions, documents)
        target = None
        for sec in sections:
            for f in sec["fields"]:
                if f["field_name"] == field_name:
                    target = f
                    break
            if target:
                break
        if not target:
            # Field isn't in the layout map. Should never happen
            # — defensive fallback returns nothing so HTMX clears
            # the row rather than rendering stale markup.
            return HTMLResponse("", status_code=200)
        return templates.TemplateResponse(
            request, "partials/_field_row_swap.html",
            {"field": target, "sub": sub},
        )

    # ── HITL EXTRACTION APPROVAL ─────────────────────────────

    @router.post("/submissions/{submission_id}/approve-extraction", response_class=HTMLResponse)
    async def approve_extraction(request: Request, submission_id: str):
        """Process HITL overrides and complete the Information Review
        stage. Writes user-corrected values to submission_extraction's
        hitl_* channel and clears review flags.

        NOTE: per-field override reason text from the form is currently
        dropped on the floor. Phase 6 routes per-field reasons through
        submission_extraction_audit and the Verity hitl_override API
        when the sparkle/pen UX lands.
        """
        form = await request.form()
        reviewer = form.get("reviewer_name", "Underwriter")

        # Single transaction: per-field corrections + flag clear +
        # stage transition + user-action event all commit together
        # so the audit trail is consistent with the data writes.
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                # Apply per-field human corrections to the hitl_* channel.
                # Form keys look like 'override_<field_name>'; values
                # are the new value the underwriter typed in.
                for key, value in form.items():
                    if key.startswith("override_") and value:
                        field_name = key.replace("override_", "")
                        await cur.execute(
                            """UPDATE submission_extraction SET
                                hitl_value = %s,
                                hitl_by    = %s,
                                hitl_at    = NOW(),
                                needs_review = FALSE
                            WHERE submission_id = %s AND field_name = %s""",
                            (value, reviewer, submission_id, field_name),
                        )

                # Clear remaining flags — fields the reviewer accepted as-is.
                await cur.execute(
                    """UPDATE submission_extraction SET needs_review = FALSE
                    WHERE submission_id = %s AND needs_review = TRUE""",
                    (submission_id,),
                )

                await record_event(
                    cur, submission_id,
                    event_category="user_action",
                    event_type="extraction_approved",
                    actor=reviewer,
                )
                await transition_stage(
                    cur, submission_id, "information_review", "complete",
                    changed_by=reviewer,
                    reason="Reviewer approved extracted fields",
                )
            await conn.commit()

        # Auto-trigger Pipeline 2 after HITL approval. The
        # risk-assessment internal helper writes its own stage
        # transitions for the triage + appetite stages.
        await verity.ensure_connected()
        sub = await _get_submission(submission_id)
        await _run_risk_assessment_internal(verity, submission_id, sub, templates)

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

    Stage transitions written by this function:
      on entry             → triage.status        = running
      workflow exception   → triage.status        = failed
      pipeline 'failed'    → triage.status        = failed
      pipeline succeeded   → triage / appetite stages updated per
                             their per-step status from the result.

    The execution_context_id is reused from the submission row if
    set; otherwise a new context is minted and persisted so the
    "View in Verity" link is always populated after a run.
    """
    # ── Pre-flight: mark triage running, record pipeline start ──
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await transition_stage(
                cur, submission_id, "triage", "running",
                changed_by="system",
                reason="Triage pipeline starting",
            )
            await record_event(
                cur, submission_id,
                event_category="pipeline",
                event_type="started",
                actor="system",
                payload={"kind": "risk_assessment"},
            )
        await conn.commit()

    # Resolve the execution context: reuse if set, else mint and persist.
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

    # ── Run the pipeline (network/AI work, outside DB tx) ────────
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
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE submission SET
                        execution_context_id = COALESCE(execution_context_id, %s)
                    WHERE id = %s""",
                    (str(exec_ctx_id) if exec_ctx_id else None, submission_id),
                )
                await transition_stage(
                    cur, submission_id, "triage", "failed",
                    changed_by="system",
                    reason=f"Workflow exception: {str(e)[:200]}",
                )
                await record_event(
                    cur, submission_id,
                    event_category="pipeline",
                    event_type="failed",
                    actor="system",
                    payload={"kind": "risk_assessment",
                             "error": str(e)[:200]},
                )
            await conn.commit()
        return

    run_id = str(result.workflow_run_id)

    # ── Pipeline reported failure (steps failed) ─────────────────
    if result.status == "failed":
        error_msg = ""
        for step in result.all_steps:
            if step.status == "failed":
                error_msg = step.error_message or "Unknown error"
                break
        logger.error(f"Pipeline 2 failed for {submission_id}: {error_msg}")
        async with await _get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """UPDATE submission SET
                        last_risk_workflow_run_id = %s,
                        execution_context_id = COALESCE(execution_context_id, %s)
                    WHERE id = %s""",
                    (run_id, str(exec_ctx_id) if exec_ctx_id else None,
                     submission_id),
                )
                await transition_stage(
                    cur, submission_id, "triage", "failed",
                    changed_by="system",
                    run_id=run_id,
                    reason=error_msg[:200],
                )
                await record_event(
                    cur, submission_id,
                    event_category="pipeline",
                    event_type="failed",
                    actor="system",
                    payload={"kind": "risk_assessment",
                             "error": error_msg[:200]},
                    workflow_run_id=run_id,
                )
            await conn.commit()
        return

    # ── Pipeline succeeded — map per-step results to stage statuses
    # Each Verity step maps to one stage; same-status no-op handled
    # internally by transition_stage (idempotent).
    step_to_stage = {
        "triage_submission": "triage",
        "assess_appetite":   "appetite",
    }
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """UPDATE submission SET
                    last_risk_workflow_run_id = %s,
                    execution_context_id = COALESCE(execution_context_id, %s)
                WHERE id = %s""",
                (run_id, str(exec_ctx_id) if exec_ctx_id else None,
                 submission_id),
            )
            for step in result.all_steps:
                stage = step_to_stage.get(step.step_name)
                if not stage:
                    continue
                # 'skipped' from the workflow maps to 'complete' on
                # the stage (the stage was decided not-to-run, but
                # the overall workflow can move forward).
                target_status = (
                    "complete" if step.status in ("complete", "skipped")
                    else "failed"
                )
                await transition_stage(
                    cur, submission_id, stage, target_status,
                    changed_by="system",
                    run_id=run_id,
                    reason=(step.error_message[:200]
                            if (target_status == "failed" and step.error_message)
                            else None),
                )
        await conn.commit()

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

    # Final pipeline-level event. Per-stage transitions above already
    # captured the granular outcome; this is the umbrella record.
    async with await _get_conn() as conn:
        async with conn.cursor() as cur:
            await record_event(
                cur, submission_id,
                event_category="pipeline",
                event_type="completed",
                actor="system",
                payload={"kind": "risk_assessment",
                         "outcome": result.status},
                workflow_run_id=run_id,
            )
        await conn.commit()
