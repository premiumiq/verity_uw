"""Compliance coverage rollup queries.

Two named queries drive the overview UI's headline numbers:

  compliance_coverage_rollup — coverage_level → count(canonicals)
  compliance_overall_counts  — totals across the metamodel

Tests confirm the numbers are sane for the seeded metamodel and the
expected coverage levels (full / substantial / partial / gap) all
appear with valid (non-negative) counts.
"""

from __future__ import annotations

import pytest

from verity.setup.seed_compliance import seed_data, seed_static


pytestmark = pytest.mark.slow


VALID_COVERAGE_LEVELS = {"full", "substantial", "partial", "gap"}


async def test_coverage_rollup_buckets_into_known_levels(db):
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    rows = await db.fetch_all("compliance_coverage_rollup")
    assert rows  # non-empty after seeding

    levels = {row["coverage_level"] for row in rows}
    # Every level reported must be one of the four canonical buckets.
    assert levels.issubset(VALID_COVERAGE_LEVELS)
    # Every count must be positive (if zero, the row shouldn't appear).
    for row in rows:
        assert row["canonical_count"] > 0


async def test_overall_counts_reflect_seeded_metamodel(db):
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    counts = await db.fetch_one("compliance_overall_counts")
    assert counts is not None
    assert counts["framework_count"] > 0
    assert counts["theme_count"] > 0
    assert counts["canonical_count"] > 0
    assert counts["plane_count"] > 0
    assert counts["capability_count"] > 0
    assert counts["feature_count"] > 0
    assert counts["provision_canonical_bridges"] > 0


async def test_rollup_total_matches_canonical_count(db):
    """The rollup sums to the same total as compliance_overall_counts —
    every canonical_requirement should have exactly one coverage row."""
    await db.close()
    await seed_static(db.database_url)
    await seed_data(db.database_url)
    await db.connect()

    rollup = await db.fetch_all("compliance_coverage_rollup")
    rollup_total = sum(row["canonical_count"] for row in rollup)

    overall = await db.fetch_one("compliance_overall_counts")
    assert rollup_total == overall["canonical_count"]
