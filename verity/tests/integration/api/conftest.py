"""API test harness.

The ``client`` fixture spins up a FastAPI app whose API router is wired
to a Verity SDK instance pointing at the per-test cloned DB. Tests use
``httpx.AsyncClient`` over an ASGI transport — in-process, no real
network.

Why a separate Verity instance per test? The ``Verity`` SDK class owns
its own ``Database`` connection pool, governance/runtime objects, and
the application_id resolution cache. Each per-test DB is a fresh clone
of the template, so each test gets a fresh Verity facade. Setup cost is
dominated by the existing template-clone (~50ms); the Verity init is
cheap on top.
"""

from __future__ import annotations

import httpx
import pytest_asyncio
from fastapi import FastAPI

from verity.client.inprocess import Verity
from verity.web.api.router import build_api_router


@pytest_asyncio.fixture
async def client(db):
    """Yields an httpx.AsyncClient over the Verity API mounted on a
    FastAPI app.

    The fixture builds a Verity SDK instance against the per-test cloned
    DB URL (already taken from the ``db`` fixture), connects it, mounts
    the /api/v1 router, and exposes an httpx client. After the test, the
    Verity instance is closed cleanly.

    Tests issue requests with the API prefix:
        await client.get("/api/v1/agents")
        await client.post("/api/v1/lifecycle/promote", json={...})
    """
    verity = Verity(database_url=db.database_url, application="tests")
    await verity.connect()

    app = FastAPI()
    app.include_router(build_api_router(verity))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver",
    ) as client_:
        try:
            yield client_
        finally:
            await verity.close()
