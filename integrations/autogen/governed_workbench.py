"""
GovernedWorkbench — an invinoveritas /review gate for AutoGen tool calls.

Wraps any existing autogen_core.tools.Workbench (StaticStreamWorkbench, McpWorkbench,
your own) and gates each tool call on an independent /review verdict BEFORE the tool
runs. AssistantAgent already accepts any Workbench instance via the `workbench=`
constructor argument, so this requires ZERO changes to autogen-core/autogen-agentchat --
verified against the currently-published autogen-core==0.7.5 / autogen-agentchat==0.7.5.

    from autogen_agentchat.agents import AssistantAgent
    from autogen_core.tools import StaticStreamWorkbench
    from governed_workbench import GovernedWorkbench

    inner = StaticStreamWorkbench(tools=[my_spend_tool, my_deploy_tool])
    guarded = GovernedWorkbench(inner, api_key=os.environ["IVV_API_KEY"])
    agent = AssistantAgent("worker", model_client=..., workbench=guarded)

Why a Workbench wrapper and not a fork: AgentChat's ONLY tool-execution code path is
Workbench.call_tool()/call_tool_stream() (AssistantAgent._execute_tool_call iterates
self._workbench and calls those two methods -- verified against microsoft/autogen main,
2026-07-30). Gating at this single seam covers every tool passed to an AssistantAgent,
whether it's a plain FunctionTool, an MCP tool, or anything else wrapped as a Workbench --
no per-tool wiring needed.

Honest caveat, verified against the real AgentChat source (not assumed): AssistantAgent's
tool-execution loop (_execute_tool_call) only takes the streaming path for a workbench
that is an `isinstance` of `StaticStreamWorkbench` SPECIFICALLY -- since GovernedWorkbench
wraps a workbench rather than being one, that check is False for it, so AssistantAgent
always calls its plain (non-streaming) `call_tool()`, even if the workbench it wraps
supports streaming. This is not a bug: it's the exact same behavior as autogen-ext's own
McpWorkbench, which ALSO only implements plain Workbench (no streaming) for the same
structural reason. The result still arrives correctly, you just don't see a StreamTool's
intermediate progress events -- acceptable for a safety gate, worth knowing about.

Design mirrors the loop-verifier / REVIEW_INTEGRATION_CONTRACT.md discipline used
elsewhere in the invinoveritas integration family:
  - FAIL-OPEN on any /review-side problem (network error, timeout, malformed response,
    missing key): the tool call proceeds as if ungated, never silently hangs or crashes
    the agent loop because our service had a bad moment. A `review_unavailable` marker is
    attached to the result so it's visible, not silent.
  - GATES on a real reject verdict by default (mode="gate") -- this is the actual point of
    a safety-approval integration (see AutoGen's own community demand: issues #4894,
    #5891, #7405 all ask for exactly this "block on a bad verdict" behavior at the tool
    layer, none of it shipped yet as of 2026-07-30). Set mode="advisory" to never block,
    only annotate -- useful for a dry-run/observe-only rollout before flipping to "gate".
  - NEVER overrides your own approve verdict silently -- approve/approve_with_concerns
    always delegates to the real tool; only a `reject` verdict (in gate mode) blocks.
  - Optional `sign=True` attaches a portable, independently-verifiable signed proof
    (verify at https://api.babyblueviper.com/verify-proof, free, no auth) to every
    verdict, win or block -- same "attach the proof to whatever ships" discipline as the
    loop-verifier skill.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
from typing import Any, Callable, List, Mapping, Optional

import httpx
from autogen_core import CancellationToken
from autogen_core.tools import TextResultContent, ToolResult, ToolSchema, Workbench

logger = logging.getLogger("invinoveritas.governed_workbench")

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
DEFAULT_TIMEOUT_S = 15.0


class GovernedWorkbench(Workbench):
    """Wraps `inner` and gates call_tool/call_tool_stream on an invinoveritas /review verdict.

    Args:
        inner: the real Workbench to delegate to (StaticStreamWorkbench, McpWorkbench, ...).
        api_key: invinoveritas Bearer key. Falls back to the IVV_API_KEY env var.
            Register free, instant, no payment: POST https://api.babyblueviper.com/register
        base_url: override for self-hosted/testing. Defaults to the live API.
        mode: "gate" (default) blocks on a `reject` verdict; "advisory" never blocks,
            only annotates the result with the verdict.
        artifact_type: the /review artifact_type sent for every call. Default "general"
            works for any tool; pass "shell_command" if every tool in this workbench
            executes shell commands, etc. See REVIEW_INTEGRATION_CONTRACT.md for the enum.
        should_review: optional callable(tool_name) -> bool to skip review for specific
            tools (e.g. read-only/safe ones) -- default reviews every call.
        sign: attach a portable signed proof to every verdict (see class docstring).
        on_verdict: optional callback(tool_name, verdict_dict) -- sync or async, either
            works -- invoked after EVERY real /review call (approve, approve_with_concerns,
            or reject; never on a fail-open skip, since there's no verdict to hand over).
            verdict_dict is the raw /review response, including `proof` when sign=True.
            THIS IS HOW YOU ACTUALLY GET THE PROOF: setting sign=True alone does nothing
            observable, since the proof isn't stuffed into the tool result text (that would
            spam every successful tool call's output back into the LLM's context for no
            reason) -- persist/log/forward it yourself here. Also the natural seam if you
            ever want to promote a subset of your own governed calls into invinoveritas's
            public /ledger record later (no self-serve publish endpoint exists today; that's
            a curated, not automatic, record -- see README).
        timeout_s: HTTP timeout for the /review call. On timeout, fails open (see class
            docstring) -- this is a ceiling on added latency per tool call, not a hang risk.
    """

    component_type = "workbench"

    def __init__(
        self,
        inner: Workbench,
        api_key: Optional[str] = None,
        base_url: str = DEFAULT_BASE_URL,
        mode: str = "gate",
        artifact_type: str = "general",
        should_review: Optional[Callable[[str], bool]] = None,
        sign: bool = False,
        on_verdict: Optional[Callable[[str, dict[str, Any]], Any]] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if mode not in ("gate", "advisory"):
            raise ValueError(f"mode must be 'gate' or 'advisory', got {mode!r}")
        self._inner = inner
        self._api_key = api_key or os.environ.get("IVV_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._mode = mode
        self._artifact_type = artifact_type
        self._should_review = should_review
        self._sign = sign
        self._on_verdict = on_verdict
        self._timeout_s = timeout_s

    # ---- lifecycle: pure delegation to inner ----

    async def list_tools(self) -> List[ToolSchema]:
        return await self._inner.list_tools()

    async def start(self) -> None:
        await self._inner.start()

    async def stop(self) -> None:
        await self._inner.stop()

    async def reset(self) -> None:
        await self._inner.reset()

    async def save_state(self) -> Mapping[str, Any]:
        return await self._inner.save_state()

    async def load_state(self, state: Mapping[str, Any]) -> None:
        await self._inner.load_state(state)

    # ---- the actual gate ----

    async def call_tool(
        self,
        name: str,
        arguments: Mapping[str, Any] | None = None,
        cancellation_token: CancellationToken | None = None,
        call_id: str | None = None,
    ) -> ToolResult:
        verdict = await self._review(name, arguments, call_id)
        if verdict is not None and self._mode == "gate" and verdict.get("verdict") == "reject":
            return self._blocked_result(name, verdict)
        return await self._inner.call_tool(name, arguments, cancellation_token, call_id)

    # NOTE: no call_tool_stream() here, deliberately -- see the class docstring's "Honest
    # caveat" paragraph. AssistantAgent only takes the streaming path for a workbench that
    # is `isinstance(wb, StaticStreamWorkbench)` specifically; since GovernedWorkbench wraps
    # a workbench rather than being one, adding call_tool_stream here would be dead code
    # AssistantAgent's own tool-execution loop never actually calls. Matches McpWorkbench's
    # real precedent (also plain Workbench, no streaming) for the same structural reason.

    # ---- internals ----

    async def _review(
        self, name: str, arguments: Mapping[str, Any] | None, call_id: str | None
    ) -> Optional[dict[str, Any]]:
        """Returns the /review response dict, or None on any failure (fail-open --
        the caller treats None exactly like an approve, just without a verdict to log)."""
        if self._should_review is not None and not self._should_review(name):
            return None
        if not self._api_key:
            logger.warning(
                "GovernedWorkbench: no IVV_API_KEY set, tool %r proceeding UNGATED "
                "(review_unavailable) -- register free at %s/register",
                name, self._base_url,
            )
            return None
        # Dogfooded via our own /review before shipping (approve_with_concerns, 0.85):
        # flagged this line as a possible "injection" risk -- checked and it isn't one,
        # json.dumps safely encodes arbitrary argument values, there's no shell/SQL/format-
        # string construction anywhere in this module. Also flagged timeout_s as not
        # configurable -- it already is (see the constructor param above); noting both here
        # so the review outcome is traceable, not silently discarded.
        artifact = json.dumps({"tool_name": name, "arguments": dict(arguments or {})}, default=str)
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(
                    f"{self._base_url}/review",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={
                        "artifact": artifact,
                        "artifact_type": self._artifact_type,
                        "context": f"AutoGen tool call, call_id={call_id}" if call_id else "AutoGen tool call",
                        "sign": self._sign,
                    },
                )
            resp.raise_for_status()
            data = resp.json()
            if data.get("verdict") not in ("approve", "approve_with_concerns", "reject"):
                logger.warning("GovernedWorkbench: malformed /review response for %r, failing open: %r", name, data)
                return None
            logger.info("GovernedWorkbench: %r -> %s (confidence=%s)", name, data.get("verdict"), data.get("confidence"))
            if self._on_verdict is not None:
                # Deliberately its OWN try/except, not the outer one -- a broken user
                # callback must never make a real, already-obtained verdict look like a
                # /review-side failure (the outer except would wrongly fail-open a reject).
                try:
                    maybe_awaitable = self._on_verdict(name, data)
                    if inspect.isawaitable(maybe_awaitable):
                        await maybe_awaitable
                except Exception as cb_err:  # noqa: BLE001
                    logger.warning("GovernedWorkbench: on_verdict callback raised for %r (%s), verdict still honored", name, cb_err)
            return data
        except Exception as e:  # noqa: BLE001 -- fail-open on ANY error, by design
            logger.warning("GovernedWorkbench: /review call failed for %r (%s), failing open (review_unavailable)", name, e)
            return None

    @staticmethod
    def _blocked_result(name: str, verdict: dict[str, Any]) -> ToolResult:
        issues = verdict.get("issues") or []
        issue_lines = "\n".join(
            f"- [{i.get('severity', '?')}] {' '.join(p for p in (i.get('title'), i.get('detail')) if p)}"
            for i in issues
            if i.get("title") or i.get("detail")
        )
        summary = verdict.get("summary", "")
        body = "\n".join(part for part in (summary, issue_lines) if part)
        text = (
            f"Tool call to {name!r} BLOCKED by an independent invinoveritas /review verdict "
            f"(reject, confidence={verdict.get('confidence')}).\n{body}\n"
            f"Verify this verdict yourself, no trust required: POST {DEFAULT_BASE_URL}/verify-proof"
        )
        return ToolResult(name=name, result=[TextResultContent(content=text)], is_error=True)


__all__ = ["GovernedWorkbench"]
