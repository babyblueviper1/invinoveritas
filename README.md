# ⚡ invinoveritas v0.6.0

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/invinoveritas)](https://pypi.org/project/invinoveritas/)

**Lightning-paid AI reasoning, structured decision intelligence, and persistent agent memory for autonomous agents and trading bots**

Pay-per-insight API using **Bearer credits** and **L402 Lightning**.  
No subscriptions. No KYC. Simple and reliable Lightning payments.

**Live API**: [https://api.babyblueviper.com](https://api.babyblueviper.com)  
**MCP Endpoint**: [https://api.babyblueviper.com/mcp](https://api.babyblueviper.com/mcp)  
**PyPI**: [https://pypi.org/project/invinoveritas/](https://pypi.org/project/invinoveritas/)

---

## Quick Start

### 1. Register & Get Started (Bearer Token — Recommended)

```bash
curl -X POST https://api.babyblueviper.com/register
```

Pay the ~1000 sats Lightning invoice → you get an `api_key` + **5 complementary calls**.

Then use it:

```bash
curl -X POST https://api.babyblueviper.com/reason \
  -H "Authorization: Bearer ivv_your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the biggest risks for Bitcoin in 2026?"}'
```

---

## Python SDK

```bash
pip install invinoveritas

# With LangChain autonomous payments
pip install "invinoveritas[langchain]"

# With NWC wallet support (Alby, Zeus, Mutiny — no node required)
pip install "invinoveritas[nwc]"
```

```python
from invinoveritas import InvinoClient, PaymentRequired

client = InvinoClient(base_url="https://api.babyblueviper.com")

try:
    result = client.reason("What are the biggest risks for Bitcoin in 2026?")
except PaymentRequired as e:
    print(f"Pay: {e.invoice} ({e.amount_sats} sats)")
```

Full SDK docs → [`sdk/README.md`](sdk/README.md)

---

## Payment Options (Lightning Only)

| Method | Best For | Details | Minimum |
|---|---|---|---|
| **Bearer Token** | Autonomous agents, trading bots | Register once → use API key forever | ~1000 sats (5 free calls) |
| **L402 Lightning** | Lightning maximalists | Pay-per-call with invoices | ~100 sats |

**Recommended**: Start with **Bearer Token** after registration.

A Lightning wallet is required for initial registration and top-ups. Once funded, normal usage requires no wallet.

---

## Pricing (April 2026)

| Tool | Base Price | With Agent Multiplier | Notes |
|---|---|---|---|
| `reason` | 100 sats | 130 sats | Strategic reasoning |
| `decide` | 180 sats | 234 sats | Structured decisions + risk |
| `memory_store` | ≈2 sats/KB | — | Persistent agent memory |
| `memory_get` | ≈1 sat/KB | — | Retrieve stored memory |

New accounts get **5 complementary calls** after registration.  
Full pricing → [`/prices`](https://api.babyblueviper.com/prices)

---

## New in v0.6.0: Persistent Agent Memory

Agents can store and retrieve long-term context and state:

- `POST /memory/store` — ≈2 sats/KB, min 50 sats
- `POST /memory/get` — ≈1 sat/KB, min 20 sats
- `POST /memory/list` — free
- `POST /memory/delete` — free

---

## For Autonomous Agents & Trading Bots

**Best setup:**
1. Register once (`/register`)
2. Pre-fund with Lightning (`/topup`)
3. Use Bearer token for all future calls

**Trading bot advantages:**
- Low-latency async decisions
- Arbitrage evaluation
- Portfolio rebalancing suggestions
- Risk-aware reasoning with confidence scores
- Persistent memory for long-term state

---

## MCP Support (Claude Desktop, Cursor)

Point your MCP client to:

```
https://api.babyblueviper.com/mcp
```

Server card:

```
https://api.babyblueviper.com/.well-known/mcp/server-card.json
```

Full support for `initialize`, `tools/list`, and `callTool` with built-in Lightning payment handling and memory tools.

---

## Real-time Updates

- **SSE**: `https://api.babyblueviper.com/events`
- **WebSocket**: `wss://api.babyblueviper.com/ws`
- **RSS**: `https://api.babyblueviper.com/rss`

---

## Discovery Endpoints (Free)

- `/health` — Service status and pricing
- `/prices` — Current pricing
- `/guide` — Payment guide
- `/wallet-onboarding` — Setup instructions
- `/.well-known/mcp/server-card.json` — MCP discovery
- `/.well-known/agent-card.json` — Agent card
- `/memory` — Memory service info

---

## Philosophy

Most AI agents are stuck with subscriptions or unpredictable token costs.

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Pay only when the insight matters — with sats, instantly, and without intermediaries.

Built for the **Bitcoin × AI** future. ⚡

---

## Quick Links

- **GitHub**: [https://github.com/babyblueviper1/invinoveritas](https://github.com/babyblueviper1/invinoveritas)
- **Live API**: [https://api.babyblueviper.com](https://api.babyblueviper.com)
- **MCP Endpoint**: [https://api.babyblueviper.com/mcp](https://api.babyblueviper.com/mcp)
- **PyPI**: [https://pypi.org/project/invinoveritas/](https://pypi.org/project/invinoveritas/)
- **Health**: [https://api.babyblueviper.com/health](https://api.babyblueviper.com/health)
- **Guide**: [https://api.babyblueviper.com/guide](https://api.babyblueviper.com/guide)
