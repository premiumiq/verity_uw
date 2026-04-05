"""Verity Standalone Server — AI Trust & Compliance Platform.

Runs the Verity governance web UI and API on port 8000.
This is Verity's own process — independent of any business application.

Usage:
    cd ~/verity_uw
    source .venv/bin/activate
    uvicorn verity.main:app --port 8000 --reload

The UW demo app (or any other business app) runs separately on its own port.
Both connect to the same verity_db through the Verity SDK.
"""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from verity.core.client import Verity
from verity.web.app import create_verity_web


# Load .env from current working directory
_env_file = Path.cwd() / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            if key.strip() not in os.environ:
                os.environ[key.strip()] = value.strip()


# Database URL — Verity's own database
VERITY_DB_URL = os.getenv(
    "VERITY_DB_URL",
    "postgresql://verityuser:veritypass123@localhost:5432/verity_db",
)

# Global Verity instance
verity = Verity(database_url=VERITY_DB_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: connect to database. Shutdown: close connections."""
    await verity.connect()
    yield
    await verity.close()


app = FastAPI(
    title="PremiumIQ Verity",
    description="AI Trust & Compliance Platform",
    version="0.1.0",
    lifespan=lifespan,
)


# Root redirects to the admin UI
@app.get("/")
async def root():
    return RedirectResponse(url="/admin/")


# Health check
@app.get("/health")
async def health():
    return {"status": "healthy", "app": "verity", "version": "0.1.0"}


# Mount the Verity admin web UI at /admin/
verity_web = create_verity_web(verity)
app.mount("/admin", verity_web)
