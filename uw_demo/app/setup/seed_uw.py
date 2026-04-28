"""Seed uw_db with demo submissions, loss history, documents,
extractions, and assessments.

Creates the schema (idempotent) and inserts 10 demo submissions
across DO and GL lines of business with varied stages of the UW
workflow:

  - 5 in 'intake'             — fresh submissions, no docs persisted
  - 2 in 'review'             — extraction has flagged HITL items
  - 2 in 'approved'           — extraction passed cleanly
  - 1 in 'assessed'           — full pipeline complete (extraction + triage + appetite)

For non-intake submissions the seed also writes:
  - one row per document into uw_db `document` (referencing the
    EDMS UUIDs returned by seed_edms);
  - per-field rows into `submission_extraction`;
  - for the 'assessed' row, triage and appetite rows into
    `submission_assessment`.

Usage:
    # Called from register_all.py with the EDMS doc id map:
    await seed_uw_db(edms_doc_ids=edms_doc_ids)

    # Or standalone (no document/extraction seeding for non-intake):
    python -m uw_demo.app.setup.seed_uw
"""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg

# We import SUBMISSION_DOCS so this script and seed_edms agree on
# which files belong to which submission. Single source of truth.
from uw_demo.app.setup.seed_edms import SUBMISSION_DOCS
# Stage-aware state machine helpers — the seed script uses the same
# transition path the runtime uses so we don't drift away from rule
# checks in seed-time data shaping.
from uw_demo.app.db.state import ensure_stages, transition_stage


# ── DATABASE URL ─────────────────────────────────────────────

UW_DB_URL = os.environ.get(
    "UW_DB_URL",
    "postgresql://verityuser:veritypass123@localhost:5432/uw_db",
)

# Path to schema file
SCHEMA_FILE = Path(__file__).parent.parent / "db" / "schema.sql"


# ── DEMO SUBMISSIONS ────────────────────────────────────────
# 10 submissions across DO and GL with varied stages.
#
# Status field values used here match what _compute_next_action and
# the UI templates already recognise:
#   intake | documents_received | documents_processed | review |
#   approved | assessed
# (The formal ENUM with transition guards is added in a later phase.)

