"""Seed uw_db with demo submissions and loss history.

Two seeding shapes per submission, picked by an external
allowlist file (showcase_submissions.txt):

  * Showcase rows (uncommented in showcase_submissions.txt):
    full column set seeded. These demo the "AI already
    extracted everything" path — open the submission and the
    Submission Details tab is fully populated.

  * Everything else: only the four intake-metadata columns
    the broker actually sends in the submission email body
    (named_insured, lob, sic_code, sic_description) plus loss
    history. Every document-extractable column is left NULL
    so the user walks Discover Documents → Extract → Review
    without pre-seeded values shadowing AI extractions in the
    audit log or the sparkle UX.

To change which submissions get full-data treatment, edit
showcase_submissions.txt and (un)comment the relevant line —
no code change required.

The companion seed_edms.py uploads documents to the Vault
(EDMS) for both shapes so the user can run extraction on
workflow rows.

CLI:
    # Default — additive seed (creates missing rows only):
    python -m uw_demo.app.setup.seed_uw

    # Surgical re-seed of every non-showcase submission.
    # Showcase rows and any extractions / HITL edits made
    # against them are preserved untouched:
    python -m uw_demo.app.setup.seed_uw --reseed-workflow

    # Reset a single submission to its seed state. Showcase
    # rows reset to full data; others to minimal:
    python -m uw_demo.app.setup.seed_uw --reset <uuid>
"""

import asyncio
import os
from pathlib import Path

import psycopg

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


# ── SHOWCASE ALLOWLIST ───────────────────────────────────────
# File holding the UUIDs of submissions that should be seeded
# with the FULL field set. Anything not in this set (or not in
# the file at all) is seeded with only the minimal intake
# metadata (named_insured, lob, sic_code, sic_description).
#
# Lives next to this script as a plain text file so it can be
# edited without touching code.

SHOWCASE_FILE = Path(__file__).parent / "showcase_submissions.txt"


def _load_showcase_ids() -> frozenset[str]:
    """Read showcase-submission UUIDs from showcase_submissions.txt.

    File format: one entry per line. Lines beginning with '#'
    (after any leading whitespace) are treated as comments and
    skipped. On a non-comment line the first whitespace-
    delimited token is the UUID; anything after it is a human-
    readable label and is ignored.

    A missing file is non-fatal: returns an empty set and prints
    a warning so the misconfiguration is visible in the seeder
    output rather than failing register_all silently.
    """
    if not SHOWCASE_FILE.exists():
        print(
            f"  ! showcase_submissions.txt not found at {SHOWCASE_FILE}; "
            f"all rows will seed minimally"
        )
        return frozenset()
    ids: set[str] = set()
    for line in SHOWCASE_FILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # First token is the UUID; rest of line is label / inline
        # comment and is ignored.
        ids.add(stripped.split()[0])
    return frozenset(ids)


