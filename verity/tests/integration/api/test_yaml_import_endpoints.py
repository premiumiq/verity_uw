"""HTTP endpoint tests for ``POST /api/v1/yaml/import`` (slice 4B).

Importer behaviour is covered by the governance tests; these focus on
the API surface — content-type handling, status codes, error shape.
"""

from __future__ import annotations

import yaml as yaml_lib

from tests.fixtures.builders import make_complete_agent


# Minimal valid bundle with no DB references — easiest payload to ship.
_MINIMAL_TOOL_YAML = """\
apiVersion: studio.verity.ai/v1
kind: Bundle
entities:
- kind: Tool
  name: api_imported_tool
  display_name: API Imported Tool
  description: Inserted via the YAML import endpoint.
  transport: python_inprocess
  implementation_path: x.y.api_imported
  input_schema:
    type: object
  output_schema:
    type: object
"""


async def test_yaml_import_endpoint_accepts_yaml_body(client, db):
    """Posting a YAML body inserts the entity and returns the
    per-entity outcome summary."""
    r = await client.post(
        "/api/v1/yaml/import",
        content=_MINIMAL_TOOL_YAML,
        headers={"Content-Type": "application/yaml"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    inserted = {(e["kind"], e["name"]) for e in body["headers_inserted"]}
    assert ("Tool", "api_imported_tool") in inserted
    assert body["headers_skipped"] == []


async def test_yaml_import_endpoint_is_idempotent(client, db):
    """Re-posting the same body is a no-op — all rows reported as
    skipped, no error."""
    first = await client.post(
        "/api/v1/yaml/import", content=_MINIMAL_TOOL_YAML,
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/yaml/import", content=_MINIMAL_TOOL_YAML,
    )
    assert second.status_code == 200
    body = second.json()
    skipped = {(e["kind"], e["name"]) for e in body["headers_skipped"]}
    assert ("Tool", "api_imported_tool") in skipped
    assert body["headers_inserted"] == []


async def test_yaml_import_endpoint_400_on_invalid_yaml(client, db):
    # An unclosed flow sequence is one of the few inputs that PyYAML
    # truly refuses to parse — most "garbage" strings come back as a
    # plain string scalar. Use one of the legitimate parse failures.
    r = await client.post(
        "/api/v1/yaml/import",
        content="[unclosed",
    )
    assert r.status_code == 400


async def test_yaml_import_endpoint_400_on_empty_body(client, db):
    r = await client.post(
        "/api/v1/yaml/import",
        content="",
    )
    assert r.status_code == 400


async def test_yaml_import_endpoint_422_on_dangling_reference(client, db):
    """A bundle that references something neither in the bundle nor
    in the DB returns 422 with structured errors."""
    yaml_text = """\
apiVersion: studio.verity.ai/v1
kind: Bundle
entities:
- kind: Agent
  name: api_dangling_agent
  display_name: API Dangling Agent
  description: References nothing.
  versions:
  - version_label: 1.0.0
    change_summary: Initial.
    inference_config: not_a_real_config
"""
    r = await client.post(
        "/api/v1/yaml/import", content=yaml_text,
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert detail["error_code"] == "validation_failed"
    assert detail["errors"], "Should have at least one structured error"
    err = detail["errors"][0]
    assert err["code"] == "dangling_reference"
    assert "not_a_real_config" in err["message"]


async def test_yaml_export_then_import_via_http(client, db):
    """Drive the full export → import loop through HTTP. Catches
    integration issues that the SDK-level round-trip test wouldn't —
    request shapes, content types, response decoding."""
    bundle_setup = await make_complete_agent(
        db, name="api_round_trip_agent", promote_to_champion=False,
    )

    # Export
    export_resp = await client.post(
        "/api/v1/yaml/export",
        json={"kind": "agent", "name": bundle_setup.name},
    )
    assert export_resp.status_code == 200
    yaml_text = export_resp.text

    # Import the exported YAML back into the same DB.
    # Existing rows are skipped (idempotency rule).
    import_resp = await client.post(
        "/api/v1/yaml/import",
        content=yaml_text,
        headers={"Content-Type": "application/yaml"},
    )
    assert import_resp.status_code == 200, import_resp.text
    body = import_resp.json()
    # Every entity already exists → every header is skipped.
    skipped_kinds = {e["kind"] for e in body["headers_skipped"]}
    assert "Agent" in skipped_kinds


async def test_yaml_import_endpoint_creates_versions_as_draft(client, db):
    """Even when the YAML claims ``lifecycle_state: champion``, the
    HTTP endpoint must create as draft (the importer's lifecycle-
    masking rule needs to be honoured at the API surface too)."""
    yaml_text = """\
apiVersion: studio.verity.ai/v1
kind: Bundle
entities:
- kind: Prompt
  name: api_lifecycle_test
  display_name: API Lifecycle Test
  description: Will be created as draft regardless of YAML.
  versions:
  - version_label: 1.0.0
    lifecycle_state: champion
    api_role: system
    governance_tier: behavioural
    change_summary: Initial.
    content: Champion in YAML.
"""
    r = await client.post("/api/v1/yaml/import", content=yaml_text)
    assert r.status_code == 200

    # Verify the resulting row is draft, not champion.
    row = await db.fetch_one_raw(
        """
        SELECT pv.lifecycle_state
        FROM governance.prompt_version pv
        JOIN governance.prompt p ON p.id = pv.prompt_id
        WHERE p.name = %(name)s AND pv.version_label = %(label)s
        """,
        {"name": "api_lifecycle_test", "label": "1.0.0"},
    )
    assert row is not None
    assert str(row["lifecycle_state"]) == "draft"
