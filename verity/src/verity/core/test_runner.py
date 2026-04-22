"""Test runner — re-export shim.

The TestRunner (and CaseResult, SuiteResult dataclasses) now live at
verity.runtime.test_runner. This module re-exports them so existing
`from verity.core.test_runner import TestRunner` imports keep working
during the registry/runtime split.
"""

from verity.runtime.test_runner import CaseResult, SuiteResult, TestRunner  # noqa: F401

__all__ = ["TestRunner", "SuiteResult", "CaseResult"]
