"""seed_static — frameworks, themes, planes, capabilities, features.

This is the L3 metamodel's static layer. Tests verify:
  - Loading the seed produces the expected counts
  - Re-running is idempotent (UPSERT by natural code)
  - Required tables are non-empty after seeding

The yaml itself ships with the package — these tests confirm the
seeder reads it and writes the rows correctly. Slow-ish (~2s) because
the yaml is real production data.
"""

from __future__ import annotations

import pytest

from verity.setup.seed_compliance import seed_static


pytestmark = pytest.mark.slow


async def test_seed_static_loads_data(db):
    """First seed: confirm row counts non-zero in every static table."""
    await db.close()
    counts = await seed_static(db.database_url)
    await db.connect()

    # The seeder returns counts per table — none should be zero on
    # first run. (Second run shows 0 for upserts that hit existing rows.)
    assert counts["frameworks"] > 0
    assert counts["themes"] > 0
    assert counts["feature_planes"] > 0
    assert counts["feature_capabilities"] > 0
    assert counts["features"] > 0

    # Confirm rows actually landed in the DB.
    fw_rows = await db.fetch_all_raw("SELECT code FROM compliance.regulatory_framework")
    assert len(fw_rows) == counts["frameworks"]


async def test_seed_static_is_idempotent(db):
    """Running seed_static twice must not create duplicates. The
    returned counts may differ run-to-run (the seeder reports inserts
    only — re-runs that hit existing rows show 0 for those buckets),
    but the actual TABLE sizes stay stable."""
    await db.close()
    await seed_static(db.database_url)
    await db.connect()
    fw_after_first = (await db.fetch_one_raw(
        "SELECT count(*) AS n FROM compliance.regulatory_framework"
    ))["n"]

    await db.close()
    await seed_static(db.database_url)
    await db.connect()
    fw_after_second = (await db.fetch_one_raw(
        "SELECT count(*) AS n FROM compliance.regulatory_framework"
    ))["n"]

    assert fw_after_second == fw_after_first
    # No duplicate codes either — the UNIQUE constraint would have
    # caught it, but verify the post-state for clarity.
    dups = await db.fetch_all_raw(
        "SELECT code, count(*) AS n FROM compliance.regulatory_framework "
        "GROUP BY code HAVING count(*) > 1"
    )
    assert dups == []


async def test_seeded_frameworks_have_unique_codes(db):
    await db.close()
    await seed_static(db.database_url)
    await db.connect()

    rows = await db.fetch_all_raw(
        "SELECT code, count(*) AS n FROM compliance.regulatory_framework "
        "GROUP BY code HAVING count(*) > 1"
    )
    assert rows == []
