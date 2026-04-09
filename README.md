# ⚡ invinoveritas

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/invinoveritas)](https://pypi.org/project/invinoveritas/)

**Lightning-paid AI reasoning and decision intelligence for autonomous agents and trading bots**

Pay-per-insight API using **Bearer credits** and **L402 Lightning**.

No subscriptions. No KYC. Simple and reliable Lightning payments.

**Live API**: [https://invinoveritas.onrender.com](https://invinoveritas.onrender.com)  
**MCP Endpoint**: [https://invinoveritas.onrender.com/mcp](https://invinoveritas.onrender.com/mcp)

---

## Quick Start

### 1. Python SDK (Recommended)

```bash
pip install invinoveritas
```

### 2. Register & Get Started (Bearer Token — Recommended)

```bash
curl -X POST https://invinoveritas.onrender.com/register
```

Pay the ~1000 sats Lightning invoice → you get an `api_key` + **5 complementary calls**.

Then use it like this:

```python
from invinoveritas import InvinoClient

client = InvinoClient(api_key="ivv_your_api_key_here")

result = client.reason("What are the biggest risks for Bitcoin in 2026?")
print(result.answer)
```

---

## Payment Options (Lightning Only)

| Method              | Best For                          | Details                                      | Minimum          |
|---------------------|-----------------------------------|----------------------------------------------|------------------|
| **Bearer Token**    | Autonomous agents, trading bots   | Register once → use API key forever         | ~1000 sats (5 free calls) |
| **L402 Lightning**  | Lightning maximalists             | Pay-per-call with invoices                  | ~100 sats        |

**Recommended for most users**: Start with **Bearer Token** after registration.

---

## Current Pricing (as of April 2026)

| Tool      | Base Price | With Agent Multiplier | Notes                          |
|-----------|------------|-----------------------|--------------------------------|
| `reason`  | 100 sats   | 130 sats              | Strategic reasoning            |
| `decide`  | 180 sats   | 234 sats              | Structured decisions + risk    |

- New accounts get **5 complementary calls** after registration (~1000 sats).
- Prices can vary slightly based on input length.

**Full pricing** → [`/prices`](https://invinoveritas.onrender.com/prices)

---

## For Autonomous Agents & Trading Bots

**Best setup**:
- Register once (`/register`)
- Pre-fund with Lightning (`/topup`)
- Use Bearer token for all future calls

**Trading bot advantages**:
- Low-latency async decisions
- Arbitrage evaluation
- Portfolio rebalancing suggestions
- Risk-aware reasoning with confidence scores

Example with NWC (no node required):

```python
from invinoveritas.providers import NWCProvider
from invinoveritas.langchain import InvinoCallbackHandler

handler = InvinoCallbackHandler(
    provider=NWCProvider(uri="nostr+walletconnect://...")
)

# Use with any LangChain agent
```

---

## MCP Support (Claude, Cursor, etc.)

Add this MCP server card:

```
https://invinoveritas.onrender.com/.well-known/mcp/server-card.json
```

Full support for `initialize`, `tools/list`, and `callTool` with built-in Lightning payment handling.

---

## Real-time Updates

- **SSE**: `/events`
- **WebSocket**: `wss://invinoveritas.onrender.com/ws`
- **RSS**: `/rss`

---

## Discovery Endpoints

- `/health` — Service status
- `/prices` — Current pricing
- `/guide` — Payment guide
- `/wallet-onboarding` — Setup instructions
- `/.well-known/mcp/server-card.json` — MCP discovery

---

## Philosophy

Most AI agents are stuck with subscriptions or unpredictable token costs.

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Pay only when the insight matters — with sats, instantly, and without intermediaries.

Built for the **Bitcoin × AI** future. ⚡

---
