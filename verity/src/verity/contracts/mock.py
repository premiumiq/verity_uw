"""MockContext — caller-supplied mock control for an execution.

MockContext is constructed by the caller (UW app, test runner, validation
runner) and passed into the runtime's run_* methods. It controls every
flavour of mocking the runtime supports — from "skip the LLM call
entirely and use this canned answer" down to "fake just this one tool's
output."

What MockContext covers:
  - step_responses   — per-step / per-entity canned answers. When set,
                       the engine skips Claude AND skips source resolution
                       AND skips target writes for matching runs — the
                       supplied dict IS the structured output. Keyed by
                       step_name first (workflow steps), then entity_name
                       as fallback. This is how UW's mock-mode demo runs
                       complete instantly without burning Anthropic
                       tokens.
  - tool_responses   — per-tool canned outputs, keyed by tool name. Tools
                       NOT in this dict make real calls (unless
                       mock_all_tools=True or the tool's DB
                       mock_mode_enabled flag is set). Used during real
                       LLM runs to control specific tool outputs.
  - mock_all_tools   — when True, ALL tools return their DB-registered
                       `mock_responses` entry (one per tool). Specific
                       entries in `tool_responses` still override.
  - source_responses — per-source canned payloads, keyed by the Task's
                       declared input field name. When a Task has a
                       declared source whose input field matches, the
                       connector fetch is skipped and this payload is
                       bound to the mapped template variable.
  - target_blocks    — set of target names whose declared writes should
                       be suppressed (logged but not executed). Used by
                       test and validation runners to prevent side
                       effects.
  - sub_agent_mocks  — per-sub-agent MockContexts (for FC-1 sub-agent
                       delegation when that ships).

USAGE:

    # Real Claude, mock specific tools (any number, by name)
    mock = MockContext(tool_responses={
        "store_triage_result": {"stored": True},
        "update_submission_event": {"event_id": "123"},
        # Tools NOT listed here run live
    })

    # Real Claude, ALL tools mocked from DB-registered responses
    mock = MockContext(mock_all_tools=True)

    # Partial replay from a prior execution — tool outputs only
    # (LLM-level replay retired; use audit_rerun for governance narrative)
    mock = MockContext.from_decision_log(prior_decision)

    # Production — everything live
    result = await verity.execute_agent("triage_agent", context)

When a MockContext is provided, the caller has EXPLICIT CONTROL over
which tools are mocked. DB-level mock flags (tool.mock_mode_enabled)
are ignored in this mode — caller decides everything. DB flags only
apply as defaults when `mock=None`.

Kept as @dataclass (not BaseModel) to keep the current behavior exactly.
Will be promoted to BaseModel if we ever need HTTP serialization of
mock contexts across the wire.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MockContext:
    """Controls tool-level mocking during an execution.

    Passed as an optional parameter to run_agent(), run_task(), or
    run_tool(). When None (the default), tools fall back to their
    DB-registered `mock_mode_enabled` flag, which defaults to off for
    production tools.
    """

    # ── STEP / ENTITY MOCK ────────────────────────────────────
    # Per-run canned answers — the heaviest form of mocking. When the
    # engine finds a match here it skips Claude entirely AND skips
    # source resolution AND skips target writes. The matching value
    # IS the structured output the run returns.
    #
    # Lookup order: step_name first (set when called from a multi-step
    # workflow), then entity_name as a fallback. A non-empty match on
    # either key is honored. Decision_log row is still written; the
    # mock_mode flag flips to True. Tokens / duration are zero.
    step_responses: Optional[dict[str, Any]] = None

    # ── TOOL MOCK ─────────────────────────────────────────────
    # Per-tool mock responses. Key = tool name, value = response dict.
    # Tools NOT in this dict make real calls (unless mock_all_tools=True
    # or the tool's DB flag mock_mode_enabled=True). Only meaningful on
    # real LLM runs — step_responses bypasses tool dispatch entirely.
    #
    # For multi-call scenarios (same tool called twice), the value can
    # be a list — each call consumes the next response in order.
    tool_responses: Optional[dict[str, Any]] = None

    # If True, ALL tools return their DB-registered mock responses
    # (from tool.mock_responses JSONB column).
    # Individual entries in tool_responses override this.
    mock_all_tools: bool = False

    # ── TASK SOURCE MOCK ──────────────────────────────────────
    # Per-source canned payloads. Key = input_field_name declared on
    # task_version_source. When the execution engine is resolving a
    # Task's declared sources, it checks this dict first — if the
    # input_field_name is present, the payload is bound to the mapped
    # template variable and the connector fetch is skipped entirely.
    source_responses: Optional[dict[str, Any]] = None

    # ── TASK TARGET BLOCK ─────────────────────────────────────
    # Set of output_field_names whose declared target writes should be
    # suppressed (logged but not executed). Used by test/validation
    # runners to prevent real writes during non-production execution.
    # When None, the channel/write_mode gate alone controls writes.
    target_blocks: Optional[set[str]] = None

    # ── SUB-AGENT MOCK (FC-1 groundwork) ──────────────────────
    # Per-sub-agent MockContexts. Key = agent name.
    # When an agent delegates to a sub-agent, the sub-agent's
    # execution uses this MockContext instead of the parent's.
    sub_agent_mocks: Optional[dict[str, "MockContext"]] = None

    # ── INTERNAL STATE (managed by the gateway) ───────────────
    # Tracks per-tool call counts for list-based tool_responses.
    _tool_call_counts: dict[str, int] = field(default_factory=dict, repr=False)

    def get_tool_response(self, tool_name: str) -> Optional[dict]:
        """Get mock response for a specific tool.

        Returns None if this tool should make a real call.
        Handles both single responses and lists (for multi-call scenarios).
        """
        if self.tool_responses is None:
            return None
        if tool_name not in self.tool_responses:
            return None

        response = self.tool_responses[tool_name]

        # If the response is a list, consume them in order
        if isinstance(response, list):
            count = self._tool_call_counts.get(tool_name, 0)
            if count < len(response):
                self._tool_call_counts[tool_name] = count + 1
                return response[count]
            return None  # Exhausted mock responses for this tool

        return response

    def get_source_response(self, input_field_name: str) -> tuple[bool, Any]:
        """Check for a source mock for the given input field name.

        Returns a (is_mocked, payload) tuple — the boolean is needed to
        distinguish "no mock registered" from "mock registered with value None".
        Callers that get is_mocked=True should skip the connector fetch and
        use the payload verbatim.
        """
        if self.source_responses is None or input_field_name not in self.source_responses:
            return (False, None)
        return (True, self.source_responses[input_field_name])

    def is_target_blocked(self, output_field_name: str) -> bool:
        """True if the declared target write for this output field should be suppressed."""
        if self.target_blocks is None:
            return False
        return output_field_name in self.target_blocks

    def get_step_response(
        self, step_name: Optional[str], entity_name: str,
    ) -> tuple[bool, Any]:
        """Look up a per-run canned answer.

        Returns (is_mocked, response). is_mocked=True signals that the
        engine should skip Claude / sources / targets and use `response`
        as the structured output verbatim.

        Lookup order: step_name first when supplied (workflows pass it
        per step), then entity_name. The two-tier lookup lets a workflow
        pin a specific step's output without affecting other invocations
        of the same entity.
        """
        if not self.step_responses:
            return (False, None)
        if step_name and step_name in self.step_responses:
            return (True, self.step_responses[step_name])
        if entity_name in self.step_responses:
            return (True, self.step_responses[entity_name])
        return (False, None)

    def get_sub_agent_mock(self, agent_name: str) -> Optional["MockContext"]:
        """Get the MockContext for a sub-agent invocation."""
        if self.sub_agent_mocks and agent_name in self.sub_agent_mocks:
            return self.sub_agent_mocks[agent_name]
        return None

    @classmethod
    def from_decision_log(cls, decision) -> "MockContext":
        """Build a tool-only MockContext from a prior execution's stored tool calls.

        Rebuilds `tool_responses` from the decision's `tool_calls_made`,
        keyed by tool name. If the same tool was called multiple times,
        the responses are ordered in a list.

        Previously this method also rebuilt LLM responses from the stored
        message_history. That capability was retired along with
        `MockContext.llm_responses`. For deterministic no-LLM replay of a
        prior decision, build a MockContext with `step_responses` keyed
        by the entity name and the decision's `output_json` as the value.
        """
        tool_responses: Optional[dict] = None
        if hasattr(decision, "tool_calls_made") and decision.tool_calls_made:
            tool_responses = {}
            for tc in decision.tool_calls_made:
                name = tc.get("tool_name", "")
                output = tc.get("output_data", {})
                if name in tool_responses:
                    existing = tool_responses[name]
                    if isinstance(existing, list):
                        existing.append(output)
                    else:
                        tool_responses[name] = [existing, output]
                else:
                    tool_responses[name] = output

        return cls(tool_responses=tool_responses)
