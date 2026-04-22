"""Verity client — re-export shim.

The Verity consumer facade was moved to verity.client.inprocess as part
of Phase 2d of the registry/runtime split. Internally, Verity now holds
a GovernanceCoordinator (verity.governance.coordinator) and a Runtime
(verity.runtime.runtime) instead of directly instantiating each module.

This shim exists so existing code that did `from verity.core.client
import Verity` keeps working. The top-level `from verity import Verity`
path also continues to work because verity/__init__.py re-exports from
here. Both paths migrate to `from verity.client.inprocess import Verity`
in Phase 2e.
"""

from verity.client.inprocess import Verity  # noqa: F401

__all__ = ["Verity"]
