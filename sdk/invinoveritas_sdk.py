"""
invinoveritas SDK
~~~~~~~~~~~~~~~~~
Lightning-paid reasoning and decision intelligence for autonomous agents.

Install:
    pip install invinoveritas
    pip install invinoveritas[async]   # for AsyncInvinoClient

Sync quickstart:
    from invinoveritas_sdk import InvinoClient, PaymentRequired

    client = InvinoClient()

    try:
        result = client.reason("What are the biggest risks for Bitcoin in 2026?")
    except PaymentRequired as e:
        print(f"Pay this invoice: {e.invoice}")
        print(f"Amount: {e.amount_sats} sats")
        # pay via your Lightning wallet, then:
        result = client.reason(
            "What are the biggest risks for Bitcoin in 2026?",
            payment_hash=e.payment_hash,
            preimage="your_preimage_here"
        )
        print(result.answer)

Async quickstart:
    import asyncio
    from invinoveritas_sdk import AsyncInvinoClient, PaymentRequired

    async def main():
        async with AsyncInvinoClient() as client:
            try:
                result = await client.reason("What are the biggest risks for Bitcoin in 2026?")
            except PaymentRequired as e:
                result = await client.reason(
                    "What are the biggest risks for Bitcoin in 2026?",
                    payment_hash=e.payment_hash,
                    preimage="your_preimage_here"
                )
                print(result.answer)

    asyncio.run(main())
"""

import requests
from dataclasses import dataclass
from typing import Optional

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


BASE_URL = "https://invinoveritas.onrender.com"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvinoError(Exception):
    """Base exception for all invinoveritas SDK errors."""


class PaymentRequired(InvinoError):
    """
    Raised when the server returns 402 Payment Required.

    Attributes:
        payment_hash: Lightning payment hash for the Authorization header.
        invoice:      The bolt11 invoice to pay.
        amount_sats:  Amount in satoshis.
    """
    def __init__(self, payment_hash: str, invoice: str, amount_sats: int):
        self.payment_hash = payment_hash
        self.invoice = invoice
        self.amount_sats = amount_sats
        super().__init__(
            f"Payment required: {amount_sats} sats. "
            f"Pay invoice and retry with payment_hash + preimage.\n"
            f"Invoice: {invoice}"
        )


class PaymentError(InvinoError):
    """Raised when payment verification fails (already used, invalid preimage, etc.)."""


class ServiceError(InvinoError):
    """Raised when the invinoveritas service returns an unexpected error."""


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

@dataclass
class ReasoningResult:
    answer: str
    payment_hash: str
    amount_sats: int


@dataclass
class DecisionResult:
    decision: str
    confidence: float
    reasoning: str
    risk_level: str
    payment_hash: str
    amount_sats: int


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _auth_header(payment_hash: str, preimage: str) -> str:
    return f"L402 {payment_hash}:{preimage}"


def _parse_402(body: dict) -> None:
    try:
        detail = body.get("detail", {})
        raise PaymentRequired(
            payment_hash=detail["payment_hash"],
            invoice=detail["invoice"],
            amount_sats=detail["amount_sats"],
        )
    except PaymentRequired:
        raise
    except Exception:
        raise ServiceError(f"Unexpected 402 response: {body}")


def _raise_for_status(status_code: int, body: dict, raw: str) -> None:
    if status_code == 402:
        _parse_402(body)
    elif status_code in (401, 403):
        detail = body.get("detail", raw) if body else raw
        raise PaymentError(f"Payment error ({status_code}): {detail}")
    elif status_code == 429:
        raise InvinoError("Rate limited. Wait a moment before retrying.")
    else:
        raise ServiceError(f"Service error ({status_code}): {raw}")


def _parse_reasoning(data: dict, payment_hash: Optional[str]) -> ReasoningResult:
    return ReasoningResult(
        answer=data["answer"],
        payment_hash=payment_hash or "",
        amount_sats=0,
    )


def _parse_decision(data: dict, payment_hash: Optional[str]) -> DecisionResult:
    result = data["result"]
    return DecisionResult(
        decision=result["decision"],
        confidence=result["confidence"],
        reasoning=result["reasoning"],
        risk_level=result["risk_level"],
        payment_hash=payment_hash or "",
        amount_sats=0,
    )


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------

