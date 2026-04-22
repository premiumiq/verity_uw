"""Inference configuration models.

InferenceConfig and InferenceConfigSnapshot were moved to
verity.contracts.inference as of Phase 1 of the Registry/Runtime split.
They are re-exported here for backward compatibility.

What stays here (governance-internal):
- InferenceConfigCreate — the write-path input used by register_inference_config().
"""

from typing import Any, Optional

from pydantic import BaseModel

# Re-export boundary models from contracts for backward compatibility.
from verity.contracts.inference import InferenceConfig, InferenceConfigSnapshot  # noqa: F401


class InferenceConfigCreate(BaseModel):
    """Input to register_inference_config() — the create shape, no id/timestamps."""
    name: str
    description: str
    intended_use: str
    model_name: str = "claude-sonnet-4-20250514"
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    extended_params: dict[str, Any] = {}
