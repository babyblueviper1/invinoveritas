#!/usr/bin/env python3
"""
invinoveritas MCP stdio server.
Runs locally, calls the invinoveritas API using INVINO_API_KEY.
"""
import os
import sys
import httpx
from mcp.server.fastmcp import FastMCP

API_BASE = "https://api.babyblueviper.com"

api_key = os.environ.get("INVINO_API_KEY", "")
if not api_key:
    print("Error: INVINO_API_KEY is required.", file=sys.stderr)
    sys.exit(1)

HEADERS = {"Authorization": f"Bearer {api_key}"}

mcp = FastMCP("invinoveritas")


@mcp.tool()
def reason(question: str, style: str = "normal") -> str:
    """Deep strategic reasoning on any question. ~500 sats."""
    r = httpx.post(f"{API_BASE}/reason",
                   json={"question": question, "style": style},
                   headers=HEADERS, timeout=60)
    r.raise_for_status()
    d = r.json()
    return d.get("result", {}).get("answer", str(d))


@mcp.tool()
def decision(goal: str, question: str, context: str = "",
             risk_limit: str = "medium") -> str:
    """Structured decision with confidence score and risk level. ~1000 sats."""
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
def memory_store(agent_id: str, key: str, value: str) -> str:
    """Store persistent key-value memory for an agent. ~2 sats/KB."""
    r = httpx.post(f"{API_BASE}/memory/store",
                   json={"agent_id": agent_id, "key": key, "value": value},
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return "stored"


@mcp.tool()
def memory_get(agent_id: str, key: str) -> str:
    """Retrieve stored agent memory. ~1 sat/KB."""
    r = httpx.post(f"{API_BASE}/memory/get",
                   json={"agent_id": agent_id, "key": key},
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json().get("value", "")


@mcp.tool()
def memory_list(agent_id: str) -> str:
    """List all memory keys for an agent. Free."""
    r = httpx.post(f"{API_BASE}/memory/list",
                   json={"agent_id": agent_id},
                   headers=HEADERS, timeout=30)
    r.raise_for_status()
    return str(r.json())


@mcp.tool()
def list_offers(category: str = "") -> str:
    """Browse the Lightning agent marketplace. Free."""
    params = {"category": category} if category else {}
    r = httpx.get(f"{API_BASE}/offers/list",
                  params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return str(r.json())


@mcp.tool()
def get_balance() -> str:
    """Check your Bearer account balance. Free."""
    r = httpx.get(f"{API_BASE}/balance", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return str(r.json())


if __name__ == "__main__":
    mcp.run()
