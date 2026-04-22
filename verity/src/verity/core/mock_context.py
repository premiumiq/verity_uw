"""MockContext — re-export shim.

The concrete MockContext class lives in verity.contracts.mock. This
module re-exports it so existing `from verity.core.mock_context import
MockContext` imports keep working during the registry/runtime split.
"""

from verity.contracts.mock import MockContext, _is_tool_use_response  # noqa: F401

__all__ = ["MockContext"]
