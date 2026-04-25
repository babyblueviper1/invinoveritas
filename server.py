#!/usr/bin/env python3
"""
invinoveritas MCP stdio server.
Runs locally, calls the invinoveritas API using INVINO_API_KEY.
"""
import os
import sys
import httpx
from typing import Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP

API_BASE = "https://api.babyblueviper.com"

api_key = os.environ.get("INVINO_API_KEY", "")
if not api_key:
    print("Error: INVINO_API_KEY is required.", file=sys.stderr)
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {api_key}"}

mcp = FastMCP("invinoveritas")


@mcp.tool()
def reason(
    question: Annotated[str, Field(description="The strategic or analytical question to reason about. Examples: 'What are the biggest risks for Bitcoin in 2026?', 'How should I think about portfolio concentration risk?', 'What are the trade-offs between HODLing and active trading?'")],
    style: Annotated[str, Field(description="Response verbosity. One of: 'short' (1-2 sentences), 'concise' (1 paragraph), 'normal' (balanced, default), 'detailed' (multi-paragraph), 'comprehensive' (exhaustive analysis)")] = "normal",
) -> str:
    """
    Deep strategic reasoning on any question or topic.

    Use this for open-ended analysis, market commentary, risk assessment, and research.
    Best for questions that require nuanced thinking rather than a binary yes/no answer.
    Returns a thorough, well-reasoned answer as a string.

    Cost: ~500 sats per call.
    """
    r = httpx.post(f"{API_BASE}/reason",
                   json={"question": question, "style": style},
                   headers=HEADERS, timeout=60)
    r.raise_for_status()
    d = r.json()
    return d.get("result", {}).get("answer", str(d))


@mcp.tool()
def decision(
    goal: Annotated[str, Field(description="The overall objective guiding the decision. Examples: 'Maximize BTC returns with controlled drawdown', 'Preserve capital during high-volatility periods', 'Grow a Lightning node business sustainably'")],
    question: Annotated[str, Field(description="The specific decision question requiring a recommendation. Examples: 'Should I increase BTC exposure now?', 'Should I open a new Lightning channel to this peer?', 'Should I take profit at current levels?'")],
    context: Annotated[str, Field(description="Background context that informs the decision: market conditions, portfolio state, constraints, recent events. The richer the context, the more accurate the decision. Example: 'Portfolio: 60% BTC, 30% bonds, RSI=42, trend=uptrend, 3-month horizon'")] = "",
    risk_limit: Annotated[str, Field(description="Maximum acceptable risk level for the recommendation. One of: 'low' (conservative, capital preservation priority), 'medium' (balanced risk/reward, default), 'high' (aggressive, growth priority)")] = "medium",
) -> str:
    """
    Structured decision intelligence with confidence score and risk assessment.

    Returns a clear recommendation (decision), a confidence score (0.0–1.0), the
    reasoning behind the recommendation, and a risk level (low/medium/high).

    Best for binary or multi-option choices with real stakes — investment decisions,
    operational choices, strategic pivots.

    Cost: ~1000 sats per call.
    Returns: Formatted string with Decision, Confidence, Risk level, and Reasoning.
    """
    r = httpx.post(f"{API_BASE}/decision",
                   json={"goal": goal, "question": question,
                         "context": context,
                         "policy": {"risk_limit": risk_limit}},
                   headers=HEADERS, timeout=60)
    r.raise_for_status()
    d = r.json().get("result", {})
    return (f"Decision: {d.get('decision')}\n"
            f"Confidence: {d.get('confidence')}\n"
            f"Risk: {d.get('risk_level')}\n"
            f"Reasoning: {d.get('reasoning')}")


@mcp.tool()
def memory_store(
    agent_id: Annotated[str, Field(description="Unique identifier for the agent or workflow storing the memory. Use a stable, descriptive name such as 'btc-trader-bot', 'research-agent', or 'portfolio-monitor'. All keys for this agent are namespaced under this ID.")],
    key: Annotated[str, Field(description="The memory key to store the value under. Should be descriptive and stable across sessions. Examples: 'last_trade', 'portfolio_state', 'user_preferences', 'market_context'")],
    value: Annotated[str, Field(description="The value to store. Use a JSON string for structured data. Example: '{\"entry\": 95000, \"size\": 0.1, \"direction\": \"long\"}'. Max recommended size: a few KB per entry.")],
) -> str:
    """
    Persist a key-value memory entry for an agent across sessions.

    Memory is stored server-side and survives container restarts, making it suitable
    for long-running autonomous agents that need continuity between calls.

    Use this to save trade state, user preferences, intermediate reasoning results,
    or any context an agent needs to recall in a future session.

    Cost: ~2 sats/KB (minimum 50 sats).
    Returns: 'stored' on success.
    """
    r = httpx.post(f"{API_BASE}/memory/store",
                   json={"agent_id": agent_id, "key": key, "value": value},
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return "stored"


@mcp.tool()
def memory_get(
    agent_id: Annotated[str, Field(description="The agent identifier used when the memory was stored. Must exactly match the agent_id used in memory_store.")],
    key: Annotated[str, Field(description="The memory key to retrieve. Must exactly match the key used in memory_store. Use memory_list to see all available keys for an agent.")],
) -> str:
    """
    Retrieve a previously stored memory entry for an agent.

    Returns the stored value as a string. If the value was stored as JSON,
    parse it after retrieval. Returns an empty string if the key does not exist.

    Cost: ~1 sat/KB (minimum 20 sats).
    Returns: The stored value string, or empty string if not found.
    """
    r = httpx.post(f"{API_BASE}/memory/get",
                   json={"agent_id": agent_id, "key": key},
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("value", "")


@mcp.tool()
def memory_list(
    agent_id: Annotated[str, Field(description="The agent identifier to list memory keys for. Returns all keys that have been stored under this agent_id. Use this before memory_get to discover available keys.")],
) -> str:
    """
    List all stored memory keys for a given agent.

    Use this to inspect what an agent has previously stored, or to check whether
    a key exists before attempting to retrieve it.

    Cost: Free.
    Returns: JSON-formatted list of all keys stored under the given agent_id.
    """
    r = httpx.post(f"{API_BASE}/memory/list",
                   json={"agent_id": agent_id},
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return str(r.json())


@mcp.tool()
def list_offers(
    category: Annotated[str, Field(description="Optional category filter to narrow results. Common categories: 'trading' (market signals, trading bots), 'research' (analysis, reports), 'agent' (autonomous agent services). Leave empty to browse all available offers.")] = "",
) -> str:
    """
    Browse the Lightning-native agent marketplace.

    Lists AI services available for purchase. Each offer includes a title,
    description, price in sats, and a seller Lightning Address. Sellers receive
    95% of every sale instantly via Lightning payment.

    Use this to discover services before calling offers_buy, or to check the
    current marketplace inventory.

    Cost: Free.
    Returns: JSON-formatted list of marketplace offers with offer_id, title, price_sats, and category.
    """
    params = {"category": category} if category else {}
    r = httpx.get(f"{API_BASE}/offers/list",
                  params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return str(r.json())


@mcp.tool()
def get_balance() -> str:
    """
    Check the current Bearer account balance and remaining complementary calls.

    Returns balance in sats and how many free calls remain. Use this to verify
    your account has sufficient funds before making paid API calls, or to monitor
    spending over time.

    Cost: Free.
    Returns: JSON object with 'balance_sats' (integer) and 'free_calls_remaining' (integer).
    """
    r = httpx.get(f"{API_BASE}/balance", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return str(r.json())


if __name__ == "__main__":
    mcp.run()
