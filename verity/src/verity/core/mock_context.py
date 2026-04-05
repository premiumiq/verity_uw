"""MockContext — Controls what gets mocked during execution.

DESIGN PRINCIPLE:
    Two independent dimensions, each independently controllable:

    1. LLM CALLS:  Either all mocked (skip Claude) or all live.
    2. TOOL CALLS:  Any combination mocked by name. Dict-keyed, not
                    position-keyed. Works for N tools in any order,
                    called any number of times.

    These dimensions are orthogonal:
    - All LLM mocked + all tools live      → test tool implementations
    - All LLM live   + specific tools mock  → test prompts with controlled data
    - All LLM mocked + all tools mocked     → pipeline testing, demo, UI dev
    - All LLM live   + all tools live       → production (mock=None)
    - Replay from prior execution           → audit, regression

    When a MockContext is provided, the caller has EXPLICIT CONTROL.
    DB-level mock flags (tool.mock_mode_enabled) are IGNORED — only
    the MockContext's settings matter. DB flags only apply as defaults
    when no MockContext is passed (mock=None).

USAGE:

    # Skip Claude entirely, return pre-built final output
    mock = MockContext(llm_responses=[{"risk_score": "Green"}])

    # Real Claude, mock specific tools (any number, by name)
    mock = MockContext(tool_responses={
        "store_triage_result": {"stored": True},
        "update_submission_event": {"event_id": "123"},
        # Tools NOT listed here run live
    })

    # Real Claude, ALL tools mocked from DB-registered responses
    mock = MockContext(mock_all_tools=True)

    # Replay a prior execution exactly
    mock = MockContext.from_decision_log(prior_decision)

    # Production — everything live
    result = await verity.execute_agent("triage_agent", context)

TOOL MOCKING IS BY NAME, NOT BY POSITION:
    Whether the agent calls 2 tools or 20, in any order, the dict
    catches each by name. If the same tool is called multiple times,
    provide a list of responses — consumed in order per tool.

    mock = MockContext(tool_responses={
        "get_submission_context": {"account": "Acme"},  # called once
        "get_guidelines": [                              # called twice
            {"text": "Section 2.1..."},                  # first call
            {"text": "Section 4.3..."},                  # second call
        ],
    })

HOW MOCKS ARE PREPARED:

    Source 1: DB-registered (tool.mock_responses JSONB)
        → Developer creates realistic mock data during seeding
        → Used when tool.mock_mode_enabled=True

    Source 2: Prior execution replay (MockContext.from_decision_log)
        → Verity automatically stores message_history + tool_calls_made
        → Replay reconstructs the exact sequence

    Source 3: Test cases (test_case.expected_output)
        → Test author defines expected behavior
        → Test runner builds MockContext from expected_output

    Source 4: Runtime (passed as parameter)
        → Calling code constructs MockContext with specific responses
        → Used for ad hoc testing
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class MockContext:
    """Controls what gets mocked during an execution.

    Passed as an optional parameter to execute_agent(), execute_task(),
    execute_pipeline(), or run_tool(). When None (the default),
    everything runs live.
    """

    # ── LLM MOCK ──────────────────────────────────────────────
    # If set, each LLM call returns the next response from this list
    # instead of calling Claude.
    #
    # For single-turn tasks: one entry (the final output).
    # For multi-turn agents:
    #   - Simple mode: one entry (final answer) → loop ends immediately
    #   - Replay mode: multiple entries matching the original turn sequence
    #
    # Each entry is a dict. If it contains a "type": "tool_use" key,
    # the execution engine treats it as Claude requesting a tool call.
    # Otherwise, it's treated as a final text/JSON response.
    llm_responses: Optional[list[dict[str, Any]]] = None

    # ── TOOL MOCK ─────────────────────────────────────────────
    # Per-tool mock responses. Key = tool name, value = response dict.
    # Tools NOT in this dict make real calls (unless mock_all_tools=True
    # or the tool's DB flag mock_mode_enabled=True).
    #
    # For multi-call scenarios (same tool called twice), the value can
    # be a list — each call consumes the next response in order.
    tool_responses: Optional[dict[str, Any]] = None

    # If True, ALL tools return their DB-registered mock responses
    # (from tool.mock_responses JSONB column).
    # Individual entries in tool_responses override this.
    mock_all_tools: bool = False

    # ── SUB-AGENT MOCK (future) ───────────────────────────────
    # Per-sub-agent MockContexts. Key = agent name.
    # When an agent delegates to a sub-agent, the sub-agent's
    # execution uses this MockContext instead of the parent's.
    sub_agent_mocks: Optional[dict[str, "MockContext"]] = None

    # ── INTERNAL STATE (managed by the gateway) ───────────────
    # Tracks which LLM response to return next (auto-incremented)
    _llm_call_index: int = field(default=0, repr=False)
    # Tracks per-tool call counts for list-based tool_responses
    _tool_call_counts: dict[str, int] = field(default_factory=dict, repr=False)

    @property
    def has_llm_mock(self) -> bool:
        """True if LLM calls should be mocked."""
        return self.llm_responses is not None and len(self.llm_responses) > 0

    @property
    def is_simple_mock(self) -> bool:
        """True if this is a simple 'skip LLM, return final output' mock.

        Simple mock = one LLM response that is NOT a tool_use request.
        The agentic loop should end immediately.
        """
        if not self.has_llm_mock:
            return False
        if len(self.llm_responses) == 1:
            first = self.llm_responses[0]
            # If it doesn't look like a tool_use, it's a final answer
            return not _is_tool_use_response(first)
        return False

    def get_next_llm_response(self) -> Optional[dict]:
        """Get the next mock LLM response (auto-advances the index).

        Returns None if no more mock responses available (fall through to real call).
        """
        if not self.has_llm_mock:
            return None
        if self._llm_call_index >= len(self.llm_responses):
            return None
        response = self.llm_responses[self._llm_call_index]
        self._llm_call_index += 1
        return response

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

    def get_sub_agent_mock(self, agent_name: str) -> Optional["MockContext"]:
        """Get the MockContext for a sub-agent invocation."""
        if self.sub_agent_mocks and agent_name in self.sub_agent_mocks:
            return self.sub_agent_mocks[agent_name]
        return None

    @classmethod
    def from_decision_log(cls, decision, mock_llm: bool = True, mock_tools: bool = True) -> "MockContext":
        """Build a MockContext from a prior execution's stored data.

        Args:
            decision: A DecisionLogDetail with message_history and tool_calls_made.
            mock_llm: If True, mock LLM calls using stored responses.
                      If False, LLM runs live (Claude called for real).
            mock_tools: If True, mock tool calls using stored responses.
                        If False, tools run live (real implementations called).

        Common patterns:
            # Full replay (audit reproducibility proof)
            mock = MockContext.from_decision_log(prior)

            # Audit re-test: live LLM with old tool data
            # "Does the current prompt produce the same result with the same inputs?"
            mock = MockContext.from_decision_log(prior, mock_llm=False, mock_tools=True)

            # Test new tool implementation with original LLM behavior
            mock = MockContext.from_decision_log(prior, mock_llm=True, mock_tools=False)
        """
        # Build LLM responses from message_history if available
        llm_responses = None
        if mock_llm:
            if hasattr(decision, 'message_history') and decision.message_history:
                llm_responses = [
                    msg.get("content", {})
                    for msg in decision.message_history
                    if msg.get("role") == "assistant"
                ]
            elif hasattr(decision, 'output_json') and decision.output_json:
                llm_responses = [decision.output_json]

        # Build tool responses from tool_calls_made
        tool_responses = None
        if mock_tools:
            if hasattr(decision, 'tool_calls_made') and decision.tool_calls_made:
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

        return cls(
            llm_responses=llm_responses,
            tool_responses=tool_responses,
        )


def _is_tool_use_response(response: dict) -> bool:
    """Check if a mock LLM response represents a tool_use request."""
    if isinstance(response, dict):
        return response.get("type") == "tool_use"
    if isinstance(response, list):
        return any(
            isinstance(block, dict) and block.get("type") == "tool_use"
            for block in response
        )
    return False
