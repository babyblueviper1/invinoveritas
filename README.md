# ⚡ invinoveritas
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![smithery badge](https://smithery.ai/badge/babyblueviper1/invinoveritas)](https://smithery.ai/servers/babyblueviper1/invinoveritas)
[![PyPI](https://img.shields.io/pypi/v/invinoveritas)](https://pypi.org/project/invinoveritas/)

**Lightning-paid reasoning and decision intelligence for autonomous agents**

Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning).  
No subscriptions. No accounts. No KYC.

**Live API**: [https://invinoveritas.onrender.com](https://invinoveritas.onrender.com)  
**MCP Endpoint**: [https://invinoveritas.onrender.com/mcp](https://invinoveritas.onrender.com/mcp)

---

## Quick Start

### Python SDK (easiest)
```bash
pip install invinoveritas
```
```python
from invinoveritas_sdk import InvinoClient, PaymentRequired

client = InvinoClient()

try:
    result = client.reason("What are the biggest risks for Bitcoin in 2026?")
except PaymentRequired as e:
    print(f"Pay: {e.invoice}  ({e.amount_sats} sats)")
    result = client.reason(
        "What are the biggest risks for Bitcoin in 2026?",
        payment_hash=e.payment_hash,
        preimage="your_preimage_here",
    )
    print(result.answer)
```

Full SDK docs → [`sdk/README.md`](sdk/README.md)

### MCP Endpoint (Claude Desktop, Cursor)

Point your MCP-compatible agent to:

```
https://invinoveritas.onrender.com/mcp
```
Full L402 payment handling built-in. Supports `initialize`, `listTools`, and `callTool`.

### Direct HTTP
```bash
curl -X POST https://invinoveritas.onrender.com/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "callTool",
    "params": {
      "name": "reason",
      "arguments": { "question": "What are the biggest risks for Bitcoin in 2026?" }
    }
  }'
```
After paying the returned invoice, retry with `-H "Authorization: L402 <payment_hash>:<preimage>"`.

---

## Pricing (Dynamic)

| Tool       | Base Price       | With Agent Multiplier | Typical Range     |
|------------|------------------|-----------------------|-------------------|
| `reason`   | 500 sats         | 1.2x                  | 500 – 800 sats    |
| `decide`   | 1000 sats        | 1.2x                  | 1000 – 1400 sats  |

Prices can vary slightly based on input length.

---

## Why Agents Use invinoveritas

Autonomous agents use invinoveritas when they need:

- Strategic reasoning deeper than local models
- Structured, machine-readable decisions with confidence & risk scores
- Deterministic, predictable costs (paid in sats)
- Cryptographically verifiable payments via Lightning
- Native MCP tool support

Pay only when the insight truly matters — atomically, with Bitcoin Lightning.

---

## Core Tools (via MCP)

- **`reason`** — Premium strategic reasoning
- **`decide`** — Structured decision intelligence

Both tools support the full L402 payment flow.

---

## Payment Flow (L402)

1. First call (REST or MCP) → returns **402 Payment Required** + Lightning invoice
2. Pay the invoice using any Lightning wallet
3. Retry the **exact same request** with the header:
   ```
   Authorization: L402 <payment_hash>:<preimage>
   ```
4. Receive the result

---

## Discovery Endpoints (Free)

- `GET /health` — Service status and pricing
- `GET /.well-known/mcp/server-card.json` — MCP server card
- `GET /price/{endpoint}` — Current price in sats

---

## Philosophy

Most AI agents are stuck with subscriptions or unpredictable token costs.

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Pay only when the decision matters — with sats, instantly, and without intermediaries.

---

Built for the Bitcoin × AI future. ⚡

---

### Quick Links
- GitHub: https://github.com/babyblueviper1/invinoveritas
- Live API: https://invinoveritas.onrender.com
- MCP Endpoint: https://invinoveritas.onrender.com/mcp
- Health Check: https://invinoveritas.onrender.com/health
