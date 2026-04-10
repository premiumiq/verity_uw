"""Seed EDMS with demo documents for the 4 submissions.

Uploads documents to EDMS via its standard REST API (multipart upload),
then triggers text extraction for each. Uses httpx directly — no edms
package dependency.

The documents come from uw_demo/seed_docs/filled/ which contains
generated PDF applications, loss runs, financial statements, and
board resolutions for 20 fictional companies.

Document-to-submission mapping:
  SUB-001 (Acme D&O):     do_app, loss_run, board_resolution
  SUB-002 (TechFlow D&O): do_app, loss_run, financial_stmt
  SUB-003 (Meridian GL):  gl_app, loss_run, financial_stmt
  SUB-004 (Acme GL):      gl_app (Atlas Building), loss_run (Acme)

Usage:
    # Called from register_all.py at the end of seeding
    await seed_edms()

    # Or standalone:
    python -m uw_demo.app.setup.seed_edms
"""

import asyncio
import os
from pathlib import Path

import httpx


# ── CONFIGURATION ────────────────────────────────────────────

EDMS_URL = os.environ.get("EDMS_URL", "http://localhost:8002")

# Path to seed documents — inside Docker container, this is
# /app/uw_demo/seed_docs/filled/ (via volume mount ./uw_demo:/app/uw_demo)
# Outside Docker, it's relative to the project root.
SEED_DOC_DIR = Path(os.environ.get(
    "SEED_DOC_DIR",
    "/app/uw_demo/seed_docs/filled"
    if os.path.exists("/app/uw_demo/seed_docs/filled")
    else str(Path(__file__).parents[3] / "seed_docs" / "filled"),
))

# Timeout for uploads + text extraction (PDFs can be ~500KB)
TIMEOUT = 60.0


# ── SUBMISSION → DOCUMENT MAPPING ────────────────────────────
# Maps each submission UUID to a list of filenames in seed_docs/filled/

SUBMISSION_DOCS = {
    "00000001-0001-0001-0001-000000000001": [
        "do_app_acme_dynamics.pdf",
        "loss_run_acme_dynamics.txt",
        "board_resolution_acme_dynamics.txt",
    ],
    "00000002-0002-0002-0002-000000000002": [
        "do_app_techflow_industries.pdf",
        "loss_run_techflow_industries.txt",
        "financial_stmt_techflow_industries.txt",
    ],
    "00000003-0003-0003-0003-000000000003": [
        "gl_app_meridian_holdings.pdf",
        "loss_run_meridian_holdings.txt",
        "financial_stmt_meridian_holdings.txt",
    ],
    "00000004-0004-0004-0004-000000000004": [
        "gl_app_atlas_building.pdf",
        "loss_run_acme_dynamics.txt",
    ],
}

# Content type mapping
_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".json": "application/json",
}


async def seed_edms():
    """Upload demo documents to EDMS and trigger text extraction.

    Steps:
    1. Find the 'general' collection in EDMS (created by EDMS seed script)
    2. For each submission, check if documents already exist (idempotent)
    3. Upload each document via standard multipart POST
    4. Trigger text extraction for each uploaded document
    """
    print(f"  EDMS URL: {EDMS_URL}")
    print(f"  Seed docs: {SEED_DOC_DIR}")

    async with httpx.AsyncClient(base_url=EDMS_URL, timeout=TIMEOUT) as http:

        # ── Step 1: Find the "general" collection ────────────
        resp = await http.get("/collections")
        resp.raise_for_status()
        collections = resp.json().get("collections", [])

        general = next((c for c in collections if c["name"] == "general"), None)
        if not general:
            print("  ERROR: 'general' collection not found in EDMS.")
            print("  Make sure the EDMS service has started and seeded its data.")
            return
        collection_id = str(general["id"])
        print(f"  Collection 'general': {collection_id}")

        # ── Step 2-4: Upload documents per submission ────────
        total_uploaded = 0
        total_extracted = 0

        for sub_id, doc_files in SUBMISSION_DOCS.items():
            context_ref = f"submission:{sub_id}"

            # Idempotency check — skip if documents already exist
            resp = await http.get("/documents", params={"context_ref": context_ref})
            resp.raise_for_status()
            existing = resp.json().get("documents", [])
            if existing:
                print(f"  = {context_ref}: {len(existing)} docs already exist, skipping")
                continue

            for filename in doc_files:
                file_path = SEED_DOC_DIR / filename
                if not file_path.exists():
                    print(f"  ! File not found: {file_path}")
                    continue

                # Determine content type
                suffix = file_path.suffix.lower()
                content_type = _CONTENT_TYPES.get(suffix, "application/octet-stream")

                # Upload via multipart POST
                # Tags must include 'sensitivity' (required by EDMS governance)
                import json as _json
                tags = _json.dumps({"sensitivity": ["internal"]})

                with open(file_path, "rb") as f:
                    resp = await http.post(
                        "/documents/upload",
                        data={
                            "collection_id": collection_id,
                            "context_ref": context_ref,
                            "context_type": "submission",
                            "uploaded_by": "seed_script",
                            "tags": tags,
                        },
                        files={"file": (filename, f, content_type)},
                    )
                    if resp.status_code != 200:
                        print(f"  ! Upload failed for {filename}: {resp.status_code} {resp.text}")
                        continue
                    doc = resp.json()
                    doc_id = doc["id"]
                    total_uploaded += 1
                    print(f"  + uploaded {filename} → {doc_id[:8]}...")

                # Trigger text extraction
                resp = await http.post(f"/documents/{doc_id}/extract")
                resp.raise_for_status()
                extract_result = resp.json()
                chars = extract_result.get("char_count", 0)
                total_extracted += 1
                print(f"    extracted {chars} chars")

        print(f"  EDMS seed complete: {total_uploaded} uploaded, {total_extracted} extracted")


# ── STANDALONE ENTRY POINT ───────────────────────────────────

if __name__ == "__main__":
    asyncio.run(seed_edms())
