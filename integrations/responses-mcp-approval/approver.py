"""
approver.py -- an independent approver for MCP tool approvals in the Responses API.

The OpenAI Responses API, and servers that implement it (OGX, the Open GenAI Stack formerly Llama Stack, and others),
let you mark a remote MCP server `require_approval: "always"` (or a filter). Before such a tool runs, the response
stops with an output item

    {"type": "mcp_approval_request", "id": "mcpr_...", "server_label": "...", "name": "<tool>", "arguments": "<json>"}

and waits for the client to send back

    {"type": "mcp_approval_response", "approval_request_id": "mcpr_...", "approve": true | false}

with `previous_response_id` set. The approver is usually a human clicking a button, or code that says yes.

This module answers each request with a signed invinoveritas /review verdict instead. The verdict binds the exact call
(`action_binding`: tool = "<server_label>/<name>", the parsed arguments, your agent id), so the signed proof says
which call was approved, not just that something was. `approve` is true only when the verdict is in `proceed_on`.
Every decision keeps the proof, which anyone can check for free at POST /verify-proof or offline against the
published key.

    from openai import OpenAI
    from approver import run_with_approvals

    client = OpenAI()                     # or OpenAI(base_url="http://localhost:8321/v1") for OGX
    final, decisions = run_with_approvals(
        client,
        model="gpt-4.1",
        tools=[{"type": "mcp", "server_label": "payments", "server_url": "https://...", "require_approval": "always"}],
        input="Refund order 1042",
        agent_id="refund-agent-prod",
    )
    for d in decisions:
        print(d.name, d.approve, d.verdict, d.proof_event_id)

If /review cannot be reached or returns no usable verdict, the default is to REJECT (`on_unavailable="reject"`).
That differs from our other integrations, which fail open: a tool marked require_approval was gated on purpose, so
silently approving it when the approver is down defeats the gate. Pass `on_unavailable="approve"` to fail open, or a
`human` callback to hand the decision to a person.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

import httpx

logger = logging.getLogger("invinoveritas.responses_mcp_approval")

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
DEFAULT_TIMEOUT_S = 60.0
DEFAULT_PROCEED_ON = ("approve", "approve_with_concerns")
VERDICTS = ("approve", "approve_with_concerns", "reject")


@dataclass
class Decision:
    approval_request_id: str
    server_label: str
    name: str
    arguments: Any
    approve: bool
    verdict: Optional[str]                 # None when /review gave no verdict
    source: str                            # "review", "human", or "unavailable:<policy>"
    reason: str
    proof_event_id: Optional[str] = None
    proof: Optional[dict] = None           # the signed event; POST it to /verify-proof
    call_bound: Optional[bool] = None      # the proof binds this tool name and these args (needs rfc8785)
    review: Optional[dict] = field(default=None, repr=False)

    def response_item(self, include_reason: bool = False) -> dict:
        item = {"type": "mcp_approval_response", "approval_request_id": self.approval_request_id, "approve": self.approve}
        if include_reason:                 # OGX accepts `reason`; leave it off for servers that reject unknown fields
            item["reason"] = self.reason[:500]
        return item


def _get(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def approval_requests(response: Any) -> list[Any]:
    """The mcp_approval_request items in a Responses API response (SDK object or plain dict)."""
    return [it for it in (_get(response, "output") or []) if _get(it, "type") == "mcp_approval_request"]


def _parse_args(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


def _call_bound(proof_event: Optional[dict], tool: str, args: Any) -> Optional[bool]:
    """Check the signed verdict binds THIS call: action_binding_tool_hash = "sha256:" + sha256(tool, UTF-8) and
    action_binding_args_hash = "sha256:" + sha256(RFC 8785 JCS(args)). None if rfc8785 is not installed."""
    if not proof_event or not isinstance(args, dict):
        return None
    try:
        import rfc8785
    except ImportError:
        return None
    try:
        c = json.loads(proof_event.get("content") or "{}")
    except (TypeError, ValueError):
        return False
    want_args = "sha256:" + hashlib.sha256(rfc8785.dumps(args)).hexdigest()
    want_tool = "sha256:" + hashlib.sha256(tool.encode("utf-8")).hexdigest()
    return c.get("action_binding_args_hash") == want_args and c.get("action_binding_tool_hash") == want_tool


def review_request(
    req: Any,
    *,
    agent_id: str,
    api_key: Optional[str] = None,
    base_url: str = DEFAULT_BASE_URL,
    proceed_on: Iterable[str] = DEFAULT_PROCEED_ON,
    artifact_type: str = "general",
    context: Optional[str] = None,
    on_unavailable: str = "reject",
    human: Optional[Callable[[Any, Optional[dict]], bool]] = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    http: Optional[httpx.Client] = None,
) -> Decision:
    """Decide one mcp_approval_request with a signed /review verdict."""
    if on_unavailable not in ("reject", "approve"):
        raise ValueError("on_unavailable must be 'reject' or 'approve'")
    proceed_on = tuple(proceed_on)
    rid, label, name = str(_get(req, "id")), str(_get(req, "server_label")), str(_get(req, "name"))
    args = _parse_args(_get(req, "arguments"))
    key = api_key or os.environ.get("IVV_API_KEY", "")
    body = {
        "artifact": json.dumps({"server_label": label, "tool": name, "arguments": args}, sort_keys=True, default=str),
        "artifact_type": artifact_type,
        "context": context or f"Responses API MCP approval request: {label}/{name}",
        "sign": True,
        "action_binding": {"tool": f"{label}/{name}", "agent_id": agent_id,
                           "args": args if isinstance(args, dict) else {"_raw": args}},
    }
    data: Optional[dict] = None
    problem = ""
    if not key:
        problem = "no api key (IVV_API_KEY)"
    else:
        try:
            client = http or httpx.Client(timeout=timeout_s)
            try:
                r = client.post(f"{base_url.rstrip('/')}/review", json=body,
                                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            finally:
                if http is None:
                    client.close()
            r.raise_for_status()
            data = r.json()
            if _get(data, "verdict") not in VERDICTS:
                problem, data = f"no usable verdict in the /review response: {str(data)[:200]}", None
        except (httpx.HTTPError, ValueError) as e:
            problem = f"/review unavailable: {type(e).__name__}: {e}"[:300]

    if data is None:
        if human is not None:
            ok = bool(human(req, None))
            return Decision(rid, label, name, args, ok, None, "human", f"human decided ({problem})")
        ok = on_unavailable == "approve"
        logger.warning("no verdict for %s/%s, %s per on_unavailable=%r: %s", label, name,
                       "approving" if ok else "rejecting", on_unavailable, problem)
        return Decision(rid, label, name, args, ok, None, f"unavailable:{on_unavailable}", problem)

    verdict = data["verdict"]
    proof = (data.get("proof") or {}).get("event") if isinstance(data.get("proof"), dict) else None
    approve = verdict in proceed_on
    source = "review"
    reason = f"invinoveritas verdict {verdict}" + (f" (proof {proof.get('id')})" if proof else "")
    if not approve and human is not None:
        approve, source = bool(human(req, data)), "human"
        reason += "; a human decided after the verdict"
    return Decision(rid, label, name, args, approve, verdict, source, reason,
                    proof_event_id=(proof or {}).get("id"), proof=proof,
                    call_bound=_call_bound(proof, f"{label}/{name}", args if isinstance(args, dict) else {"_raw": args}),
                    review=data)


def decide_all(response: Any, **kw) -> list[Decision]:
    """Decide every mcp_approval_request in a response."""
    return [review_request(r, **kw) for r in approval_requests(response)]


def run_with_approvals(client: Any, *, agent_id: str, max_rounds: int = 8, include_reason: bool = False,
                       review_kwargs: Optional[dict] = None, **create_kwargs) -> tuple[Any, list[Decision]]:
    """Call client.responses.create(**create_kwargs), answer every approval request with a verdict, and continue
    (previous_response_id) until the response has none left. Returns (final response, all decisions)."""
    rk = dict(review_kwargs or {}, agent_id=agent_id)
    resp = client.responses.create(**create_kwargs)
    decisions: list[Decision] = []
    for _ in range(max_rounds):
        reqs = approval_requests(resp)
        if not reqs:
            return resp, decisions
        round_ = [review_request(r, **rk) for r in reqs]
        decisions += round_
        follow = {k: v for k, v in create_kwargs.items() if k not in ("input", "previous_response_id")}
        resp = client.responses.create(previous_response_id=_get(resp, "id"),
                                       input=[d.response_item(include_reason) for d in round_], **follow)
    raise RuntimeError(f"still asking for approval after {max_rounds} rounds")
