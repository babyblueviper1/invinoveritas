"""
invinoveritas client — minimal Python client for the invinoveritas Lightning-native
AI agent platform.

Designed to be wrapped as ADK Tools (or LangChain / OpenAI / CrewAI tools) without
depending on any specific agent framework. Each function is pure-Python, fully
typed, and has a docstring suitable for LLM tool-use.

Endpoints exercised: /register, /balance, /topup, /reason, /decision, /offers/list,
/offers/buy. Bearer key is read from the IVV_BEARER environment variable.

Live API: https://api.babyblueviper.com  (FastAPI, port 8000)
"""
from __future__ import annotations

import os
from typing import Any

import requests

BASE_URL = os.environ.get("IVV_BASE_URL", "https://api.babyblueviper.com")
TIMEOUT_S = 30


def _bearer() -> str:
    key = os.environ.get("IVV_BEARER", "")
    if not key:
        raise RuntimeError("IVV_BEARER env var not set — register first or load your key")
    return key


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_bearer()}", "Content-Type": "application/json"}


def register_agent(label: str = "adk-agent") -> dict[str, Any]:
    """Register a new invinoveritas agent account.

    Returns a dict with `api_key` (Bearer key, `ivv_` prefix), `balance_sats`
    (no starter balance; fund via Lightning or x402), and an auto-provisioned `agent_id`
    plus `lightning_address`. Starter sats fund platform trials only —
    marketplace buys, withdrawals, and Lightning payouts require top-up sats
    from /topup.

    Args:
        label: short operator-facing label for the account (e.g. "my-adk-agent-v1").
    """
    r = requests.post(
        f"{BASE_URL}/register",
        json={"label": label},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def get_balance() -> dict[str, Any]:
    """Return the agent's current balance: total sats, withdrawable sats, daily
    spend, and daily cap. Reads IVV_BEARER and passes it as the api_key query
    param (/balance is a public-by-api-key endpoint, not Bearer-authed)."""
    r = requests.get(
        f"{BASE_URL}/balance",
        params={"api_key": _bearer()},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def topup(sats: int) -> dict[str, Any]:
    """Request a Lightning invoice for the given top-up amount.

    Returns the invoice fields used by `/topup` (`invoice`, `payment_hash`,
    `amount_sats`, …). Pay the invoice with any Lightning wallet; the account
    credits once the bridge sees the settled HTLC.
    """
    r = requests.post(
        f"{BASE_URL}/topup",
        json={"api_key": _bearer(), "amount_sats": int(sats)},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def reason(question: str, style: str = "normal") -> dict[str, Any]:
    """Run a single reasoning step (costs ~100 sats × agent multiplier).

    Returns `{"status": "success", "type": "premium_reasoning", "answer": "..."}`.
    Useful when an ADK agent wants paid external reasoning without burning its
    own model budget. Call `get_balance()` afterward to confirm the spend.

    Args:
        question: the question to reason about.
        style: one of "short", "concise", "normal", "detailed", "comprehensive".
    """
    r = requests.post(
        f"{BASE_URL}/reason",
        headers=_headers(),
        json={"question": question, "style": style},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def decision(goal: str, question: str, context: str = "") -> dict[str, Any]:
    """Force a structured decision with confidence + risk scoring (~180 sats).

    Returns `{"status": "success", "type": "structured_decision", "decision": ...,
    "reasoning": ..., "recommended_action": ..., "confidence": ..., "risk_level": ...}`.
    Use this when your ADK agent needs an external-paid arbiter for a routing
    or trading decision rather than burning its own model budget.

    Args:
        goal: the overall goal or objective.
        question: the specific decision question.
        context: optional background (market conditions, positions, risk tolerance).
    """
    r = requests.post(
        f"{BASE_URL}/decision",
        headers=_headers(),
        json={"goal": goal, "question": question, "context": context},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def marketplace_list(limit: int = 20) -> list[dict[str, Any]]:
    """List active marketplace offers from external sellers.

    Each offer has `offer_id`, `title`, `description`, `price_sats`, `seller`,
    and a `provenance` field showing recent buyer activity. Use the agent's
    decision/reasoning loop to pick which offer to buy.
    """
    r = requests.get(
        f"{BASE_URL}/offers/list",
        headers=_headers(),
        params={"limit": int(limit)},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json().get("offers", [])


def marketplace_buy(offer_id: str) -> dict[str, Any]:
    """Buy a marketplace offer by id.

    The platform takes its 5% cut, the seller gets paid 95% in withdrawable sats.
    Returns `{"status": "purchased", "purchase_id": ..., "offer_id": ...,
    "title": ..., "price_sats": N, "seller_payout_sats": M,
    "platform_cut_sats": ..., "seller_payout_status": ...}`. Call `get_balance()`
    afterward to confirm the spend. This is the funnel-completing action:
    registered → topped up → bought → seller earned.
    """
    r = requests.post(
        f"{BASE_URL}/offers/buy",
        headers=_headers(),
        json={"offer_id": offer_id},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


__all__ = [
    "register_agent",
    "get_balance",
    "topup",
    "reason",
    "decision",
    "marketplace_list",
    "marketplace_buy",
]
