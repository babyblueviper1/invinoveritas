"""Offline tests for approver.py: a mocked /review and a fake Responses client. No network.

    python3 -m pytest -q integrations/responses-mcp-approval/test_approver.py
"""
import hashlib
import json
import os
import sys

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import approver as A  # noqa: E402

REQ = {"type": "mcp_approval_request", "id": "mcpr_1", "server_label": "payments", "name": "refund",
       "arguments": json.dumps({"order_id": "1042", "amount": "25.00"})}


def jcs_hash(args):
    rfc8785 = pytest.importorskip("rfc8785")
    return "sha256:" + hashlib.sha256(rfc8785.dumps(args)).hexdigest()


def tool_hash(tool):
    return "sha256:" + hashlib.sha256(tool.encode("utf-8")).hexdigest()


def review_http(verdict="approve", bind_args=None, status=200, body=None, seen=None):
    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        if seen is not None:
            seen.append(sent)
        if body is not None:
            return httpx.Response(status, json=body)
        args = sent["action_binding"]["args"] if bind_args is None else bind_args
        content = {"verdict": verdict, "action_binding_args_hash": jcs_hash(args) if _has_rfc() else "",
                   "action_binding_tool_hash": tool_hash(sent["action_binding"]["tool"])}
        return httpx.Response(status, json={"verdict": verdict, "proof": {"event": {"id": "ev_" + verdict, "content": json.dumps(content)}}})
    return httpx.Client(transport=httpx.MockTransport(handler))


def _has_rfc():
    try:
        import rfc8785  # noqa: F401
        return True
    except ImportError:
        return False


def decide(**kw):
    kw.setdefault("api_key", "k")
    kw.setdefault("agent_id", "refund-agent")
    return A.review_request(REQ, **kw)


def test_approve_binds_the_exact_call():
    seen = []
    d = decide(http=review_http("approve", seen=seen))
    assert d.approve and d.verdict == "approve" and d.source == "review" and d.proof_event_id == "ev_approve"
    sent = seen[0]
    assert sent["sign"] is True
    assert sent["action_binding"] == {"tool": "payments/refund", "agent_id": "refund-agent", "args": {"order_id": "1042", "amount": "25.00"}}
    assert d.response_item() == {"type": "mcp_approval_response", "approval_request_id": "mcpr_1", "approve": True}


def test_reject_answers_false():
    d = decide(http=review_http("reject"))
    assert d.approve is False and d.verdict == "reject"


def test_proceed_on_is_respected():
    d = decide(http=review_http("approve_with_concerns"), proceed_on=("approve",))
    assert d.approve is False and d.verdict == "approve_with_concerns"


def test_unavailable_rejects_by_default():
    d = decide(http=review_http(status=503, body={"detail": "down"}))
    assert d.approve is False and d.verdict is None and d.source == "unavailable:reject"


def test_unavailable_can_fail_open():
    d = decide(http=review_http(status=200, body={"something": "else"}), on_unavailable="approve")
    assert d.approve is True and d.source == "unavailable:approve"


def test_no_key_never_calls_review():
    calls = []
    d = A.review_request(REQ, agent_id="a", api_key="", http=review_http(seen=calls))
    assert d.approve is False and calls == [] and "no api key" in d.reason


def test_human_decides_when_verdict_does_not_allow():
    asked = []
    d = decide(http=review_http("reject"), human=lambda req, review: asked.append(review["verdict"]) or True)
    assert d.approve is True and d.source == "human" and asked == ["reject"]


def test_call_bound_detects_a_verdict_for_other_arguments():
    pytest.importorskip("rfc8785")
    assert decide(http=review_http("approve")).call_bound is True
    other = decide(http=review_http("approve", bind_args={"order_id": "9999", "amount": "25.00"}))
    assert other.call_bound is False


def test_call_bound_matches_the_live_proof_format():
    """Pinned from a real /review proof (2026-10-12): prefixes and hash construction match the server."""
    pytest.importorskip("rfc8785")
    args = {"order_id": "1042", "amount": "25.00", "currency": "USD", "reason": "item arrived damaged, photo attached"}
    live = {"content": json.dumps({
        "action_binding_args_hash": "sha256:8252acfebaf56960b514100b000d9da79746a0f2d947823e30b076b2be296d01",
        "action_binding_tool_hash": "sha256:d072709f8bda302e6c9898387f5a7fc5734af9d1df0ebd1caa4a39f538a334cb"})}
    assert A._call_bound(live, "payments/refund", args) is True
    assert A._call_bound(live, "payments/refund", dict(args, amount="2500.00")) is False
    assert A._call_bound(live, "payments/wire_transfer", args) is False


def test_include_reason_is_opt_in():
    d = decide(http=review_http("approve"))
    assert "reason" not in d.response_item()
    assert d.response_item(include_reason=True)["reason"].startswith("invinoveritas verdict approve")


class FakeResponses:
    """Two rounds of approval requests, then a final message."""
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        if n == 1:
            return {"id": "resp_1", "output": [dict(REQ)]}
        if n == 2:
            return {"id": "resp_2", "output": [dict(REQ, id="mcpr_2", name="lookup_payment", arguments="{}")]}
        return {"id": "resp_3", "output": [{"type": "message", "content": "done"}]}


class FakeClient:
    def __init__(self):
        self.responses = FakeResponses()


def test_run_with_approvals_continues_until_no_requests(monkeypatch):
    http = review_http("approve")
    client = FakeClient()
    final, decisions = A.run_with_approvals(client, agent_id="a", model="m", tools=[{"type": "mcp"}], input="go",
                                            review_kwargs={"api_key": "k", "http": http})
    assert final["id"] == "resp_3" and [d.approval_request_id for d in decisions] == ["mcpr_1", "mcpr_2"]
    second = client.responses.calls[1]
    assert second["previous_response_id"] == "resp_1" and second["model"] == "m" and second["tools"] == [{"type": "mcp"}]
    assert second["input"] == [{"type": "mcp_approval_response", "approval_request_id": "mcpr_1", "approve": True}]


def test_run_with_approvals_stops_after_max_rounds():
    class Loop(FakeResponses):
        def create(self, **kw):
            self.calls.append(kw)
            return {"id": f"r{len(self.calls)}", "output": [dict(REQ)]}
    c = FakeClient()
    c.responses = Loop()
    with pytest.raises(RuntimeError):
        A.run_with_approvals(c, agent_id="a", max_rounds=2, model="m", input="x",
                             review_kwargs={"api_key": "k", "http": review_http("approve")})


def test_sdk_style_objects_are_accepted():
    class Item:
        type, id, server_label, name, arguments = "mcp_approval_request", "mcpr_9", "s", "t", "{}"
    class Resp:
        output = [Item()]
    assert [r.id for r in A.approval_requests(Resp())] == ["mcpr_9"]
