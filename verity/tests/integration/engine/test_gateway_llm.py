"""Tests for ``ExecutionEngine._gateway_llm_call``.

The gateway is the ONLY place the engine calls Claude. Every other code
path goes through it, so its behavior — particularly retry semantics —
governs how Verity reacts to flaky upstream conditions.

Behaviors under test:
  - Successful call: response forwarded as-is
  - Retry on transient error codes (429, 500, 502, 503, 529)
  - Retry on connection error
  - Exhaustion: raise after max_retries
  - Non-retryable status codes: raise immediately, no retries
  - No client configured: RuntimeError with a useful message
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

from tests.fixtures.fakes import (
    FakeAnthropicClient,
    text_response,
)


# ── Successful path ─────────────────────────────────────────────────────────

async def test_returns_scripted_response(engine):
    engine.client.script(text_response("hello"))
    response = await engine._gateway_llm_call(
        api_params={"model": "claude-sonnet-4-20250514", "max_tokens": 1024,
                    "messages": [{"role": "user", "content": "hi"}]},
        mock=None,
    )
    assert response.content[0].text == "hello"
    assert response.stop_reason == "end_turn"


async def test_forwards_api_params_to_client(engine):
    engine.client.script(text_response("ok"))
    await engine._gateway_llm_call(
        api_params={"model": "claude-sonnet-4-20250514", "max_tokens": 4096,
                    "temperature": 0.0,
                    "messages": [{"role": "user", "content": "hi"}]},
        mock=None,
    )
    assert len(engine.client.calls) == 1
    call = engine.client.calls[0]
    assert call["model"] == "claude-sonnet-4-20250514"
    assert call["max_tokens"] == 4096
    assert call["temperature"] == 0.0


# ── No client configured ────────────────────────────────────────────────────

async def test_raises_when_no_client_configured(engine):
    """Engine constructed with empty key → client is None.
    Calling the gateway must raise with a clear message."""
    engine.client = None
    with pytest.raises(RuntimeError, match="No Anthropic API key configured"):
        await engine._gateway_llm_call(api_params={}, mock=None)


# ── Retry on transient errors ──────────────────────────────────────────────

def _api_status_error(status_code: int) -> anthropic.APIStatusError:
    """Build an APIStatusError with a real-shaped HTTP response.

    The constructor needs both `response` (httpx.Response) and `body`,
    which is the parsed error JSON Anthropic returns.
    """
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request)
    return anthropic.APIStatusError(
        message=f"transient {status_code}",
        response=response,
        body={"error": {"type": "test", "message": f"transient {status_code}"}},
    )


@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 529])
async def test_retries_on_transient_status_then_succeeds(
    engine, monkeypatch, status_code,
):
    """Each retryable status: gateway should retry, then return on success."""
    # Two failures, then a success.
    create_mock = AsyncMock(side_effect=[
        _api_status_error(status_code),
        _api_status_error(status_code),
        text_response("recovered"),
    ])
    monkeypatch.setattr(engine.client.messages, "create", create_mock)
    # asyncio.sleep is real; speed it up so the test isn't slow.
    monkeypatch.setattr(
        "verity.runtime.engine.asyncio.sleep",
        AsyncMock(return_value=None),
    )

    response = await engine._gateway_llm_call(api_params={}, mock=None)
    assert response.content[0].text == "recovered"
    assert create_mock.call_count == 3  # 2 failures + 1 success


async def test_retries_exhausted_raises(engine, monkeypatch):
    """After max_retries (3) the gateway must give up and re-raise."""
    create_mock = AsyncMock(side_effect=_api_status_error(503))
    monkeypatch.setattr(engine.client.messages, "create", create_mock)
    monkeypatch.setattr(
        "verity.runtime.engine.asyncio.sleep",
        AsyncMock(return_value=None),
    )

    with pytest.raises(anthropic.APIStatusError):
        await engine._gateway_llm_call(api_params={}, mock=None)
    # 1 initial + 3 retries = 4 attempts total.
    assert create_mock.call_count == 4


async def test_non_retryable_status_raises_immediately(engine, monkeypatch):
    """A 400 (bad request) is the user's fault, not a transient — no retry."""
    create_mock = AsyncMock(side_effect=_api_status_error(400))
    monkeypatch.setattr(engine.client.messages, "create", create_mock)
    sleep_mock = AsyncMock(return_value=None)
    monkeypatch.setattr("verity.runtime.engine.asyncio.sleep", sleep_mock)

    with pytest.raises(anthropic.APIStatusError):
        await engine._gateway_llm_call(api_params={}, mock=None)
    assert create_mock.call_count == 1
    assert sleep_mock.call_count == 0  # No backoff happened.


async def test_retries_on_connection_error_then_succeeds(engine, monkeypatch):
    """APIConnectionError = network blip; always retry up to max_retries."""
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    create_mock = AsyncMock(side_effect=[
        anthropic.APIConnectionError(request=request),
        text_response("recovered"),
    ])
    monkeypatch.setattr(engine.client.messages, "create", create_mock)
    monkeypatch.setattr(
        "verity.runtime.engine.asyncio.sleep",
        AsyncMock(return_value=None),
    )

    response = await engine._gateway_llm_call(api_params={}, mock=None)
    assert response.content[0].text == "recovered"
    assert create_mock.call_count == 2
