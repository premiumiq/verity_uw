"""Shared pytest fixtures for the Verity test suite.

Two flavors of test live alongside each other:

  tests/unit/         — pure-Python tests, no DB, no I/O. Fast.
  tests/integration/  — real Postgres, mocked LLM/EDMS. Slower but exercises
                        the actual SQL.

Database isolation strategy
---------------------------
We reuse the running ``verity_postgres`` container instead of spinning up a
disposable one — CI is expected to bring up the same docker-compose stack.

Per-test isolation comes from Postgres' built-in template-database feature:

  1. ``template_database`` (session scope, sync) creates ``verity_test_template``
     once, applies the full Verity schema to it, runs the canonical seed, and
     marks it ``IS_TEMPLATE = true``. Teardown drops it.

  2. ``db`` (function scope, async) clones the template per test:
     ``CREATE DATABASE verity_test_<uuid> TEMPLATE verity_test_template``
     — Postgres copies it at the file level in ~50ms. The test gets a fully
     seeded, fully isolated DB and drops it on teardown.

This pattern needs no special savepoint juggling: each test sees a real
database it can commit to freely.

Configuration
-------------
``VERITY_TEST_DATABASE_URL`` overrides the default admin connection string.
Defaults match the docker-compose ``verity_postgres`` container.

Don't connect to ``verity_test_template`` while tests are running. Postgres
refuses to clone a template that has active connections, and the resulting
"source database is being accessed by other users" error is confusing.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import psycopg
import pytest
import pytest_asyncio


# ── Connection plumbing ─────────────────────────────────────────────────────
#
# All admin operations (CREATE/DROP DATABASE, ALTER DATABASE) run against the
# Postgres ``postgres`` admin database. Per-test work runs against a freshly
# cloned database. ``_db_url`` swaps the database name in the URL while
# preserving credentials, host, and port.

DEFAULT_ADMIN_URL = (
    "postgresql://verityuser:veritypass123@localhost:5432/postgres"
)
TEMPLATE_DB_NAME = os.getenv("VERITY_TEST_TEMPLATE_NAME", "verity_test_template")

# Application databases the docker-compose stack uses. If anyone ever points
# VERITY_TEST_DATABASE_URL at one of these, the safety check in
# ``pytest_configure`` aborts before any test runs — otherwise per-test
# CREATE DATABASE / DROP DATABASE operations would commingle with real data.
PRODUCTION_DB_NAMES = frozenset({"verity_db", "uw_db", "edms_db", "pas_db"})


def _admin_url() -> str:
    """Connection URL for the postgres admin DB. Override via env."""
    return os.getenv("VERITY_TEST_DATABASE_URL", DEFAULT_ADMIN_URL)


def _db_url(database_name: str) -> str:
    """Return the admin URL with the database portion replaced.

    Example: ``postgresql://u:p@host:5432/postgres`` → ``…/<database_name>``.
    """
    base = _admin_url()
    head, _, _ = base.rpartition("/")
    return f"{head}/{database_name}"


async def _execute_admin(sql: str) -> None:
    """Run a single statement against the admin DB in autocommit mode.

    CREATE DATABASE / DROP DATABASE / ALTER DATABASE all require autocommit
    and refuse to run inside a transaction block.
    """
    async with await psycopg.AsyncConnection.connect(
        _admin_url(), autocommit=True
    ) as conn:
        await conn.execute(sql)


def _database_name_from_url(url: str) -> str:
    """Pull the database name out of a Postgres URL.

    ``postgresql://u:p@host:5432/dbname?opt=v`` → ``dbname``.
    """
    return url.rsplit("/", 1)[-1].split("?")[0]


# ── pytest hooks ────────────────────────────────────────────────────────────

def pytest_addoption(parser: pytest.Parser) -> None:
    """Register Verity-specific CLI flags.

    ``--preserve-test-db`` is the only one for now: when set, the per-test
    ``db`` fixture skips its DROP DATABASE teardown so a developer can
    connect to the cloned DB after a failure and inspect state.
    """
    parser.addoption(
        "--preserve-test-db",
        action="store_true",
        default=False,
        help=(
            "Don't drop per-test cloned databases at teardown. The DB names "
            "are printed; connect with `docker exec -it verity_postgres "
            "psql -U verityuser -d verity_test_<id>` to inspect state. The "
            "session template DB is still cleaned up at session end."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Safety check: refuse to run if the test URL points at a real app DB.

    The fixture issues ``CREATE DATABASE`` / ``DROP DATABASE`` against the
    URL it's given. If that URL pointed at ``verity_db`` (or any other live
    app DB), per-test clones would land alongside production data and the
    safety story for tests collapses. Caught at session start instead of
    only when the first integration test runs.
    """
    url = _admin_url()
    db_name = _database_name_from_url(url)
    if db_name in PRODUCTION_DB_NAMES:
        raise pytest.UsageError(
            f"Refusing to run tests against production database {db_name!r}.\n"
            f"VERITY_TEST_DATABASE_URL must point at the Postgres admin DB "
            f"(typically ``postgres``), not an application database — the "
            f"fixture creates per-test ``verity_test_<uuid>`` databases at "
            f"that URL.\n"
            f"Current URL: {url}"
        )