# Loaded once at import time so every entry point in this module
# (the bulk seeder, the surgical reseeder, the single-row reset)
# sees the same set without having to re-parse the file.
SHOWCASE_IDS: frozenset[str] = _load_showcase_ids()


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
    # ── Row 6: DO, mid revenue, software — intake ──────────────
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
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 95000, "paid": 75000, "reserves": 20000},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 220000, "paid": 0, "reserves": 220000},
        ],
    },
    # ── Row 7: DO, large revenue, hardware mfg — intake ────────
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
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 2, "incurred": 380000, "paid": 280000, "reserves": 100000},
            {"year": 2024, "claims": 1, "incurred": 45000, "paid": 45000, "reserves": 0},
            {"year": 2025, "claims": 3, "incurred": 720000, "paid": 200000, "reserves": 520000},
        ],
    },
    # ── Row 8: GL, mid revenue, precision parts — intake ───────
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
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 28000, "paid": 28000, "reserves": 0},
            {"year": 2024, "claims": 1, "incurred": 42000, "paid": 42000, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    # ── Row 9: GL, large revenue, structural metal — intake ────
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
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 4, "incurred": 380000, "paid": 320000, "reserves": 60000},
            {"year": 2024, "claims": 3, "incurred": 245000, "paid": 220000, "reserves": 25000},
            {"year": 2025, "claims": 2, "incurred": 110000, "paid": 90000, "reserves": 20000},
        ],
    },
    # ── Row 10: GL, mid-large revenue, chemicals — intake ──────
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
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 2, "incurred": 165000, "paid": 165000, "reserves": 0},
            {"year": 2024, "claims": 1, "incurred": 88000, "paid": 88000, "reserves": 0},
            {"year": 2025, "claims": 2, "incurred": 220000, "paid": 80000, "reserves": 140000},
        ],
    },
    # ── Row 12: DO, mid revenue, business services — intake ────
    {
        "id": "00000012-0012-0012-0012-000000000012",
        "named_insured": "Continental Services Corp",
        "lob": "DO",
        "fein": "38-9911223",
        "entity_type": "Corporation",
        "state_of_incorporation": "Virginia",
        "sic_code": "7389",
        "sic_description": "Business Services NEC",
        "annual_revenue": 60000000,
        "employee_count": 320,
        "board_size": 7,
        "independent_directors": 3,
        "effective_date": "2026-08-01",
        "expiration_date": "2027-08-01",
        "limits_requested": 5000000,
        "retention_requested": 100000,
        "prior_carrier": "Hartford",
        "prior_premium": 58000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2024, "claims": 1, "incurred": 35000, "paid": 35000, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    # ── Row 13: GL, small revenue, mining — intake ─────────────
    {
        "id": "00000013-0013-0013-0013-000000000013",
        "named_insured": "Granite Peak Mining LLC",
        "lob": "GL",
        "fein": "44-2233445",
        "entity_type": "LLC",
        "state_of_incorporation": "Colorado",
        "sic_code": "1041",
        "sic_description": "Gold Mining",
        "annual_revenue": 18000000,
        "employee_count": 110,
        "effective_date": "2026-09-15",
        "expiration_date": "2027-09-15",
        "limits_requested": 2000000,
        "retention_requested": 75000,
        "prior_carrier": "Zurich",
        "prior_premium": 42000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 2, "incurred": 95000, "paid": 75000, "reserves": 20000},
            {"year": 2024, "claims": 1, "incurred": 38000, "paid": 38000, "reserves": 0},
            {"year": 2025, "claims": 2, "incurred": 120000, "paid": 60000, "reserves": 60000},
        ],
    },
    # ── Row 14: DO, large revenue, financial services — intake ─
    {
        "id": "00000014-0014-0014-0014-000000000014",
        "named_insured": "Horizon Capital Partners",
        "lob": "DO",
        "fein": "61-3344556",
        "entity_type": "Corporation",
        "state_of_incorporation": "New York",
        "sic_code": "6199",
        "sic_description": "Finance Services",
        "annual_revenue": 150000000,
        "employee_count": 540,
        "board_size": 10,
        "independent_directors": 6,
        "effective_date": "2026-05-15",
        "expiration_date": "2027-05-15",
        "limits_requested": 12000000,
        "retention_requested": 350000,
        "prior_carrier": "Chubb",
        "prior_premium": 165000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 180000, "paid": 180000, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 95000, "paid": 0, "reserves": 95000},
        ],
    },
    # ── Row 15: GL, mid revenue, environmental services — intake
    {
        "id": "00000015-0015-0015-0015-000000000015",
        "named_insured": "Clearwater Environmental Inc",
        "lob": "GL",
        "fein": "73-4455667",
        "entity_type": "Corporation",
        "state_of_incorporation": "Washington",
        "sic_code": "4959",
        "sic_description": "Environmental Services NEC",
        "annual_revenue": 40000000,
        "employee_count": 195,
        "effective_date": "2026-07-15",
        "expiration_date": "2027-07-15",
        "limits_requested": 3000000,
        "retention_requested": 100000,
        "prior_carrier": "Liberty Mutual",
        "prior_premium": 48000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 55000, "paid": 55000, "reserves": 0},
            {"year": 2024, "claims": 2, "incurred": 110000, "paid": 80000, "reserves": 30000},
            {"year": 2025, "claims": 1, "incurred": 42000, "paid": 30000, "reserves": 12000},
        ],
    },
    # ── Row 16: DO, small-mid revenue, technology — intake ─────
    {
        "id": "00000016-0016-0016-0016-000000000016",
        "named_insured": "Novatech Holdings Inc",
        "lob": "DO",
        "fein": "85-5566778",
        "entity_type": "Corporation",
        "state_of_incorporation": "Texas",
        "sic_code": "7370",
        "sic_description": "Computer Services",
        "annual_revenue": 28000000,
        "employee_count": 165,
        "board_size": 6,
        "independent_directors": 3,
        "effective_date": "2026-08-01",
        "expiration_date": "2027-08-01",
        "limits_requested": 3000000,
        "retention_requested": 75000,
        "prior_carrier": "Travelers",
        "prior_premium": 32000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2024, "claims": 1, "incurred": 22000, "paid": 22000, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
    # ── Row 17: GL, mid-large revenue, timber/forestry — intake ─
    {
        "id": "00000017-0017-0017-0017-000000000017",
        "named_insured": "Redwood Timber Co",
        "lob": "GL",
        "fein": "92-6677889",
        "entity_type": "Corporation",
        "state_of_incorporation": "California",
        "sic_code": "2411",
        "sic_description": "Logging",
        "annual_revenue": 110000000,
        "employee_count": 480,
        "effective_date": "2026-04-15",
        "expiration_date": "2027-04-15",
        "limits_requested": 8000000,
        "retention_requested": 250000,
        "prior_carrier": "AIG",
        "prior_premium": 145000,
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 3, "incurred": 215000, "paid": 180000, "reserves": 35000},
            {"year": 2024, "claims": 2, "incurred": 130000, "paid": 130000, "reserves": 0},
            {"year": 2025, "claims": 4, "incurred": 290000, "paid": 100000, "reserves": 190000},
        ],
    },
    # ── Row 11: GL, small revenue, logistics — intake.
    # Has NO entry in SUBMISSION_DOCS, so Vault is empty for this
    # submission. Exercises the empty-state UX in the Documents
    # tab even before any extraction has happened. ──────────────
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
        "status": "intake",
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 35000, "paid": 35000, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 18000, "paid": 18000, "reserves": 0},
        ],
    },
]