class InvinoClient:
    """
    Synchronous client for the invinoveritas API.

    Args:
        base_url: Override the default API URL (useful for local dev).
        timeout:  HTTP timeout in seconds (default: 30).

    Usage::

        client = InvinoClient()

        # Step 1 — get the invoice
        try:
            result = client.reason("Should I invest in AI infrastructure?")
        except PaymentRequired as e:
            payment_hash = e.payment_hash   # save this
            # pay e.invoice with your Lightning wallet, then:

        # Step 2 — retry with credentials
        result = client.reason(
            "Should I invest in AI infrastructure?",
            payment_hash=payment_hash,
            preimage="preimage_from_your_wallet"
        )
        print(result.answer)
    """

    def __init__(self, base_url: str = BASE_URL, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def _post(self, path: str, payload: dict, payment_hash: Optional[str], preimage: Optional[str]) -> dict:
        headers = {}
        if payment_hash and preimage:
            headers["Authorization"] = _auth_header(payment_hash, preimage)
        response = self._session.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=headers,
            timeout=self.timeout,
        )
        if not response.ok:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)
        return response.json()

    def reason(
        self,
        question: str,
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> ReasoningResult:
        """
        Strategic reasoning. Raises PaymentRequired on first call with the bolt11 invoice.

        Args:
            question:     The question to reason about.
            payment_hash: From a previous PaymentRequired exception.
            preimage:     From your Lightning wallet after paying.

        Returns:
            ReasoningResult with .answer
        """
        data = self._post("/reason", {"question": question}, payment_hash, preimage)
        return _parse_reasoning(data, payment_hash)

    def decide(
        self,
        goal: str,
        question: str,
        context: str = "",
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> DecisionResult:
        """
        Structured decision intelligence. Raises PaymentRequired on first call.

        Args:
            goal:         What you are trying to achieve.
            question:     The specific decision question.
            context:      Optional background context.
            payment_hash: From a previous PaymentRequired exception.
            preimage:     From your Lightning wallet after paying.

        Returns:
            DecisionResult with .decision, .confidence, .reasoning, .risk_level
        """
        data = self._post(
            "/decision",
            {"goal": goal, "context": context, "question": question},
            payment_hash,
            preimage,
        )
        return _parse_decision(data, payment_hash)

    def check_health(self) -> dict:
        """Fetch /health. Free, no payment required."""
        response = self._session.get(f"{self.base_url}/health", timeout=self.timeout)
        if not response.ok:
            raise ServiceError(f"Health check failed ({response.status_code})")
        return response.json()

    def get_price(self, endpoint: str) -> int:
        """Get current base price in sats for 'reason', 'decision', or 'mcp'."""
        response = self._session.get(f"{self.base_url}/price/{endpoint}", timeout=self.timeout)
        if not response.ok:
            raise ServiceError(f"Price check failed ({response.status_code})")
        return response.json().get("price_sats", 0)


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------

class AsyncInvinoClient:
    """
    Async client for the invinoveritas API.
    Requires httpx: pip install invinoveritas[async]

    Usage (context manager — recommended)::

        async with AsyncInvinoClient() as client:
            try:
                result = await client.reason("What are Bitcoin's biggest risks?")
            except PaymentRequired as e:
                result = await client.reason(
                    "What are Bitcoin's biggest risks?",
                    payment_hash=e.payment_hash,
                    preimage="your_preimage"
                )
                print(result.answer)

    LangChain tool example::

        async def invino_reason_tool(question: str, payment_hash: str, preimage: str) -> str:
            async with AsyncInvinoClient() as client:
                result = await client.reason(question, payment_hash, preimage)
                return result.answer

    AutoGen tool example::

        @tool
        async def reason_tool(question: str, payment_hash: str, preimage: str) -> str:
            async with AsyncInvinoClient() as client:
                result = await client.reason(question, payment_hash, preimage)
                return result.answer
    """

    def __init__(self, base_url: str = BASE_URL, timeout: int = 30):
        if not _HTTPX_AVAILABLE:
            raise ImportError(
                "httpx is required for AsyncInvinoClient. "
                "Install with: pip install invinoveritas[async]"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional["httpx.AsyncClient"] = None

    async def start(self):
        """Initialise the underlying httpx client."""
        self._client = httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )

    async def close(self):
        """Close the underlying httpx client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.close()

    def _ensure_started(self):
        if self._client is None:
            raise RuntimeError(
                "AsyncInvinoClient not started. "
                "Use 'async with AsyncInvinoClient() as client:' or call await client.start() first."
            )

    async def _post(self, path: str, payload: dict, payment_hash: Optional[str], preimage: Optional[str]) -> dict:
        self._ensure_started()
        headers = {}
        if payment_hash and preimage:
            headers["Authorization"] = _auth_header(payment_hash, preimage)
        response = await self._client.post(
            f"{self.base_url}{path}",
            json=payload,
            headers=headers,
        )
        if not response.is_success:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)
        return response.json()

    async def reason(
        self,
        question: str,
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> ReasoningResult:
        """Async version of reason(). See InvinoClient.reason() for full docs."""
        data = await self._post("/reason", {"question": question}, payment_hash, preimage)
        return _parse_reasoning(data, payment_hash)

    async def decide(
        self,
        goal: str,
        question: str,
        context: str = "",
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> DecisionResult:
        """Async version of decide(). See InvinoClient.decide() for full docs."""
        data = await self._post(
            "/decision",
            {"goal": goal, "context": context, "question": question},
            payment_hash,
            preimage,
        )
        return _parse_decision(data, payment_hash)

    async def check_health(self) -> dict:
        """Async health check. Free, no payment required."""
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/health")
        if not response.is_success:
            raise ServiceError(f"Health check failed ({response.status_code})")
        return response.json()

    async def get_price(self, endpoint: str) -> int:
        """Async price check in sats for 'reason', 'decision', or 'mcp'."""
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/price/{endpoint}")
        if not response.is_success:
            raise ServiceError(f"Price check failed ({response.status_code})")
        return response.json().get("price_sats", 0)


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def reason(
    question: str,
    payment_hash: Optional[str] = None,
    preimage: Optional[str] = None,
    base_url: str = BASE_URL,
) -> ReasoningResult:
    """Shortcut: InvinoClient().reason(...) without instantiating a client."""
    return InvinoClient(base_url=base_url).reason(question, payment_hash, preimage)


def decide(
    goal: str,
    question: str,
    context: str = "",
    payment_hash: Optional[str] = None,
    preimage: Optional[str] = None,
    base_url: str = BASE_URL,
) -> DecisionResult:
    """Shortcut: InvinoClient().decide(...) without instantiating a client."""
    return InvinoClient(base_url=base_url).decide(
        goal, question, context, payment_hash, preimage
    )
