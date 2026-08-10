"""
review_gate.py -- an invinoveritas /review gate for LlamaIndex tool functions.

Wraps a LlamaIndex agent tool's real action behind an independent /review verdict, using
the framework's own documented human-in-the-loop event pair -- InputRequiredEvent /
HumanResponseEvent (llama_index.core.workflow). Verified directly against
llama-index-core==0.14.23's actual `call_tool` step (agent/workflow/base_agent.py): it goes
straight from receiving a ToolCall event to invoking the tool, no pre-execution hook exists
anywhere in the framework itself. The one documented extension point for gating a specific
tool call is inside the tool function, via ctx.wait_for_event(HumanResponseEvent,
waiter_event=InputRequiredEvent(...)) -- see run-llama/llama_index#18636 and
docs/understanding/agent/human_in_the_loop/. Every existing example (including the
maintainer's own) wires this to a REAL waiting human, unconditionally, for every gated call.

What this module adds: the SAME event pair, but a human is only actually asked when an
independent /review verdict is uncertain or negative. A clean, high-confidence approve
resolves automatically -- no human in the loop for the common case. This mirrors the
"escalate only when needed" composition already shipped for AgentScope's
on_check_permission middleware and Qwen-Agent's PythonExecutor confirm_callback.

REAL GOTCHA, found by direct testing, not assumed: llama-index-core's workflow engine
REPLAYS a step from the top every time `ctx.wait_for_event(...)` is checked against a new
incoming event (confirmed directly -- a step containing only an in-memory
`wait_for_event` call, no network I/O at all, was still entered twice for a single human
response: once to register the wait, once more when the response arrived). This means any
side effect that runs BEFORE `wait_for_event` in the same step -- like a real, billed
`/review` call -- gets RE-EXECUTED on every replay unless it's memoized. This module
memoizes the /review response in `ctx.store` (keyed by tool_name + a hash of the
arguments) BEFORE ever reaching `wait_for_event`, so the real network call fires exactly
once no matter how many times the framework replays the step while waiting on a human.
Skipping this memoization is the single most likely way to accidentally double- (or
triple-, or more-) bill a single logical tool call when adapting this pattern elsewhere.
A related, non-deterministic-waiter_id variant of this same replay issue is fixed here too
(waiter_id derives from the same stable cache key, not a fresh uuid4() per entry). Both
filed upstream: run-llama/llama_index#22559.

    from llama_index.core.workflow import Context
    from review_gate import review_gate

    async def delete_file(ctx: Context, path: str) -> str:
        \"\"\"Delete a file at the given path.\"\"\"
        result = await review_gate(ctx, tool_name="delete_file", arguments={"path": path},
                                    artifact_type="shell_command")
        if result.blocked:
            return f"BLOCKED: {result.summary}"
        # ... real deletion logic
        return f"Deleted {path}"

Fail-open discipline matches every other invinoveritas integration: any /review-side
problem (network error, timeout, malformed response, missing key) proceeds as if approved,
never silently hangs or blocks a tool call because our service had a bad moment.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx
from llama_index.core.workflow import Context, HumanResponseEvent, InputRequiredEvent

logger = logging.getLogger("invinoveritas.llamaindex.review_gate")

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
DEFAULT_TIMEOUT_S = 15.0
DEFAULT_APPROVE_CONFIDENCE = 0.9


@dataclass
class GateResult:
    blocked: bool
    verdict: Optional[dict[str, Any]]
    escalated: bool  # True if a human was actually asked
    summary: str


async def review_gate(
    ctx: Context,
    tool_name: str,
    arguments: Mapping[str, Any],
    artifact_type: str = "general",
    api_key: Optional[str] = None,
    base_url: str = DEFAULT_BASE_URL,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    approve_confidence: float = DEFAULT_APPROVE_CONFIDENCE,
    human_wait_timeout: Optional[float] = 2000,
) -> GateResult:
    """Call /review for (tool_name, arguments). Auto-approves on a clean, high-confidence
    verdict; otherwise escalates to a real human via InputRequiredEvent/HumanResponseEvent,
    the same event pair LlamaIndex's own docs use for human-in-the-loop tool gating.

    MEMOIZED via ctx.store BEFORE the network call -- see the module docstring's "REAL
    GOTCHA" section. Without this, a replay triggered by wait_for_event would re-fire the
    real /review call (and re-bill it) every time the step is re-entered while waiting."""
    key = api_key or os.environ.get("IVV_API_KEY", "")
    artifact = json.dumps({"tool_name": tool_name, "arguments": dict(arguments)}, default=str, sort_keys=True)
    cache_key = f"_invinoveritas_review_gate::{tool_name}::{hash(artifact)}"
    verdict: Optional[dict[str, Any]] = await ctx.store.get(cache_key, default=None)
    if verdict is None:
        if key:
            try:
                async with httpx.AsyncClient(timeout=timeout_s) as client:
                    resp = await client.post(
                        f"{base_url.rstrip('/')}/review",
                        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                        json={
                            "artifact": artifact,
                            "artifact_type": artifact_type,
                            "context": f"LlamaIndex tool call: {tool_name}",
                        },
                    )
                resp.raise_for_status()
                data = resp.json()
                if data.get("verdict") in ("approve", "approve_with_concerns", "reject"):
                    verdict = data
                    await ctx.store.set(cache_key, verdict)
                else:
                    logger.warning("review_gate: malformed /review response for %r, failing open: %r", tool_name, data)
            except Exception as e:  # noqa: BLE001 -- fail-open on ANY error, by design
                logger.warning("review_gate: /review call failed for %r (%s), failing open", tool_name, e)
        else:
            logger.warning(
                "review_gate: no IVV_API_KEY set, tool %r proceeding UNGATED (review_unavailable) "
                "-- register free at %s/register", tool_name, base_url,
            )

    if verdict is not None and verdict.get("verdict") == "approve" and verdict.get("confidence", 0) >= approve_confidence:
        return GateResult(
            blocked=False, verdict=verdict, escalated=False,
            summary=f"auto-approved (confidence={verdict.get('confidence')})",
        )

    if verdict is None:
        # fail-open: no verdict to escalate on, proceed same as an approve.
        return GateResult(blocked=False, verdict=None, escalated=False, summary="review_unavailable, proceeding ungated")

    # Uncertain or reject verdict: escalate to a real human, the documented pattern.
    # waiter_id MUST be deterministic across replays -- a fresh uuid4() here would change
    # on every replay triggered by wait_for_event (see the module's "REAL GOTCHA" section),
    # so a response matched against the FIRST waiter_id would never match the SECOND one
    # the replay generates, hanging forever. Reusing cache_key (already stable per logical
    # call) as the waiter_id fixes this the same way memoization fixed the double-billing.
    waiter_id = cache_key
    prefix = (
        f"invinoveritas /review flagged {tool_name!r} ({verdict.get('verdict')}, "
        f"confidence={verdict.get('confidence')}): {verdict.get('summary', '')}\n"
        f"Arguments: {json.dumps(dict(arguments), default=str)}\n"
        "Approve this action anyway? (yes/no)"
    )
    response = await ctx.wait_for_event(
        HumanResponseEvent,
        waiter_id=waiter_id,
        waiter_event=InputRequiredEvent(prefix=prefix, tool_name=tool_name, verdict=verdict, waiter_id=waiter_id),
        requirements={"waiter_id": waiter_id},
        timeout=human_wait_timeout,
    )
    approved = str(getattr(response, "response", "")).strip().lower() in ("yes", "y", "approve", "approved")
    return GateResult(
        blocked=not approved,
        verdict=verdict,
        escalated=True,
        summary=f"human {'approved' if approved else 'rejected'} after a {verdict.get('verdict')} /review verdict",
    )


__all__ = ["review_gate", "GateResult"]
