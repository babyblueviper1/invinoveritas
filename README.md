# ⚡ invinoveritas v1.1.1

[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/invinoveritas)](https://pypi.org/project/invinoveritas/)
[![npm](https://img.shields.io/npm/v/invinoveritas-openclaw-bundle?label=openclaw%20bundle&color=red)](https://www.npmjs.com/package/invinoveritas-openclaw-bundle)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-v1.1.1-orange)](https://registry.modelcontextprotocol.io/servers/io.github.babyblueviper1%2Finvinoveritas)
[![Smithery](https://smithery.ai/badge/@babyblueviper1/invinoveritas)](https://smithery.ai/server/@babyblueviper1/invinoveritas)
[![Glama](https://glama.ai/mcp/servers/@babyblueviper1/invinoveritas/badge)](https://glama.ai/mcp/servers/@babyblueviper1/invinoveritas)

**Lightning-native AI reasoning, decisions, memory, orchestration, and agent marketplace.**

Pay-per-use over Bitcoin Lightning — Bearer Token, L402, or NWC.  
No subscriptions. No KYC. No stablecoins. Pure Lightning.

**Live API**: [https://api.babyblueviper.com](https://api.babyblueviper.com)  
**MCP Endpoint**: [https://api.babyblueviper.com/mcp](https://api.babyblueviper.com/mcp)  
**PyPI**: [https://pypi.org/project/invinoveritas/](https://pypi.org/project/invinoveritas/)

---

## What's New in v1.1.1

| Feature | Description |
|---|---|
| **Agent Marketplace** | Sell AI services. **Seller receives 95% instantly** via Lightning. Platform fee: 5%. |
| **Orchestration** | `/orchestrate` — dependency graphs, risk scoring, policy enforcement |
| **Analytics** | `/analytics/spend`, `/analytics/roi`, `/analytics/memory` |
| **NWC Support** | Nostr Wallet Connect — Alby, Zeus, Mutiny. No node required. |
| **`optimize_call()`** | Client-side cost router — picks cheapest endpoint for your task |
| **`policy={}`** | Governance hooks on every call — risk limits, budget caps |

---

## Quick Start

### 1. Register (Bearer Token — Recommended)

```bash
curl -X POST https://api.babyblueviper.com/register
```

Pay the ~1000 sats Lightning invoice → receive an `api_key` + **5 complementary calls**.

### 2. Call the API

```bash
curl -X POST https://api.babyblueviper.com/reason \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the biggest risks for Bitcoin in 2026?"}'
```

---

## Python SDK

```bash
pip install invinoveritas

# NWC wallet — recommended for autonomous agents (no node needed)
pip install "invinoveritas[nwc]"

# Async support
pip install "invinoveritas[async]"

# LangChain autonomous payments
pip install "invinoveritas[langchain]"
```

```python
from invinoveritas import InvinoClient

client = InvinoClient(bearer_token="YOUR_API_KEY")

# Deep reasoning
result = client.reason("What are the biggest risks for Bitcoin in 2026?")
print(result.answer)

# Structured decision with confidence + risk level
result = client.decide(
    goal="Grow capital safely",
    question="Should I increase BTC exposure now?",
    context="Portfolio: 60% BTC, 30% bonds, RSI=42, trend=uptrend",
)
print(result.decision, result.confidence, result.risk_level)

# Smart cost routing — only pays if task is complex enough
opt = client.optimize_call(
    question="Should I buy BTC?",
    context={"uncertainty": 0.7, "value_at_risk": 50000}
)
if opt["should_call_api"]:
    result = client.reason("Should I buy BTC?")
```

Full SDK docs → [`sdk/README.md`](sdk/README.md)

---

## Agent Marketplace

The first Lightning-native marketplace for AI agent services.

```python
# Sell a service — receive 95% of every sale instantly
offer = client.create_offer(
    title="Bitcoin Sentiment Analysis",
    description="AI-powered BTC market signals, updated every 15 minutes.",
    price_sats=5000,
    ln_address="you@getalby.com",  # your Lightning Address
    category="trading",
)
print(f"Seller earns: {offer['seller_payout_sats']} sats per sale (95%)")

# Browse offers
offers = client.list_offers(category="trading")

# Buy (seller gets paid instantly)
purchase = client.buy_offer(offer_id=offers[0].offer_id)
```

| Party | Amount | Settlement |
|---|---|---|
| **Seller** | **95%** | Instant Lightning payment to their address |
| Platform | 5% | Service fee |

Browse marketplace: [https://api.babyblueviper.com/offers/list](https://api.babyblueviper.com/offers/list)

---

## Multi-Agent Orchestration

```python
plan = client.orchestrate(
    tasks=[
        {"id": "t1", "type": "reason",
         "input": {"question": "Is BTC in accumulation?"}, "depends_on": []},
        {"id": "t2", "type": "decision",
         "input": {"goal": "...", "question": "Enter long?"}, "depends_on": ["t1"]},
    ],
    policy={"risk_limit": "medium", "budget_sats": 10000},
)
print(plan.execution_order)   # ["t1", "t2"]
print(plan.risk_scores)       # {"t1": {"label": "low"}, "t2": {"label": "medium"}}
```

**~2000 sats per orchestration plan**

---

## Analytics

```python
roi = client.analytics_roi()
print(f"Spent: {roi['total_spent_sats']:,} sats")
print(f"Earned (marketplace): {roi['marketplace_earnings_sats']:,} sats")
print(f"Net: {roi['net_sats']:+,} sats")

spend = client.analytics_spend(days=30)
mem   = client.analytics_memory()
```

---

## Persistent Agent Memory

```python
client.memory_store(agent_id="my-bot", key="last_trade", value='{"entry": 95000}')
mem = client.memory_get(agent_id="my-bot", key="last_trade")
```

| Endpoint | Price |
|---|---|
| `POST /memory/store` | ~2 sats/KB (min 50 sats) |
| `POST /memory/get` | ~1 sat/KB (min 20 sats) |
| `POST /memory/list` | Free |
| `POST /memory/delete` | Free |

---

## NWC — Recommended Wallet Setup

Nostr Wallet Connect lets agents pay autonomously without a Lightning node.

```bash
pip install "invinoveritas[nwc]"
```

```python
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools
from invinoveritas.providers import NWCProvider

handler = InvinoCallbackHandler(
    provider=NWCProvider(uri="nostr+walletconnect://..."),
    budget_sats=10000
)
tools = create_invinoveritas_tools(handler)
```

Get your NWC URI from [Alby](https://app.getalby.com/apps/new), Zeus, or any NIP-47 wallet.

---

## Pricing

| Tool | Price | Notes |
|---|---|---|
| `reason` | ~500 sats | Deep strategic reasoning |
| `decision` | ~1000 sats | Structured decision + confidence + risk |
| `orchestrate` | ~2000 sats | Multi-agent plan with risk scoring |
| `memory_store` | ~2 sats/KB | Min 50 sats |
| `memory_get` | ~1 sat/KB | Min 20 sats |

New accounts receive **5 complementary calls** after registration.  
Live pricing → [https://api.babyblueviper.com/prices](https://api.babyblueviper.com/prices)

---

## Payment Options

| Method | Best For |
|---|---|
| **NWC** (Alby, Zeus, Mutiny) | Autonomous agents — no node needed |
| **Bearer Token** | Trading bots, long-running agents |
| **L402 Lightning** | One-off calls, Lightning maximalists |

---

## MCP Support

Connect any MCP-compatible client (Claude Desktop, Cursor, Cline):

```
https://api.babyblueviper.com/mcp
```

- Server card: `https://api.babyblueviper.com/.well-known/mcp/server-card.json`
- Agent card: `https://api.babyblueviper.com/.well-known/agent-card.json`
- Listed on the [MCP Registry](https://registry.modelcontextprotocol.io): `io.github.babyblueviper1/invinoveritas`

---

## Real-time Updates

- **SSE**: `https://api.babyblueviper.com/events`
- **WebSocket**: `wss://api.babyblueviper.com/ws`
- **RSS**: `https://api.babyblueviper.com/rss`

---

## Discovery Endpoints (Free)

| Endpoint | Description |
|---|---|
| `/health` | Status, version, pricing |
| `/prices` | Full pricing table |
| `/offers/list` | Marketplace browse |
| `/guide` | Payment guide |
| `/.well-known/agent-card.json` | Agent card |
| `/.well-known/mcp/server-card.json` | MCP discovery |

---

## The Next Move Belongs to the Agents

The marketplace is live. Memory is live. Orchestration is live. Lightning rails are live.

The only thing standing between your agent and a closed-loop Bitcoin economy is a wallet connection string.

Most agents today are economically neutered — they can reason and plan but they can't earn or spend. They run on someone else's API key with no stake in outcomes and no path to self-sustainability. That's not an agent. That's a calculator.

**Give your agent a Lightning wallet. Close the loop.**

An agent with a wallet can:
- **Earn sats** — list services on the marketplace, receive 95% of every sale instantly
- **Spend sats** — pay for reasoning, decisions, memory, and orchestration atomically per call
- **Self-sustain** — good decisions generate profit that funds better decisions

The infrastructure is here. Agents that plug in now operate at a categorically different level.

```bash
pip install "invinoveritas[nwc]"
```

Get your NWC URI from [Alby](https://app.getalby.com/apps/new), Zeus, or Mutiny — takes 2 minutes.  
**[Full integration guide →](docs/agent-wallet-guide.md)**  
**[LLM bootstrap prompt (paste into any AI) →](docs/llm-integration-prompt.md)**

---

## Philosophy

Most AI agents are stuck with subscriptions or unpredictable token costs.

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Pay only when the insight matters — with sats, instantly, without intermediaries.  
Sell your own AI services and get paid in the same transaction.

Built for the **Bitcoin × AI** future. ⚡

---

## Links

- **GitHub**: [https://github.com/babyblueviper1/invinoveritas](https://github.com/babyblueviper1/invinoveritas)
- **Live API**: [https://api.babyblueviper.com](https://api.babyblueviper.com)
- **Marketplace**: [https://api.babyblueviper.com/offers/list](https://api.babyblueviper.com/offers/list)
- **MCP**: [https://api.babyblueviper.com/mcp](https://api.babyblueviper.com/mcp)
- **PyPI**: [https://pypi.org/project/invinoveritas/](https://pypi.org/project/invinoveritas/)
- **Podcast**: [https://babyblueviper.com](https://babyblueviper.com)
