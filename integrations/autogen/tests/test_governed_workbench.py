"""Offline unit tests for GovernedWorkbench -- deterministic, no network calls, no
funded account required (uses httpx.MockTransport, no extra test dependency beyond
httpx itself, which GovernedWorkbench already requires).

Live behavior against the real API is separately exercised in tests/dogfood_live.py
(requires a real IVV_API_KEY, not run in CI).
"""
import json
import os
import sys

import httpx
import pytest
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool, StaticStreamWorkbench

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from governed_workbench import GovernedWorkbench  # noqa: E402


def add(a: int, b: int) -> int:
    return a + b


def _workbench():
    return StaticStreamWorkbench(tools=[FunctionTool(add, description="add two numbers")])


def _mock_client(verdict: str, status_code: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        if status_code != 200:
            return httpx.Response(status_code, json={"detail": "error"})
        return httpx.Response(
            200,
            json={
                "status": "success", "type": "structured_review", "verdict": verdict,
                "confidence": 0.9, "summary": "test verdict", "issues": [],
            },
        )
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def _patch_httpx(monkeypatch):
    """Point GovernedWorkbench's internal AsyncClient at a MockTransport instead of the network."""
    _transport_holder: dict[str, httpx.MockTransport] = {}

    def set_transport(transport: httpx.MockTransport) -> None:
        _transport_holder["t"] = transport

    real_client = httpx.AsyncClient

    class PatchedClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _transport_holder.get("t")
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)
    yield set_transport


@pytest.mark.asyncio
async def test_approve_delegates_to_inner(_patch_httpx):
    _patch_httpx(_mock_client("approve"))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False
    assert "5" in result.to_text()


@pytest.mark.asyncio
async def test_approve_with_concerns_still_delegates(_patch_httpx):
    _patch_httpx(_mock_client("approve_with_concerns"))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False, "approve_with_concerns must never block in gate mode"


@pytest.mark.asyncio
async def test_reject_blocks_in_gate_mode(_patch_httpx):
    _patch_httpx(_mock_client("reject"))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is True
    assert "BLOCKED" in result.to_text()
    assert "5" not in result.to_text(), "the real tool must never have run"


@pytest.mark.asyncio
async def test_reject_does_not_block_in_advisory_mode(_patch_httpx):
    _patch_httpx(_mock_client("reject"))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="advisory")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False, "advisory mode must never block, only annotate"
    assert "5" in result.to_text()


@pytest.mark.asyncio
async def test_missing_api_key_fails_open(_patch_httpx):
    # No transport needed -- _review() short-circuits before any HTTP call when api_key is empty.
    gw = GovernedWorkbench(_workbench(), api_key="", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False
    assert "5" in result.to_text()
    assert gw.last_review_unavailable["error"] == "review_unavailable"
    assert gw.last_review_unavailable["reason"] == "no_api_key"


@pytest.mark.asyncio
async def test_network_error_fails_open(_patch_httpx):
    def raise_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")
    _patch_httpx(httpx.MockTransport(raise_handler))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False, "a /review-side network failure must never block the real tool"
    assert "5" in result.to_text()
    assert gw.last_review_unavailable["error"] == "review_unavailable"
    assert gw.last_review_unavailable["reason"] == "timeout"


@pytest.mark.asyncio
async def test_timeout_and_malformed_share_marker_not_reason(_patch_httpx):
    """Negative control matching recompute-kit#13's dimensionality: two real
    causes, same review_unavailable marker, different reason. A present-vs-
    absent reason field would not have caught the collapse."""
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout")

    def malformed_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "verdict": "not-a-real-verdict"})

    gw_t = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    _patch_httpx(httpx.MockTransport(timeout_handler))
    r_t = await gw_t.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")

    gw_m = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    _patch_httpx(httpx.MockTransport(malformed_handler))
    r_m = await gw_m.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")

    assert r_t.is_error is False and r_m.is_error is False
    a, b = gw_t.last_review_unavailable, gw_m.last_review_unavailable
    assert a["error"] == b["error"] == "review_unavailable"
    assert a["review_unavailable"] is True and b["review_unavailable"] is True
    assert a["reason"] == "timeout"
    assert b["reason"] == "malformed_response"
    assert a["reason"] != b["reason"]


@pytest.mark.asyncio
async def test_http_error_status_fails_open(_patch_httpx):
    _patch_httpx(_mock_client("approve", status_code=402))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False, "an HTTP error from /review must fail open, not raise/block"
    assert "5" in result.to_text()
    assert gw.last_review_unavailable["error"] == "review_unavailable"
    assert gw.last_review_unavailable["reason"] == "http_error"


