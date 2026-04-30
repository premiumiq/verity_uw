"""Unit tests for ``verity.models.tool``."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from verity.models.tool import Tool


def _make_tool_kwargs(**overrides):
    base = {
        "id": uuid.uuid4(),
        "name": "lookup_policy",
        "display_name": "Lookup Policy",
        "description": "Reads a policy by id.",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "implementation_path": "uw_demo.tools.lookup_policy",
    }
    base.update(overrides)
    return base


def test_tool_defaults():
    tool = Tool(**_make_tool_kwargs())
    assert tool.transport == "python_inprocess"
    assert tool.mock_mode_enabled is True
    assert tool.is_write_operation is False
    assert tool.requires_confirmation is False
    assert tool.tags == []
    assert tool.active is True
    assert tool.data_classification_max == "tier3_confidential"


def test_tool_mcp_transport_uses_server_name():
    tool = Tool(**_make_tool_kwargs(
        transport="mcp_stdio",
        mcp_server_name="duckduckgo",
        mcp_tool_name="search",
    ))
    assert tool.transport == "mcp_stdio"
    assert tool.mcp_server_name == "duckduckgo"
    assert tool.mcp_tool_name == "search"


def test_tool_requires_implementation_path():
    kwargs = _make_tool_kwargs()
    del kwargs["implementation_path"]
    with pytest.raises(ValidationError):
        Tool(**kwargs)


def test_tool_requires_input_and_output_schema():
    for missing in ("input_schema", "output_schema"):
        kwargs = _make_tool_kwargs()
        del kwargs[missing]
        with pytest.raises(ValidationError):
            Tool(**kwargs)


def test_tool_round_trip():
    tool = Tool(**_make_tool_kwargs(
        is_write_operation=True,
        requires_confirmation=True,
        tags=["external", "search"],
    ))
    assert Tool.model_validate(tool.model_dump()) == tool