SUBMISSIONS = [
    # ── Row 1: DO, mid revenue, machinery — intake ─────────────
    {
        "id": "00000001-0001-0001-0001-000000000001",
        "named_insured": "Acme Dynamics LLC",
        "lob": "DO",
        "fein": "12-3456789",
        "entity_type": "LLC",
        "state_of_incorporation": "Delaware",
        "sic_code": "3559",
        "sic_description": "Special Industry Machinery",
        "annual_revenue": 50000000,
        "employee_count": 250,
        "board_size": 7,
        "independent_directors": 4,
        "effective_date": "2026-07-01",
        "expiration_date": "2027-07-01",
        "limits_requested": 5000000,
        "retention_requested": 100000,
        "prior_carrier": "National Union",
        "prior_premium": 45000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    # ── Row 2: DO, large revenue, software — intake ────────────
    {
        "id": "00000002-0002-0002-0002-000000000002",
        "named_insured": "TechFlow Industries Inc",
        "lob": "DO",
        "fein": "98-7654321",
        "entity_type": "Corporation",
        "state_of_incorporation": "California",
        "sic_code": "7372",
        "sic_description": "Prepackaged Software",
        "annual_revenue": 120000000,
        "employee_count": 800,
        "board_size": 9,
        "independent_directors": 5,
        "effective_date": "2026-06-01",
        "expiration_date": "2027-06-01",
        "limits_requested": 10000000,
        "retention_requested": 250000,
        "prior_carrier": "AIG",
        "prior_premium": 125000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 75000, "paid": 50000, "reserves": 25000},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 150000, "paid": 0, "reserves": 150000},
        ],
    },
    # ── Row 3: GL, small revenue, financial services — intake ──
    {
        "id": "00000003-0003-0003-0003-000000000003",
        "named_insured": "Meridian Holdings Corp",
        "lob": "GL",
        "fein": "55-1234567",
        "entity_type": "Corporation",
        "state_of_incorporation": "New York",
        "sic_code": "6159",
        "sic_description": "Federal-Sponsored Credit Agencies",
        "annual_revenue": 25000000,
        "employee_count": 150,
        "effective_date": "2026-09-01",
        "expiration_date": "2027-09-01",
        "limits_requested": 2000000,
        "retention_requested": 50000,
        "prior_carrier": "Hartford",
        "prior_premium": 35000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 5, "incurred": 320000, "paid": 280000, "reserves": 40000},
            {"year": 2024, "claims": 4, "incurred": 185000, "paid": 150000, "reserves": 35000},
            {"year": 2025, "claims": 3, "incurred": 95000, "paid": 60000, "reserves": 35000},
        ],
    },
    # ── Row 4: GL, mid revenue, machinery — intake ─────────────
    {
        "id": "00000004-0004-0004-0004-000000000004",
        "named_insured": "Acme Dynamics LLC",
        "lob": "GL",
        "fein": "12-3456789",
        "entity_type": "LLC",
        "state_of_incorporation": "Delaware",
        "sic_code": "3559",
        "sic_description": "Special Industry Machinery",
        "annual_revenue": 50000000,
        "employee_count": 250,
        "effective_date": "2026-07-01",
        "expiration_date": "2027-07-01",
        "limits_requested": 3000000,
        "retention_requested": 75000,
        "prior_carrier": "Travelers",
        "prior_premium": 28000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 45000, "paid": 45000, "reserves": 0},
            {"year": 2024, "claims": 2, "incurred": 80000, "paid": 60000, "reserves": 20000},
            {"year": 2025, "claims": 2, "incurred": 65000, "paid": 40000, "reserves": 25000},
        ],
    },
    # ── Row 5: DO, small revenue, data analytics — intake ──────
    {
        "id": "00000005-0005-0005-0005-000000000005",
        "named_insured": "Brightline Analytics LLC",
        "lob": "DO",
        "fein": "33-2244557",
        "entity_type": "LLC",
        "state_of_incorporation": "Massachusetts",
        "sic_code": "7374",
        "sic_description": "Computer Processing and Data Preparation",
        "annual_revenue": 15000000,
        "employee_count": 90,
        "board_size": 5,
        "independent_directors": 2,
        "effective_date": "2026-08-15",
        "expiration_date": "2027-08-15",
        "limits_requested": 2000000,
        "retention_requested": 50000,
        "prior_carrier": "Chubb",
        "prior_premium": 18000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    # ── Row 6: DO, mid revenue, software — review ──────────────
    {
        "id": "00000006-0006-0006-0006-000000000006",
        "named_insured": "Pinnacle Software Inc",
        "lob": "DO",
        "fein": "47-3344558",
        "entity_type": "Corporation",
        "state_of_incorporation": "Washington",
        "sic_code": "7372",
        "sic_description": "Prepackaged Software",
        "annual_revenue": 80000000,
        "employee_count": 420,
        "board_size": 8,
        "independent_directors": 4,
        "effective_date": "2026-06-15",
        "expiration_date": "2027-06-15",
        "limits_requested": 7500000,
        "retention_requested": 150000,
        "prior_carrier": "Liberty Mutual",
        "prior_premium": 78000,
        "status": "review",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 95000, "paid": 75000, "reserves": 20000},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 220000, "paid": 0, "reserves": 220000},
        ],
    },
    # ── Row 7: DO, large revenue, hardware mfg — review ────────
    {
        "id": "00000007-0007-0007-0007-000000000007",
        "named_insured": "Westfield Manufacturing Co",
        "lob": "DO",
        "fein": "59-4455661",
        "entity_type": "Corporation",
        "state_of_incorporation": "Ohio",
        "sic_code": "3429",
        "sic_description": "Hardware NEC",
        "annual_revenue": 200000000,
        "employee_count": 1100,
        "board_size": 11,
        "independent_directors": 6,
        "effective_date": "2026-05-01",
        "expiration_date": "2027-05-01",
        "limits_requested": 15000000,
        "retention_requested": 500000,
        "prior_carrier": "AIG",
        "prior_premium": 195000,
        "status": "review",
        "loss_history": [
            {"year": 2023, "claims": 2, "incurred": 380000, "paid": 280000, "reserves": 100000},
            {"year": 2024, "claims": 1, "incurred": 45000, "paid": 45000, "reserves": 0},
            {"year": 2025, "claims": 3, "incurred": 720000, "paid": 200000, "reserves": 520000},
        ],
    },
    # ── Row 8: GL, mid revenue, precision parts — approved ─────
    {
        "id": "00000008-0008-0008-0008-000000000008",
        "named_insured": "Cascade Precision LLC",
        "lob": "GL",
        "fein": "82-5566772",
        "entity_type": "LLC",
        "state_of_incorporation": "Oregon",
        "sic_code": "3599",
        "sic_description": "Industrial and Commercial Machinery NEC",
        "annual_revenue": 45000000,
        "employee_count": 220,
        "effective_date": "2026-10-01",
        "expiration_date": "2027-10-01",
        "limits_requested": 4000000,
        "retention_requested": 100000,
        "prior_carrier": "Travelers",
        "prior_premium": 52000,
        "status": "approved",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 28000, "paid": 28000, "reserves": 0},
            {"year": 2024, "claims": 1, "incurred": 42000, "paid": 42000, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    # ── Row 9: GL, large revenue, structural metal — approved ──
    {
        "id": "00000009-0009-0009-0009-000000000009",
        "named_insured": "Ironworks Heavy Industries",
        "lob": "GL",
        "fein": "91-6677883",
        "entity_type": "Corporation",
        "state_of_incorporation": "Pennsylvania",
        "sic_code": "3441",
        "sic_description": "Fabricated Structural Metal Products",
        "annual_revenue": 180000000,
        "employee_count": 950,
        "effective_date": "2026-04-15",
        "expiration_date": "2027-04-15",
        "limits_requested": 12000000,
        "retention_requested": 350000,
        "prior_carrier": "Zurich",
        "prior_premium": 215000,
        "status": "approved",
        "loss_history": [
            {"year": 2023, "claims": 4, "incurred": 380000, "paid": 320000, "reserves": 60000},
            {"year": 2024, "claims": 3, "incurred": 245000, "paid": 220000, "reserves": 25000},
            {"year": 2025, "claims": 2, "incurred": 110000, "paid": 90000, "reserves": 20000},
        ],
    },
    # ── Row 10: GL, mid-large revenue, chemicals — assessed ────
    {
        "id": "00000010-0010-0010-0010-000000000010",
        "named_insured": "Bayview Chemical Co",
        "lob": "GL",
        "fein": "16-7788994",
        "entity_type": "Corporation",
        "state_of_incorporation": "Texas",
        "sic_code": "2899",
        "sic_description": "Industrial Inorganic Chemicals NEC",
        "annual_revenue": 95000000,
        "employee_count": 410,
        "effective_date": "2026-03-01",
        "expiration_date": "2027-03-01",
        "limits_requested": 8000000,
        "retention_requested": 200000,
        "prior_carrier": "Liberty Mutual",
        "prior_premium": 138000,
        "status": "assessed",
        "loss_history": [
            {"year": 2023, "claims": 2, "incurred": 165000, "paid": 165000, "reserves": 0},
            {"year": 2024, "claims": 1, "incurred": 88000, "paid": 88000, "reserves": 0},
            {"year": 2025, "claims": 2, "incurred": 220000, "paid": 80000, "reserves": 140000},
        ],
    },
    # ── Row 11: GL, small revenue, logistics — documents_received,
    # but Vault has NO documents for this submission (no entry in
    # SUBMISSION_DOCS). Exercises the empty-state UX in the
    # Documents tab — the user sees "no docs" with both Discover
    # and Upload buttons available even after status has moved
    # past 'intake'. ─────────────────────────────────────────────
    {
        "id": "00000011-0011-0011-0011-000000000011",
        "named_insured": "Skyline Logistics Group",
        "lob": "GL",
        "fein": "27-8899005",
        "entity_type": "Corporation",
        "state_of_incorporation": "Illinois",
        "sic_code": "4213",
        "sic_description": "Trucking, Except Local",
        "annual_revenue": 22000000,
        "employee_count": 130,
        "effective_date": "2026-11-01",
        "expiration_date": "2027-11-01",
        "limits_requested": 1500000,
        "retention_requested": 50000,
        "prior_carrier": "Progressive",
        "prior_premium": 24000,
        "status": "documents_received",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 35000, "paid": 35000, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 18000, "paid": 18000, "reserves": 0},
        ],
    },
]


