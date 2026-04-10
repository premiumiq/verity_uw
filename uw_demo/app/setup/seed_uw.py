"""Seed uw_db with demo submission and loss history data.

Creates the schema (idempotent) and inserts 4 demo submissions with
their loss history records. These are the same submissions that were
previously hardcoded in Python dicts.

Usage:
    # Called from register_all.py
    await seed_uw_db()

    # Or standalone:
    python -m uw_demo.app.setup.seed_uw
"""

import asyncio
import os
from pathlib import Path

import psycopg


# ── DATABASE URL ─────────────────────────────────────────────

UW_DB_URL = os.environ.get(
    "UW_DB_URL",
    "postgresql://verityuser:veritypass123@localhost:5432/uw_db",
)

# Path to schema file
SCHEMA_FILE = Path(__file__).parent.parent / "db" / "schema.sql"


# ── DEMO SUBMISSIONS ────────────────────────────────────────
# Same data as the old hardcoded _SUBMISSIONS dict, but now going
# into a real database.

SUBMISSIONS = [
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
        "loss_history": [
            {"year": 2023, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
        ],
    },
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
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 75000, "paid": 50000, "reserves": 25000},
            {"year": 2024, "claims": 0, "incurred": 0, "paid": 0, "reserves": 0},
            {"year": 2025, "claims": 1, "incurred": 150000, "paid": 0, "reserves": 150000},
        ],
    },
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
        "loss_history": [
            {"year": 2023, "claims": 5, "incurred": 320000, "paid": 280000, "reserves": 40000},
            {"year": 2024, "claims": 4, "incurred": 185000, "paid": 150000, "reserves": 35000},
            {"year": 2025, "claims": 3, "incurred": 95000, "paid": 60000, "reserves": 35000},
        ],
    },
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
        "loss_history": [
            {"year": 2023, "claims": 1, "incurred": 45000, "paid": 45000, "reserves": 0},
            {"year": 2024, "claims": 2, "incurred": 80000, "paid": 60000, "reserves": 20000},
            {"year": 2025, "claims": 2, "incurred": 65000, "paid": 40000, "reserves": 25000},
        ],
    },
]


async def seed_uw_db():
    """Apply schema and insert demo submissions + loss history."""

    # ── Apply schema (idempotent — uses IF NOT EXISTS) ────────
    schema_sql = SCHEMA_FILE.read_text()

    async with await psycopg.AsyncConnection.connect(UW_DB_URL) as conn:
        async with conn.cursor() as cur:
            await cur.execute(schema_sql)
        await conn.commit()
        print("  + uw_db schema applied")

        # ── Insert submissions ────────────────────────────────
        async with conn.cursor() as cur:
            for sub in SUBMISSIONS:
                # Idempotency — skip if already exists
                await cur.execute(
                    "SELECT 1 FROM submission WHERE id = %s",
                    (sub["id"],),
                )
                if await cur.fetchone():
                    print(f"  = submission {sub['id'][:8]}... already exists, skipping")
                    continue

                await cur.execute(
                    """INSERT INTO submission (
                        id, named_insured, lob, fein, entity_type,
                        state_of_incorporation, sic_code, sic_description,
                        annual_revenue, employee_count, board_size,
                        independent_directors, effective_date, expiration_date,
                        limits_requested, retention_requested,
                        prior_carrier, prior_premium, status
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s,
                        %s, %s,
                        %s, %s, %s
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
                        "intake",
                    ),
                )
                print(f"  + submission: {sub['named_insured']} ({sub['lob']})")

                # Insert loss history for this submission
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

                # Insert 5 workflow steps (intake=complete, rest=pending)
                workflow_steps = [
                    ("intake", 1, "complete"),
                    ("document_processing", 2, "pending"),
                    ("extraction_review", 3, "pending"),
                    ("triage", 4, "pending"),
                    ("appetite", 5, "pending"),
                ]
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                for step_name, step_order, status in workflow_steps:
                    await cur.execute(
                        """INSERT INTO workflow_step (
                            submission_id, step_name, step_order, status,
                            completed_at, completed_by
                        ) VALUES (%s, %s, %s, %s, %s, %s)""",
                        (
                            sub["id"], step_name, step_order, status,
                            now if status == "complete" else None,
                            "seed_script" if status == "complete" else None,
                        ),
                    )

        await conn.commit()
        print(f"  + {len(SUBMISSIONS)} submissions with loss history + workflow steps seeded")

        # ── Seed app settings ─────────────────────────────────
        async with conn.cursor() as cur:
            settings_data = [
                ("pipeline_mode", "mock", "mock = pre-built outputs (free, instant). live = real Claude API calls (~$0.15/submission)."),
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
