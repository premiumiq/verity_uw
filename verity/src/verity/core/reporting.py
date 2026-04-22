"""Reporting — re-export shim.

The Reporting class now lives at verity.governance.reporting. This module
re-exports it so existing `from verity.core.reporting import Reporting`
imports keep working during the registry/runtime split.
"""

from verity.governance.reporting import Reporting  # noqa: F401

__all__ = ["Reporting"]
