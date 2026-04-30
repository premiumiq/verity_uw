"""Application-management endpoints.

Applications are the multi-tenant anchor — register / list / get /
unregister. The canonical seed already inserts three governance apps
(ai_ops, model_validation, compliance_audit), so listing should always
return at least those.
"""

from __future__ import annotations


async def test_list_applications_returns_seeded_governance_apps(client):
    r = await client.get("/api/v1/applications")
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert {"ai_ops", "model_validation", "compliance_audit"}.issubset(names)


async def test_get_application_by_name(client):
    r = await client.get("/api/v1/applications/ai_ops")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "ai_ops"
    assert body["display_name"] == "AI Operations"


async def test_get_application_404_for_unknown_name(client):
    r = await client.get("/api/v1/applications/never_registered")
    assert r.status_code == 404


async def test_register_application_succeeds(client):
    r = await client.post(
        "/api/v1/applications",
        json={
            "name": "uw_demo",
            "display_name": "UW Demo",
            "description": "Underwriting demo app.",
        },
    )
    assert r.status_code == 200
    body = r.json()
    # The insert query returns id + created_at; name comes back via list/get.
    assert "id" in body

    # Now visible in list.
    r = await client.get("/api/v1/applications")
    names = {row["name"] for row in r.json()}
    assert "uw_demo" in names


async def test_register_application_duplicate_name_returns_400(client):
    """Re-registering an existing name is a UNIQUE-violation; the router
    catches PsycopgError and converts to 400."""
    body = {
        "name": "duplicate_app",
        "display_name": "Duplicate App",
        "description": "First registration.",
    }
    r1 = await client.post("/api/v1/applications", json=body)
    assert r1.status_code == 200

    r2 = await client.post("/api/v1/applications", json=body)
    assert r2.status_code == 400
