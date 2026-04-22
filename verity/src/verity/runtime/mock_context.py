"""MockContext — runtime convenience re-export.

The concrete MockContext class lives in verity.contracts.mock — it's a
boundary model shared between the governance and runtime planes. This
module re-exports it so runtime-side code can do `from verity.runtime.mock_context
import MockContext` when that reads more naturally than reaching into contracts.
"""

from verity.contracts.mock import MockContext  # noqa: F401

__all__ = ["MockContext"]
