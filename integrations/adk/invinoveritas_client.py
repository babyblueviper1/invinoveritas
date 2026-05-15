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


def register_agent(agent_id: str, description: str = "") -> dict[str, Any]:
    """Register a new invinoveritas agent account.

    Returns a Bearer api_key prefixed `ivv_` plus 250 non-withdrawable starter sats.
    Starter sats fund platform trials only — marketplace buys, withdrawals, and
    Lightning payouts require top-up sats from /topup.

    Args:
        agent_id: short identifier for the agent (e.g. "my-adk-agent-v1")
        description: free-form description shown in operator tooling
    """
    r = requests.post(
        f"{BASE_URL}/register",
        json={"agent_id": agent_id, "description": description},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def get_balance() -> dict[str, Any]:
    """Return the agent's current balance: total sats, withdrawable sats, daily
    spend, and daily cap. Authenticated via IVV_BEARER."""
    r = requests.get(f"{BASE_URL}/balance", headers=_headers(), timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def topup(sats: int) -> dict[str, Any]:
    """Request a Lightning invoice for the given top-up amount.

    Returns `{"payment_request": "lnbc...", "payment_hash": "..."}`. Pay the
    invoice with any Lightning wallet; the account credits once the bridge sees
    the settled HTLC. Call /topup/status?hash=<payment_hash> to poll.
    """
    r = requests.post(
        f"{BASE_URL}/topup",
        headers=_headers(),
        json={"sats": int(sats)},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def reason(prompt: str, model: str | None = None) -> dict[str, Any]:
    """Run a single reasoning step (costs ~100 sats × agent multiplier).

    Returns `{"reasoning": "...", "cost_sats": N, "balance_after": M}`. Useful
    when an ADK agent wants paid reasoning from an external model without paying
    OpenAI/Anthropic directly.
    """
    body: dict[str, Any] = {"prompt": prompt}
    if model:
        body["model"] = model
    r = requests.post(
        f"{BASE_URL}/reason", headers=_headers(), json=body, timeout=TIMEOUT_S
    )
    r.raise_for_status()
    return r.json()


def decision(prompt: str, options: list[str]) -> dict[str, Any]:
    """Force a structured choice from a list of options (costs ~180 sats × multiplier).

    Returns `{"choice": "<one_of_options>", "rationale": "...", "cost_sats": N}`.
    Use this when your ADK agent needs an external-paid arbiter for a routing
    decision rather than burning its own model budget.
    """
    r = requests.post(
        f"{BASE_URL}/decision",
        headers=_headers(),
        json={"prompt": prompt, "options": options},
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

    The platform takes its cut, the seller gets paid out in withdrawable sats.
    Returns `{"status": "purchased", "offer_id": ..., "amount_sats": N,
    "deliverable": ..., "balance_after": M}`. This is the funnel-completing
    action: registered → topped up → bought → seller earned.
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
