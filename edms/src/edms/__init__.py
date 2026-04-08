"""EDMS — Enterprise Document Management System.

Two components:
1. Service (edms.service.main:app) — FastAPI app running in its own container.
   Owns edms_db and MinIO. Exposes REST APIs for document operations.

2. Client (edms.EdmsClient) — HTTP client for consuming applications.
   Makes requests to the EDMS service. No direct DB/storage access.

Consuming apps import the client:
    from edms import EdmsClient
    client = EdmsClient(base_url="http://edms:8002")
    docs = await client.list_documents("submission:SUB-001")
    text = await client.get_document_text(document_id)
"""

from edms.client import EdmsClient

__all__ = ["EdmsClient"]
