"""Pure-unit tests for ``TestRunner._compute_metrics`` and
``TestRunner._summarize_failure``.

These methods don't touch the DB or the engine — they're metric-math
helpers. Testing them at unit speed catches regressions in the metric
computation independently of any execution path.
"""

from __future__ import annotations


pytestmark = []   # no auto-applied markers; this file is unit-style


def _runner():
    """Build a TestRunner with stubbed deps — only the metric methods
    are exercised, so the registry/testing/engine references are
    irrelevant. Pass None and rely on the methods being self-contained.
    """
    from verity.runtime.test_runner import TestRunner
    return TestRunner(registry=None, execution_engine=None, testing=None)


# ── exact_match ────────────────────────────────────────────────────────────

def test_exact_match_passes_when_dicts_equal():
    r = _runner()
    result = r._compute_metrics(
        "exact_match",
        actual={"a": 1, "b": "x"},
        expected={"a": 1, "b": "x"},
    )
    assert result.get("matched") is True or result.get("passed") is True


def test_exact_match_fails_when_dicts_differ():
    r = _runner()
    result = r._compute_metrics(
        "exact_match",
        actual={"a": 1},
        expected={"a": 2},
    )
    # "passed" is the canonical key; some metrics also set "matched".
    assert result.get("passed", result.get("matched")) is False


# ── classification_f1 ──────────────────────────────────────────────────────

def test_classification_f1_passes_when_labels_match():
    r = _runner()
    result = r._compute_metrics(
        "classification_f1",
        actual={"document_type": "invoice"},
        expected={"document_type": "invoice"},
    )
    assert result["passed"] is True
    assert result["f1"] >= 0.5


def test_classification_f1_fails_when_labels_differ():
    r = _runner()
    result = r._compute_metrics(
        "classification_f1",
        actual={"document_type": "invoice"},
        expected={"document_type": "policy"},
    )
    assert result["passed"] is False


# ── _summarize_failure ─────────────────────────────────────────────────────

def test_summarize_failure_returns_string():
    """Whatever the metric_result shape, summarize must return a string
    so the test_execution_log row's failure_reason is human-readable."""
    r = _runner()
    summary = r._summarize_failure({"passed": False, "diff": "a:1 != a:2"})
    assert isinstance(summary, str)
    assert len(summary) > 0
