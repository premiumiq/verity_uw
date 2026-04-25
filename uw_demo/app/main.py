"""UW Demo Application — Powered by PremiumIQ Verity.

A standalone business application that uses the Verity SDK for
AI governance. Runs on its own port (8001), separate from Verity (8000).

HOW IT WORKS:
1. Imports the Verity Python package (SDK — direct function calls, not HTTP)
2. Connects to verity_db on startup (same database Verity's own server uses)
3. Registers tool implementations (the Python functions Claude calls)
4. Serves the underwriting workflow UI at /

Verity's web UI runs separately at http://localhost:8000.
"View in Verity" links in this app point there.

Usage:
    cd ~/verity_uw
    source .venv/bin/activate
    uvicorn uw_demo.app.main:app --port 8001 --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from pathlib import Path

from fastapi.staticfiles import StaticFiles

# Configure structured logging before anything else
from uw_demo.app.utils.logging import CorrelationMiddleware, setup_logging
setup_logging(service_name="uw_demo")

from uw_demo.app.config import settings
from uw_demo.app.ui.routes import create_uw_routes
from verity import Verity


# ── VERITY SDK INSTANCE ───────────────────────────────────────
# This is a library import, not an HTTP client. The UW app calls
# verity.execution.run_task(), verity.execution.run_agent(),
# verity.get_audit_trail(), etc. as direct Python function calls.
# Multi-step workflows are orchestrated in uw_demo/app/workflows.py
# now that pipelines are descoped from Verity. Both this app and
# Verity's own server share the same verity_db database.
verity = Verity(
    database_url=settings.VERITY_DB_URL,
    anthropic_api_key=settings.ANTHROPIC_API_KEY,
    application="uw_demo",
)

# ── REGISTER TOOL IMPLEMENTATIONS ─────────────────────────────
# These are the Python functions that Claude calls when an agent
# uses a tool. Each function's signature matches the tool's
# registered input_schema in Verity.
from uw_demo.app.tools.submission_tools import (
    get_submission_context,
    get_loss_history,
    store_extraction_result,
    update_submission_event,
)
from uw_demo.app.tools.guidelines_tools import get_underwriting_guidelines
from uw_demo.app.tools.document_tools import get_documents_for_submission

# NOTE: get_enrichment_data was retired in Phase 4d-3 (FC-14). The
# combined LexisNexis/D&B/PitchBook Python callable is replaced by four
# MCP-sourced tools (lexisnexis_lookup, dnb_lookup, pitchbook_lookup,
# factset_lookup), dispatched through verity.runtime.mcp_client.MCPClient
# to the in-repo enrichment MCP server at mcp_servers/enrichment/. See
# docs/architecture/registry_runtime_split_plan.md for the migration.

verity.register_tool_implementation("get_submission_context", get_submission_context)
verity.register_tool_implementation("get_loss_history", get_loss_history)
verity.register_tool_implementation("get_underwriting_guidelines", get_underwriting_guidelines)
verity.register_tool_implementation("get_documents_for_submission", get_documents_for_submission)
verity.register_tool_implementation("store_extraction_result", store_extraction_result)
verity.register_tool_implementation("update_submission_event", update_submission_event)
# store_triage_result + update_appetite_status retired 2026-04-25.
# triage_agent + appetite_agent now use enforce_output_schema=True so
# their structured output_json IS the canonical conclusion. Persistence
# is driven by the route reading agent_decision_log.output_json after
# the run.

# ── EDMS DOCUMENT TOOLS ──────────────────────────────────────
# Calls the EDMS service over HTTP (no package dependency).
# In production, EDMS runs on a separate server.
from uw_demo.app.tools.edms_tools import list_documents, get_document_text
verity.register_tool_implementation("list_documents", list_documents)
verity.register_tool_implementation("get_document_text", get_document_text)

# ── EDMS DATA CONNECTOR (Task declarative sources) ───────────
# Register the EdmsProvider under the connector name "edms" so Tasks
# that declare `connector=edms` can resolve their sources at runtime.
# Verity stores the connector name and non-secret tuning config in its
# data_connector table (seeded via register_all.py); the in-process
# provider binding below is what the execution engine actually calls.
from verity.runtime.connectors import register_provider
from uw_demo.app.edms_provider import EdmsProvider
register_provider("edms", EdmsProvider(base_url=settings.EDMS_URL))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to Verity database. Shutdown: close connections."""
    await verity.connect()
    yield
    await verity.close()


app = FastAPI(
    title="UW Demo — Powered by PremiumIQ Verity",
    description="Commercial underwriting platform with AI governance",
    version="0.1.0",
    lifespan=lifespan,
)

# Correlation ID middleware — generates/propagates trace IDs across requests
app.add_middleware(CorrelationMiddleware)


# ── HEALTH CHECK ──────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy", "app": "uw_demo", "env": settings.APP_ENV})


# ── STATIC FILES ──────────────────────────────────────────────
# CSS and images for the UW app (same PremiumIQ branding as Verity)
_static_dir = Path(__file__).parent / "ui" / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="uw-static")

# ── UW BUSINESS ROUTES ───────────────────────────────────────
# Underwriting workflow pages at /*
uw_router = create_uw_routes(verity)
app.include_router(uw_router)
