"""Metrics — re-export shim.

The Verity metrics engine now lives at verity.runtime.metrics. This module
re-exports the public functions so existing `from verity.core.metrics import ...`
imports keep working during the registry/runtime split.
"""

from verity.runtime.metrics import (  # noqa: F401
    check_thresholds,
    classification_metrics,
    exact_match,
    field_accuracy,
    schema_valid,
)

__all__ = [
    "check_thresholds",
    "classification_metrics",
    "exact_match",
    "field_accuracy",
    "schema_valid",
]
