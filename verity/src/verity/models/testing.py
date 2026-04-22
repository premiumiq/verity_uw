"""Testing and validation models.

TestSuite, TestCase, TestExecutionResult, and ValidationRun were all
moved to verity.contracts.testing as of Phase 1 of the Registry/Runtime
split — they cross the governance↔runtime boundary (governance owns the
suites/cases/dataset definitions; the runtime produces the results).

This file now exists only as a backward-compat shim. Any existing code
that did `from verity.models.testing import TestSuite` keeps working and
resolves to the class object defined in verity.contracts.testing.
"""

# Re-export all boundary models from contracts for backward compatibility.
from verity.contracts.testing import (  # noqa: F401
    TestCase,
    TestExecutionResult,
    TestSuite,
    ValidationRun,
)
