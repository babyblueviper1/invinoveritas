"""
invinoveritas SDK test suite
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Run with:
    pip install pytest pytest-asyncio
    pytest test_invinoveritas_sdk.py -v
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from invinoveritas_sdk import (
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
    "version": "0.1.0",
    "pricing": {
        "currency": "sats",
        "dynamic_pricing": True,
    },
}

PRICES_RESPONSE = {
    "currency": "sats",
    "dynamic_pricing": True,
    "agent_multiplier": 1.4,
    "minimum_price_sats": 500,
    "prices": {
        "reason": {
            "base": 500,
            "agent": 700,
            "description": "Premium strategic reasoning",
        },
        "decide": {
            "base": 1000,
            "agent": 1400,
            "description": "Structured decision intelligence",
        }
    },
    "last_updated": 1743800000,
}

TOOL_DEFINITION_RESPONSE = {
    "name": "invinoveritas",
    "type": "lightning_paid_ai",
    "description": "Lightning-paid strategic reasoning...",
    "payment_protocol": "L402",
    "mcp_endpoint": "/mcp",
}


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
# Sync Client Tests
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
        """Test the new get_prices() method."""
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, PRICES_RESPONSE)):
            result = client.get_prices()
        assert result["currency"] == "sats"
        assert result["prices"]["reason"]["base"] == 500
        assert result["prices"]["decide"]["agent"] == 1400

    def test_get_price_reason(self):
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, {"price_sats": 500})):
            price = client.get_price("reason")
        assert price == 500

    def test_get_tool_definition(self):
        """Test the new get_tool_definition() method."""
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, TOOL_DEFINITION_RESPONSE)):
            result = client.get_tool_definition()
        assert result["name"] == "invinoveritas"
        assert result["mcp_endpoint"] == "/mcp"


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
        assert result["currency"] == "sats"
        assert "reason" in result["prices"]

    async def test_async_get_tool_definition(self):
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "get", return_value=make_async_mock_response(200, TOOL_DEFINITION_RESPONSE)):
                result = await client.get_tool_definition()
        assert result["name"] == "invinoveritas"

    async def test_async_context_manager(self):
        async with AsyncInvinoClient() as client:
            assert client._client is not None
        assert client._client is None


# ---------------------------------------------------------------------------
# Two-step Flow Tests
# ---------------------------------------------------------------------------

class TestTwoStepFlow:
    def test_full_reason_flow(self):
        client = InvinoClient()
        question = "Should I increase my BTC exposure in 2026?"

        with patch.object(client._session, "post", return_value=make_mock_response(402, REASON_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc:
                client.reason(question)
        payment_required = exc.value

        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)):
            result = client.reason(question, payment_required.payment_hash, FAKE_PREIMAGE)

        assert isinstance(result, ReasoningResult)


# ---------------------------------------------------------------------------
# Exception Tests
# ---------------------------------------------------------------------------

class TestExceptions:
    def test_payment_required_attributes(self):
        err = PaymentRequired(FAKE_PAYMENT_HASH, FAKE_INVOICE, 500)
        assert err.payment_hash == FAKE_PAYMENT_HASH
        assert err.amount_sats == 500
        assert isinstance(err, InvinoError)
