"""
invinoveritas SDK test suite
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Run with:
    pip install pytest pytest-asyncio
    pytest test_invinoveritas_sdk.py -v
    pytest test_invinoveritas_sdk.py -v -k "not handler"  # skip handler tests
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from invinoveritas import (                    # Correct import for the package
    InvinoClient,
    AsyncInvinoClient,
    PaymentRequired,
    PaymentError,
    ServiceError,
    InvinoError,
    ReasoningResult,
    DecisionResult,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

FAKE_INVOICE = "lnbc500n1fake_invoice_for_testing"
FAKE_PAYMENT_HASH = "abc123def456abc123def456abc123def456abc123def456abc123def456abc1"
FAKE_PREIMAGE = "preimage123preimage123preimage123preimage123preimage123preimage1"

REASON_402_RESPONSE = {
    "detail": {
        "message": "Payment Required",
        "payment_hash": FAKE_PAYMENT_HASH,
        "invoice": FAKE_INVOICE,
        "amount_sats": 500,
    }
}

REASON_SUCCESS_RESPONSE = {
    "status": "success",
    "type": "premium_reasoning",
    "answer": "Bitcoin faces risks from regulatory pressure, ETF concentration, and macro liquidity tightening in 2026.",
}

DECIDE_402_RESPONSE = {
    "detail": {
        "message": "Payment Required",
        "payment_hash": FAKE_PAYMENT_HASH,
        "invoice": FAKE_INVOICE,
        "amount_sats": 1000,
    }
}

DECIDE_SUCCESS_RESPONSE = {
    "status": "success",
    "type": "decision_intelligence",
    "result": {
        "decision": "Increase BTC exposure slightly",
        "confidence": 0.78,
        "reasoning": "Market structure improving while macro risk remains moderate.",
        "risk_level": "medium",
    },
}

HEALTH_RESPONSE = {
    "status": "ok",
    "service": "invinoveritas",
    "version": "0.2.0",
    "pricing": {"currency": "sats", "dynamic_pricing": True},
}

PRICES_RESPONSE = {
    "currency": "sats",
    "dynamic_pricing": True,
    "agent_multiplier": 1.2,
    "minimum_price_sats": 50,
    "prices": {
        "reason": {"base": 500, "agent": 600, "description": "Premium strategic reasoning"},
        "decide": {"base": 1000, "agent": 1200, "description": "Structured decision intelligence"},
    },
    "last_updated": 1743800000,
}

TOOL_DEFINITION_RESPONSE = {
    "name": "invinoveritas",
    "type": "lightning_paid_ai",
    "description": "Lightning-paid strategic reasoning and structured decision intelligence",
    "payment_protocol": "L402",
    "mcp_endpoint": "/mcp",
}

LNCLI_SUCCESS_OUTPUT = """
{
    "payment_hash": "abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    "payment_preimage": "preimage123preimage123preimage123preimage123preimage123preimage1",
    "value_sat": "500",
    "status": "SUCCEEDED"
}
"""


def make_mock_response(status_code: int, json_data: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.ok = status_code < 400
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


def make_async_mock_response(status_code: int, json_data: dict):
    mock = MagicMock()
    mock.status_code = status_code
    mock.is_success = status_code < 400
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


# ---------------------------------------------------------------------------
# Core SDK Tests (Sync)
# ---------------------------------------------------------------------------

class TestReasonSync:
    def test_reason_raises_payment_required_without_auth(self):
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(402, REASON_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc:
                client.reason("What are the biggest risks for Bitcoin in 2026?")
        assert exc.value.payment_hash == FAKE_PAYMENT_HASH
        assert exc.value.amount_sats == 500

    def test_reason_returns_result_with_valid_payment(self):
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)):
            result = client.reason(
                "What are the biggest risks for Bitcoin in 2026?",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )
        assert isinstance(result, ReasoningResult)
        assert "Bitcoin" in result.answer

    def test_reason_sends_auth_header(self):
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)) as mock_post:
            client.reason("test", payment_hash=FAKE_PAYMENT_HASH, preimage=FAKE_PREIMAGE)
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == f"L402 {FAKE_PAYMENT_HASH}:{FAKE_PREIMAGE}"


class TestDecideSync:
    def test_decide_raises_payment_required(self):
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(402, DECIDE_402_RESPONSE)):
            with pytest.raises(PaymentRequired):
                client.decide(goal="Grow capital", question="Increase BTC?")

    def test_decide_returns_result(self):
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, DECIDE_SUCCESS_RESPONSE)):
            result = client.decide(
                goal="Grow capital safely",
                question="Should I increase BTC exposure?",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )
        assert isinstance(result, DecisionResult)
        assert result.confidence == 0.78


class TestUtilitySync:
    def test_check_health(self):
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, HEALTH_RESPONSE)):
            result = client.check_health()
        assert result["status"] == "ok"

    def test_get_prices(self):
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, PRICES_RESPONSE)):
            result = client.get_prices()
        assert result["currency"] == "sats"
        assert result["prices"]["reason"]["base"] == 500

    def test_get_price_reason(self):
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, {"price_sats": 500})):
            price = client.get_price("reason")
        assert price == 500

    def test_get_tool_definition(self):
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, TOOL_DEFINITION_RESPONSE)):
            result = client.get_tool_definition()
        assert result["name"] == "invinoveritas"


# ---------------------------------------------------------------------------
# Async Client Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestAsyncClient:
    async def test_async_reason_raises_payment_required(self):
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "post", return_value=make_async_mock_response(402, REASON_402_RESPONSE)):
                with pytest.raises(PaymentRequired):
                    await client.reason("test question")

    async def test_async_get_prices(self):
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "get", return_value=make_async_mock_response(200, PRICES_RESPONSE)):
                result = await client.get_prices()
        assert "reason" in result["prices"]

    async def test_async_get_tool_definition(self):
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "get", return_value=make_async_mock_response(200, TOOL_DEFINITION_RESPONSE)):
                result = await client.get_tool_definition()
        assert result["name"] == "invinoveritas"

    async def test_async_context_manager_closes(self):
        async with AsyncInvinoClient() as client:
            assert client._client is not None
        assert client._client is None


# ---------------------------------------------------------------------------
# Two-step Flow
# ---------------------------------------------------------------------------

class TestTwoStepFlow:
    def test_full_reason_flow(self):
        client = InvinoClient()
        question = "Should I increase my BTC exposure in 2026?"

        with patch.object(client._session, "post", return_value=make_mock_response(402, REASON_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc:
                client.reason(question)

        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)):
            result = client.reason(question, exc.value.payment_hash, FAKE_PREIMAGE)

        assert isinstance(result, ReasoningResult)


# ---------------------------------------------------------------------------
# Exception Tests
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_payment_required_attributes(self):
        err = PaymentRequired(FAKE_PAYMENT_HASH, FAKE_INVOICE, 500)
        assert err.payment_hash == FAKE_PAYMENT_HASH
        assert err.amount_sats == 500

    def test_exceptions_inherit_from_invino_error(self):
        assert isinstance(PaymentRequired(FAKE_PAYMENT_HASH, FAKE_INVOICE, 500), InvinoError)
        assert isinstance(PaymentError("bad"), InvinoError)
        assert isinstance(ServiceError("bad"), InvinoError)


# ---------------------------------------------------------------------------
# Optional: LangChain / Provider Tests (skippable)
# ---------------------------------------------------------------------------

class TestLangChainHandler:

    def test_handler_requires_provider_or_pay_fn(self):
        try:
            from invinoveritas.langchain import InvinoCallbackHandler
        except ImportError:
            pytest.skip("langchain extras not installed")
        with pytest.raises(Exception):
            InvinoCallbackHandler()

    def test_lnd_provider_builds(self):
        try:
            from invinoveritas.providers import LNDProvider
        except ImportError:
            pytest.skip("providers not available")
        provider = LNDProvider(macaroon_path="/fake/admin.macaroon", cert_path="/fake/tls.cert")
        assert provider.host == "localhost:10009"

    @pytest.mark.asyncio
    async def test_l402_client_pays_and_retries(self):
        try:
            from invinoveritas.langchain import L402Client
            from invinoveritas.providers import CustomProvider
        except ImportError:
            pytest.skip("langchain extras not installed")

        async def fake_pay(invoice: str) -> str:
            return FAKE_PREIMAGE

        provider = CustomProvider(pay_fn=fake_pay)
        l402_client = L402Client(provider=provider)

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return make_async_mock_response(402, REASON_402_RESPONSE)
            return make_async_mock_response(200, REASON_SUCCESS_RESPONSE)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = mock_post
            mock_client_cls.return_value = mock_client

            result = await l402_client.post("/reason", {"question": "test"})

        assert result["answer"] is not None
        assert call_count == 2
