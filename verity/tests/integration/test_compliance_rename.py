"""Regression test for PR 1 — the ``verity_compliance`` → ``compliance`` and
``verity_analytics`` → ``analytics`` rename.

If anyone ever resurrects the legacy schema names — by reverting a query,
copy-pasting old SQL from docs, or restoring a backup — this fails fast.
After PR 3 (``public`` → ``governance`` + extract ``runtime``), update the
expected set rather than removing this test.
"""

from __future__ import annotations


EXPECTED_VERITY_OWNED_SCHEMAS = {"public", "compliance", "analytics"}
LEGACY_SCHEMAS_THAT_MUST_NOT_EXIST = {"verity_compliance", "verity_analytics"}


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


async def test_renamed_schemas_present(db):
    rows = await db.fetch_all_raw(
        "SELECT nspname FROM pg_namespace WHERE nspname IN "
        "('compliance', 'analytics')"
    )
    found = {r["nspname"] for r in rows}
    assert found == {"compliance", "analytics"}
