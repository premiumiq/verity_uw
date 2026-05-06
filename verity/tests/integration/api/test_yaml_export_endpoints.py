"""HTTP endpoint tests for ``POST /api/v1/yaml/export`` (slice 4A).

Exporter behaviour is covered by
``tests/integration/governance/test_yaml_export.py`` — these tests
focus on the API surface: routing, response shape, error codes.
"""

from __future__ import annotations

import yaml

from tests.fixtures.builders import make_complete_agent


async def test_yaml_export_endpoint_returns_yaml_text(client, db):
    """Round-trip the export through the HTTP endpoint to confirm
    routing + response shape."""
    bundle_setup = await make_complete_agent(
        db, name="endpoint_test_agent", promote_to_champion=False,
    )
    r = await client.post(
        "/api/v1/yaml/export",
        json={"kind": "agent", "name": bundle_setup.name},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/yaml")
    parsed = yaml.safe_load(r.text)
    assert parsed["apiVersion"] == "studio.verity.ai/v1"
    kinds = [e["kind"] for e in parsed["entities"]]
    assert "Agent" in kinds
    assert "Prompt" in kinds
    assert "InferenceConfig" in kinds


async def test_yaml_export_endpoint_404_for_unknown(client, db):
    r = await client.post(
        "/api/v1/yaml/export",
        json={"kind": "agent", "name": "no_such_agent"},
    )
    assert r.status_code == 404


async def test_yaml_export_endpoint_422_for_unknown_kind(client, db):
    r = await client.post(
        "/api/v1/yaml/export",
        json={"kind": "not_a_kind", "name": "anything"},
    )
    assert r.status_code == 422