@pytest.mark.asyncio
async def test_should_review_callback_can_skip_specific_tools(_patch_httpx):
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(200, json={"status": "success", "type": "structured_review",
                                          "verdict": "reject", "confidence": 0.9,
                                          "summary": "x", "issues": []})
    _patch_httpx(httpx.MockTransport(handler))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate", should_review=lambda name: False)
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert calls["count"] == 0, "should_review=False must skip the /review call entirely"
    assert result.is_error is False
    assert "5" in result.to_text()


@pytest.mark.asyncio
async def test_on_verdict_sync_callback_receives_full_verdict_incl_proof(_patch_httpx):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "status": "success", "type": "structured_review", "verdict": "approve",
            "confidence": 0.9, "summary": "ok", "issues": [],
            "proof": {"event": {"id": "deadbeef"}, "verify_url": "https://x/verify-proof"},
        })
    _patch_httpx(httpx.MockTransport(handler))
    received = {}

    def on_verdict(name: str, verdict: dict) -> None:
        received["name"] = name
        received["verdict"] = verdict

    gw = GovernedWorkbench(_workbench(), api_key="test-key", sign=True, on_verdict=on_verdict)
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False
    assert received["name"] == "add"
    assert received["verdict"]["proof"]["event"]["id"] == "deadbeef", "the proof must actually reach the callback"


@pytest.mark.asyncio
async def test_on_verdict_async_callback_is_awaited(_patch_httpx):
    _patch_httpx(_mock_client("approve"))
    called = {"count": 0}

    async def on_verdict(name: str, verdict: dict) -> None:
        import asyncio
        await asyncio.sleep(0)
        called["count"] += 1

    gw = GovernedWorkbench(_workbench(), api_key="test-key", on_verdict=on_verdict)
    await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert called["count"] == 1, "an async on_verdict callback must actually be awaited"


@pytest.mark.asyncio
async def test_broken_on_verdict_callback_does_not_corrupt_a_real_reject(_patch_httpx):
    """A user's own on_verdict raising must never turn a real reject verdict into an
    accidental approve -- that would be the callback silently defeating the gate."""
    _patch_httpx(_mock_client("reject"))

    def broken_callback(name: str, verdict: dict) -> None:
        raise RuntimeError("user's own logging code is broken")

    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate", on_verdict=broken_callback)
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is True, "the reject verdict must still block even though the callback raised"
    assert "5" not in result.to_text()


@pytest.mark.asyncio
async def test_on_verdict_not_called_on_fail_open(_patch_httpx):
    called = {"count": 0}
    gw = GovernedWorkbench(_workbench(), api_key="", on_verdict=lambda n, v: called.__setitem__("count", called["count"] + 1))
    await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert called["count"] == 0, "no verdict exists on a fail-open skip, so on_verdict must not fire"


@pytest.mark.asyncio
async def test_list_tools_delegates_to_inner():
    inner = _workbench()
    gw = GovernedWorkbench(inner, api_key="test-key")
    tools = await gw.list_tools()
    assert any(t["name"] == "add" for t in tools)


@pytest.mark.asyncio
async def test_lifecycle_methods_delegate_to_inner():
    inner = _workbench()
    gw = GovernedWorkbench(inner, api_key="test-key")
    await gw.start()
    await gw.reset()
    state = await gw.save_state()
    await gw.load_state(state)
    await gw.stop()  # should not raise


@pytest.mark.asyncio
async def test_nested_reject_emits_not_reached_for_inner_and_does_not_run_it(_patch_httpx):
    """Outer deny must still block, and emit a not_reached marker for the inner
    provider that never ran -- not a verdict, just {provider_id, reason: upstream_deny}."""
    review_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        review_calls["count"] += 1
        return httpx.Response(
            200,
            json={
                "status": "success", "type": "structured_review", "verdict": "reject",
                "confidence": 0.9, "summary": "outer deny", "issues": [],
            },
        )

    _patch_httpx(httpx.MockTransport(handler))
    inner_not_reached: list[dict] = []
    inner_verdicts: list[dict] = []
    inner = GovernedWorkbench(
        _workbench(),
        api_key="test-key",
        mode="gate",
        provider_id="inner.gw",
        on_verdict=lambda n, v: inner_verdicts.append(v),
        on_not_reached=lambda n, m: inner_not_reached.append(m),
    )
    outer_markers: list[tuple[str, dict]] = []

    def on_not_reached(name: str, marker: dict) -> None:
        outer_markers.append((name, marker))

    outer = GovernedWorkbench(
        inner,
        api_key="test-key",
        mode="gate",
        provider_id="outer.gw",
        on_not_reached=on_not_reached,
    )
    result = await outer.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is True
    assert "BLOCKED" in result.to_text()
    assert "5" not in result.to_text(), "the real tool must never have run"
    assert review_calls["count"] == 1, "inner.call_tool must not run, so only outer /review fires"
    assert inner_verdicts == [], "inner never reviewed -- no verdict for it"
    assert inner_not_reached == [], "inner's own callback must not fire; it never ran"
    assert len(outer_markers) == 1
    assert outer_markers[0][0] == "add"
    assert outer_markers[0][1] == {"provider_id": "inner.gw", "reason": "upstream_deny"}
    assert set(outer_markers[0][1].keys()) == {"provider_id", "reason"}


