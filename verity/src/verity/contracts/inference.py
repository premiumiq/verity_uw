"""Inference configuration — the LLM parameter set carried across the boundary.

InferenceConfig is embedded in AgentConfig/TaskConfig when the governance
plane resolves a version; InferenceConfigSnapshot is what the runtime
copies into every decision log so the exact params used can be audited
even if the config is later modified.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class InferenceConfig(BaseModel):
    """A named, reusable LLM parameter set."""
    id: UUID
    name: str
    description: str
    intended_use: str
    model_name: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    extended_params: dict[str, Any] = {}
    active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class InferenceConfigSnapshot(BaseModel):
    """Stored with every decision log — captures exact params at execution time.

    This is a frozen copy of the parameters used for one particular execution.
    If the InferenceConfig is later updated, this snapshot still reflects what
    actually ran, which is essential for audit and replay.
    """
    config_name: str
    model_name: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    extended_params: dict[str, Any] = {}
