"""MockContext — re-export shim.

The concrete MockContext class was moved to verity.contracts.mock as of
Phase 1 of the Registry/Runtime split. It is re-exported here so existing
code like `from verity.core.mock_context import MockContext` keeps working
and resolves to the same class object.
"""

from verity.contracts.mock import MockContext, _is_tool_use_response  # noqa: F401

__all__ = ["MockContext"]
