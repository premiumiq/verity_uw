"""Seed EDMS with ALL demo documents.

Uploads ALL 54 generated documents to EDMS via its REST API:
- 4 submission packages → 'underwriting' collection, per-submission folders
- 16 additional company documents → 'ground_truth' collection, per-company folders

Every document gets uploaded and text-extracted. Returns a complete
filename→document_id mapping so ground truth records reference EDMS
documents, never local files.

Usage:
    # Called from register_all.py
    doc_id_map = await seed_edms()
"""

import asyncio
import json as _json
import os
from pathlib import Path

import httpx


# ── CONFIGURATION ────────────────────────────────────────────

EDMS_URL = os.environ.get("EDMS_URL", "http://localhost:8002")

SEED_DOC_DIR = Path(os.environ.get(
    "SEED_DOC_DIR",
    "/app/uw_demo/seed_docs/filled"
    if os.path.exists("/app/uw_demo/seed_docs/filled")
    else str(Path(__file__).parents[3] / "seed_docs" / "filled"),
))

TIMEOUT = 60.0

# ── 4 UW SUBMISSIONS (go to 'underwriting' collection) ──────

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

# All filenames that belong to submissions (so we know what's left for GT)
_SUBMISSION_FILES = set()
for files in SUBMISSION_DOCS.values():
    _SUBMISSION_FILES.update(files)

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".json": "application/json",
}


async def seed_edms() -> dict[str, str]:
    """Upload ALL demo documents to EDMS and trigger text extraction.

    Returns:
        Dict of filename → EDMS document UUID string.
        Every file in seed_docs/filled/ will have an entry.
    """
    print(f"  EDMS URL: {EDMS_URL}")
    print(f"  Seed docs: {SEED_DOC_DIR}")

    doc_id_map: dict[str, str] = {}

    if not SEED_DOC_DIR.exists():
        print(f"  ! Seed docs directory not found: {SEED_DOC_DIR}")
        return doc_id_map

    async with httpx.AsyncClient(base_url=EDMS_URL, timeout=TIMEOUT) as http:

        # ── Find collections ────────────────────────────────
        resp = await http.get("/collections")
        resp.raise_for_status()
        collections = {c["name"]: c for c in resp.json().get("collections", [])}

        uw_coll = collections.get("underwriting")
        gt_coll = collections.get("ground_truth")

        if not uw_coll:
            print("  ERROR: 'underwriting' collection not found in EDMS.")
            return doc_id_map
        if not gt_coll:
            print("  ERROR: 'ground_truth' collection not found in EDMS.")
            return doc_id_map

        uw_coll_id = str(uw_coll["id"])
        gt_coll_id = str(gt_coll["id"])

        # ── Find submission folders in underwriting collection ──
        resp = await http.get(f"/collections/{uw_coll_id}/folders")
        resp.raise_for_status()
        uw_folder_tree = resp.json().get("tree", [])
        # Flatten: find folders named as submission UUIDs
        uw_folder_map = _flatten_folder_tree(uw_folder_tree)

        # ── Find/create company folders in ground_truth collection ──
        resp = await http.get(f"/collections/{gt_coll_id}/folders")
        resp.raise_for_status()
        gt_folder_tree = resp.json().get("tree", [])
        gt_folder_map = _flatten_folder_tree(gt_folder_tree)

        total_uploaded = 0
        total_extracted = 0

        # ── 1. Upload submission documents to 'underwriting' ────
        for sub_id, doc_files in SUBMISSION_DOCS.items():
            context_ref = f"submission:{sub_id}"
            folder_id = uw_folder_map.get(sub_id)

            # Idempotency: check if already uploaded
            resp = await http.get("/documents", params={"context_ref": context_ref})
            resp.raise_for_status()
            existing = resp.json().get("documents", [])
            if existing:
                for doc in existing:
                    doc_id_map[doc["filename"]] = str(doc["id"])
                print(f"  = {sub_id[:8]}...: {len(existing)} docs already exist")
                continue

            for filename in doc_files:
                doc_id = await _upload_and_extract(
                    http, SEED_DOC_DIR / filename, uw_coll_id,
                    context_ref, "submission", folder_id,
                )
                if doc_id:
                    doc_id_map[filename] = doc_id
                    total_uploaded += 1
                    total_extracted += 1

        # ── 2. Upload ALL remaining documents to 'ground_truth' ──
        for filepath in sorted(SEED_DOC_DIR.iterdir()):
            if filepath.name in doc_id_map:
                continue  # Already uploaded as submission doc
            if filepath.is_dir():
                continue

            # Extract company name from filename
            company_id = _extract_company_id(filepath.name)
            context_ref = f"ground_truth:{company_id}"

            # Find or create a folder for this company in ground_truth collection
            folder_id = gt_folder_map.get(company_id)
            if not folder_id:
                # Create the company folder
                resp = await http.post("/folders", data={
                    "collection_id": gt_coll_id,
                    "name": company_id,
                    "description": f"Ground truth documents for {company_id}",
                    "created_by": "seed_script",
                })
                if resp.status_code == 200:
                    folder_id = str(resp.json()["id"])
                    gt_folder_map[company_id] = folder_id

            # Idempotency: check existing
            resp = await http.get("/documents", params={"context_ref": context_ref})
            resp.raise_for_status()
            existing = resp.json().get("documents", [])
            existing_names = {d["filename"] for d in existing}
            if filepath.name in existing_names:
                for doc in existing:
                    if doc["filename"] == filepath.name:
                        doc_id_map[filepath.name] = str(doc["id"])
                continue

            doc_id = await _upload_and_extract(
                http, filepath, gt_coll_id,
                context_ref, "ground_truth", folder_id,
            )
            if doc_id:
                doc_id_map[filepath.name] = doc_id
                total_uploaded += 1
                total_extracted += 1

        print(f"  EDMS seed complete: {total_uploaded} uploaded, {total_extracted} extracted, {len(doc_id_map)} in mapping")

    return doc_id_map


