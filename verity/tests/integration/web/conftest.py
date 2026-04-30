"""Web UI test harness.

Mounts ``verity.web.app.create_verity_web`` over the per-test cloned DB
and exposes an httpx.AsyncClient. Tests verify HTML routes return 200
and contain expected content fragments — not pixel-perfect rendering,
just smoke-level coverage that the templates load without crashing.
"""

from __future__ import annotations

import httpx
import pytest_asyncio

from verity.client.inprocess import Verity
from verity.web.app import create_verity_web


@pytest_asyncio.fixture
async def web_client(db):
    """Yields an httpx.AsyncClient over the Verity admin web UI."""
    verity = Verity(database_url=db.database_url, application="tests")
    await verity.connect()

    app = create_verity_web(verity)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as client_:
        try:
            yield client_
        finally:
            await verity.close()
