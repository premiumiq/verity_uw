"""seed_data — provisions, canonical requirements, bridges, coverage.

Phase 1.3 layer of the metamodel. Depends on seed_static having run.
Tests verify the bridges (provision_requirement_map +
requirement_feature_link) actually link between the two side axes.
"""

from __future__ import annotations

import pytest

from verity.setup.seed_compliance import seed_data, seed_static


pytestmark = pytest.mark.slow


async def test_seed_data_loads_provisions_and_canonicals(db):
    await db.close()
    await seed_static(db.database_url)
    counts = await seed_data(db.database_url)
    await db.connect()

    assert counts["provisions"] > 0
    assert counts["canonical_requirements"] > 0
    assert counts["provision_requirement_maps"] > 0
    # Coverage rows: one per canonical requirement.
    assert counts["requirement_coverage"] > 0


async def test_seed_data_is_idempotent(db):
    """Same idempotency check as seed_static — table sizes match across
    runs, no duplicate canonical codes."""
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()
    canon_after_first = (await db.fetch_one_raw(
        "SELECT count(*) AS n FROM compliance.canonical_requirement"
    ))["n"]

    await db.close()
    await seed_data(db.database_url)
    await db.connect()
    canon_after_second = (await db.fetch_one_raw(
        "SELECT count(*) AS n FROM compliance.canonical_requirement"
    ))["n"]

    assert canon_after_second == canon_after_first

    dups = await db.fetch_all_raw(
        "SELECT code, count(*) AS n FROM compliance.canonical_requirement "
        "GROUP BY code HAVING count(*) > 1"
    )
    assert dups == []


async def test_seeded_bridges_only_reference_existing_rows(db):
    """The provision_requirement_map FKs to both provision and
    canonical_requirement; broken bridges would fail at insert time.
    This test confirms post-seed integrity by counting orphaned rows."""
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    orphans = await db.fetch_one_raw(
        """
        SELECT count(*) AS n
        FROM compliance.provision_requirement_map prm
        WHERE NOT EXISTS (
            SELECT 1 FROM compliance.regulatory_provision p WHERE p.id = prm.provision_id
        )
        OR NOT EXISTS (
            SELECT 1 FROM compliance.canonical_requirement c WHERE c.id = prm.canonical_requirement_id
        )
        """
    )
    assert orphans["n"] == 0
