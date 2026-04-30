"""Compliance bootstrap-material endpoints.

The /compliance/* surface exposes the artifacts a customer warehouse
needs to ingest the L2 mart: DDL files, metamodel YAML, reports YAML,
feeds YAML. Plus a manifest.json passthrough from MinIO (skipped
here — requires a populated bucket).

These tests skip the metamodel/reports/feeds YAML endpoints because
they require ``seed_static`` + ``seed_data`` to have populated
``compliance.*`` rows — too heavy for an API smoke. Compliance seeders
are tested directly in ``tests/integration/compliance/``.
"""

from __future__ import annotations


# ── DDL allowlist ──────────────────────────────────────────────────────────

async def test_ddl_returns_known_file(client):
    """DDL files in the allowlist (schema_compliance.sql and
    schema_compliance_views.sql) are served as text/x-sql. The main
    schema.sql is NOT in the allowlist — customers don't ingest it."""
    r = await client.get("/api/v1/compliance/ddl/schema_compliance.sql")
    assert r.status_code == 200
    assert "CREATE" in r.text  # contains DDL


async def test_ddl_404_for_unknown_filename(client):
    r = await client.get("/api/v1/compliance/ddl/never_existed.sql")
    assert r.status_code == 404
    assert "Unknown DDL file" in r.json()["detail"]


async def test_ddl_compliance_schema_served(client):
    r = await client.get("/api/v1/compliance/ddl/schema_compliance.sql")
    assert r.status_code == 200
    assert "compliance" in r.text.lower()