# ── EXTRACTION SEED DATA ────────────────────────────────────
# For submissions in 'review' / 'approved' / 'assessed' we pre-seed
# `submission_extraction` rows so the UI has realistic data to render
# without requiring the user to first run the extraction pipeline.
#
# 'review' rows include needs_review=TRUE on a couple of fields with
# lower confidence to demonstrate the HITL flag flow. 'approved' and
# 'assessed' rows are clean (no review flags).
#
# Schema columns in this phase: field_name, extracted_value, confidence,
# needs_review, review_reason, extraction_notes. Provenance columns
# (source_document_id, source_page, etc.) are added in a later phase
# and will be backfilled then.

EXTRACTIONS_BY_SUBMISSION: dict[str, list[dict]] = {
    # ── Row 6: Pinnacle Software (review) ──────────────────────
    "00000006-0006-0006-0006-000000000006": [
        {"field": "named_insured", "value": "Pinnacle Software Inc", "confidence": 0.98},
        {"field": "fein", "value": "47-3344558", "confidence": 0.95},
        {"field": "annual_revenue", "value": "80000000", "confidence": 0.91},
        {"field": "employee_count", "value": "420", "confidence": 0.88},
        {"field": "board_size", "value": "8", "confidence": 0.92},
        {"field": "independent_directors", "value": "4", "confidence": 0.65,
         "needs_review": True, "review_reason": "low_confidence"},
        {"field": "limits_requested", "value": "7500000", "confidence": 0.94},
        {"field": "retention_requested", "value": "150000", "confidence": 0.90},
        {"field": "prior_carrier", "value": "Liberty Mutual", "confidence": 0.62,
         "needs_review": True, "review_reason": "low_confidence"},
    ],
    # ── Row 7: Westfield Manufacturing (review) ────────────────
    "00000007-0007-0007-0007-000000000007": [
        {"field": "named_insured", "value": "Westfield Manufacturing Co", "confidence": 0.97},
        {"field": "fein", "value": "59-4455661", "confidence": 0.96},
        {"field": "annual_revenue", "value": "200000000", "confidence": 0.89},
        {"field": "employee_count", "value": "1100", "confidence": 0.87},
        {"field": "board_size", "value": "11", "confidence": 0.91},
        {"field": "independent_directors", "value": "6", "confidence": 0.85},
        {"field": "limits_requested", "value": "15000000", "confidence": 0.66,
         "needs_review": True, "review_reason": "low_confidence"},
        {"field": "retention_requested", "value": "500000", "confidence": 0.93},
        {"field": "prior_carrier", "value": "AIG", "confidence": 0.95},
    ],
    # ── Row 8: Cascade Precision (approved) ────────────────────
    "00000008-0008-0008-0008-000000000008": [
        {"field": "named_insured", "value": "Cascade Precision LLC", "confidence": 0.98},
        {"field": "fein", "value": "82-5566772", "confidence": 0.96},
        {"field": "annual_revenue", "value": "45000000", "confidence": 0.94},
        {"field": "employee_count", "value": "220", "confidence": 0.93},
        {"field": "limits_requested", "value": "4000000", "confidence": 0.95},
        {"field": "retention_requested", "value": "100000", "confidence": 0.92},
        {"field": "prior_carrier", "value": "Travelers", "confidence": 0.97},
    ],
    # ── Row 9: Ironworks Heavy (approved) ──────────────────────
    "00000009-0009-0009-0009-000000000009": [
        {"field": "named_insured", "value": "Ironworks Heavy Industries", "confidence": 0.99},
        {"field": "fein", "value": "91-6677883", "confidence": 0.97},
        {"field": "annual_revenue", "value": "180000000", "confidence": 0.91},
        {"field": "employee_count", "value": "950", "confidence": 0.89},
        {"field": "limits_requested", "value": "12000000", "confidence": 0.94},
        {"field": "retention_requested", "value": "350000", "confidence": 0.90},
        {"field": "prior_carrier", "value": "Zurich", "confidence": 0.95},
    ],
    # ── Row 10: Bayview Chemical (assessed) ────────────────────
    "00000010-0010-0010-0010-000000000010": [
        {"field": "named_insured", "value": "Bayview Chemical Co", "confidence": 0.98},
        {"field": "fein", "value": "16-7788994", "confidence": 0.95},
        {"field": "annual_revenue", "value": "95000000", "confidence": 0.92},
        {"field": "employee_count", "value": "410", "confidence": 0.90},
        {"field": "limits_requested", "value": "8000000", "confidence": 0.93},
        {"field": "retention_requested", "value": "200000", "confidence": 0.91},
        {"field": "prior_carrier", "value": "Liberty Mutual", "confidence": 0.96},
    ],
}


