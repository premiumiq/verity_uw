"""Testing — re-export shim.

The Testing class now lives at verity.governance.testing_meta (renamed
from "testing" to avoid colliding with the verity.contracts.testing and
verity.models.testing modules, which hold the Pydantic result shapes).

This module re-exports Testing so existing
`from verity.core.testing import Testing` imports keep working during
the registry/runtime split.
"""

from verity.governance.testing_meta import Testing  # noqa: F401

__all__ = ["Testing"]
