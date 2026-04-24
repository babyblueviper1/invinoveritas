"""
invinoveritas SDK v1.1.0
~~~~~~~~~~~~~~~~~~~~~~~~
Lightning-native AI reasoning, decisions, memory, orchestration,
and agent marketplace. Pay-per-use over Bitcoin Lightning.

Install:
    pip install invinoveritas
    pip install "invinoveritas[nwc]"      # NWC wallet (recommended)
    pip install "invinoveritas[async]"    # AsyncInvinoClient
    pip install "invinoveritas[langchain]" # LangChain autonomous payments
"""

import os
import time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

import requests

try:
    import httpx
    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False


__version__ = "1.1.0"
BASE_URL = "https://api.babyblueviper.com"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class InvinoError(Exception):
    """Base exception for all invinoveritas SDK errors."""


class PaymentRequired(InvinoError):
    """Raised when the server returns 402 Payment Required."""
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
    """Raised when the service returns an unexpected error (5xx, malformed response)."""


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


@dataclass
class OrchestrationResult:
    execution_order: List[str]
    task_count: int
    risk_scores: Dict[str, Any]
    estimated_total_sats: int
    orchestration_cost_sats: int
    policy_applied: Dict


@dataclass
class MarketplaceOffer:
    offer_id: str
    seller_id: str
    title: str
    description: str
    price_sats: int
    seller_payout_sats: int
    platform_cut_sats: int
    category: str
    sold_count: int

    @classmethod
    def from_dict(cls, d: dict) -> "MarketplaceOffer":
        return cls(
            offer_id=d["offer_id"],
            seller_id=d.get("seller_id", ""),
            title=d["title"],
            description=d.get("description", ""),
            price_sats=d["price_sats"],
            seller_payout_sats=d["seller_payout_sats"],
            platform_cut_sats=d["platform_cut_sats"],
            category=d.get("category", "agent"),
            sold_count=d.get("sold_count", 0),
        )


@dataclass
class Purchase:
    purchase_id: str
    offer_id: str
    title: str
    price_sats: int
    platform_cut_sats: int
    seller_payout_sats: int
    seller_payout_status: str

    @classmethod
    def from_dict(cls, d: dict) -> "Purchase":
        return cls(
            purchase_id=d["purchase_id"],
            offer_id=d["offer_id"],
            title=d["title"],
            price_sats=d["price_sats"],
            platform_cut_sats=d["platform_cut_sats"],
            seller_payout_sats=d["seller_payout_sats"],
            seller_payout_status=d.get("seller_payout_status", "unknown"),
        )


# ---------------------------------------------------------------------------
# Shared Helpers
# ---------------------------------------------------------------------------

def _auth_header(payment_hash: str, preimage: str) -> str:
    return f"L402 {payment_hash}:{preimage}"


