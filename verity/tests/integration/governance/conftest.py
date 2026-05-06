"""Governance test fixtures.

Currently exposes ``db_target`` — a SECOND per-test cloned database
used by the YAML round-trip property test (slice 4B). Same shape as
the top-level ``db`` fixture, but a separate clone, so a single test
can export from one DB and import into another and assert equivalence.

Both clones come from the same template database, so they start from
identical seed data. The round-trip test asserts that "export from A
+ import into B + re-export from B" produces the same bytes as the
first export — proving that the YAML format is information-preserving
across a clean import.
"""

from __future__ import annotations

import uuid

import pytest_asyncio

from tests.conftest import _db_url, _execute_admin


@pytest_asyncio.fixture
async def db_target(request, template_database):
    """Per-test cloned DB, distinct from the ``db`` fixture's clone.

    The ``db`` fixture is the source of truth for a test's data; this
    fixture is the clean target for an import. Both come from the
    template, so seed data is identical at start.
    """
    from verity.db.connection import Database

    test_db_name = f"verity_test_target_{uuid.uuid4().hex[:12]}"
    await _execute_admin(
        f"CREATE DATABASE {test_db_name} TEMPLATE {template_database}"
    )
    await _execute_admin(
        f"ALTER DATABASE {test_db_name} "
        "SET search_path TO governance, runtime, compliance, analytics, public"
    )

    db = Database(database_url=_db_url(test_db_name))
    await db.connect()
    try:
        yield db
    finally:
        await db.close()
        if not request.config.getoption("--preserve-test-db"):
            await _execute_admin(f"DROP DATABASE IF EXISTS {test_db_name}")
