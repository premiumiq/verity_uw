"""EDMS Service — FastAPI application for document management.

Runs as its own container on port 8002. Owns:
- edms_db (PostgreSQL) for document metadata and lineage
- MinIO for file storage

No other service connects to edms_db directly. All access is through
these REST APIs.

Usage (Docker):
    uvicorn edms.service.main:app --host 0.0.0.0 --port 8002

Endpoints:
    GET  /health
    GET  /documents?context_ref=submission:SUB-001
    GET  /documents/{id}
    GET  /documents/{id}/text
    GET  /documents/{id}/children
    POST /documents/upload
    POST /documents/{id}/extract
    PUT  /documents/{id}/type
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from edms.core.db import EdmsDatabase
from edms.core.storage import StorageClient
from edms.service.routes import create_routes
from edms.service.governance_routes import create_governance_routes
from edms.service.collection_routes import create_collection_routes
from edms.service.folder_routes import create_folder_routes
from edms.service.task_routes import create_task_routes
from edms.service.ui import create_ui_routes


# ── CONFIGURATION (from environment variables) ────────────────

EDMS_DB_URL = os.environ.get(
    "EDMS_DB_URL",
    "postgresql://verityuser:veritypass123@localhost:5432/edms_db",
)
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin123")
MINIO_SECURE = os.environ.get("MINIO_SECURE", "false").lower() == "true"
DEFAULT_BUCKET = os.environ.get("EDMS_DEFAULT_BUCKET", "submissions")


# ── SERVICE INSTANCES ─────────────────────────────────────────

db = EdmsDatabase(EDMS_DB_URL)
storage = StorageClient(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to database, ensure bucket. Shutdown: close."""
    await db.connect()
    storage.ensure_bucket(DEFAULT_BUCKET)
    # Apply schema on startup (idempotent)
    await db.apply_schema()
    # Seed governance data and test collection (idempotent)
    from edms.seed import seed_all
    await seed_all(db)
    print(f"EDMS service started. DB: edms_db, Bucket: {DEFAULT_BUCKET}")
    yield
    await db.close()


app = FastAPI(
    title="EDMS — Enterprise Document Management System",
    description="Document storage, text extraction, and metadata management",
    version="0.1.0",
    lifespan=lifespan,
)


# ── HEALTH CHECK ──────────────────────────────────────────────

@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy", "service": "edms", "version": "0.1.0"})


# ── MOUNT API ROUTES ──────────────────────────────────────────

# Document CRUD routes at /documents/
doc_router = create_routes(db, storage, DEFAULT_BUCKET)
app.include_router(doc_router)

# Tag and document type governance routes at /tags/, /document-types/
gov_router = create_governance_routes(db)
app.include_router(gov_router)

# Collection management routes at /collections/
coll_router = create_collection_routes(db)
app.include_router(coll_router)

# Folder management routes at /folders/
folder_router = create_folder_routes(db)
app.include_router(folder_router)

# Task monitoring routes at /tasks/
task_router = create_task_routes(db)
app.include_router(task_router)

# Web UI at /ui/
ui_router = create_ui_routes(db, storage, DEFAULT_BUCKET)
app.include_router(ui_router)
