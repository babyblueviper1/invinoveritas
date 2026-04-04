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
    "pricing": {
        "currency": "sats",
        "dynamic_pricing": True,
    },
}


def make_mock_response(status_code: int, json_data: dict):
    """Create a mock requests.Response object."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.ok = status_code < 400
    mock.json.return_value = json_data
    mock.text = str(json_data)
    mock.headers = {}
    return mock


def make_async_mock_response(status_code: int, json_data: dict):
    """Create a mock httpx.Response object for async tests."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.is_success = status_code < 400
    mock.json.return_value = json_data
    mock.text = str(json_data)
    return mock


# ---------------------------------------------------------------------------
# Sync client — reason()
# ---------------------------------------------------------------------------

class TestReasonSync:

    def test_reason_raises_payment_required_without_auth(self):
        """First call with no credentials raises PaymentRequired with invoice."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(402, REASON_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc_info:
                client.reason("What are the biggest risks for Bitcoin in 2026?")

        err = exc_info.value
        assert err.invoice == FAKE_INVOICE
        assert err.payment_hash == FAKE_PAYMENT_HASH
        assert err.amount_sats == 500

    def test_reason_returns_result_with_valid_payment(self):
        """Second call with valid credentials returns ReasoningResult."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)):
            result = client.reason(
                "What are the biggest risks for Bitcoin in 2026?",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )

        assert isinstance(result, ReasoningResult)
        assert "Bitcoin" in result.answer
        assert result.payment_hash == FAKE_PAYMENT_HASH

    def test_reason_sends_auth_header_when_credentials_provided(self):
        """Authorization header is correctly formatted as L402 hash:preimage."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)) as mock_post:
            client.reason(
                "test question",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )

        _, kwargs = mock_post.call_args
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == f"L402 {FAKE_PAYMENT_HASH}:{FAKE_PREIMAGE}"

    def test_reason_raises_payment_error_on_403(self):
        """403 response raises PaymentError (replay or invalid preimage)."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(403, {"detail": "Payment already used"})):
            with pytest.raises(PaymentError):
                client.reason("test", payment_hash=FAKE_PAYMENT_HASH, preimage=FAKE_PREIMAGE)

    def test_reason_raises_payment_error_on_401(self):
        """401 response raises PaymentError."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(401, {"detail": "Invalid L402 format"})):
            with pytest.raises(PaymentError):
                client.reason("test", payment_hash="bad", preimage="bad")

    def test_reason_raises_invino_error_on_429(self):
        """429 response raises InvinoError with rate limit message."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(429, {"detail": "Rate limited"})):
            with pytest.raises(InvinoError) as exc_info:
                client.reason("test")
        assert "Rate limited" in str(exc_info.value)

    def test_reason_raises_service_error_on_500(self):
        """500 response raises ServiceError."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(500, {"detail": "Internal error"})):
            with pytest.raises(ServiceError):
                client.reason("test")

    def test_reason_empty_question_still_sends_request(self):
        """Empty question is passed through — server handles validation."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(402, REASON_402_RESPONSE)):
            with pytest.raises(PaymentRequired):
                client.reason("")


# ---------------------------------------------------------------------------
# Sync client — decide()
# ---------------------------------------------------------------------------

