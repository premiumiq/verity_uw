"""In-memory fakes for the boundaries Verity normally calls out across.

The mock seams Verity exposes for testing:

  - LLM: ``ExecutionEngine`` accepts an empty ``anthropic_api_key``;
    tests construct the engine that way and then overwrite
    ``engine.client`` with a ``FakeAnthropicClient`` to script
    Messages-API responses.
  - EDMS: ``register_provider("edms", FakeEdmsProvider())`` swaps out
    the real ``EdmsProvider`` (HTTP to the edms_service container) for
    an in-memory dict. Same interface; nothing else changes.
  - Tools: register an in-process Python tool implementation in test
    setup via ``engine.register_tool_implementation(name, func)``.

These three seams are enough to test most engine behavior without any
network or DB dependency. The DB itself is real (per-test cloned
template DB) so we exercise the actual SQL and write paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ── Anthropic Messages-API shape ───────────────────────────────────────────
#
# The engine reads attribute paths on the response object:
#   response.content (iterable of blocks)
#   response.stop_reason (str)
#   response.usage.input_tokens / .output_tokens / .cache_*_tokens
#
# Each content block is either a TextBlock or a ToolUseBlock with its own
# attributes (.type, .text for text; .id, .name, .input for tool_use).
# Plain dicts won't work — we need real attribute access, so dataclasses.

@dataclass
class FakeUsage:
    """Mirrors ``anthropic.types.Usage`` — only the fields the engine reads."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass
class FakeTextBlock:
    """Mirrors ``anthropic.types.TextBlock``."""
    text: str
    type: str = "text"


@dataclass
class FakeToolUseBlock:
    """Mirrors ``anthropic.types.ToolUseBlock``."""
    id: str
    name: str
    input: dict[str, Any]
    type: str = "tool_use"


@dataclass
class FakeAnthropicResponse:
    """Stand-in for ``anthropic.types.Message``.

    Construct these to script what the engine sees from
    ``client.messages.create``. Helper functions below cover the common
    shapes (text-only response, tool-use response).
    """
    content: list[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: FakeUsage = field(default_factory=FakeUsage)


def text_response(
    text: str,
    *,
    input_tokens: int = 100,
    output_tokens: int = 50,
    stop_reason: str = "end_turn",
) -> FakeAnthropicResponse:
    """Helper: a single-turn text response from Claude."""
    return FakeAnthropicResponse(
        content=[FakeTextBlock(text=text)],
        stop_reason=stop_reason,
        usage=FakeUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def tool_use_response(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tool_use_id: str = "toolu_test_001",
    leading_text: str | None = None,
    input_tokens: int = 100,
    output_tokens: int = 50,
) -> FakeAnthropicResponse:
    """Helper: a turn that requests a tool call.

    If ``leading_text`` is provided, prepends a TextBlock — Claude often
    explains what it's about to do before the tool_use block.
    """
    blocks: list[Any] = []
    if leading_text:
        blocks.append(FakeTextBlock(text=leading_text))
    blocks.append(FakeToolUseBlock(id=tool_use_id, name=tool_name, input=tool_input))
    return FakeAnthropicResponse(
        content=blocks,
        stop_reason="tool_use",
        usage=FakeUsage(input_tokens=input_tokens, output_tokens=output_tokens),
    )


# ── Anthropic client ───────────────────────────────────────────────────────

class FakeAnthropicClient:
    """Records every messages.create call and returns scripted responses.

    Usage:

        client = FakeAnthropicClient(responses=[text_response("hi")])
        engine.client = client                    # override after construction
        result = await engine.run_agent(...)
        assert len(client.calls) == 1
        assert client.calls[0]["model"] == "claude-sonnet-4-20250514"

    Multi-turn: pass a list of responses; each ``messages.create`` pops
    the next one. Running out raises AssertionError to surface
    underscripted tests early.
    """

    def __init__(self, responses: list[FakeAnthropicResponse] | None = None):
        self.responses: list[FakeAnthropicResponse] = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        # The engine calls ``self.client.messages.create(**kwargs)``;
        # mirror that nested-attribute shape with a tiny inner object.
        self.messages = _MessagesNamespace(self)

    def script(self, *responses: FakeAnthropicResponse) -> None:
        """Append more scripted responses (variadic for readability)."""
        self.responses.extend(responses)


class _MessagesNamespace:
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


# ── EDMS provider ──────────────────────────────────────────────────────────

class FakeEdmsProvider:
    """In-memory drop-in for the real ``EdmsProvider``.

    Stores documents as a dict ``{document_id: text}``. Tests prime the
    dict via ``provider.put(doc_id, text)`` and the engine reads via the
    same interface the real provider exposes.
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
