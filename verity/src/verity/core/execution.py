"""Execution engine — re-export shim.

The execution engine (ExecutionEngine class) now lives at verity.runtime.engine.
Result types (ExecutionResult, ExecutionEvent, ExecutionEventType) live in
verity.contracts.decision.

This module re-exports them so existing code like
`from verity.core.execution import ExecutionEngine, ExecutionResult` keeps
working during the registry/runtime split.
"""

from verity.contracts.decision import (  # noqa: F401
    ExecutionEvent,
    ExecutionEventType,
    ExecutionResult,
)
from verity.runtime.engine import ExecutionEngine  # noqa: F401

__all__ = [
    "ExecutionEngine",
    "ExecutionEvent",
    "ExecutionEventType",
    "ExecutionResult",
]