async def _upload_and_extract(
    http: httpx.AsyncClient,
    filepath: Path,
    collection_id: str,
    context_ref: str,
    context_type: str,
    folder_id: str | None,
) -> str | None:
    """Upload one file to EDMS and trigger text extraction. Returns document ID or None."""
    if not filepath.exists():
        print(f"  ! File not found: {filepath}")
        return None

    suffix = filepath.suffix.lower()
    content_type = _CONTENT_TYPES.get(suffix, "application/octet-stream")
    tags = _json.dumps({"sensitivity": ["confidential"]})

    form_data = {
        "collection_id": collection_id,
        "context_ref": context_ref,
        "context_type": context_type,
        "uploaded_by": "seed_script",
        "tags": tags,
    }
    if folder_id:
        form_data["folder_id"] = folder_id

    with open(filepath, "rb") as f:
        resp = await http.post(
            "/documents/upload",
            data=form_data,
            files={"file": (filepath.name, f, content_type)},
        )
        if resp.status_code != 200:
            print(f"  ! Upload failed for {filepath.name}: {resp.status_code} {resp.text[:200]}")
            return None
        doc = resp.json()
        doc_id = str(doc["id"])
        print(f"  + {filepath.name} → {doc_id[:8]}...")

    # Trigger text extraction
    resp = await http.post(f"/documents/{doc_id}/extract")
    if resp.status_code == 200:
        chars = resp.json().get("char_count", 0)
        print(f"    extracted {chars} chars")
    else:
        print(f"    ! extraction failed: {resp.status_code}")

    return doc_id


def _flatten_folder_tree(tree: list) -> dict[str, str]:
    """Flatten a folder tree into {name: folder_id} mapping."""
    result = {}
    for node in tree:
        result[node["name"]] = str(node["id"])
        if node.get("children"):
            result.update(_flatten_folder_tree(node["children"]))
    return result


def _extract_company_id(filename: str) -> str:
    """Extract company ID from a generated document filename.
    'do_app_acme_dynamics.pdf' → 'acme_dynamics'
    'loss_run_techflow_industries.txt' → 'techflow_industries'
    """
    # Remove extension
    stem = filename.rsplit(".", 1)[0]
    # Remove known prefixes
    for prefix in ("do_app_", "gl_app_", "loss_run_", "financial_stmt_",
                    "board_resolution_", "supplemental_gl_"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


if __name__ == "__main__":
    result = asyncio.run(seed_edms())
    print(f"Document ID mapping: {len(result)} entries")
