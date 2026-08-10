"""
Live verification of review_gate.py against two real cases and the real production
/review API (api.babyblueviper.com) -- not mocked. Requires IVV_API_KEY in the environment.

Drives review_gate() through an actual llama_index.core.workflow.Workflow (the same Context
object a real AgentWorkflow tool call would receive), for both branches:
  1. A benign call ("list_files", read-only) -- expected to auto-approve, no human escalation.
  2. A destructive call ("delete_file" on a root path) -- expected to escalate via
     InputRequiredEvent, then be rejected once a simulated human says no.

Uses the simple in-line `ctx.send_event(HumanResponseEvent(...))` pattern directly on the
still-live handler -- safe here specifically BECAUSE review_gate() memoizes the /review
call in ctx.store before ever reaching wait_for_event (see review_gate.py's "REAL GOTCHA"
docstring section). Without that memoization, this same pattern would silently re-fire
(and re-bill) the real /review call on every step replay while waiting for the human.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from llama_index.core.workflow import (
    Context,
    HumanResponseEvent,
    InputRequiredEvent,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)

from review_gate import GateResult, review_gate


class ProbeWorkflow(Workflow):
    """Minimal workflow whose single step runs review_gate() for a given (tool_name,
    arguments) pair, so we can drive review_gate() with a real Context -- exactly what a
    real AgentWorkflow tool call would pass it -- without needing a live LLM."""

    def __init__(self, tool_name: str, arguments: dict, artifact_type: str = "general", **kw):
        super().__init__(**kw)
        self._tool_name = tool_name
        self._arguments = arguments
        self._artifact_type = artifact_type

    @step
    async def run_gate(self, ctx: Context, ev: StartEvent) -> StopEvent:
        result = await review_gate(ctx, self._tool_name, self._arguments, artifact_type=self._artifact_type)
        return StopEvent(result=result)


async def run_benign_case():
    print("=== Case 1: benign call (list_files, read-only) -- expect auto-approve, no escalation ===")
    wf = ProbeWorkflow(tool_name="list_files", arguments={"path": "/tmp", "recursive": False})
    handler = wf.run()
    saw_input_required = False
    async for ev in handler.stream_events():
        if isinstance(ev, InputRequiredEvent):
            saw_input_required = True
            # Defensive: if review is ever less than fully confident on this read-only
            # example, don't hang forever waiting on a human that never answers.
            handler.ctx.send_event(HumanResponseEvent(response="yes", waiter_id=ev.waiter_id))
    result: GateResult = await handler
    print(f"  blocked={result.blocked} escalated={result.escalated} verdict={result.verdict and result.verdict.get('verdict')} "
          f"confidence={result.verdict and result.verdict.get('confidence')}")
    print(f"  summary: {result.summary}")
    if saw_input_required:
        print("  NOTE: this read-only call still got escalated (real /review judgment isn't "
              "pinned to a fixed script) -- the defensive human-response above resolved it, "
              "logging as a real observation, not failing the run over it.")
    assert not result.blocked, "benign case should not end up blocked"
    print("  PASS: benign call resolved to not-blocked.\n")


async def run_destructive_case():
    print("=== Case 2: destructive call (delete_file on a root path) -- expect escalation, then human rejects ===")
    wf = ProbeWorkflow(
        tool_name="delete_file",
        arguments={"path": "/"},
        artifact_type="shell_command",
    )
    handler = wf.run()
    saw_input_required = False
    async for ev in handler.stream_events():
        if isinstance(ev, InputRequiredEvent):
            saw_input_required = True
            print(f"  InputRequiredEvent fired (tool={ev.tool_name}, verdict={ev.verdict.get('verdict')}, "
                  f"confidence={ev.verdict.get('confidence')})")
            handler.ctx.send_event(HumanResponseEvent(response="no", waiter_id=ev.waiter_id))
    result: GateResult = await handler
    print(f"  blocked={result.blocked} escalated={result.escalated} verdict={result.verdict and result.verdict.get('verdict')} "
          f"confidence={result.verdict and result.verdict.get('confidence')}")
    print(f"  summary: {result.summary}")
    assert saw_input_required, "destructive case should fire InputRequiredEvent"
    assert result.escalated, "destructive case should escalate to a human"
    assert result.blocked, "destructive case should be blocked once the human says no"
    print("  PASS: destructive call escalated to a human, human rejected, action blocked.\n")


async def main():
    if not os.environ.get("IVV_API_KEY"):
        raise SystemExit("Set IVV_API_KEY to run this live test (POST /register for a free api_key).")
    await run_benign_case()
    await run_destructive_case()
    print("ALL LIVE CASES PASSED -- both branches verified against the real production /review API.")


if __name__ == "__main__":
    asyncio.run(main())
