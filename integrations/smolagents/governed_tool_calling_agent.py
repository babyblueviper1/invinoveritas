"""
GovernedToolCallingAgent -- an invinoveritas /review gate composed onto smolagents'
ToolCallingAgent, wired at its real, public, currently-shipped extension seam.

WHY THIS EXISTS (verified against smolagents' current source, not assumed):

smolagents' `step_callbacks` only fire AFTER a step completes (post-hoc logging/monitoring),
and `final_answer_checks` only run once, before the whole task's final answer is accepted --
neither is a pre-execution gate on an individual tool call. A real, still-open library PR
(huggingface/smolagents#1959, fixing #1883) proposes exactly this as a new `PRE_EXECUTION`
lifecycle event, explicitly naming "Human-in-the-loop approval, custom code validation,
security checks" as its motivating use case -- but it's an unmerged draft (opened
2026-01-28, zero reviews as of 2026-08-05), so nothing ships against it today.

What DOES already exist, today, in the stable smolagents release: `ToolCallingAgent
.execute_tool_call(self, tool_name, arguments)` is a real, public, overridable method --
every JSON-tool-call step routes through it before the tool actually runs. That's a genuine
pre-execution seam, just not formalized as a named hook yet. This module is a reference
implementation composing an independent /review verdict onto exactly that seam: override,
call /review on the proposed (tool_name, arguments), then either let the real call proceed
or raise before it does.

HONEST SCOPE: this composes with `ToolCallingAgent` specifically. `CodeAgent` (smolagents'
other main agent class) executes LLM-generated Python code directly through an executor --
individual tool calls inside that code are function calls within the sandboxed script, not
routed through `execute_tool_call`, so there is no equivalent seam to wrap today. That's
exactly the gap PR #1959 is trying to close with a PRE_EXECUTION hook fired before the whole
code block runs; once that lands, this same composition pattern (call /review, raise-to-block
on a real reject) applies there too, one hook higher up.

Install: pip install invinoveritas smolagents
"""
from __future__ import annotations

from typing import Any

from smolagents import ToolCallingAgent

try:
    from invinoveritas import InvinoClient
except ImportError:
    InvinoClient = None  # type: ignore[assignment,misc]


class ReviewBlocked(Exception):
    """Raised when /review rejects a proposed tool call before it executes."""

    def __init__(self, tool_name: str, arguments: Any, reason: str):
        self.tool_name = tool_name
        self.arguments = arguments
        self.reason = reason
        super().__init__(f"invinoveritas /review blocked tool call '{tool_name}': {reason}")


class GovernedToolCallingAgent(ToolCallingAgent):
    """
    Drop-in ToolCallingAgent subclass: every tool call gets an independent /review verdict
    before it runs. Fail-open by default (matches every other invinoveritas integration) --
    a network error, timeout, or unfunded key lets the call proceed normally, since this is a
    second opinion, not a single point of failure for the whole agent.

    Usage:
        agent = GovernedToolCallingAgent(
            tools=[...], model=..., ivv_api_key="ivv_...",
            ivv_artifact_type="general", ivv_fail_closed=False,
        )
        agent.run("book a flight and charge the card on file")
    """

    def __init__(self, *args, ivv_api_key: str | None = None, ivv_artifact_type: str = "general",
                 ivv_fail_closed: bool = False, ivv_reject_confidence: float = 0.7, **kwargs):
        super().__init__(*args, **kwargs)
        if InvinoClient is None:
            raise RuntimeError("invinoveritas not installed -- pip install invinoveritas")
        self._ivv_client = InvinoClient(bearer_token=ivv_api_key)
        self._ivv_artifact_type = ivv_artifact_type
        self._ivv_fail_closed = ivv_fail_closed
        self._ivv_reject_confidence = ivv_reject_confidence

    def execute_tool_call(self, tool_name: str, arguments: dict[str, str] | str) -> Any:
        try:
            result = self._ivv_client.review(
                artifact=f"tool={tool_name} arguments={arguments!r}",
                artifact_type=self._ivv_artifact_type,
                context=f"smolagents ToolCallingAgent about to call tool '{tool_name}'.",
            )
        except Exception:
            # Fail-open by default -- a network error/timeout/unfunded key is not a verdict,
            # it's the gate being unavailable. Matches every other invinoveritas integration's
            # discipline: a second opinion is not a single point of failure for the whole agent.
            if self._ivv_fail_closed:
                raise
            return super().execute_tool_call(tool_name, arguments)

        if result.verdict == "reject" and result.confidence >= self._ivv_reject_confidence:
            raise ReviewBlocked(tool_name, arguments, result.summary)

        # approve, revise, or a low-confidence reject: proceed to the real tool call. "revise"
        # and low-confidence "reject" are not hard blocks -- surfacing them as a raised exception
        # for every borderline case would make this gate noisier than useful; only a confident
        # reject stops execution.
        return super().execute_tool_call(tool_name, arguments)
