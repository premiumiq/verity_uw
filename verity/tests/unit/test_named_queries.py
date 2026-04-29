"""Unit tests for the named-query loader in ``verity.db.connection``.

The loader is the bridge between ``.sql`` files and Python callers — a
silent regression here would route Python calls to the wrong SQL. Tests
use ``tmp_path`` so we control the file content exactly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from verity.db.connection import _load_all_queries, _load_queries_from_file


def test_parses_two_named_queries(tmp_path: Path):
    sql_file = tmp_path / "queries.sql"
    sql_file.write_text(
        "-- name: get_one\n"
        "SELECT 1;\n"
        "\n"
        "-- name: get_two\n"
        "SELECT 2;\n"
    )
    queries = _load_queries_from_file(sql_file)
    assert queries == {"get_one": "SELECT 1;", "get_two": "SELECT 2;"}


def test_strips_leading_whitespace_around_query_text(tmp_path: Path):
    sql_file = tmp_path / "queries.sql"
    sql_file.write_text("-- name: q\n\n   SELECT 1;\n\n")
    queries = _load_queries_from_file(sql_file)
    assert queries["q"] == "SELECT 1;"


def test_skips_anonymous_queries(tmp_path: Path):
    # Lines without a `-- name:` marker are part of the preamble or the
    # previous query — the loader should not register them as queries.
    sql_file = tmp_path / "queries.sql"
    sql_file.write_text(
        "-- File header comment\n"
        "SELECT 'preamble' /* not registered */;\n"
        "-- name: real_query\n"
        "SELECT 1;\n"
    )
    queries = _load_queries_from_file(sql_file)
    assert list(queries.keys()) == ["real_query"]


def test_load_all_queries_aggregates_directory(tmp_path: Path):
    (tmp_path / "a.sql").write_text("-- name: q_a\nSELECT 1;\n")
    (tmp_path / "b.sql").write_text("-- name: q_b\nSELECT 2;\n")
    queries = _load_all_queries(tmp_path)
    assert set(queries) == {"q_a", "q_b"}


def test_load_all_queries_rejects_duplicate_names(tmp_path: Path):
    (tmp_path / "a.sql").write_text("-- name: dup\nSELECT 1;\n")
    (tmp_path / "b.sql").write_text("-- name: dup\nSELECT 2;\n")
    with pytest.raises(ValueError, match="Duplicate query name 'dup'"):
        _load_all_queries(tmp_path)


def test_load_all_queries_returns_empty_for_missing_directory(tmp_path: Path):
    assert _load_all_queries(tmp_path / "does_not_exist") == {}
