"""Registry — re-export shim.

The Registry class now lives at verity.governance.registry. This module
re-exports it so existing `from verity.core.registry import Registry`
imports keep working during the registry/runtime split.
"""

from verity.governance.registry import Registry  # noqa: F401

__all__ = ["Registry"]