@pytest.mark.asyncio
async def test_approve_emits_zero_not_reached_markers(_patch_httpx):
    _patch_httpx(_mock_client("approve"))
    markers: list[dict] = []
    gw = GovernedWorkbench(
        _workbench(),
        api_key="test-key",
        mode="gate",
        provider_id="solo.gw",
        on_not_reached=lambda n, m: markers.append(m),
    )
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False
    assert "5" in result.to_text()
    assert markers == [], "approve delegates; no downstream was skipped, so no not_reached"


@pytest.mark.asyncio
async def test_explicit_downstream_ids_used_when_inner_has_no_provider_id(_patch_httpx):
    _patch_httpx(_mock_client("reject"))
    markers: list[dict] = []
    gw = GovernedWorkbench(
        _workbench(),
        api_key="test-key",
        mode="gate",
        provider_id="outer.gw",
        downstream_provider_ids=["other.gate", "yet.another"],
        on_not_reached=lambda n, m: markers.append(m),
    )
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is True
    assert markers == [
        {"provider_id": "other.gate", "reason": "upstream_deny"},
        {"provider_id": "yet.another", "reason": "upstream_deny"},
    ]


@pytest.mark.asyncio
async def test_advisory_reject_does_not_emit_not_reached(_patch_httpx):
    """Advisory reject still delegates, so downstream *did* run -- not 'never reached'."""
    _patch_httpx(_mock_client("reject"))
    markers: list[dict] = []
    outer = GovernedWorkbench(
        _workbench(),
        api_key="test-key",
        mode="advisory",
        provider_id="outer.gw",
        downstream_provider_ids=["would.have.been.skipped"],
        on_not_reached=lambda n, m: markers.append(m),
    )
    result = await outer.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False
    assert markers == []


def _mock_client_sequence(verdicts: list[str]):
    """Like _mock_client, but returns a different verdict on each successive request --
    simulates the underlying authority/policy state changing between two separate
    tool-call attempts (per github.com/microsoft/autogen#7405, nsolland 2026-09-14:
    "approve under policy version A, revoke or narrow authority before execution,
    then assert that the tool is never called and the decision terminates as
    denied/escalated rather than consuming the stale approval")."""
    calls: list[str] = list(verdicts)

    def handler(request: httpx.Request) -> httpx.Response:
        verdict = calls.pop(0) if calls else verdicts[-1]
        return httpx.Response(
            200,
            json={
                "status": "success", "type": "structured_review", "verdict": verdict,
                "confidence": 0.9, "summary": "test verdict", "issues": [],
            },
        )
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_narrowed_authority_between_calls_is_never_consumed_as_stale_approval(_patch_httpx):
    """The regression nsolland asked for (autogen#7405 / langgraph#8102), adapted to how
    GovernedWorkbench actually works: it holds NO persisted verdict to go stale in the
    first place -- call_tool() does `verdict = await self._review(...)` immediately
    followed by delegating to the inner tool, every single invocation, with nothing
    cached in between. So the failure this test rules out isn't "a stored approval gets
    reused after authority narrows" (there is no store) -- it's the sharper adjacent
    claim: a SECOND, separate call_tool() for the identical tool+arguments must reflect
    the CURRENT verdict, never an earlier one silently carried forward.

    Simulates authority narrowing between two back-to-back calls by having the review
    endpoint return approve, then reject, for the identical request shape."""
    _patch_httpx(_mock_client_sequence(["approve", "reject"]))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")

    first = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert first.is_error is False, "call under policy A (approve) must execute"
    assert "5" in first.to_text()

    second = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c2")
    assert second.is_error is True, (
        "call after authority narrows (reject) must be denied -- if this executed, "
        "it would mean an earlier approve was silently reused instead of a fresh check"
    )
    assert "BLOCKED" in second.to_text()
    assert "5" not in second.to_text(), "the real tool must never have run on the narrowed-authority call"
