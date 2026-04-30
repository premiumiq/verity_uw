"""Regression test for the schema renames in PR 1 + PR 3.

PR 1 dropped the ``verity_`` prefix from the compliance and analytics
schemas. PR 3 split the catch-all ``public`` schema into ``governance``
(definitions, lifecycle, validation, admin) and ``runtime`` (execution
runs, decision logs).

If any of those legacy names reappear — via a reverted query, copy-paste
from old docs, or a restored backup — these tests fail fast.
"""

from __future__ import annotations


# Verity owns these four schemas after PR 3.
EXPECTED_VERITY_OWNED_SCHEMAS = {"governance", "runtime", "compliance", "analytics"}

# Schemas that must NOT exist (PR 1 + PR 3 cleanup).
LEGACY_SCHEMAS_THAT_MUST_NOT_EXIST = {"verity_compliance", "verity_analytics"}

# Tables that must NOT live in `public` after PR 3 — every governance/
# runtime table moved out. ``public`` itself still exists (Postgres
# default), but Verity-owned objects don't live there.
SAMPLE_TABLES_THAT_MUST_NOT_BE_IN_PUBLIC = {
    "agent", "agent_version", "task", "execution_run",
    "agent_decision_log", "approval_record",
}


async def test_legacy_schemas_are_gone(db):
    rows = await db.fetch_all_raw(
        "SELECT nspname FROM pg_namespace "
        "WHERE nspname IN ('verity_compliance', 'verity_analytics')"
    )
    found = {r["nspname"] for r in rows}
    assert not found, (
        f"Legacy schema names still present: {sorted(found)}. "
        f"PR 1 dropped the verity_ prefix; if these reappear someone "
        f"reverted that change."
    )


async def test_verity_owned_schemas_present(db):
    rows = await db.fetch_all_raw(
        "SELECT nspname FROM pg_namespace WHERE nspname IN "
        "('governance', 'runtime', 'compliance', 'analytics') "
        "ORDER BY nspname"
    )
    found = {r["nspname"] for r in rows}
    assert found == EXPECTED_VERITY_OWNED_SCHEMAS


async def test_no_verity_tables_in_public(db):
    # public still exists (Postgres default schema) but should hold no
    # Verity-owned tables. PR 3 moved everything out.
    rows = await db.fetch_all_raw(
        "SELECT tablename FROM pg_tables "
        "WHERE schemaname = 'public' "
        f"AND tablename = ANY(%(names)s)",
        {"names": sorted(SAMPLE_TABLES_THAT_MUST_NOT_BE_IN_PUBLIC)},
    )
    found = {r["tablename"] for r in rows}
    assert not found, (
        f"Tables still in `public` that should be in governance/runtime: "
        f"{sorted(found)}. PR 3 moved everything out — if these reappear "
        f"the schema was applied against an outdated DDL."
    )