# ── ASSESSMENT SEED DATA ────────────────────────────────────
# Only the 'assessed' submission gets pre-seeded triage + appetite.
# Everything else lights up via the live mock pipeline when the user
# clicks Process Documents → Assess Risk.

ASSESSMENTS_BY_SUBMISSION: dict[str, dict[str, dict]] = {
    "00000010-0010-0010-0010-000000000010": {
        "triage": {
            "risk_score": "Amber",
            "routing": "assign_to_senior_uw",
            "confidence": 0.84,
            "reasoning": (
                "Bayview Chemical has a clean financial profile and "
                "moderate claims frequency, but 2025 reserves remain "
                "open at $140K and the SIC 2899 chemical class warrants "
                "senior review for products/completed-ops exposure. "
                "Routing to senior underwriter."
            ),
        },
        "appetite": {
            "determination": "borderline",
            "confidence": 0.78,
            "reasoning": (
                "Industrial chemicals (SIC 2899) is on the appetite "
                "watch list. Revenue and loss history are within "
                "guidelines but the sector requires explicit senior "
                "approval per §4.1 of the GL guidelines."
            ),
        },
    },
}


# ── SEEDING LOGIC ────────────────────────────────────────────


async def _seed_submission_row(cur, sub: dict) -> None:
    """Insert one row into `submission`. Idempotency is handled by the
    caller before this is invoked. The submission table has no
    `status` column — stage state lives in submission_stage rows
    (seeded by _seed_submission_stages)."""
    await cur.execute(
        """INSERT INTO submission (
            id, named_insured, lob, fein, entity_type,
            state_of_incorporation, sic_code, sic_description,
            annual_revenue, employee_count, board_size,
            independent_directors, effective_date, expiration_date,
            limits_requested, retention_requested,
            prior_carrier, prior_premium
        ) VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s,
            %s, %s
        )""",
        (
            sub["id"], sub["named_insured"], sub["lob"],
            sub.get("fein"), sub.get("entity_type"),
            sub.get("state_of_incorporation"), sub.get("sic_code"),
            sub.get("sic_description"),
            sub.get("annual_revenue"), sub.get("employee_count"),
            sub.get("board_size"), sub.get("independent_directors"),
            sub.get("effective_date"), sub.get("expiration_date"),
            sub.get("limits_requested"), sub.get("retention_requested"),
            sub.get("prior_carrier"), sub.get("prior_premium"),
        ),
    )


