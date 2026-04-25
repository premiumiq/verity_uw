# Error Recovery — Retry, Backoff, Fallback Configs

> **Status:** planned (not built); generalises ad-hoc handling that exists today
> **Source:** [archive/future_capabilities.md FC-4](../archive/future_capabilities.md), [vision.md § Runtime plane (status: Coming)](../vision.md)
> **Priority:** medium — important for production reliability, not blocking demo

## What's missing today

Failures in the agent loop (rate limits, overloaded responses, transient timeouts) are logged into `execution_run_error` but not retried. Each failure surfaces immediately to the caller. There is no exponential backoff, no jitter, no fallback to a cheaper / different model.

## Proposed approach

Retry policy is **declarative and governed**, expressed in `inference_config.extended_params`:

```json
{
    "retry": {
        "max_attempts": 3,
        "backoff_ms": [1000, 2000, 4000],
        "jitter_pct": 25,
        "retry_on": ["rate_limit", "overloaded", "timeout", "5xx"]
    },
    "fallback_inference_config_id": "<uuid of cheaper/different config>"
}
```

The Execution Engine's call wrapper:

1. Tries the LLM call
2. On a retryable error, sleeps `backoff_ms[attempt] * (1 ± jitter_pct/100)` and retries
3. After `max_attempts`, if a `fallback_inference_config_id` is set, switches to that config and retries from attempt 1 (with its own retry policy)
4. After all attempts exhausted, writes `execution_run_error` and propagates

Each retry attempt is its own `model_invocation_log` row (so cost is correctly attributed even when retries fail). The decision_log row records the final outcome and a count of retries in `risk_factors`.

## Acceptance criteria

- `inference_config.extended_params` parsed for retry block at admit time (validation)
- Retry loop in `runtime/engine.py`
- Fallback config switch works and is logged
- Existing tests pass; new tests cover rate-limit-then-success and rate-limit-then-fallback scenarios

## Notes

Do **not** put retry logic in tools — that's where teams stash imperative escape hatches. Retry belongs in the LLM call wrapper, governed via `inference_config`. Tool-level retries are the tool implementation's business and not Verity's concern.
