"""Database connection pool and named query loader.

Uses psycopg 3 (async) with connection pooling.
SQL queries live in .sql files and are loaded by name.
No ORM — raw SQL, transparent and debuggable.
"""

import re
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool


# Pattern to split .sql files into named queries.
# Each query starts with: -- name: query_name
_QUERY_NAME_PATTERN = re.compile(r"^--\s*name:\s*(\S+)", re.MULTILINE)


def _load_queries_from_file(path: Path) -> dict[str, str]:
    """Parse a .sql file into a dict of {query_name: sql_text}.

    File format:
        -- name: get_agent_champion
        SELECT ... ;

        -- name: list_agents
        SELECT ... ;
    """
    text = path.read_text()
    parts = _QUERY_NAME_PATTERN.split(text)
    # parts: ['preamble', 'name1', 'sql1', 'name2', 'sql2', ...]
    queries = {}
    for i in range(1, len(parts), 2):
        name = parts[i].strip()
        sql = parts[i + 1].strip()
        if sql:
            queries[name] = sql
    return queries


def _load_all_queries(queries_dir: Path) -> dict[str, str]:
    """Load all named queries from all .sql files in a directory."""
    all_queries: dict[str, str] = {}
    if not queries_dir.exists():
        return all_queries
    for sql_file in sorted(queries_dir.glob("*.sql")):
        file_queries = _load_queries_from_file(sql_file)
        # Check for duplicate names across files
        for name in file_queries:
            if name in all_queries:
                raise ValueError(
                    f"Duplicate query name '{name}' found in {sql_file}. "
                    f"Query names must be unique across all .sql files."
                )
        all_queries.update(file_queries)
    return all_queries


class Database:
    """Async PostgreSQL database interface with named query support.

    Usage:
        db = Database(database_url="postgresql://...")
        await db.connect()

        row = await db.fetch_one("get_agent_champion", {"agent_name": "triage_agent"})
        rows = await db.fetch_all("list_agents")
        await db.execute("update_lifecycle_state", {"id": ..., "state": "champion"})

        await db.close()
    """

    def __init__(self, database_url: str, queries_dir: Path | None = None):
        self.database_url = database_url
        self._pool: AsyncConnectionPool | None = None

        # Load queries from the default directory if not specified
        if queries_dir is None:
            queries_dir = Path(__file__).parent / "queries"
        self.queries = _load_all_queries(queries_dir)

    async def connect(self) -> None:
        """Open the connection pool."""
        self._pool = AsyncConnectionPool(
            conninfo=self.database_url,
            min_size=2,
            max_size=10,
            kwargs={"row_factory": dict_row},
        )
        await self._pool.open()

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    def _get_sql(self, query_name: str) -> str:
        """Look up a named query. Raises KeyError if not found."""
        if query_name not in self.queries:
            available = ", ".join(sorted(self.queries.keys())[:20])
            raise KeyError(
                f"Query '{query_name}' not found. Available: {available}..."
            )
        return self.queries[query_name]

    async def fetch_one(
        self, query_name: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute a named query and return the first row as a dict, or None."""
        sql = self._get_sql(query_name)
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params or {})
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetch_all(
        self, query_name: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a named query and return all rows as a list of dicts."""
        sql = self._get_sql(query_name)
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params or {})
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    async def execute(
        self, query_name: str, params: dict[str, Any] | None = None
    ) -> None:
        """Execute a named query (INSERT/UPDATE/DELETE) without returning rows."""
        sql = self._get_sql(query_name)
        async with self._pool.connection() as conn:
            await conn.execute(sql, params or {})

    async def execute_returning(
        self, query_name: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute a named query with RETURNING clause, return the first row."""
        sql = self._get_sql(query_name)
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params or {})
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def execute_raw(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> None:
        """Execute arbitrary SQL. Use sparingly — prefer named queries."""
        async with self._pool.connection() as conn:
            await conn.execute(sql, params or {})

    async def fetch_one_raw(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Execute arbitrary SQL and return first row. Use sparingly."""
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params or {})
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def fetch_all_raw(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute arbitrary SQL and return all rows. Use sparingly."""
        async with self._pool.connection() as conn:
            cursor = await conn.execute(sql, params or {})
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
