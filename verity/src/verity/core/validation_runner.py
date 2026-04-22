"""Validation runner — re-export shim.

The ValidationRunner (and RecordResult, ValidationResult dataclasses) now
live at verity.runtime.validation_runner. This module re-exports them so
existing `from verity.core.validation_runner import ValidationRunner`
imports keep working during the registry/runtime split.
"""

from verity.runtime.validation_runner import (  # noqa: F401
    RecordResult,
    ValidationResult,
    ValidationRunner,
)

__all__ = ["ValidationRunner", "ValidationResult", "RecordResult"]
