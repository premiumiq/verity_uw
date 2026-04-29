"""In-memory fakes for the boundaries Verity normally calls out across.

Parked here for the next PR (engine-layer tests, no DB). The classes are
written but not yet wired into a fixture — tests that use them will land
when we build out Layer 2.

The mock seams Verity already exposes:

  - LLM: ``ExecutionEngine`` accepts an empty ``anthropic_api_key``; tests
    can also overwrite ``engine.client`` with a ``FakeAnthropicClient``
    after construction to script Messages-API responses.

  - EDMS: ``register_provider("edms", FakeEdmsProvider())`` swaps out the
    real ``EdmsProvider`` (HTTP to the edms_service container) for an
    in-memory dict. Same interface; nothing else changes.

  - Tools: register an in-process Python tool implementation in test setup
    via ``engine.register_tool_implementation(name, func)``.

These three seams are enough to test most engine behavior without any
network or DB dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FakeAnthropicResponse:
    """Minimal stand-in for ``anthropic.types.Message``.

    Tests construct these to script what the engine sees from
    ``client.messages.create``. Add fields as the engine reads more of the
    response shape — keep this lean rather than mirroring the full SDK.
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: dict[str, int] = field(default_factory=lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
    })


class FakeAnthropicClient:
    """Records every Messages.create call and returns scripted responses.

    Usage:
        client = FakeAnthropicClient(responses=[FakeAnthropicResponse(...)])
        engine.client = client            # override after construction
        await engine.run_agent(...)
        assert len(client.calls) == 1
        assert client.calls[0]["model"] == "claude-sonnet-4-20250514"
    """

    def __init__(self, responses: list[FakeAnthropicResponse] | None = None):
        self.responses: list[FakeAnthropicResponse] = list(responses or [])
        self.calls: list[dict[str, Any]] = []

        # The engine calls ``self.client.messages.create(**kwargs)``; mirror
        # that nested-attribute shape with a tiny inner object.
        self.messages = _MessagesNamespace(self)


class _MessagesNamespace:
    """Implements the ``client.messages.create`` shape Anthropic SDK uses."""

    def __init__(self, parent: FakeAnthropicClient):
        self._parent = parent

    async def create(self, **kwargs: Any) -> FakeAnthropicResponse:
        self._parent.calls.append(kwargs)
        if not self._parent.responses:
            raise AssertionError(
                "FakeAnthropicClient: no scripted responses left, but the "
                "engine called messages.create. Add another response to the "
                "fixture, or assert call count earlier."
            )
        return self._parent.responses.pop(0)


class FakeEdmsProvider:
    """In-memory drop-in for the real ``EdmsProvider``.

    Stores documents as a dict ``{document_id: text}``. Tests prime the
    dict via ``provider.put(doc_id, text)`` and the engine reads via the
    same interface the real provider exposes (``get_document_text``).

    Add methods here as the connector contract grows — keep parity with
    the real provider so swapping is transparent.
    """

    def __init__(self) -> None:
        self._documents: dict[str, str] = {}
        self.calls: list[dict[str, Any]] = []

    def put(self, document_id: str, text: str) -> None:
        """Test-side helper to load a document before exercising code."""
        self._documents[document_id] = text

    async def get_document_text(self, document_id: str) -> str:
        self.calls.append({"method": "get_document_text", "id": document_id})
        if document_id not in self._documents:
            raise KeyError(
                f"FakeEdmsProvider: no document with id {document_id!r}. "
                f"Call provider.put({document_id!r}, '...') in test setup."
            )
        return self._documents[document_id]
