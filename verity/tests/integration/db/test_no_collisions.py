"""Invariant guard: no table name may exist in more than one Verity schema.

The PR 3 convention says application queries (SELECT/INSERT/UPDATE) stay
unqualified and the database's ``search_path`` resolves them. That works
only as long as each table name is unique across the four Verity schemas.

If anyone ever introduces ``runtime.audit_log`` while ``governance.audit_log``
already exists, unqualified ``FROM audit_log`` would silently resolve to
whichever schema appears first in search_path — a footgun that causes
queries to read or write the wrong table without erroring. This test
catches the collision at the next CI run, forcing an explicit decision:
either rename one, or qualify every reference.
"""

from __future__ import annotations


VERITY_OWNED_SCHEMAS = ("governance", "runtime", "compliance", "analytics")


async def test_no_cross_schema_table_name_collisions(db):
    rows = await db.fetch_all_raw(
        """
        SELECT
            tablename,
            array_agg(schemaname ORDER BY schemaname) AS schemas
        FROM   pg_tables
        WHERE  schemaname = ANY(%(schemas)s)
        GROUP BY tablename
        HAVING count(*) > 1
        """,
        {"schemas": list(VERITY_OWNED_SCHEMAS)},
    )

    if rows:
        details = "\n".join(
            f"  {r['tablename']}: {r['schemas']}" for r in rows
        )
        raise AssertionError(
            "Table name(s) appear in multiple Verity schemas, breaking the "
            "search_path convention. Either rename one, or qualify every "
            "reference to those tables across the codebase:\n" + details
        )


async def test_no_cross_schema_view_name_collisions(db):
    # Views are looked up via search_path the same way tables are. Same
    # collision risk, same guard.
    rows = await db.fetch_all_raw(
        """
        SELECT
            viewname,
            array_agg(schemaname ORDER BY schemaname) AS schemas
        FROM   pg_views
        WHERE  schemaname = ANY(%(schemas)s)
        GROUP BY viewname
        HAVING count(*) > 1
        """,
        {"schemas": list(VERITY_OWNED_SCHEMAS)},
    )

    if rows:
        details = "\n".join(
            f"  {r['viewname']}: {r['schemas']}" for r in rows
        )
        raise AssertionError(
            "View name(s) appear in multiple Verity schemas:\n" + details
        )
