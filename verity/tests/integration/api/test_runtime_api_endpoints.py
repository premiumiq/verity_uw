"""Runtime sync execution endpoints — POST /runtime/agents/{name}/run.

Synchronous run_agent/run_task over HTTP. Happy paths require an
LLM (real or mocked at the SDK level), which the API harness can't
do in-process — those scenarios are covered by direct engine tests.
This file covers the 404 paths that don't reach the LLM.
"""

from __future__ import annotations


async def test_run_agent_404_for_unknown_name(client):
    r = await client.post(
        "/api/v1/runtime/agents/never_existed/run",
        json={"context": {"q": "x"}},
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


async def test_run_task_404_for_unknown_name(client):
    r = await client.post(
        "/api/v1/runtime/tasks/never_existed/run",
        json={"input_data": {"q": "x"}},
    )
    assert r.status_code == 404
