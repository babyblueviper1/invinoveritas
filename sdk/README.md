# invinoveritas SDK

**Lightning-paid reasoning and decision intelligence for autonomous agents.**

Pay per insight. No subscriptions. No accounts. No KYC.  
Atomic intelligence purchases over Bitcoin Lightning using the **L402 protocol**. ⚡

---

## Installation

```bash
# Sync client only (lightweight)
pip install invinoveritas

# With async support (recommended for agents)
pip install "invinoveritas[async]"
```

---

## Quickstart

### Synchronous

```python
from invinoveritas_sdk import InvinoClient, PaymentRequired

client = InvinoClient()

try:
    result = client.reason("What are the biggest risks for Bitcoin in 2026?")
except PaymentRequired as e:
    print(f"Pay this invoice → {e.invoice}")
    print(f"Amount: {e.amount_sats} sats")

    # After paying with any Lightning wallet
    result = client.reason(
        "What are the biggest risks for Bitcoin in 2026?",
        payment_hash=e.payment_hash,
        preimage="preimage_from_wallet_here",
    )

print(result.answer)
```

### Asynchronous

```python
import asyncio
from invinoveritas_sdk import AsyncInvinoClient, PaymentRequired

async def main():
    async with AsyncInvinoClient() as client:
        try:
            result = await client.reason("What are the biggest risks for Bitcoin in 2026?")
        except PaymentRequired as e:
            result = await client.reason(
                "What are the biggest risks for Bitcoin in 2026?",
                payment_hash=e.payment_hash,
                preimage="preimage_from_wallet_here",
            )
            print(result.answer)

asyncio.run(main())
```

---

## Core Tools

### `reason()` — Deep strategic reasoning

```python
result = client.reason(
    question="Should we expand into the European market in 2026?",
    payment_hash=...,
    preimage=...
)

print(result.answer)
```

**Base price:** ~500 sats

---

### `decide()` — Structured decision intelligence

```python
result = client.decide(
    goal="Grow capital safely while managing risk",
    question="Should I increase BTC exposure now?",
    context="Portfolio is 60% BTC, 30% stablecoins, 10% cash",  # optional
    payment_hash=...,
    preimage=...
)

print(result.decision)      # "Increase BTC exposure slightly"
print(result.confidence)    # 0.78
print(result.reasoning)
print(result.risk_level)    # "low" | "medium" | "high"
```

**Base price:** ~1000 sats

---

## Utility & Discovery Methods

```python
client = InvinoClient()

# Get full current pricing (recommended for agents)
pricing = client.get_prices()

# Get single base price (for backward compatibility)
price = client.get_price("reason")

# Get tool definition for agent frameworks
tool = client.get_tool_definition()
```

**Same methods are available** on `AsyncInvinoClient`.

---

## Payment Flow (L402)

1. Call any method → server returns **402 Payment Required** + Lightning invoice.
2. Pay the invoice using any Lightning wallet.
3. Retry the **same** call, passing `payment_hash` and `preimage`.

The SDK makes this simple: `PaymentRequired` exception carries everything you need.

> **Note:** Each invoice is **single-use**. Reusing a payment hash returns `PaymentError`.

---

## Agent Framework Integration Examples

### LangChain Tool

```python
from langchain.tools import tool
from invinoveritas_sdk import AsyncInvinoClient, PaymentRequired

@tool
async def invino_reason(question: str, payment_hash: str = None, preimage: str = None) -> str:
    """Get strategic reasoning powered by Lightning payments."""
    async with AsyncInvinoClient() as client:
        try:
            result = await client.reason(question, payment_hash=payment_hash, preimage=preimage)
            return result.answer
        except PaymentRequired as e:
            raise ValueError(f"Payment required. Invoice: {e.invoice}")
```

### Get Invoice First (Orchestration Pattern)

```python
client = InvinoClient()
question = "What are the biggest risks for Bitcoin in 2026?"

try:
    result = client.reason(question)
except PaymentRequired as e:
    # Send invoice to user / payment service
    invoice = e.invoice
    payment_hash = e.payment_hash
    amount = e.amount_sats
    # ... wait for payment confirmation ...
    result = client.reason(question, payment_hash=payment_hash, preimage=received_preimage)
```

---

## Exceptions

| Exception          | Trigger                              | Attributes |
|--------------------|--------------------------------------|----------|
| `PaymentRequired`  | 402 - No valid payment provided     | `.invoice`, `.payment_hash`, `.amount_sats` |
| `PaymentError`     | 401 / 403 - Invalid or used payment | - |
| `InvinoError`      | Rate limiting (429)                 | - |
| `ServiceError`     | Server errors (5xx) or malformed responses | - |

All exceptions inherit from `InvinoError`.

---

## Local Development

```python
client = InvinoClient(base_url="http://localhost:8000")
```

Same for `AsyncInvinoClient`.

---

## MCP Support

If you're using Claude Desktop, Cursor, or any MCP-compatible client, you can connect directly without the SDK:

**MCP Endpoint:** `https://invinoveritas.onrender.com/mcp`

---

## Links

- **Live API:** https://invinoveritas.onrender.com
- **Health:** https://invinoveritas.onrender.com/health
- **Full Pricing:** https://invinoveritas.onrender.com/prices
- **MCP Endpoint:** https://invinoveritas.onrender.com/mcp
- **GitHub:** https://github.com/babyblueviper1/invinoveritas

---

## License

Apache-2.0

---
