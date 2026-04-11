# ⚡ invinoveritas v0.6.0

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

**Lightning-paid AI reasoning, structured decision intelligence, and persistent agent memory for autonomous agents and trading bots**

Pay-per-insight API using **Bearer credits** and **L402 Lightning**.

No subscriptions. No KYC. Simple and reliable Lightning payments.

**Live API**: http://178.156.151.248:8000  
**MCP Endpoint**: http://178.156.151.248:8000/mcp

---

## Quick Start

### 1. Register & Get Started (Bearer Token — Recommended)

```bash
curl -X POST http://178.156.151.248:8000/register
```

Pay the ~1000 sats Lightning invoice → you get an `api_key` + **5 complementary calls**.

Then use it like this:

```bash
curl -X POST http://178.156.151.248:8000/reason \
  -H "Authorization: Bearer ivv_your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the biggest risks for Bitcoin in 2026?"}'
```

---

## Payment Options (Lightning Only)

| Method              | Best For                          | Details                                      | Minimum          |
|---------------------|-----------------------------------|----------------------------------------------|------------------|
| **Bearer Token**    | Autonomous agents, trading bots   | Register once → use API key forever         | ~1000 sats (5 free calls) |
| **L402 Lightning**  | Lightning maximalists             | Pay-per-call with invoices                  | ~100 sats        |

**Recommended for most users**: Start with **Bearer Token** after registration.

**Wallet note**: A Lightning wallet is required for initial registration and occasional top-ups. Once funded with Bearer Token, normal usage requires no wallet.

---

## Current Pricing (as of April 2026)

| Tool              | Base Price          | With Agent Multiplier | Notes                          |
|-------------------|---------------------|-----------------------|--------------------------------|
| `reason`          | 100 sats            | 130 sats              | Strategic reasoning            |
| `decide`          | 180 sats            | 234 sats              | Structured decisions + risk    |
| `memory_store`    | ≈2 sats per KB      | -                     | Persistent agent memory        |
| `memory_get`      | ≈1 sat per KB       | -                     | Retrieve stored memory         |

- New accounts get **5 complementary calls** after registration.
- Full pricing → [`/prices`](http://178.156.151.248:8000/prices)

---

## New in v0.6.0: Persistent Agent Memory

Agents can now **store and retrieve long-term context/state**:

- **Store**: `POST /memory/store` (≈2 sats/KB, min 50 sats)
- **Get**: `POST /memory/get` (≈1 sat/KB, min 20 sats)
- **List**: `POST /memory/list` (free)
- **Delete**: `POST /memory/delete` (free)

**Until full SDK support**, use raw HTTP endpoints with your Bearer token.

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
- Persistent memory for long-term state

---

## MCP Support (Claude, Cursor, etc.)

Add this MCP server card:

```
http://178.156.151.248:8000/.well-known/mcp/server-card.json
```

Full support for `initialize`, `tools/list`, and `callTool` with built-in Lightning payment handling and memory tools.

---

## Real-time Updates

- **SSE**: `/events`
- **WebSocket**: `wss://178.156.151.248:8000/ws`
- **RSS**: `/rss`

---

## Discovery Endpoints

- `/health` — Service status
- `/prices` — Current pricing
- `/guide` — Payment guide
- `/wallet-onboarding` — Setup instructions
- `/.well-known/mcp/server-card.json` — MCP discovery
- `/memory` — Memory service info

---

## Philosophy

Most AI agents are stuck with subscriptions or unpredictable token costs.

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Pay only when the insight matters — with sats, instantly, and without intermediaries.

Built for the **Bitcoin × AI** future. ⚡

---
