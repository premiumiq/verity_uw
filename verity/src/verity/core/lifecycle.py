"""Lifecycle — re-export shim.

The Lifecycle class now lives at verity.governance.lifecycle. This module
re-exports it so existing `from verity.core.lifecycle import Lifecycle`
imports keep working during the registry/runtime split.
"""

from verity.governance.lifecycle import Lifecycle  # noqa: F401

__all__ = ["Lifecycle"]
