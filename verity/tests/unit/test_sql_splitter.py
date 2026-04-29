"""Unit tests for ``verity.db.migrate._split_sql_statements``.

The splitter walks a SQL file character-by-character so it can keep
track of strings, comments, and dollar-quoted blocks. The tests below
exercise each of those state machines independently — if a future
refactor breaks one, you'll see exactly which case regressed.
"""

from __future__ import annotations

from verity.db.migrate import _split_sql_statements


def test_splits_simple_statements():
    sql = "CREATE TABLE a (id int); CREATE TABLE b (id int);"
    assert _split_sql_statements(sql) == [
        "CREATE TABLE a (id int)",
        "CREATE TABLE b (id int)",
    ]


def test_ignores_semicolons_inside_line_comments():
    sql = """
    -- This comment has a ; semicolon; in it
    CREATE TABLE a (id int);
    """
    statements = _split_sql_statements(sql)
    assert len(statements) == 1
    assert "CREATE TABLE a" in statements[0]


def test_ignores_semicolons_inside_string_literals():
    sql = "INSERT INTO a (note) VALUES ('a;b;c');"
    statements = _split_sql_statements(sql)
    assert statements == ["INSERT INTO a (note) VALUES ('a;b;c')"]


def test_handles_escaped_quotes_in_strings():
    # Postgres-style escaped quote: '' inside a string literal.
    sql = "INSERT INTO a (note) VALUES ('it''s; fine');"
    statements = _split_sql_statements(sql)
    assert statements == ["INSERT INTO a (note) VALUES ('it''s; fine')"]


def test_ignores_semicolons_inside_dollar_quoted_blocks():
    # DO $$ blocks are how migrate.py wraps PL/pgSQL — the splitter MUST
    # treat the whole $$...$$ region as one statement, semicolons inside.
    sql = """
    DO $$ DECLARE r RECORD; BEGIN
        FOR r IN (SELECT 1) LOOP
            RAISE NOTICE 'x';
        END LOOP;
    END $$;
    """
    statements = _split_sql_statements(sql)
    assert len(statements) == 1
    assert "DO $$" in statements[0]
    assert "END $$" in statements[0]


def test_handles_tagged_dollar_quotes():
    # Postgres allows custom tags between dollar signs to nest blocks.
    sql = "SELECT $tag$ inside; $tag$;"
    statements = _split_sql_statements(sql)
    assert statements == ["SELECT $tag$ inside; $tag$"]


def test_skips_empty_trailing_statement():
    # A file that ends with a semicolon shouldn't produce an empty entry.
    sql = "SELECT 1;"
    assert _split_sql_statements(sql) == ["SELECT 1"]


def test_handles_statement_without_trailing_semicolon():
    sql = "SELECT 1"
    assert _split_sql_statements(sql) == ["SELECT 1"]