async def _seed_loss_history(cur, sub: dict) -> None:
    """Insert all loss-history years for a submission."""
    for loss in sub.get("loss_history", []):
        await cur.execute(
            """INSERT INTO loss_history (
                submission_id, policy_year, claims_count,
                incurred, paid, reserves
            ) VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                sub["id"], loss["year"], loss["claims"],
                loss["incurred"], loss["paid"], loss["reserves"],
            ),
        )


async def _seed_submission_stages(cur, sub: dict) -> None:
    """Seed submission_stage rows so the new submission lands in
    the same workflow position the old `status` enum implied.

    Status mapping (from the legacy `status` field on the seed dict
    to the per-stage statuses we now write):

      intake               — all stages pending
      documents_received   — intake.complete,
                             document_processing.blocked_on_input
                             (waiting for the user to click Process)
      review               — intake + document_processing complete,
                             information_review.running
      approved             — through information_review complete
      assessed             — all forward stages complete
      declined             — declined.failed (terminal)

    Re-uses the runtime's transition_stage helper so the audit
    events the runtime would emit are emitted here too — seeded
    submissions get a coherent submission_event timeline.
    """
    sid = sub["id"]
    status = sub.get("status", "intake")

    # Always create the row-per-stage skeleton first.
    await ensure_stages(cur, sid)

    # Intake is "we have the submission record" — true by virtue of
    # the row existing. Transition unconditionally so even the
    # freshest 'intake' submission has its first stage marked done
    # and current_stage moves to document_processing.
    await transition_stage(cur, sid, "intake", "complete",
                            changed_by="seed_script",
                            reason="seed: intake auto-complete (row exists)")

    # Walk forward stages to the position implied by the legacy
    # `status` field. transition_stage is idempotent on same-status,
    # so unhit stages stay at their default 'pending'.

    if status == "documents_received":
        await transition_stage(cur, sid, "document_processing",
                                "blocked_on_input",
                                changed_by="seed_script",
                                blocked_reason="awaiting_pipeline_trigger",
                                reason="seed: docs discovered, awaiting processing")

    if status in ("review", "approved", "assessed"):
        await transition_stage(cur, sid, "document_processing", "complete",
                                changed_by="seed_script",
                                reason="seed: doc-processing pipeline finished")

    if status == "review":
        await transition_stage(cur, sid, "information_review", "running",
                                changed_by="seed_script",
                                reason="seed: HITL review pending")

    if status in ("approved", "assessed"):
        await transition_stage(cur, sid, "information_review", "complete",
                                changed_by="seed_script",
                                reason="seed: review approved (auto or HITL)")

    if status == "assessed":
        await transition_stage(cur, sid, "triage", "complete",
                                changed_by="seed_script",
                                reason="seed: triage complete")
        await transition_stage(cur, sid, "appetite", "complete",
                                changed_by="seed_script",
                                reason="seed: appetite complete")


async def _seed_documents(cur, sub: dict, edms_doc_ids: dict[str, str]) -> int:
    """Insert one `document` row per file in SUBMISSION_DOCS for this
    submission. Looks up each filename in the edms_doc_ids map (built
    by seed_edms during upload). Files not found in the map are
    skipped with a warning print — usually means seed_edms didn't run
    or the file is missing from seed_docs/filled/.

    Returns the number of rows inserted."""
    filenames = SUBMISSION_DOCS.get(sub["id"], [])
    if not filenames:
        return 0

    inserted = 0
    for fname in filenames:
        edms_uuid = edms_doc_ids.get(fname)
        if not edms_uuid:
            print(f"    ! skip {fname} — not in EDMS upload map")
            continue
        # content_type from extension; cheap and good enough for the
        # demo display. EDMS already has the canonical value.
        content_type = "application/pdf" if fname.endswith(".pdf") else "text/plain"
        await cur.execute(
            """INSERT INTO document (
                submission_id, edms_document_id, filename, content_type,
                discovery_status, extraction_status
            ) VALUES (%s, %s, %s, %s, 'received', 'pending')
            ON CONFLICT (submission_id, edms_document_id) DO NOTHING
            """,
            (sub["id"], edms_uuid, fname, content_type),
        )
        inserted += 1
    return inserted


def _application_filename(submission_id: str) -> str | None:
    """Pick the submission's primary application PDF — the
    do_app_*.pdf or gl_app_*.pdf in its SUBMISSION_DOCS list.
    That's the file most extracted fields are sourced from for
    seed purposes; the sparkle tooltip names it as the source.
    Falls back to the first listed file when no application file
    is identified."""
    files = SUBMISSION_DOCS.get(submission_id, [])
    for f in files:
        if f.startswith("do_app_") or f.startswith("gl_app_"):
            return f
    return files[0] if files else None


async def _seed_extractions(cur, sub: dict) -> int:
    """Insert per-field extraction rows in the new ai_*/hitl_* model
    with structured provenance the sparkle UX needs.

    For each seeded field we set:
      ai_value, ai_confidence, ai_found=TRUE
      source_document_id  (uw_db `document.id` of the submission's
                           primary application PDF)
      source_snippet      (a quoted version of the value; stand-in
                           for a real verbatim quote)
      extractor_id        ('field_extractor@seed' so the sparkle
                           tooltip's Extractor: line is non-empty)
      output_path         ('$.fields.<name>.value' — same convention
                           live runs use)
      verity_execution_run_id stays NULL on seeded rows because no
      Verity decision exists; the edit handler will recognise NULL
      and skip the override-API forwarding path for these rows."""
    fields = EXTRACTIONS_BY_SUBMISSION.get(sub["id"])
    if not fields:
        return 0

    # Resolve the source document id once per submission.
    src_filename = _application_filename(sub["id"])
    src_doc_id: str | None = None
    if src_filename:
        await cur.execute(
            """SELECT id FROM document
            WHERE submission_id = %s AND filename = %s""",
            (sub["id"], src_filename),
        )
        row = await cur.fetchone()
        if row:
            src_doc_id = str(row[0])

    for f in fields:
        snippet = f'"{f["value"]}"' if f.get("value") is not None else None
        output_path = f"$.fields.{f['field']}.value"
        await cur.execute(
            """INSERT INTO submission_extraction (
                submission_id, field_name,
                ai_value, ai_confidence, ai_found,
                source_document_id, source_snippet,
                extractor_id, output_path,
                needs_review, review_reason
            ) VALUES (%s, %s, %s, %s, TRUE, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (submission_id, field_name) DO NOTHING
            """,
            (
                sub["id"], f["field"], f["value"], f["confidence"],
                src_doc_id, snippet,
                "field_extractor@seed", output_path,
                f.get("needs_review", False), f.get("review_reason"),
            ),
        )
    return len(fields)


async def _seed_assessments(cur, sub: dict) -> int:
    """Insert triage and appetite rows for the 'assessed' submission."""
    by_type = ASSESSMENTS_BY_SUBMISSION.get(sub["id"])
    if not by_type:
        return 0

    triage = by_type.get("triage")
    if triage:
        await cur.execute(
            """INSERT INTO submission_assessment (
                submission_id, assessment_type, result,
                risk_score, routing, confidence, reasoning
            ) VALUES (%s, 'triage', %s, %s, %s, %s, %s)
            ON CONFLICT (submission_id, assessment_type) DO NOTHING
            """,
            (
                sub["id"], json.dumps(triage),
                triage.get("risk_score"), triage.get("routing"),
                triage.get("confidence"), triage.get("reasoning"),
            ),
        )

    appetite = by_type.get("appetite")
    if appetite:
        await cur.execute(
            """INSERT INTO submission_assessment (
                submission_id, assessment_type, result,
                determination, confidence, reasoning
            ) VALUES (%s, 'appetite', %s, %s, %s, %s)
            ON CONFLICT (submission_id, assessment_type) DO NOTHING
            """,
            (
                sub["id"], json.dumps(appetite),
                appetite.get("determination"),
                appetite.get("confidence"), appetite.get("reasoning"),
            ),
        )
    return (1 if triage else 0) + (1 if appetite else 0)


async def seed_uw_db(edms_doc_ids: dict[str, str] | None = None):
    """Apply schema and insert all demo data.

    Args:
        edms_doc_ids: filename → EDMS UUID map returned by seed_edms.
            When None (standalone run), document/extraction/assessment
            seeding for non-intake submissions is skipped.
    """
    edms_doc_ids = edms_doc_ids or {}

    # ── Apply schema (idempotent — uses IF NOT EXISTS) ────────
    schema_sql = SCHEMA_FILE.read_text()

    async with await psycopg.AsyncConnection.connect(UW_DB_URL) as conn:
        async with conn.cursor() as cur:
            await cur.execute(schema_sql)
        await conn.commit()
        print("  + uw_db schema applied")

        # ── Insert submissions + supporting rows ──────────────
        async with conn.cursor() as cur:
            for sub in SUBMISSIONS:
                # Idempotency — skip if the submission already exists.
                await cur.execute(
                    "SELECT 1 FROM submission WHERE id = %s",
                    (sub["id"],),
                )
                if await cur.fetchone():
                    print(f"  = submission {sub['id'][:8]}… already exists, skipping")
                    continue

                await _seed_submission_row(cur, sub)
                await _seed_loss_history(cur, sub)
                await _seed_submission_stages(cur, sub)

                # For non-intake rows, seed documents + extractions
                # (and assessments for 'assessed').
                doc_count = 0
                ext_count = 0
                ass_count = 0
                if sub.get("status", "intake") != "intake":
                    doc_count = await _seed_documents(cur, sub, edms_doc_ids)
                    ext_count = await _seed_extractions(cur, sub)
                    ass_count = await _seed_assessments(cur, sub)

                tag = f"{sub['named_insured']} ({sub['lob']}, {sub.get('status', 'intake')})"
                extras: list[str] = []
                if doc_count: extras.append(f"{doc_count} docs")
                if ext_count: extras.append(f"{ext_count} extractions")
                if ass_count: extras.append(f"{ass_count} assessments")
                extras_str = f" [{', '.join(extras)}]" if extras else ""
                print(f"  + {tag}{extras_str}")

        await conn.commit()
        print(f"  + {len(SUBMISSIONS)} submissions seeded")

        # ── Seed app settings ─────────────────────────────────
        async with conn.cursor() as cur:
            settings_data = [
                ("pipeline_mode", "mock",
                 "mock = pre-built outputs (free, instant). live = real Claude API calls (~$0.15/submission)."),
            ]
            for key, value, desc in settings_data:
                await cur.execute(
                    """INSERT INTO app_settings (key, value, description)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key) DO NOTHING""",
                    (key, value, desc),
                )
        await conn.commit()
        print(f"  + app_settings seeded (pipeline_mode=mock)")


# ── STANDALONE ENTRY POINT ───────────────────────────────────

if __name__ == "__main__":
    asyncio.run(seed_uw_db())
