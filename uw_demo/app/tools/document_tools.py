"""Document Tools — document metadata from MinIO.

In production, this queries MinIO for actual uploaded documents.
For the demo, returns hardcoded document lists per submission.
"""


_DOCUMENTS = {
    "00000001-0001-0001-0001-000000000001": [
        {"filename": "acord_855_acme_do.pdf", "type": "acord_855", "uploaded": "2026-03-15", "size_kb": 245},
        {"filename": "loss_run_acme_2023_2025.pdf", "type": "loss_runs", "uploaded": "2026-03-15", "size_kb": 128},
        {"filename": "acme_board_resolution.pdf", "type": "board_resolution", "uploaded": "2026-03-16", "size_kb": 56},
    ],
    "00000002-0002-0002-0002-000000000002": [
        {"filename": "acord_855_techflow_do.pdf", "type": "acord_855", "uploaded": "2026-03-20", "size_kb": 310},
        {"filename": "loss_run_techflow.pdf", "type": "loss_runs", "uploaded": "2026-03-20", "size_kb": 95},
        {"filename": "techflow_financials_2025.pdf", "type": "financial_statements", "uploaded": "2026-03-21", "size_kb": 420},
    ],
    "00000003-0003-0003-0003-000000000003": [
        {"filename": "acord_125_meridian_gl.pdf", "type": "acord_125", "uploaded": "2026-03-25", "size_kb": 198},
        {"filename": "loss_run_meridian.pdf", "type": "loss_runs", "uploaded": "2026-03-25", "size_kb": 156},
    ],
    "00000004-0004-0004-0004-000000000004": [
        {"filename": "acord_125_acme_gl.pdf", "type": "acord_125", "uploaded": "2026-03-28", "size_kb": 210},
        {"filename": "loss_run_acme_gl.pdf", "type": "loss_runs", "uploaded": "2026-03-28", "size_kb": 88},
        {"filename": "acme_product_catalog.pdf", "type": "supplemental_gl", "uploaded": "2026-03-29", "size_kb": 340},
    ],
}


def get_documents_for_submission(submission_id: str) -> dict:
    """Returns list of documents uploaded for a submission.

    Called by document-processing tasks to know what documents
    are available for classification and extraction.
    """
    docs = _DOCUMENTS.get(submission_id, [])
    return {
        "submission_id": submission_id,
        "document_count": len(docs),
        "documents": docs,
    }
