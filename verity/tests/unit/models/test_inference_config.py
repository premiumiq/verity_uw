"""Unit tests for ``verity.models.inference_config``.

The boundary models (``InferenceConfig``, ``InferenceConfigSnapshot``)
were moved to ``verity.contracts.inference``. ``InferenceConfigCreate``
is the governance-internal write shape and stays in models.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from verity.models.inference_config import InferenceConfigCreate


def test_inference_config_create_minimal():
    cfg = InferenceConfigCreate(
        name="default",
        description="Default Verity config.",
        intended_use="General agent runs.",
    )
    # Defaults — model name is the current production Sonnet, tuning
    # params are None (Anthropic uses its defaults).
    assert cfg.model_name == "claude-sonnet-4-20250514"
    assert cfg.temperature is None
    assert cfg.max_tokens is None
    assert cfg.top_p is None
    assert cfg.top_k is None
    assert cfg.stop_sequences is None
    assert cfg.extended_params == {}


def test_inference_config_create_overrides():
    cfg = InferenceConfigCreate(
        name="strict",
        description="Strict greedy config.",
        intended_use="Determinism-critical extraction.",
        temperature=0.0,
        max_tokens=2048,
        stop_sequences=["</answer>"],
        extended_params={"thinking": {"type": "enabled", "budget_tokens": 1024}},
    )
    assert cfg.temperature == 0.0
    assert cfg.max_tokens == 2048
    assert cfg.stop_sequences == ["</answer>"]
    assert cfg.extended_params["thinking"]["type"] == "enabled"


def test_inference_config_create_requires_intended_use():
    # `intended_use` is the regulatory-traceable rationale for the config.
    # Skipping it would create configs with no documented purpose.
    with pytest.raises(ValidationError):
        InferenceConfigCreate(
            name="x",
            description="...",
            # intended_use missing
        )
