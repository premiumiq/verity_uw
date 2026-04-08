"""EDMS Seed Script - bootstrap governance data and test collection.

Run after schema is applied (happens automatically on service startup).
Idempotent - checks for existing data before inserting.

Usage:
    python -m edms.seed

Or called from the EDMS service startup.
"""

import asyncio
import os

from edms.core.db import EdmsDatabase


EDMS_DB_URL = os.environ.get(
    "EDMS_DB_URL",
    "postgresql://verityuser:veritypass123@localhost:5432/edms_db",
)


async def seed_all(db=None):
    """Run all seed steps. Pass an existing db connection or create a new one."""
    own_connection = False
    if db is None:
        db = EdmsDatabase(EDMS_DB_URL)
        await db.connect()
        own_connection = True

    print("EDMS Seed: Starting...")

    # ── Tag Definitions ───────────────────────────────────────
    tag_defs = [
        ("sensitivity", "Sensitivity Level", "restricted", True, 1,
         "Data sensitivity classification. Inherited from collection, overrideable."),
        ("category", "Category", "restricted", False, 2,
         "Document category for organizational grouping."),
        ("lob", "Line of Business", "restricted", False, 3,
         "Insurance line of business this document relates to."),
        ("source", "Source", "freetext", False, 4,
         "Where this document came from (free text)."),
    ]
    for key, display, mode, required, sort, desc in tag_defs:
        existing = await db.get_tag_definition(key)
        if not existing:
            await db.insert_tag_definition(key, display, mode, desc, required, sort)
            print(f"  + Tag definition: {key} ({mode})")

    # ── Tag Allowed Values ────────────────────────────────────
    tag_values = {
        "sensitivity": [
            ("public", "Public", 1, "No restrictions on access or distribution"),
            ("internal", "Internal", 2, "For internal use only, not for external distribution"),
            ("confidential", "Confidential", 3, "Restricted access, business-sensitive information"),
            ("pii", "PII", 4, "Contains personally identifiable information"),
            ("phi", "PHI", 5, "Contains protected health information"),
        ],
        "category": [
            ("application", "Application", 1, "Insurance application forms"),
            ("loss_report", "Loss Report", 2, "Loss run and claims history reports"),
            ("financial", "Financial", 3, "Financial statements and reports"),
            ("governance", "Governance", 4, "Board resolutions, committee docs"),
            ("supplemental", "Supplemental", 5, "Supplemental questionnaires"),
            ("correspondence", "Correspondence", 6, "Letters, emails, memos"),
            ("regulatory", "Regulatory", 7, "Regulatory filings and responses"),
            ("other", "Other", 99, "Documents that don't fit other categories"),
        ],
        "lob": [
            ("do", "D&O", 1, "Directors & Officers Liability"),
            ("gl", "GL", 2, "General Liability"),
            ("wc", "WC", 3, "Workers Compensation"),
            ("auto", "Auto", 4, "Commercial Auto"),
            ("property", "Property", 5, "Commercial Property"),
            ("professional", "Professional", 6, "Professional Liability / E&O"),
            ("cyber", "Cyber", 7, "Cyber Liability"),
        ],
    }
    for tag_key, values in tag_values.items():
        existing_values = await db.list_tag_allowed_values(tag_key)
        existing_set = {v["value"] for v in existing_values}
        for val, display, sort, desc in values:
            if val not in existing_set:
                await db.insert_tag_allowed_value(tag_key, val, display, desc, sort)
        print(f"  + Tag values for '{tag_key}': {len(values)} values")

    # ── Document Type Definitions (two-level) ─────────────────
    # Top-level types
    top_types = [
        ("application", "Application", 1, "Insurance application forms"),
        ("report", "Report", 2, "Loss runs, financial statements, and other reports"),
        ("governance", "Governance", 3, "Board resolutions, committee documents"),
        ("supplemental", "Supplemental", 4, "Supplemental questionnaires and addenda"),
        ("correspondence", "Correspondence", 5, "Letters, emails, memos"),
    ]
    type_ids = {}
    for key, display, sort, desc in top_types:
        existing = await db.get_document_type_definition(key)
        if not existing:
            result = await db.insert_document_type_definition(key, display, desc, sort_order=sort)
            type_ids[key] = result["id"]
        else:
            type_ids[key] = existing["id"]
    print(f"  + {len(top_types)} top-level document types")

    # Subtypes
    subtypes = [
        ("do_application", "D&O Application", type_ids.get("application"), 1, "Directors & Officers liability application"),
        ("gl_application", "GL Application", type_ids.get("application"), 2, "General Liability commercial application"),
        ("loss_run", "Loss Run Report", type_ids.get("report"), 1, "Historical claims and loss run data"),
        ("financial_statement", "Financial Statement", type_ids.get("report"), 2, "Audited or reviewed financial statements"),
        ("board_resolution", "Board Resolution", type_ids.get("governance"), 1, "Corporate board resolution document"),
        ("supplemental_do", "D&O Supplemental", type_ids.get("supplemental"), 1, "D&O supplemental questionnaire"),
        ("supplemental_gl", "GL Supplemental", type_ids.get("supplemental"), 2, "GL supplemental questionnaire"),
    ]
    for key, display, parent_id, sort, desc in subtypes:
        existing = await db.get_document_type_definition(key)
        if not existing and parent_id:
            await db.insert_document_type_definition(key, display, desc, parent_id, sort)
    print(f"  + {len(subtypes)} document subtypes")

    # ── Context Type Definitions ──────────────────────────────
    context_types = [
        ("submission", "Insurance Submission", 1, "Underwriting submission package"),
        ("policy", "Insurance Policy", 2, "Active or historical policy"),
        ("claim", "Insurance Claim", 3, "Claims and loss events"),
        ("renewal", "Policy Renewal", 4, "Renewal processing"),
        ("audit", "Audit", 5, "Internal or external audit"),
        ("regulatory", "Regulatory Filing", 6, "Regulatory submission or response"),
        ("general", "General", 99, "General purpose context"),
    ]
    for key, display, sort, desc in context_types:
        existing_result = await db._conn.execute(
            "SELECT id FROM context_type_definition WHERE type_key = %(k)s", {"k": key}
        )
        if not await existing_result.fetchone():
            await db.insert_context_type_definition(key, display, desc, sort)
    print(f"  + {len(context_types)} context types")

    # ── Test Collection ───────────────────────────────────────
    existing_coll = await db.get_collection_by_name("general")
    if not existing_coll:
        coll = await db.insert_collection(
            name="general",
            display_name="General Documents",
            storage_container="submissions",
            owner_name="System",
            created_by="seed_script",
            description="Default collection for general-purpose documents. Lowest sensitivity tier.",
            default_tags={"sensitivity": ["internal"]},
            status="active",
        )
        coll_id = coll["id"]
        print(f"  + Collection: general (bucket: submissions)")

        # Create miscellaneous folder
        await db.insert_folder(
            collection_id=coll_id, name="Miscellaneous",
            description="Uncategorized documents", created_by="seed_script",
        )
        print(f"  + Folder: Miscellaneous (in general collection)")
    else:
        print(f"  = Collection 'general' already exists, skipping")

    if own_connection:
        await db.close()
    print("EDMS Seed: Complete.")


if __name__ == "__main__":
    asyncio.run(seed_all())