# ── Template lifecycle ──────────────────────────────────────────────────────

async def _setup_template() -> None:
    """Build the session template DB from scratch.

    A stale template from a crashed prior session would otherwise carry
    forward. We always rebuild — the cost is one ``apply_schema`` call.
    """
    # Defensive: unmark and drop any stale template.
    try:
        await _execute_admin(
            f"ALTER DATABASE {TEMPLATE_DB_NAME} IS_TEMPLATE = false"
        )
    except psycopg.errors.InvalidCatalogName:
        # Template doesn't exist yet — nothing to unmark.
        pass

    await _execute_admin(
        f"DROP DATABASE IF EXISTS {TEMPLATE_DB_NAME} WITH (FORCE)"
    )
    await _execute_admin(f"CREATE DATABASE {TEMPLATE_DB_NAME}")

    # Imports deferred to fixture-call time — keeps unit tests in tests/unit/
    # importable even when the verity package isn't fully installed.
    from verity.db.connection import Database
    from verity.db.migrate import apply_schema

    from tests.fixtures.canonical_seed import load_canonical_seed

    template_url = _db_url(TEMPLATE_DB_NAME)
    await apply_schema(template_url, drop_existing=False)

    db = Database(database_url=template_url)
    await db.connect()
    try:
        await load_canonical_seed(db)
    finally:
        # Pool MUST close before we mark IS_TEMPLATE — Postgres tracks open
        # connections, and a lingering one prevents subsequent CREATE
        # DATABASE … TEMPLATE clones with "source DB is being accessed".
        await db.close()

    await _execute_admin(
        f"ALTER DATABASE {TEMPLATE_DB_NAME} IS_TEMPLATE = true"
    )


async def _teardown_template() -> None:
    """Unmark and drop the template at session end."""
    try:
        await _execute_admin(
            f"ALTER DATABASE {TEMPLATE_DB_NAME} IS_TEMPLATE = false"
        )
    except psycopg.errors.InvalidCatalogName:
        return
    await _execute_admin(
        f"DROP DATABASE IF EXISTS {TEMPLATE_DB_NAME} WITH (FORCE)"
    )


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def template_database():
    """Ensure ``verity_test_template`` exists; return its name.

    Synchronous on purpose: it bridges sync pytest scoping with async
    setup/teardown via ``asyncio.run``, which sidesteps the well-known
    pytest-asyncio session-loop scoping issue.
    """
    asyncio.run(_setup_template())
    yield TEMPLATE_DB_NAME
    asyncio.run(_teardown_template())


@pytest_asyncio.fixture
async def db(request, template_database):
    """Per-test cloned DB. Yields a connected ``verity.db.Database``.

    The clone is dropped after the test by default. Pass ``--preserve-test-db``
    on the pytest CLI to keep clones for inspection — useful when a test
    fails and you want to poke around in the resulting state with psql.
    """
    from verity.db.connection import Database

    test_db_name = f"verity_test_{uuid.uuid4().hex[:12]}"
    await _execute_admin(
        f"CREATE DATABASE {test_db_name} TEMPLATE {template_database}"
    )
    # Postgres' CREATE DATABASE … TEMPLATE copies tables, types, indexes —
    # but NOT per-database settings set via ALTER DATABASE. Re-apply
    # search_path on the clone so unqualified DML resolves the same way
    # production code expects (where apply_schema set it once on
    # verity_db). Without this the unqualified `FROM agent` in named
    # queries can't find governance.agent.
    await _execute_admin(
        f"ALTER DATABASE {test_db_name} "
        "SET search_path TO governance, runtime, compliance, analytics, public"
    )

    test_db = Database(database_url=_db_url(test_db_name))
    await test_db.connect()
    try:
        yield test_db
    finally:
        await test_db.close()
        if request.config.getoption("--preserve-test-db"):
            # Print to stderr via pytest's terminalreporter so the message
            # appears even when -q is set — the path through `print` would
            # be swallowed by capture.
            tr = request.config.pluginmanager.get_plugin("terminalreporter")
            if tr is not None:
                tr.write_line(
                    f"[--preserve-test-db] kept {test_db_name} "
                    f"(connect: docker exec -it verity_postgres psql "
                    f"-U verityuser -d {test_db_name})",
                    yellow=True,
                )
        else:
            await _execute_admin(
                f"DROP DATABASE IF EXISTS {test_db_name} WITH (FORCE)"
            )