# ── SEEDING LOGIC ────────────────────────────────────────────


async def _seed_submission_row(cur, sub: dict) -> None:
    """Insert one row into `submission`.

    Two paths driven by SHOWCASE_IDS:

      * Showcase id: full column set seeded — same behaviour as
        the original seeder. The Submission Details tab will
        render fully populated.

      * Anything else: minimal intake metadata only
        (named_insured, lob, sic_code, sic_description). Every
        document-extractable column is left NULL so the AI
        extractor writes the canonical value and the audit log
        / sparkle UX have a single source of truth.

    Idempotency is the caller's responsibility. Stage state
    lives in submission_stage rows (seeded by
    _seed_submission_stages), not on the submission row.
    """
    if sub["id"] in SHOWCASE_IDS:
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
    else:
        # Minimal seed — only what arrives in the broker email
        # body before any document is opened. Everything else is
        # NULL on purpose so the AI extractor populates it.
        await cur.execute(
            """INSERT INTO submission (
                id, named_insured, lob, sic_code, sic_description
            ) VALUES (%s, %s, %s, %s, %s)""",
            (
                sub["id"], sub["named_insured"], sub["lob"],
                sub.get("sic_code"), sub.get("sic_description"),
            ),
        )


async def _delete_submission(cur, submission_id: str) -> None:
    """Delete a submission row. Cascade FKs on submission_stage,
    document, submission_extraction, submission_extraction_audit,
    submission_assessment, submission_event, and loss_history all
    take their child rows down with it — so a single DELETE here
    leaves the database in a clean slate for that submission."""
    await cur.execute(
        "DELETE FROM submission WHERE id = %s", (submission_id,),
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
    """Seed submission_stage rows for a freshly-created submission.

    Every seeded submission lands in the same starting state:
      - intake.complete (the submission record exists)
      - all other stages stay at their default 'pending'

    The user advances each submission forward through the workflow
    via the UI. Re-uses transition_stage so the seed-time intake
    completion lands in submission_event with the same shape as a
    runtime-driven transition would."""
    sid = sub["id"]
    await ensure_stages(cur, sid)
    await transition_stage(
        cur, sid, "intake", "complete",
        changed_by="seed_script",
        reason="seed: intake auto-complete (row exists)",
    )


# DROP order respects FK dependencies — children before parents.
# Submission_event, submission_extraction_audit, submission_extraction,
# submission_assessment, document, loss_history, submission_stage all
# reference submission. app_settings stands alone.
_DROP_TABLES_SQL = """
DROP TABLE IF EXISTS submission_event           CASCADE;
DROP TABLE IF EXISTS submission_extraction_audit CASCADE;
DROP TABLE IF EXISTS submission_extraction      CASCADE;
DROP TABLE IF EXISTS submission_assessment      CASCADE;
DROP TABLE IF EXISTS document                   CASCADE;
DROP TABLE IF EXISTS loss_history               CASCADE;
DROP TABLE IF EXISTS submission_stage           CASCADE;
DROP TABLE IF EXISTS submission                 CASCADE;
DROP TABLE IF EXISTS app_settings               CASCADE;
DROP TYPE  IF EXISTS stage_status_enum;
DROP TYPE  IF EXISTS submission_stage_enum;
"""


async def seed_uw_db(*, drop_existing: bool = False):
    """Apply schema and insert all demo data.

    Args:
        drop_existing: if True, drop all uw_db tables/types before
            re-applying the schema. Used by register_all to make every
            seed run reproducible — submissions, stages, and audit
            events all start from an empty slate. EDMS uploads are
            owned by seed_edms.py; uw_db `document` rows are created
            by the user's "Discover Documents" click in the UI.
    """
    # ── Apply schema (idempotent — uses IF NOT EXISTS) ────────
    schema_sql = SCHEMA_FILE.read_text()

    async with await psycopg.AsyncConnection.connect(UW_DB_URL) as conn:
        if drop_existing:
            async with conn.cursor() as cur:
                await cur.execute(_DROP_TABLES_SQL)
            await conn.commit()
            print("  + uw_db tables dropped")
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

                print(f"  + {sub['named_insured']} ({sub['lob']}, intake)")

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


# ── SURGICAL RESEED HELPERS ──────────────────────────────────
#
# Used when the user wants to refresh workflow rows without
# wiping the showcase rows (or the extractions / HITL edits
# they've already made on those showcase rows). Both helpers
# operate row-by-row using DELETE … WHERE id = %s and re-insert,
# so the schema stays put and unrelated submissions are
# untouched.


async def reseed_workflow_submissions(
    *, preserve_ids: frozenset[str] | None = None,
) -> None:
    """Delete and re-seed every non-showcase submission.

    For each submission in SUBMISSIONS whose id is NOT in
    `preserve_ids`:
      1. DELETE FROM submission … (cascade kills child rows).
      2. Re-insert via _seed_submission_row (which will pick
         the minimal shape because the id is not in SHOWCASE_IDS).
      3. Re-seed loss_history and submission_stage.

    Submissions in `preserve_ids` are left exactly as they are —
    their submission row, extractions, audit rows, HITL edits
    and stage transitions are all untouched.

    Args:
        preserve_ids: UUIDs to leave alone. Defaults to
            SHOWCASE_IDS, which is the typical case (workflow
            rows refresh, showcase rows preserved).
    """
    keep = preserve_ids if preserve_ids is not None else SHOWCASE_IDS

    async with await psycopg.AsyncConnection.connect(UW_DB_URL) as conn:
        async with conn.cursor() as cur:
            preserved = 0
            reseeded = 0
            for sub in SUBMISSIONS:
                if sub["id"] in keep:
                    print(
                        f"  = preserving {sub['id'][:8]}… "
                        f"({sub['named_insured']})"
                    )
                    preserved += 1
                    continue

                await _delete_submission(cur, sub["id"])
                await _seed_submission_row(cur, sub)
                await _seed_loss_history(cur, sub)
                await _seed_submission_stages(cur, sub)
                print(
                    f"  + reseeded {sub['id'][:8]}… "
                    f"({sub['named_insured']}, minimal)"
                )
                reseeded += 1
        await conn.commit()
        print(
            f"  + workflow reseed complete — "
            f"{reseeded} reseeded, {preserved} preserved"
        )


async def reset_submission(submission_id: str) -> None:
    """Reset a single submission to its seed state.

    The submission and all child rows are deleted, then
    re-inserted via the same path as the bulk seeder. The shape
    (full vs minimal) is decided by SHOWCASE_IDS, so resetting a
    showcase row reseeds it with full data and resetting a
    workflow row reseeds it minimally.

    Raises ValueError if `submission_id` is not present in the
    SUBMISSIONS list — without a seed entry there's nothing to
    re-insert.
    """
    target = next(
        (s for s in SUBMISSIONS if s["id"] == submission_id), None,
    )
    if target is None:
        raise ValueError(
            f"No seed entry for submission {submission_id} "
            f"— check SUBMISSIONS in seed_uw.py"
        )

    async with await psycopg.AsyncConnection.connect(UW_DB_URL) as conn:
        async with conn.cursor() as cur:
            await _delete_submission(cur, submission_id)
            await _seed_submission_row(cur, target)
            await _seed_loss_history(cur, target)
            await _seed_submission_stages(cur, target)
        await conn.commit()
        kind = "full" if submission_id in SHOWCASE_IDS else "minimal"
        print(
            f"  + reset {submission_id[:8]}… "
            f"({target['named_insured']}, {kind})"
        )


# ── STANDALONE ENTRY POINT ───────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Seed / reseed uw_db demo data.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--reseed-workflow",
        action="store_true",
        help=(
            "Delete and re-seed every non-showcase submission "
            "(showcase rows listed uncommented in "
            "showcase_submissions.txt are preserved as-is, "
            "including any extractions or HITL edits already "
            "made against them)."
        ),
    )
    group.add_argument(
        "--reset",
        metavar="UUID",
        help=(
            "Delete and re-seed a single submission by id. "
            "Showcase ids reset to full data; others to minimal."
        ),
    )
    args = parser.parse_args()

    if args.reseed_workflow:
        asyncio.run(reseed_workflow_submissions())
    elif args.reset:
        asyncio.run(reset_submission(args.reset))
    else:
        asyncio.run(seed_uw_db())
