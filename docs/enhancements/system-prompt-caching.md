# Anthropic System Prompt Caching

> **Status:** partial — prompt-cache token tracking shipped; cache_control hint not yet emitted
> **Source:** [archive/future_capabilities.md FC-7](../archive/future_capabilities.md)
> **Priority:** medium — direct cost and latency reduction for long system prompts

## What's missing today

The decision_log already separates input tokens into "cache reads" vs "cache creates" vs "regular" — the bookkeeping is in place. What's missing is the upstream change: the runtime doesn't pass `cache_control` hints to the Anthropic API, so the cache is never populated. As a result, the cache-read counters stay at zero.

## Proposed approach

In `runtime/engine.py`'s `_build_api_params`:

1. If the assembled system prompt exceeds a threshold (configurable, default 1000 tokens), wrap it as a content block with `cache_control`:

```python
params["system"] = [
    {
        "type": "text",
        "text": system_prompt,
        "cache_control": {"type": "ephemeral"},
    }
]
```

2. Same treatment for the tool list when it's large (> 1000 tokens worth of tool descriptions).

3. The threshold is global; per-entity opt-out lives on `inference_config.extended_params.disable_prompt_cache = true` for the rare case it hurts.

## Acceptance criteria

- System prompts above threshold sent with `cache_control`
- Tool lists above threshold sent with `cache_control`
- Cache-read counters in `model_invocation_log` are non-zero on the second-and-subsequent identical calls
- Cost view subtracts cached input tokens from billed-input tokens correctly

## Notes

Anthropic's cache TTL is short (5 minutes for ephemeral). Best ROI is on agents that get repeated invocations within that window — exactly the demo loop. Confirm against current Anthropic docs at implementation time; pricing and TTL evolve.
