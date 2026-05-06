"""Studio test harness.

Wraps ``verity.web.studio_app.create_verity_studio`` inside a parent
FastAPI app and mounts it at ``/studio/`` — the same shape
``verity/main.py`` uses in production. Keeping the mount path
identical means in-app redirects (which use absolute ``/studio/...``
URLs) round-trip correctly in tests.

Tests therefore drive the API with ``/studio/...`` paths, matching
what a real browser would send.
"""

from __future__ import annotations

import httpx
import pytest_asyncio
from fastapi import FastAPI

from verity.client.inprocess import Verity
from verity.web.studio_app import create_verity_studio


@pytest_asyncio.fixture
async def studio_client(db):
    """Yields an httpx.AsyncClient over the Verity Studio sub-app
    mounted at ``/studio/`` (the production mount path)."""
    verity = Verity(database_url=db.database_url, application="tests")
    await verity.connect()

    app = FastAPI()
    app.mount("/studio", create_verity_studio(verity))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as client_:
        try:
            yield client_
        finally:
            await verity.close()
