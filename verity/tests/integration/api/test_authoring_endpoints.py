"""POST /api/v1/* — register entity headers + draft versions.

The router passes the request body straight to the SDK ``register_*``
methods, which in turn call ``execute_returning("insert_X", kwargs)``.
The SQL named queries enumerate every column they need; tests must
include all of them (Nones where optional). Building those payloads
exhaustively here is the test's job — exercising the HTTP plumbing,
JSON shape, and error handling.
"""

from __future__ import annotations


def _agent_body(name: str = "auth_agent") -> dict:
    return {
        "name": name,
        "display_name": name,
        "description": "Test agent.",
        "purpose": "Test.",
        "domain": "underwriting",
        "materiality_tier": "low",
        "owner_name": "tester",
        "owner_email": None,
        "business_context": None,
        "known_limitations": None,
        "regulatory_notes": None,
    }


def _task_body(name: str = "auth_task") -> dict:
    return {
        "name": name,
        "display_name": name,
        "description": "Test task.",
        "capability_type": "extraction",
        "purpose": "Test.",
        "domain": "underwriting",
        "materiality_tier": "low",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "owner_name": "tester",
        "owner_email": None,
        "business_context": None,
        "known_limitations": None,
        "regulatory_notes": None,
    }


def _tool_body(name: str = "auth_tool") -> dict:
    return {
        "name": name,
        "display_name": name,
        "description": "Test tool.",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "transport": "python_inprocess",
        "mcp_server_name": None,
        "mcp_tool_name": None,
        "implementation_path": f"tests.tools.{name}",
        "mock_mode_enabled": True,
        "mock_response_key": "default",
        "data_classification_max": "tier3_confidential",
        "is_write_operation": False,
        "requires_confirmation": False,
        "tags": [],
    }


def _inference_config_body(name: str = "tight_config") -> dict:
    return {
        "name": name,
        "display_name": name,
        "description": "Greedy.",
        "intended_use": "Determinism critical.",
        "model_name": "claude-sonnet-4-20250514",
        "temperature": 0.0,
        "max_tokens": 2048,
        "top_p": None,
        "top_k": None,
        "stop_sequences": None,
        "extended_params": {},
    }


def _agent_version_body(inference_config_id: str) -> dict:
    return {
        "major_version": 1,
        "minor_version": 0,
        "patch_version": 0,
        "lifecycle_state": "draft",
        "channel": "development",
        "inference_config_id": inference_config_id,
        "output_schema": None,
        "authority_thresholds": {},
        "mock_mode_enabled": True,
        "decision_log_detail": "standard",
        "developer_name": "tester",
        "change_summary": "Initial.",
        "change_type": "initial",
    }


# ── POST /agents ───────────────────────────────────────────────────────────

async def test_register_agent_succeeds(client):
    r = await client.post("/api/v1/agents", json=_agent_body("api_agent_1"))
    assert r.status_code == 200, r.text
    assert "id" in r.json()


async def test_register_agent_duplicate_returns_400(client):
    body = _agent_body("dup_agent")
    r1 = await client.post("/api/v1/agents", json=body)
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/agents", json=body)
    assert r2.status_code == 400


# ── POST /tasks ────────────────────────────────────────────────────────────

async def test_register_task_succeeds(client):
    r = await client.post("/api/v1/tasks", json=_task_body("api_task_1"))
    assert r.status_code == 200, r.text


# ── POST /tools ────────────────────────────────────────────────────────────

async def test_register_tool_succeeds(client):
    r = await client.post("/api/v1/tools", json=_tool_body("api_tool_1"))
    assert r.status_code == 200, r.text


# ── POST /inference-configs ────────────────────────────────────────────────

async def test_register_inference_config_succeeds(client):
    r = await client.post(
        "/api/v1/inference-configs",
        json=_inference_config_body("api_config_1"),
    )
    assert r.status_code == 200, r.text


# ── POST /agents/{name}/versions ───────────────────────────────────────────

async def test_register_agent_version_succeeds(client):
    """Create the parent agent first via the API, then add a version."""
    parent_resp = await client.post(
        "/api/v1/agents", json=_agent_body("ver_parent"),
    )
    assert parent_resp.status_code == 200

    cfgs = await client.get("/api/v1/inference-configs")
    cfg_id = next(
        c["id"] for c in cfgs.json() if c["name"] == "test_default_config"
    )

    r = await client.post(
        "/api/v1/agents/ver_parent/versions",
        json=_agent_version_body(cfg_id),
    )
    assert r.status_code == 200, r.text


async def test_register_agent_version_404_for_unknown_parent(client):
    r = await client.post(
        "/api/v1/agents/never_existed/versions",
        json={"inference_config_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert r.status_code == 404
