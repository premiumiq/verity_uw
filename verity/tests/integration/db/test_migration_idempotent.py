"""Migration idempotency.

apply_schema with drop_existing=False must be safe to re-run on a DB
that already has the schema applied. The "already exists" guard inside
the migration loop catches duplicate CREATE TABLE / TYPE / INDEX errors;
these tests verify the contract holds end-to-end.

Why this matters: the docker-compose stack restarts run apply_schema on
boot. A non-idempotent migration would either drop user data on every
restart or fail loudly and leave services in a broken state.
"""

from __future__ import annotations

from verity.db.migrate import apply_schema


async def _snapshot_schema_state(db) -> dict:
    """Capture what we expect to remain identical across a re-apply."""
    tables = await db.fetch_all_raw(
        "SELECT schemaname, tablename FROM pg_tables "
        "WHERE schemaname IN ('governance', 'runtime', 'compliance', 'analytics') "
        "ORDER BY schemaname, tablename"
    )
    types = await db.fetch_all_raw(
        "SELECT n.nspname AS schemaname, t.typname "
        "FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
        "WHERE t.typtype = 'e' AND n.nspname IN "
        "('governance', 'runtime', 'compliance', 'analytics') "
        "ORDER BY n.nspname, t.typname"
    )
    views = await db.fetch_all_raw(
        "SELECT schemaname, viewname FROM pg_views "
        "WHERE schemaname IN ('analytics') "
        "ORDER BY schemaname, viewname"
    )
    indexes = await db.fetch_all_raw(
        "SELECT schemaname, tablename, indexname FROM pg_indexes "
        "WHERE schemaname IN ('governance', 'runtime', 'compliance', 'analytics') "
        "ORDER BY schemaname, tablename, indexname"
    )
    return {
        "tables": [(r["schemaname"], r["tablename"]) for r in tables],
        "types":  [(r["schemaname"], r["typname"])  for r in types],
        "views":  [(r["schemaname"], r["viewname"]) for r in views],
        "indexes": [(r["schemaname"], r["tablename"], r["indexname"]) for r in indexes],
    }


async def test_apply_schema_is_idempotent(db):
    """Re-applying schema on top of an existing schema leaves state identical."""
    before = await _snapshot_schema_state(db)

    # The cloned per-test DB inherited the URL; pass it back into
    # apply_schema. drop_existing=False is the production restart path.
    await db.close()  # release pool — apply_schema opens its own connection
    await apply_schema(db.database_url, drop_existing=False)
    await db.connect()  # re-open pool for the assertion queries

    after = await _snapshot_schema_state(db)
    assert after == before


async def test_re_seeding_governance_apps_does_not_duplicate(db):
    """The governance application seed in apply_schema uses ON CONFLICT
    (name) DO NOTHING. Re-applying must not insert duplicate rows."""
    before_count = (await db.fetch_one_raw(
        "SELECT count(*) AS n FROM application "
        "WHERE name IN ('ai_ops', 'model_validation', 'compliance_audit')"
    ))["n"]
    assert before_count == 3

    await db.close()
    await apply_schema(db.database_url, drop_existing=False)
    await db.connect()

    after_count = (await db.fetch_one_raw(
        "SELECT count(*) AS n FROM application "
        "WHERE name IN ('ai_ops', 'model_validation', 'compliance_audit')"
    ))["n"]
    assert after_count == 3


async def test_search_path_persists_after_re_apply(db):
    """ALTER DATABASE … SET search_path is set at the end of apply_schema.
    Calling apply_schema a second time should leave search_path intact."""
    await db.close()
    await apply_schema(db.database_url, drop_existing=False)
    await db.connect()

    row = await db.fetch_one_raw("SHOW search_path")
    actual = row["search_path"]
    for schema in ("governance", "runtime", "compliance", "analytics"):
        assert schema in actual
