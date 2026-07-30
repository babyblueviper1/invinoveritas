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


@pytest.mark.asyncio
async def test_network_error_fails_open(_patch_httpx):
    def raise_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")
    _patch_httpx(httpx.MockTransport(raise_handler))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False, "a /review-side network failure must never block the real tool"
    assert "5" in result.to_text()


@pytest.mark.asyncio
async def test_http_error_status_fails_open(_patch_httpx):
    _patch_httpx(_mock_client("approve", status_code=402))
    gw = GovernedWorkbench(_workbench(), api_key="test-key", mode="gate")
    result = await gw.call_tool("add", {"a": 2, "b": 3}, CancellationToken(), call_id="c1")
    assert result.is_error is False, "an HTTP error from /review must fail open, not raise/block"
    assert "5" in result.to_text()


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
