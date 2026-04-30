"""Connection pool concurrency.

The Database class uses an AsyncConnectionPool with min_size=2,
max_size=10. Production code fires concurrent queries — for example,
the engine emits parallel decision-log writes during multi-tool turns,
and the API answers concurrent HTTP requests. These tests confirm:

  - Pool serves parallel queries without errors
  - All connections are returned to the pool (no leaks)
  - Pool stays usable after a burst of concurrency

Each test's clone DB is dropped after the test, so the pool's lifetime
is bounded to the test function.
"""

from __future__ import annotations

import asyncio


async def test_pool_serves_concurrent_reads(db):
    """20 parallel SELECTs all succeed and return the expected value."""
    async def one_read() -> int:
        row = await db.fetch_one_raw("SELECT 42 AS answer")
        return row["answer"]

    results = await asyncio.gather(*(one_read() for _ in range(20)))
    assert all(r == 42 for r in results)


async def test_pool_serves_mixed_reads_and_writes(db):
    """Concurrent INSERTs + SELECTs against the same DB don't deadlock.

    Uses unqualified `application` which resolves to governance.application
    via the database default search_path.
    """
    async def insert_and_check(i: int) -> str:
        name = f"concurrent_app_{i}"
        await db.execute_raw(
            "INSERT INTO application (name, display_name, description) "
            "VALUES (%(n)s, %(d)s, 'concurrent test') "
            "ON CONFLICT (name) DO NOTHING",
            {"n": name, "d": name},
        )
        row = await db.fetch_one_raw(
            "SELECT name FROM application WHERE name = %(n)s",
            {"n": name},
        )
        return row["name"]

    results = await asyncio.gather(*(insert_and_check(i) for i in range(15)))
    # Every task got its own row back.
    assert sorted(results) == sorted(f"concurrent_app_{i}" for i in range(15))


async def test_pool_remains_usable_after_concurrent_burst(db):
    """After firing 30 parallel queries, sequential queries still work —
    confirms connections are returned to the pool, not leaked."""
    async def one_read():
        await db.fetch_one_raw("SELECT 1")

    await asyncio.gather(*(one_read() for _ in range(30)))

    # Sequential follow-ups should succeed without exhausting the pool.
    for _ in range(5):
        row = await db.fetch_one_raw("SELECT 'still alive' AS status")
        assert row["status"] == "still alive"
