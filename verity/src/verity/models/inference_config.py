"""Inference configuration models."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel


class InferenceConfig(BaseModel):
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


class InferenceConfigCreate(BaseModel):
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


class InferenceConfigSnapshot(BaseModel):
    """Stored with every decision log — captures exact params at execution time."""
    config_name: str
    model_name: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    stop_sequences: Optional[list[str]] = None
    extended_params: dict[str, Any] = {}
