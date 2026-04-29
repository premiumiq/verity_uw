"""Integration test: ``apply_schema`` lands a complete schema on the template
DB. This is the lowest-risk integration test we can run — it doesn't exercise
business logic, just confirms the DDL parses, FKs resolve, and pgvector is
present.

If any future change to ``schema.sql`` / ``schema_compliance.sql`` /
``schema_compliance_views.sql`` introduces a typo, an unknown FK target, or
a missing extension, this test fails first.
"""

from __future__ import annotations


# A small representative slice. Not exhaustive — we don't want every table
# rename to require updating this list. Picks one heavy table per area so a
# missing schema bucket is obvious.
EXPECTED_TABLES_PER_SCHEMA = {
    "public": {
        "agent",
        "agent_version",
        "task",
        "task_version",
        "execution_run",
        "agent_decision_log",
        "validation_run",
        "approval_record",
    },
    "compliance": {
        "regulatory_framework",
        "canonical_requirement",
        "feature",
        "report_definition",
    },
    "analytics": {
        # Only physical tables here — views are checked separately below.
        "mart_field",
        "feed_view",
    },
}

EXPECTED_VIEWS_IN_ANALYTICS = {
    "v_entity_version",
    "v_application_entity",
    "v_lifecycle_event",
    "v_decision",
    "v_validation_result",
    "v_override",
}


async def test_pgvector_extension_installed(db):
    row = await db.fetch_one_raw(
        "SELECT extname FROM pg_extension WHERE extname = 'vector'"
    )
    assert row is not None, (
        "pgvector extension is missing from the template DB. apply_schema "
        "should install it; check the postgres image is pgvector/pgvector."
    )


async def test_expected_schemas_exist(db):
    rows = await db.fetch_all_raw(
        "SELECT nspname FROM pg_namespace "
        "WHERE nspname IN ('public', 'compliance', 'analytics') "
        "ORDER BY nspname"
    )
    found = {r["nspname"] for r in rows}
    assert found == {"public", "compliance", "analytics"}


async def test_expected_tables_per_schema(db):
    for schema, expected in EXPECTED_TABLES_PER_SCHEMA.items():
        rows = await db.fetch_all_raw(
            "SELECT tablename FROM pg_tables WHERE schemaname = %(schema)s",
            {"schema": schema},
        )
        found = {r["tablename"] for r in rows}
        missing = expected - found
        assert not missing, (
            f"Schema {schema!r} is missing expected tables: {sorted(missing)}. "
            f"Found: {sorted(found)}"
        )


async def test_analytics_views_exist(db):
    rows = await db.fetch_all_raw(
        "SELECT viewname FROM pg_views WHERE schemaname = 'analytics'"
    )
    found = {r["viewname"] for r in rows}
    missing = EXPECTED_VIEWS_IN_ANALYTICS - found
    assert not missing, (
        f"analytics schema is missing expected views: {sorted(missing)}"
    )


async def test_governance_applications_seeded(db):
    # apply_schema seeds three platform applications used by Verity's
    # internal governance flows. Their absence would silently break
    # validation, audit, and compliance flows.
    rows = await db.fetch_all_raw(
        "SELECT name FROM application WHERE name IN "
        "('ai_ops', 'model_validation', 'compliance_audit') ORDER BY name"
    )
    assert {r["name"] for r in rows} == {
        "ai_ops", "compliance_audit", "model_validation",
    }
