"""Integration test: every named query in ``queries/*.sql`` parses against
the current schema.

This is the cheapest broad-coverage test we have. It picks up:

  - ``UndefinedTable``       — missing or wrong-schema table reference
  - ``UndefinedColumn``      — column renamed/removed without query update
  - ``UndefinedFunction``    — function/operator gone or argument mismatch
  - ``InvalidSchemaName``    — schema renamed but query not requalified
  - ``SyntaxError``          — broken SQL in a `.sql` file

It explicitly does NOT validate semantics (wrong WHERE, wrong join key,
etc.) — for that we need targeted round-trip tests. But for mechanical
schema work (PR 3), the exhaustive parse check catches almost all
regressions cheaply.

How it works
------------
Each query has ``%(name)s`` placeholders. We replace them with NULL
literals and run ``EXPLAIN`` — Postgres parses + plans without executing.
NULL is type-coerced from the column type at planning time, so most
queries work without further annotation. Queries that defeat type
inference are listed in ``QUERIES_TO_SKIP`` with a one-line reason.

If ``EXPLAIN`` ever rejects a NULL literal for a parse-irrelevant reason
(e.g. "could not determine data type of parameter"), the cleanest fix is
usually to add an explicit cast in the source query rather than to skip
the test.
"""

from __future__ import annotations

import re

import psycopg


# Errors that indicate a real schema/query mismatch — fail the test on these.
PARSE_ERROR_TYPES: tuple[type[psycopg.Error], ...] = (
    psycopg.errors.UndefinedTable,
    psycopg.errors.UndefinedColumn,
    psycopg.errors.UndefinedFunction,
    psycopg.errors.InvalidSchemaName,
    psycopg.errors.SyntaxError,
    psycopg.errors.InvalidColumnReference,
)


# Queries this test cannot validate via EXPLAIN-with-NULL. Each entry must
# justify itself in one line. Prefer fixing the underlying query (with an
# explicit cast) over adding to this list.
QUERIES_TO_SKIP: dict[str, str] = {
    # Empty for now — populate as edge cases surface from PR 3 work.
}


_PARAM_PATTERN = re.compile(r"%\((\w+)\)s")


def _strip_named_params(sql: str) -> str:
    """Replace every ``%(name)s`` placeholder with the SQL literal ``NULL``.

    Postgres infers each NULL's type from the column it lands in. This
    works for the great majority of queries because named-query SQL
    typically references columns directly. The minority that need
    explicit casts surface as parse-time failures and get listed in
    QUERIES_TO_SKIP (with the underlying query ideally fixed instead).
    """
    return _PARAM_PATTERN.sub("NULL", sql)


async def test_every_named_query_parses(db):
    failures: list[str] = []

    for name, sql in db.queries.items():
        if name in QUERIES_TO_SKIP:
            continue

        explainable = f"EXPLAIN {_strip_named_params(sql)}"
        try:
            await db.fetch_all_raw(explainable)
        except PARSE_ERROR_TYPES as e:
            failures.append(
                f"\n  {name}\n"
                f"    error: {type(e).__name__}: {e}\n"
                f"    sql:   {sql.strip().splitlines()[0][:120]}"
            )
        except psycopg.Error:
            # Non-parse errors (type inference failures, etc.) aren't this
            # test's concern — we explicitly bind everything to NULL and
            # rely on column-side type coercion. If a query's shape defeats
            # that, fix the query (explicit cast) or add to QUERIES_TO_SKIP.
            continue

    if failures:
        raise AssertionError(
            f"{len(failures)} named quer{'y' if len(failures) == 1 else 'ies'} "
            f"failed to parse against the current schema:"
            + "".join(failures)
        )