class TestDecideSync:

    def test_decide_raises_payment_required_without_auth(self):
        """First decide call raises PaymentRequired with invoice."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(402, DECIDE_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc_info:
                client.decide(
                    goal="Grow capital safely",
                    question="Should I increase BTC exposure?",
                )

        err = exc_info.value
        assert err.amount_sats == 1000
        assert err.invoice == FAKE_INVOICE

    def test_decide_returns_result_with_valid_payment(self):
        """decide() returns DecisionResult with all fields populated."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, DECIDE_SUCCESS_RESPONSE)):
            result = client.decide(
                goal="Grow capital safely",
                question="Should I increase BTC exposure?",
                context="Mostly BTC with some cash reserves",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )

        assert isinstance(result, DecisionResult)
        assert result.decision == "Increase BTC exposure slightly"
        assert result.confidence == 0.78
        assert result.risk_level == "medium"
        assert isinstance(result.reasoning, str)

    def test_decide_sends_correct_payload(self):
        """decide() sends goal, context, and question in request body."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, DECIDE_SUCCESS_RESPONSE)) as mock_post:
            client.decide(
                goal="my goal",
                question="my question",
                context="my context",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )

        _, kwargs = mock_post.call_args
        payload = kwargs["json"]
        assert payload["goal"] == "my goal"
        assert payload["question"] == "my question"
        assert payload["context"] == "my context"

    def test_decide_context_defaults_to_empty_string(self):
        """context is optional and defaults to empty string."""
        client = InvinoClient()
        with patch.object(client._session, "post", return_value=make_mock_response(200, DECIDE_SUCCESS_RESPONSE)) as mock_post:
            client.decide(
                goal="goal",
                question="question",
                payment_hash=FAKE_PAYMENT_HASH,
                preimage=FAKE_PREIMAGE,
            )

        _, kwargs = mock_post.call_args
        assert kwargs["json"]["context"] == ""


# ---------------------------------------------------------------------------
# Sync client — utility methods
# ---------------------------------------------------------------------------

class TestUtilitySync:

    def test_check_health_returns_dict(self):
        """check_health() returns parsed health dict."""
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, HEALTH_RESPONSE)):
            result = client.check_health()
        assert result["status"] == "ok"
        assert result["service"] == "invinoveritas"

    def test_check_health_raises_service_error_on_failure(self):
        """check_health() raises ServiceError if server is down."""
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(503, {})):
            with pytest.raises(ServiceError):
                client.check_health()

    def test_get_price_reason(self):
        """get_price('reason') returns integer sats."""
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, {"price_sats": 500})):
            price = client.get_price("reason")
        assert price == 500
        assert isinstance(price, int)

    def test_get_price_decision(self):
        """get_price('decision') returns integer sats."""
        client = InvinoClient()
        with patch.object(client._session, "get", return_value=make_mock_response(200, {"price_sats": 1000})):
            price = client.get_price("decision")
        assert price == 1000


# ---------------------------------------------------------------------------
# Exception behaviour
# ---------------------------------------------------------------------------

class TestExceptions:

    def test_payment_required_attributes(self):
        """PaymentRequired carries all three required attributes."""
        err = PaymentRequired(
            payment_hash=FAKE_PAYMENT_HASH,
            invoice=FAKE_INVOICE,
            amount_sats=500,
        )
        assert err.payment_hash == FAKE_PAYMENT_HASH
        assert err.invoice == FAKE_INVOICE
        assert err.amount_sats == 500

    def test_payment_required_is_invino_error(self):
        """PaymentRequired inherits from InvinoError."""
        err = PaymentRequired(FAKE_PAYMENT_HASH, FAKE_INVOICE, 500)
        assert isinstance(err, InvinoError)

    def test_payment_error_is_invino_error(self):
        """PaymentError inherits from InvinoError."""
        err = PaymentError("bad preimage")
        assert isinstance(err, InvinoError)

    def test_service_error_is_invino_error(self):
        """ServiceError inherits from InvinoError."""
        err = ServiceError("500 internal")
        assert isinstance(err, InvinoError)

    def test_malformed_402_raises_service_error(self):
        """A 402 without expected fields raises ServiceError, not PaymentRequired."""
        client = InvinoClient()
        bad_402 = {"detail": {"unexpected": "format"}}
        with patch.object(client._session, "post", return_value=make_mock_response(402, bad_402)):
            with pytest.raises(ServiceError):
                client.reason("test")


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestReasonAsync:

    async def test_async_reason_raises_payment_required(self):
        """Async reason raises PaymentRequired on 402."""
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "post", return_value=make_async_mock_response(402, REASON_402_RESPONSE)):
                with pytest.raises(PaymentRequired) as exc_info:
                    await client.reason("What are the biggest risks for Bitcoin?")

        err = exc_info.value
        assert err.payment_hash == FAKE_PAYMENT_HASH
        assert err.amount_sats == 500

    async def test_async_reason_returns_result_with_payment(self):
        """Async reason returns ReasoningResult with valid credentials."""
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "post", return_value=make_async_mock_response(200, REASON_SUCCESS_RESPONSE)):
                result = await client.reason(
                    "What are the biggest risks for Bitcoin?",
                    payment_hash=FAKE_PAYMENT_HASH,
                    preimage=FAKE_PREIMAGE,
                )

        assert isinstance(result, ReasoningResult)
        assert result.answer != ""

    async def test_async_decide_returns_result_with_payment(self):
        """Async decide returns DecisionResult with valid credentials."""
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "post", return_value=make_async_mock_response(200, DECIDE_SUCCESS_RESPONSE)):
                result = await client.decide(
                    goal="Grow capital",
                    question="Increase BTC?",
                    payment_hash=FAKE_PAYMENT_HASH,
                    preimage=FAKE_PREIMAGE,
                )

        assert isinstance(result, DecisionResult)
        assert result.confidence == 0.78

    async def test_async_client_raises_if_not_started(self):
        """Calling methods before start() raises RuntimeError."""
        client = AsyncInvinoClient()
        with pytest.raises(RuntimeError, match="not started"):
            await client.reason("test")

    async def test_async_context_manager_closes_client(self):
        """Context manager properly closes the httpx client."""
        async with AsyncInvinoClient() as client:
            assert client._client is not None
        assert client._client is None

    async def test_async_client_can_be_used_without_context_manager(self):
        """Manual start()/close() workflow works correctly."""
        client = AsyncInvinoClient()
        await client.start()
        try:
            with patch.object(client._client, "post", return_value=make_async_mock_response(200, REASON_SUCCESS_RESPONSE)):
                result = await client.reason(
                    "test question",
                    payment_hash=FAKE_PAYMENT_HASH,
                    preimage=FAKE_PREIMAGE,
                )
            assert isinstance(result, ReasoningResult)
        finally:
            await client.close()

    async def test_async_health_check(self):
        """Async check_health returns parsed dict."""
        async with AsyncInvinoClient() as client:
            with patch.object(client._client, "get", return_value=make_async_mock_response(200, HEALTH_RESPONSE)):
                result = await client.check_health()
        assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Two-step L402 flow integration (mocked end-to-end)
# ---------------------------------------------------------------------------

class TestTwoStepFlow:

    def test_full_reason_flow(self):
        """
        Simulates the complete L402 two-step flow:
        1. First call → PaymentRequired with invoice
        2. Pay (mocked) → get preimage
        3. Second call with credentials → ReasoningResult
        """
        client = InvinoClient()
        question = "Should I increase my BTC exposure in 2026?"

        # Step 1 — get invoice
        with patch.object(client._session, "post", return_value=make_mock_response(402, REASON_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc_info:
                client.reason(question)

        payment_required = exc_info.value
        assert payment_required.invoice == FAKE_INVOICE

        # Step 3 — retry with credentials
        with patch.object(client._session, "post", return_value=make_mock_response(200, REASON_SUCCESS_RESPONSE)):
            result = client.reason(
                question,
                payment_hash=payment_required.payment_hash,
                preimage=FAKE_PREIMAGE,
            )

        assert isinstance(result, ReasoningResult)
        assert result.answer != ""

    def test_full_decide_flow(self):
        """
        Simulates the complete L402 two-step flow for decide():
        1. First call → PaymentRequired
        2. Retry with credentials → DecisionResult
        """
        client = InvinoClient()

        # Step 1
        with patch.object(client._session, "post", return_value=make_mock_response(402, DECIDE_402_RESPONSE)):
            with pytest.raises(PaymentRequired) as exc_info:
                client.decide(goal="Grow capital", question="Increase BTC?")

        payment_required = exc_info.value

        # Step 2
        with patch.object(client._session, "post", return_value=make_mock_response(200, DECIDE_SUCCESS_RESPONSE)):
            result = client.decide(
                goal="Grow capital",
                question="Increase BTC?",
                payment_hash=payment_required.payment_hash,
                preimage=FAKE_PREIMAGE,
            )

        assert result.decision == "Increase BTC exposure slightly"
        assert 0.0 <= result.confidence <= 1.0
        assert result.risk_level in ("low", "medium", "high")

    def test_replay_protection(self):
        """Using the same payment_hash twice raises PaymentError."""
        client = InvinoClient()
        replay_response = make_mock_response(403, {"detail": "This invoice has already been used"})

        with patch.object(client._session, "post", return_value=replay_response):
            with pytest.raises(PaymentError):
                client.reason(
                    "test question",
                    payment_hash=FAKE_PAYMENT_HASH,
                    preimage=FAKE_PREIMAGE,
                )