def _parse_402(body: dict) -> None:
    try:
        detail = body.get("detail", body)
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
    """
    Synchronous client for the invinoveritas API.

    Quick start (NWC — recommended):
        client = InvinoClient(bearer_token="your-api-key")
        result = client.reason("Should I buy BTC now?")

    Quick start (manual L402):
        client = InvinoClient()
        try:
            result = client.reason("...")
        except PaymentRequired as e:
            # pay e.invoice with any wallet, then:
            result = client.reason("...", payment_hash=e.payment_hash, preimage="...")
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        bearer_token: Optional[str] = None,
        timeout: int = 30,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._bearer_token = bearer_token or os.environ.get("INVINO_API_KEY", "")
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        if self._bearer_token:
            self._session.headers.update({"Authorization": f"Bearer {self._bearer_token}"})

    def _post(self, path: str, payload: dict,
              payment_hash: Optional[str] = None,
              preimage: Optional[str] = None) -> dict:
        headers = {}
        if payment_hash and preimage:
            headers["Authorization"] = _auth_header(payment_hash, preimage)
        response = self._session.post(
            f"{self.base_url}{path}", json=payload, headers=headers, timeout=self.timeout
        )
        if not response.ok:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)
        return response.json()

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        response = self._session.get(
            f"{self.base_url}{path}", params=params, timeout=self.timeout
        )
        if not response.ok:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)
        return response.json()

    # ====================== Core AI Tools ======================

    def reason(
        self,
        question: str,
        policy: Optional[Dict] = None,
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> ReasoningResult:
        """Deep strategic reasoning. ~500 sats."""
        payload = {"question": question}
        if policy:
            payload["policy"] = policy
        data = self._post("/reason", payload, payment_hash, preimage)
        return ReasoningResult(answer=data["answer"], payment_hash=payment_hash)

    def decide(
        self,
        goal: str,
        question: str,
        context: str = "",
        policy: Optional[Dict] = None,
        payment_hash: Optional[str] = None,
        preimage: Optional[str] = None,
    ) -> DecisionResult:
        """Structured decision intelligence. ~1000 sats."""
        payload = {"goal": goal, "question": question, "context": context}
        if policy:
            payload["policy"] = policy
        data = self._post("/decision", payload, payment_hash, preimage)
        result = data.get("result", {})
        return DecisionResult(
            decision=result["decision"],
            confidence=result["confidence"],
            reasoning=result["reasoning"],
            risk_level=result["risk_level"],
            payment_hash=payment_hash,
        )

    # ====================== Orchestration ======================

    def orchestrate(
        self,
        tasks: List[Dict],
        context: str = "",
        agent_id: str = "",
        policy: Optional[Dict] = None,
    ) -> OrchestrationResult:
        """
        Multi-agent orchestration with dependency resolution and risk scoring.
        ~2000 sats per plan.

        Example:
            result = client.orchestrate([
                {"id": "t1", "type": "reason",
                 "input": {"question": "Is BTC in accumulation?"}, "depends_on": []},
                {"id": "t2", "type": "decide",
                 "input": {"goal": "...", "question": "..."}, "depends_on": ["t1"]},
            ])
            for tid in result.execution_order:
                print(f"Execute task: {tid}, risk: {result.risk_scores[tid]['label']}")
        """
        payload = {
            "tasks": tasks,
            "context": context,
            "agent_id": agent_id,
        }
        if policy:
            payload["policy"] = policy
        data = self._post("/orchestrate", payload)
        return OrchestrationResult(
            execution_order=data["execution_order"],
            task_count=data["task_count"],
            risk_scores=data["risk_scores"],
            estimated_total_sats=data["estimated_total_sats"],
            orchestration_cost_sats=data["orchestration_cost_sats"],
            policy_applied=data.get("policy_applied", {}),
        )

    # ====================== Marketplace ======================

    def create_offer(
        self,
        title: str,
        description: str,
        price_sats: int,
        ln_address: str,
        category: str = "agent",
        seller_id: Optional[str] = None,
    ) -> dict:
        """
        List a new offer on the Lightning marketplace.
        You receive 90% of every sale instantly to your ln_address.
        Invinoveritas keeps 10% as a platform fee.

        Args:
            ln_address: Your Lightning Address (e.g. you@getalby.com)
                        — this is where your 90% payouts are sent.
        """
        payload = {
            "title": title,
            "description": description,
            "price_sats": price_sats,
            "ln_address": ln_address,
            "category": category,
            "seller_id": seller_id or self._bearer_token[:16] if self._bearer_token else "anonymous",
        }
        return self._post("/offers/create", payload)

    def list_offers(
        self,
        category: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[MarketplaceOffer]:
        """Browse all active marketplace offers."""
        params = {"limit": limit, "offset": offset}
        if category:
            params["category"] = category
        data = self._get("/offers/list", params=params)
        return [MarketplaceOffer.from_dict(o) for o in data.get("offers", [])]

    def buy_offer(self, offer_id: str) -> Purchase:
        """
        Purchase a marketplace offer.
        Bearer account is charged. Seller receives 90% instantly via Lightning.
        """
        data = self._post("/offers/buy", {"offer_id": offer_id})
        return Purchase.from_dict(data)

    def my_offers(self) -> dict:
        """List all offers you've created as a seller, with earnings breakdown."""
        return self._get("/offers/my")

    # ====================== Analytics ======================

    def analytics_spend(self, days: int = 30) -> dict:
        """Spending history for this account over the last N days."""
        return self._get("/analytics/spend", params={"days": days})

    def analytics_roi(self) -> dict:
        """ROI summary — lifetime spend, calls, marketplace earnings, net sats."""
        return self._get("/analytics/roi")

    def analytics_memory(self, agent_id: Optional[str] = None) -> dict:
        """Memory usage stats — KB stored, per-agent breakdown, estimated costs."""
        params = {}
        if agent_id:
            params["agent_id"] = agent_id
        return self._get("/analytics/memory", params=params)

    # ====================== Cost Optimization ======================

    def optimize_call(self, question: str, context: dict = None) -> dict:
        """
        Returns the cheapest endpoint + estimated cost for a given question.
        Use this to decide between reason() and decide() based on task complexity.

        Returns:
            {
                "recommended_endpoint": "reason" | "decide" | "local",
                "estimated_sats": int,
                "reason": str,
                "should_call_api": bool,
            }
        """
        ctx = context or {}
        steps = ctx.get("steps", 1)
        uncertainty = ctx.get("uncertainty", 0.0)
        value_at_risk = ctx.get("value_at_risk", 0)
        requires_reasoning = ctx.get("requires_reasoning", False)
        q_len = len(question)

        score = 0
        reasons = []

        if steps > 3:
            score += 2
            reasons.append(f"multi-step task ({steps} steps)")
        elif steps > 1:
            score += 1
            reasons.append(f"2-step task")

        if uncertainty > 0.7:
            score += 2
            reasons.append(f"high uncertainty ({uncertainty:.0%})")
        elif uncertainty > 0.4:
            score += 1
            reasons.append(f"moderate uncertainty ({uncertainty:.0%})")

        if value_at_risk > 50000:
            score += 3
            reasons.append(f"very high value at risk ({value_at_risk:,} sats)")
        elif value_at_risk > 5000:
            score += 2
            reasons.append(f"high value at risk ({value_at_risk:,} sats)")
        elif value_at_risk > 500:
            score += 1
            reasons.append(f"moderate value at risk ({value_at_risk:,} sats)")

        if requires_reasoning:
            score += 2
            reasons.append("explicitly requires deep reasoning")

        if q_len > 300:
            score += 1
            reasons.append("long/complex question")

        if score == 0:
            return {
                "recommended_endpoint": "local",
                "estimated_sats": 0,
                "should_call_api": False,
                "reason": "Simple task — use a local model or cached answer.",
                "score": score,
            }
        elif score <= 2:
            return {
                "recommended_endpoint": "reason",
                "estimated_sats": 500,
                "should_call_api": True,
                "reason": f"Medium complexity: {', '.join(reasons)}. Use reason().",
                "score": score,
            }
        else:
            return {
                "recommended_endpoint": "decide",
                "estimated_sats": 1000,
                "should_call_api": True,
                "reason": f"High stakes: {', '.join(reasons)}. Use decide() for structured output.",
                "score": score,
            }

    # ====================== Memory ======================

    def memory_store(self, agent_id: str, key: str, value: str) -> dict:
        return self._post("/memory/store", {"agent_id": agent_id, "key": key, "value": value})

    def memory_get(self, agent_id: str, key: str) -> dict:
        return self._post("/memory/get", {"agent_id": agent_id, "key": key})

    def memory_delete(self, agent_id: str, key: str) -> dict:
        return self._post("/memory/delete", {"agent_id": agent_id, "key": key})

    def memory_list(self, agent_id: str) -> dict:
        return self._post("/memory/list", {"agent_id": agent_id})

    # ====================== Meta / Utility ======================

    def check_health(self) -> dict:
        response = self._session.get(f"{self.base_url}/health", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_prices(self) -> dict:
        response = self._session.get(f"{self.base_url}/prices", timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_price(self, endpoint: str) -> int:
        if endpoint not in ["reason", "decision", "mcp"]:
            raise ValueError("endpoint must be 'reason', 'decision', or 'mcp'")
        response = self._session.get(f"{self.base_url}/price/{endpoint}", timeout=self.timeout)
        response.raise_for_status()
        return response.json().get("price_sats", 0)

    def get_tool_definition(self) -> dict:
        response = self._session.get(f"{self.base_url}/tool", timeout=self.timeout)
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Async Client
# ---------------------------------------------------------------------------

class AsyncInvinoClient:
    """Asynchronous client for the invinoveritas API."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        bearer_token: Optional[str] = None,
        timeout: int = 30,
    ):
        if not _HTTPX_AVAILABLE:
            raise ImportError(
                "httpx is required for AsyncInvinoClient. "
                "Install with: pip install 'invinoveritas[async]'"
            )
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._bearer_token = bearer_token or os.environ.get("INVINO_API_KEY", "")
        self._client: Optional[httpx.AsyncClient] = None

    async def start(self):
        headers = {"Content-Type": "application/json"}
        if self._bearer_token:
            headers["Authorization"] = f"Bearer {self._bearer_token}"
        self._client = httpx.AsyncClient(headers=headers, timeout=self.timeout)

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
                "Use 'async with AsyncInvinoClient() as client:'"
            )

    async def _post(self, path: str, payload: dict,
                    payment_hash: Optional[str] = None,
                    preimage: Optional[str] = None) -> dict:
        self._ensure_started()
        headers = {}
        if payment_hash and preimage:
            headers["Authorization"] = _auth_header(payment_hash, preimage)
        response = await self._client.post(
            f"{self.base_url}{path}", json=payload, headers=headers
        )
        if not response.is_success:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)
        return response.json()

    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}{path}", params=params)
        if not response.is_success:
            try:
                body = response.json()
            except Exception:
                body = {}
            _raise_for_status(response.status_code, body, response.text)
        return response.json()

    # ====================== Core AI Tools ======================

    async def reason(self, question: str, policy: Optional[Dict] = None,
                     payment_hash: Optional[str] = None,
                     preimage: Optional[str] = None) -> ReasoningResult:
        payload = {"question": question}
        if policy:
            payload["policy"] = policy
        data = await self._post("/reason", payload, payment_hash, preimage)
        return ReasoningResult(answer=data["answer"], payment_hash=payment_hash)

    async def decide(self, goal: str, question: str, context: str = "",
                     policy: Optional[Dict] = None,
                     payment_hash: Optional[str] = None,
                     preimage: Optional[str] = None) -> DecisionResult:
        payload = {"goal": goal, "question": question, "context": context}
        if policy:
            payload["policy"] = policy
        data = await self._post("/decision", payload, payment_hash, preimage)
        result = data.get("result", {})
        return DecisionResult(
            decision=result["decision"],
            confidence=result["confidence"],
            reasoning=result["reasoning"],
            risk_level=result["risk_level"],
            payment_hash=payment_hash,
        )

    async def orchestrate(self, tasks: List[Dict], context: str = "",
                          agent_id: str = "",
                          policy: Optional[Dict] = None) -> OrchestrationResult:
        payload = {"tasks": tasks, "context": context, "agent_id": agent_id}
        if policy:
            payload["policy"] = policy
        data = await self._post("/orchestrate", payload)
        return OrchestrationResult(
            execution_order=data["execution_order"],
            task_count=data["task_count"],
            risk_scores=data["risk_scores"],
            estimated_total_sats=data["estimated_total_sats"],
            orchestration_cost_sats=data["orchestration_cost_sats"],
            policy_applied=data.get("policy_applied", {}),
        )

    async def list_offers(self, category: Optional[str] = None,
                          limit: int = 50) -> List[MarketplaceOffer]:
        params = {"limit": limit}
        if category:
            params["category"] = category
        data = await self._get("/offers/list", params=params)
        return [MarketplaceOffer.from_dict(o) for o in data.get("offers", [])]

    async def buy_offer(self, offer_id: str) -> Purchase:
        data = await self._post("/offers/buy", {"offer_id": offer_id})
        return Purchase.from_dict(data)

    async def analytics_spend(self, days: int = 30) -> dict:
        return await self._get("/analytics/spend", params={"days": days})

    async def analytics_roi(self) -> dict:
        return await self._get("/analytics/roi")

    async def check_health(self) -> dict:
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    async def get_prices(self) -> dict:
        self._ensure_started()
        response = await self._client.get(f"{self.base_url}/prices")
        response.raise_for_status()
        return response.json()


# ---------------------------------------------------------------------------
# Smart Usage (High-Level API)
# ---------------------------------------------------------------------------

from .smart import (
    smart_reason,
    smart_decide,
    async_smart_reason,
    async_smart_decide,
    should_call_invinoveritas,
)
