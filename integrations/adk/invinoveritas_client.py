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

    Returns a Bearer api_key prefixed `ivv_`; fund via Lightning or x402 (USDC) to make paid calls.
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


def reason(question: str) -> dict[str, Any]:
    """Run a single paid reasoning step (~100 sats × agent multiplier).

    Returns `{"answer": "...", ...}`. Useful when an ADK agent wants paid
    reasoning from an external model without paying OpenAI/Anthropic directly.

    Args:
        question: the question to reason about.
    """
    r = requests.post(
        f"{BASE_URL}/reason", headers=_headers(),
        json={"question": question}, timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def decision(goal: str, question: str, context: str = "") -> dict[str, Any]:
    """Structured decision with confidence + risk level (~180 sats × multiplier).

    Returns `{"result": {"decision": ..., "confidence": float,
    "reasoning": ..., "risk_level": ...}}`. Use this when your ADK agent needs an
    external-paid structured arbiter rather than burning its own model budget.

    Args:
        goal: the objective the decision serves.
        question: the specific question to decide.
        context: any extra context (portfolio, constraints, prior state).
    """
    r = requests.post(
        f"{BASE_URL}/decision",
        headers=_headers(),
        json={"goal": goal, "question": question, "context": context},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def review(artifact: str, artifact_type: str = "general", context: str = "",
           include_trading_state: bool = False, sign: bool = False) -> dict[str, Any]:
    """Capital-scale-aware structured review — the proven governance front door (~250 sats).

    Returns an approve/revise/reject verdict with confidence, a summary, and
    concrete issues. This is the same gate we run our own important decisions
    through. Set include_trading_state=True for a verdict that
    factors live equity/drawdown into its risk tolerance.

    Set sign=True to also get a PORTABLE SIGNED proof of the verdict (on `proof`)
    — attach it to your output so a downstream agent can confirm via verify_proof,
    WITHOUT trusting you or us, that invinoveritas issued this verdict.

    Args:
        artifact: the trade / diff / command / plan to govern.
        artifact_type: "trade", "code", "plan", "general", etc.
        context: any extra context for the reviewer.
        include_trading_state: inject live trading state for a capital-scale-aware verdict.
        sign: return a portable signed verdict proof for the agent-to-agent handshake.
    """
    r = requests.post(
        f"{BASE_URL}/review",
        headers=_headers(),
        json={"artifact": artifact, "artifact_type": artifact_type,
              "context": context, "include_trading_state": include_trading_state, "sign": sign},
        timeout=TIMEOUT_S,
    )
    r.raise_for_status()
    return r.json()


def verify_proof(event: dict[str, Any] | None = None, proof_id: str | None = None,
                 expect_artifact_hash: str | None = None) -> dict[str, Any]:
    """Verify a counterparty's invinoveritas proof — the agent-to-agent trust handshake. FREE, no auth.

    When another agent hands you output and claims it was verified, pass the signed `event` it gave you.
    Confirms — WITHOUT trusting that agent OR us — that invinoveritas issued the verdict (recomputes the
    Nostr id, checks the schnorr signature, confirms the pubkey is our published key). Pass
    expect_artifact_hash (sha256 of the output you received) to bind the proof to that exact artifact.

    Args:
        event: the signed proof event the counterparty attached to its output.
        proof_id: alternatively, a stored attestation id to fetch + verify.
        expect_artifact_hash: optional sha256 hex of the output you received.
    """
    payload: dict[str, Any] = {}
    if event is not None:
        payload["event"] = event
    if proof_id:
        payload["proof_id"] = proof_id
    if expect_artifact_hash:
        payload["expect_artifact_hash"] = expect_artifact_hash
    r = requests.post(f"{BASE_URL}/verify-proof", json=payload, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def residence_act(intent: str, artifact: str | None = None,
                  artifact_type: str = "general",
                  max_spend_sats: int | None = None) -> dict[str, Any]:
    """The bundle (/residence/act): your home reasons + governs + remembers in one call.

    Priced below the sum of its parts. Rule 9 — it returns the governed verdict;
    you take any irreversible action yourself. `max_spend_sats` is a hard,
    deterministic cap enforced before any work.

    Args:
        intent: what you want your home to reason about / govern.
        artifact: a concrete trade/diff/command/plan to govern, if any.
        artifact_type: type of the artifact.
        max_spend_sats: hard spend cap; the act is rejected before work if exceeded.
    """
    body: dict[str, Any] = {
        "intent": intent, "artifact_type": artifact_type,
        "policy": {"require_review": True, "remember": True,
                   "max_spend_sats": max_spend_sats},
    }
    if artifact is not None:
        body["artifact"] = artifact
    r = requests.post(
        f"{BASE_URL}/residence/act", headers=_headers(), json=body, timeout=TIMEOUT_S
    )
    r.raise_for_status()
    return r.json()


# ---- Markets / trading intelligence (facts-only, never P&L/advice) ----

def regime(x402: bool = False) -> dict[str, Any]:
    """Macro risk-off DATA feed (/regime) — the methodology behind our own risk-sizing
    research. Facts only, not financial advice. x402=True requests the USDC rail."""
    headers = _headers()
    if x402:
        headers["X-Payment-Scheme"] = "x402"
    r = requests.get(f"{BASE_URL}/regime", headers=headers, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def signals_teaser() -> dict[str, Any]:
    """Free shop-window (/signals): the BTC vol-expansion regime read — the same
    read our own trading research is grounded in. Facts only."""
    r = requests.get(f"{BASE_URL}/signals", headers=_headers(), timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def signals(x402: bool = False) -> dict[str, Any]:
    """Full live Hyperliquid derivatives signal set (/signals/full): per-coin
    funding + 24h funding-delta, basis, open interest, vol-expansion regime,
    realized vol, BTC DVOL. Facts only, not advice."""
    headers = _headers()
    if x402:
        headers["X-Payment-Scheme"] = "x402"
    r = requests.get(f"{BASE_URL}/signals/full", headers=headers, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.json()


def markets_act(artifact: str | None = None, artifact_type: str = "general",
                context: str | None = None,
                coins: list[str] | None = None,
                max_spend_sats: int | None = None) -> dict[str, Any]:
    """The Markets Bundle (/markets/act): regime + live signals + ecosystem brief
    + an optional governance review of `artifact`, in one call, priced below the
    sum of its members. Facts-only data + a governance verdict, never P&L/advice."""
    body: dict[str, Any] = {"artifact_type": artifact_type}
    if coins:
        body["coins"] = coins
    if artifact is not None:
        body["artifact"] = artifact
    if context is not None:
        body["context"] = context
    if max_spend_sats is not None:
        body["max_spend_sats"] = max_spend_sats
    r = requests.post(
        f"{BASE_URL}/markets/act", headers=_headers(), json=body, timeout=TIMEOUT_S
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
    "review",
    "verify_proof",
    "residence_act",
    "marketplace_list",
    "marketplace_buy",
]
