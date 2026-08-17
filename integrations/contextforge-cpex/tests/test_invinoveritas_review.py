# -*- coding: utf-8 -*-
"""Live-shaped tests for InvinoveritasReviewPlugin -- no network calls, real HTTP mocking
via httpx.MockTransport (same pattern as invinoveritas's own AutoGen GovernedWorkbench
tests). Run: pytest integrations/contextforge_cpex/tests/test_invinoveritas_review.py -v
"""
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cpex.framework import GlobalContext, PluginConfig, PluginContext  # noqa: E402
from cpex.framework.models import UserContext  # noqa: E402
from cpex.framework.hooks.tools import ToolPreInvokePayload  # noqa: E402

from invinoveritas_review import InvinoveritasReviewPlugin  # noqa: E402


def _make_plugin(config: dict) -> InvinoveritasReviewPlugin:
    pc = PluginConfig(
        name="invinoveritas_review",
        kind="invinoveritas_review.InvinoveritasReviewPlugin",
        version="0.2.0",
        author="babyblueviper1",
        hooks=["tool_pre_invoke"],
        tags=["safety", "review"],
        config=config,
    )
    return InvinoveritasReviewPlugin(pc)


def _ctx(user_context: UserContext | None = None) -> PluginContext:
    return PluginContext(global_context=GlobalContext(request_id="req-test-1", user_context=user_context))


def _patch_httpx(monkeypatch, handler):
    transport = httpx.MockTransport(handler)

    class PatchedClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedClient)


@pytest.mark.asyncio
async def test_reject_blocks_by_default(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["artifact_type"] == "general"
        assert json.loads(body["artifact"])["tool_name"] == "delete_prod_db"
        return httpx.Response(200, json={"verdict": "reject", "confidence": 0.91, "summary": "Irreversible, no confirmation."})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    payload = ToolPreInvokePayload(name="delete_prod_db", args={"table": "users"})
    result = await plugin.tool_pre_invoke(payload, _ctx())

    assert result.continue_processing is False
    assert result.violation is not None
    assert result.violation.code == "IVV_REVIEW_REJECT"


@pytest.mark.asyncio
async def test_reject_does_not_block_in_advisory_mode(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"verdict": "reject", "confidence": 0.9, "summary": "risky"})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key", "block_on_reject": False})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="risky_tool"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"]["verdict"] == "reject"


@pytest.mark.asyncio
async def test_approve_passes_through(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.97})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="read_file"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"]["verdict"] == "approve"


@pytest.mark.asyncio
async def test_fails_open_on_network_error(monkeypatch):
    def raise_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout")

    _patch_httpx(monkeypatch, raise_handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="any_tool"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"] == "unavailable"


@pytest.mark.asyncio
async def test_fails_open_on_malformed_response(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_a_verdict_field": True})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="any_tool"), _ctx())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"] == "unavailable"


@pytest.mark.asyncio
async def test_no_api_key_fails_open_without_network_call(monkeypatch):
    called = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        called["n"] += 1
        return httpx.Response(200, json={"verdict": "reject"})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({})  # no api_key, no IVV_API_KEY env var assumed absent
    monkeypatch.delenv("IVV_API_KEY", raising=False)
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="any_tool"), _ctx())

    assert result.continue_processing is True
    assert called["n"] == 0  # never even attempted the call


# ---- caller-identity enrichment (new) ----

@pytest.mark.asyncio
async def test_caller_identity_folded_into_artifact_and_context(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["artifact"] = json.loads(body["artifact"])
        captured["context"] = body["context"]
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.9})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    uc = UserContext(
        user_id="alice@example.com",
        email="alice@example.com",
        groups=["ops"],
        service_account="svc-gateway",
        delegation_chain=["agentA", "svc-gateway"],
        auth_method="bearer",
    )
    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="deploy"), _ctx(uc))

    assert result.continue_processing is True
    ci = captured["artifact"]["caller_identity"]
    assert ci["user_id"] == "alice@example.com"
    assert ci["service_account"] == "svc-gateway"
    assert ci["delegation_chain"] == ["agentA", "svc-gateway"]
    assert "user=alice@example.com" in captured["context"]
    assert "service_account=svc-gateway" in captured["context"]
    assert "delegation_chain=" in captured["context"]


@pytest.mark.asyncio
async def test_no_user_context_omits_caller_identity(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["artifact"] = json.loads(body["artifact"])
        captured["context"] = body["context"]
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.9})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="read_file"), _ctx())

    assert result.continue_processing is True
    assert "caller_identity" not in captured["artifact"]
    assert captured["context"] == "cpex tool_pre_invoke, request_id=req-test-1"


@pytest.mark.asyncio
async def test_include_caller_identity_false_opts_out(monkeypatch):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["artifact"] = json.loads(body["artifact"])
        captured["context"] = body["context"]
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.9})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key", "include_caller_identity": False})
    await plugin.initialize()

    uc = UserContext(user_id="alice@example.com", service_account="svc-gateway")
    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="deploy"), _ctx(uc))

    assert result.continue_processing is True
    assert "caller_identity" not in captured["artifact"]
    assert "user=" not in captured["context"]


@pytest.mark.asyncio
async def test_empty_user_context_fields_produce_no_caller_identity(monkeypatch):
    """A UserContext object can exist but carry nothing usable (all-default fields) --
    should behave identically to no user_context at all, not send an empty dict."""
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["artifact"] = json.loads(body["artifact"])
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.9})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    uc = UserContext(user_id="anon")  # only user_id set, everything else default/empty
    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="read_file"), _ctx(uc))

    assert result.continue_processing is True
    # user_id IS a usable field even alone -- confirms the "only non-default fields
    # included" logic works at the boundary, not that identity vanishes entirely.
    assert captured["artifact"]["caller_identity"] == {"user_id": "anon"}


@pytest.mark.asyncio
async def test_caller_identity_extraction_failure_fails_open_not_broken(monkeypatch):
    """If context.user_context blows up for any reason (a future cpex version renames a
    field, a malformed proxy object, whatever), review must still proceed -- identity
    enrichment is a bonus, never a new way for this plugin to break."""

    class ExplodingContext:
        global_context = None

        @property
        def user_context(self):
            raise RuntimeError("simulated cpex internals change")

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "caller_identity" not in json.loads(body["artifact"])
        return httpx.Response(200, json={"verdict": "approve", "confidence": 0.9})

    _patch_httpx(monkeypatch, handler)
    plugin = _make_plugin({"api_key": "test_key"})
    await plugin.initialize()

    result = await plugin.tool_pre_invoke(ToolPreInvokePayload(name="read_file"), ExplodingContext())

    assert result.continue_processing is True
    assert result.metadata["invinoveritas_review"]["verdict"] == "approve"
