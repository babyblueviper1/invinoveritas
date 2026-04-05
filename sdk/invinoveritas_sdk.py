"""
invinoveritas SDK
~~~~~~~~~~~~~~~~~
Lightning-paid reasoning and decision intelligence for autonomous agents.

Install:
    pip install invinoveritas
    pip install "invinoveritas[async]"   # for AsyncInvinoClient
"""

import os
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any

import requests

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
    """
    def __init__(self, payment_hash: str, invoice: str, amount_sats: int):
        self.payment_hash = payment_hash
        self.invoice = invoice
        self.amount_sats = amount_sats
        super().__init__(
            f"Payment required: {amount_sats} sats. "
            f"Pay the invoice and retry with payment_hash + preimage.\n"
            f"Invoice: {invoice}"
        )


class PaymentError(InvinoError):
    """Raised when payment verification fails (already used, invalid preimage, etc.)."""


class ServiceError(InvinoError):
    """Raised when the service returns an unexpected error (5xx, malformed response, etc.)."""


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

@dataclass
class ReasoningResult:
    answer: str
    payment_hash: Optional[str] = None
    amount_sats: int = 0


@dataclass
class DecisionResult:
    decision: str
    confidence: float
    reasoning: str
    risk_level: str
    payment_hash: Optional[str] = None
    amount_sats: int = 0


# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------

def _auth_header(payment_hash: str, preimage: str) -> str:
    return f"L402 {payment_hash}:{preimage}"


def _parse_402(body: dict) -> None:
    try:
        detail = body.get("detail", body)  # some responses put fields at root
        raise PaymentRequired(
            payment_hash=detail["payment_hash"],
            invoice=detail["invoice"],
            amount_sats=detail["amount_sats"],
        )
    except PaymentRequired:
        raise
    except Exception as e:
        raise ServiceError(f"Unexpected 402 response format: {body}") from e


def _raise_for_status(status_code: int, body: dict, raw_text: str) -> None:
    if status_code == 402:
        _parse_402(body)
    elif status_code in (401, 403):
        raise PaymentError(f"Payment error ({status_code}): {body.get('detail', raw_text)}")
    elif status_code == 429:
        raise InvinoError("Rate limited. Please wait before retrying.")
    elif status_code >= 500:
        raise ServiceError(f"Service error ({status_code}): {raw_text}")
    else:
        raise InvinoError(f"Unexpected error ({status_code}): {raw_text}")


# ---------------------------------------------------------------------------
# Sync Client
# ---------------------------------------------------------------------------

class InvinoClient:
    """Synchronous client for the invinoveritas API."""

    def __init__(self, base_url: str = BASE_URL, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    def _post(self, path: str, payload: dict, payment_hash: Optional[str] = None, preimage: Optional[str] = None) -> dict:
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

    # ====================== Main Tools ======================

    def reason(self, question: str, payment_hash: Optional[str] = None, preimage: Optional[str] = None) -> ReasoningResult:
        data = self._post("/reason", {"question": question}, payment_hash, preimage)
        return ReasoningResult(
            answer=data["answer"],
            payment_hash=payment_hash,
        )

    def decide(
        self,
        goal: str,
        question: str,
        context: str = "",
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> DecisionResult:
        payload = {"goal": goal, "question": question, "context": context}
        data = self._post("/decision", payload, payment_hash, preimage)
        result = data.get("result", {})
        return DecisionResult(
            decision=result["decision"],
            confidence=result["confidence"],
            reasoning=result["reasoning"],
            risk_level=result["risk_level"],
            payment_hash=payment_hash,
        )

    # ====================== Meta / Utility ======================

    def check_health(self) -> dict:
        """Get rich health and service metadata."""
        response = self._session.get(f"{self.base_url}/health", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_prices(self) -> dict:
        """Get detailed pricing for all tools (recommended)."""
        response = self._session.get(f"{self.base_url}/prices", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_price(self, endpoint: str) -> int:
        """Get base price for a single endpoint (backward compatibility)."""
        if endpoint not in ["reason", "decision", "mcp"]:
            raise ValueError("endpoint must be 'reason', 'decision', or 'mcp'")
        response = self._session.get(f"{self.base_url}/price/{endpoint}", timeout=self.timeout)
        response.raise_for_status()
        return response.json().get("price_sats", 0)

    def get_tool_definition(self) -> dict:
        """Get tool definition for agent frameworks."""
        response = self._session.get(f"{self.base_url}/tool", timeout=self.timeout)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Async Client
# ---------------------------------------------------------------------------

class AsyncInvinoClient:
    """Asynchronous client for the invinoveritas API."""

    def __init__(self, base_url: str = BASE_URL, timeout: int = 30):
        if not _HTTPX_AVAILABLE:
            raise ImportError(
                "httpx is required for AsyncInvinoClient. "
                "Install with: pip install 'invinoveritas[async]'"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self):
        self._client = httpx.AsyncClient(
            headers={"Content-Type": "application/json"},
            timeout=self.timeout,
        )

    async def close(self):
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
                "Use 'async with AsyncInvinoClient() as client:' or await client.start()"
            )

    async def _post(self, path: str, payload: dict, payment_hash: Optional[str] = None, preimage: Optional[str] = None) -> dict:
        self._ensure_started()
        headers = {}
        if payment_hash and preimage:
            headers["Authorization"] = _auth_header(payment_hash, preimage)

        response = await self._client.post(f"{self.base_url}{path}", json=payload, headers=headers)

        if not response.is_success:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)

        return response.json()

    # ====================== Main Tools ======================

    async def reason(self, question: str, payment_hash: Optional[str] = None, preimage: Optional[str] = None) -> ReasoningResult:
        data = await self._post("/reason", {"question": question}, payment_hash, preimage)
        return ReasoningResult(answer=data["answer"], payment_hash=payment_hash)

    async def decide(
        self,
        goal: str,
        question: str,
        context: str = "",
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> DecisionResult:
        payload = {"goal": goal, "question": question, "context": context}
        data = await self._post("/decision", payload, payment_hash, preimage)
        result = data.get("result", {})
        return DecisionResult(
            decision=result["decision"],
            confidence=result["confidence"],
            reasoning=result["reasoning"],
            risk_level=result["risk_level"],
            payment_hash=payment_hash,
        )

    # ====================== Meta / Utility ======================

    async def check_health(self) -> dict:
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    async def get_prices(self) -> dict:
        """Get detailed pricing for all tools."""
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/prices")
        response.raise_for_status()
        return response.json()

    async def get_price(self, endpoint: str) -> int:
        """Get base price for a single endpoint."""
        self._ensure_started()
        if endpoint not in ["reason", "decision", "mcp"]:
            raise ValueError("endpoint must be 'reason', 'decision', or 'mcp'")
        response = await self._client.get(f"{self.base_url}/price/{endpoint}")
        response.raise_for_status()
        return response.json().get("price_sats", 0)

    async def get_tool_definition(self) -> dict:
        """Get tool definition for agent discovery."""
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/tool")
        response.raise_for_status()
        return response.json()
