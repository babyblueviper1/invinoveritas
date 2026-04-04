# invinoveritas SDK

**Lightning-paid reasoning and decision intelligence for autonomous agents.**

Pay per insight. No subscriptions. No accounts. No KYC.  
Atomic intelligence purchases over Bitcoin Lightning via the L402 protocol. ⚡

---

## Install

```bash
# Sync only
pip install invinoveritas

# With async support (recommended for agent frameworks)
pip install invinoveritas[async]
```

---

## Quickstart

### Sync

```python
from invinoveritas_sdk import InvinoClient, PaymentRequired

client = InvinoClient()

# Step 1 — first call returns a Lightning invoice
try:
    result = client.reason("What are the biggest risks for Bitcoin in 2026?")
except PaymentRequired as e:
    print(f"Invoice: {e.invoice}")       # pay this with any Lightning wallet
    print(f"Amount:  {e.amount_sats} sats")

    # Step 2 — retry with payment credentials
    result = client.reason(
        "What are the biggest risks for Bitcoin in 2026?",
        payment_hash=e.payment_hash,
        preimage="your_preimage_here",   # returned by your wallet after payment
    )
    print(result.answer)
```

### Async

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
                preimage="your_preimage_here",
            )
            print(result.answer)

asyncio.run(main())
```

---

## Tools

### `reason` — Strategic reasoning

```python
result = client.reason(
    question="Should I migrate my infrastructure to the cloud?",
    payment_hash="...",
    preimage="...",
)

print(result.answer)        # full reasoning response
print(result.payment_hash)  # hash used for this request
```

**Pricing:** from 500 sats (base) · up to ~800 sats with agent multiplier

---

### `decide` — Structured decision intelligence

```python
result = client.decide(
    goal="Reduce infrastructure costs by 30%",
    question="Should we migrate to serverless?",
    context="Current stack: Python/FastAPI on Render, ~10k req/day",  # optional
    payment_hash="...",
    preimage="...",
)

print(result.decision)    # recommended course of action
print(result.confidence)  # float 0.0–1.0
print(result.reasoning)   # explanation
print(result.risk_level)  # "low" | "medium" | "high"
```

**Pricing:** from 1000 sats (base) · up to ~1400 sats with agent multiplier

---

## Payment flow

The L402 protocol is a two-step challenge/response over HTTP:

```
1. Call any tool (no auth header)
      → server returns 402 + bolt11 invoice

2. Pay the invoice with any Lightning wallet
      → wallet returns payment_hash + preimage

3. Retry the exact same call with:
      Authorization: L402 <payment_hash>:<preimage>
      → server verifies and returns the result
```

The SDK handles all of this automatically — `PaymentRequired` carries
everything you need, and passing `payment_hash` + `preimage` back into
the same method constructs the header for you.

**Each invoice is single-use.** Replaying a used payment hash returns a
`PaymentError`.

---

## Agent framework examples

### LangChain tool

```python
from langchain.tools import tool
from invinoveritas_sdk import AsyncInvinoClient, PaymentRequired

@tool
async def reason_tool(question: str, payment_hash: str, preimage: str) -> str:
    """Call invinoveritas for strategic reasoning. Requires a paid Lightning invoice."""
    async with AsyncInvinoClient() as client:
        result = await client.reason(question, payment_hash=payment_hash, preimage=preimage)
        return result.answer
```

### AutoGen tool

```python
from autogen import tool
from invinoveritas_sdk import AsyncInvinoClient

@tool
async def invino_decide(goal: str, question: str, payment_hash: str, preimage: str) -> dict:
    async with AsyncInvinoClient() as client:
        result = await client.decide(goal, question, payment_hash=payment_hash, preimage=preimage)
        return {
            "decision": result.decision,
            "confidence": result.confidence,
            "risk_level": result.risk_level,
        }
```

### Get the invoice first (agent orchestration pattern)

```python
from invinoveritas_sdk import InvinoClient, PaymentRequired

client = InvinoClient()
question = "Which cloud provider should we use for our ML workloads?"

# Phase 1: fetch invoice (agent triggers payment flow)
try:
    client.reason(question)
except PaymentRequired as e:
    invoice = e.invoice
    payment_hash = e.payment_hash
    amount_sats = e.amount_sats
    # hand off invoice to wallet/payment orchestrator...

# Phase 2: after payment confirmed, complete the call
result = client.reason(question, payment_hash=payment_hash, preimage=received_preimage)
print(result.answer)
```

---

## Utility methods

```python
# Check service health and current pricing (free)
health = client.check_health()
print(health["pricing"])

# Get current base price for a specific endpoint
price = client.get_price("reason")    # → int (sats)
price = client.get_price("decision")  # → int (sats)
```

---

## Local development

```python
# Point at a local server
client = InvinoClient(base_url="http://localhost:8000")

# Or with async
async with AsyncInvinoClient(base_url="http://localhost:8000") as client:
    ...
```

---

## Exceptions

| Exception | When raised |
|---|---|
| `PaymentRequired` | 402 — no payment provided. Carries `.invoice`, `.payment_hash`, `.amount_sats` |
| `PaymentError` | 401/403 — bad preimage, expired, or already used invoice |
| `InvinoError` | 429 — rate limited |
| `ServiceError` | 5xx or unexpected response |

All exceptions inherit from `InvinoError`.

---

## MCP endpoint

If you're using an MCP-compatible client (Claude Desktop, Cursor), point it
directly at the MCP endpoint — no SDK needed:

```
https://invinoveritas.onrender.com/mcp
```

The MCP server exposes the same `reason` and `decide` tools with full L402
payment handling built in.

---

## Links

- **Live API:** https://invinoveritas.onrender.com
- **MCP endpoint:** https://invinoveritas.onrender.com/mcp
- **Health / pricing:** https://invinoveritas.onrender.com/health
- **GitHub:** https://github.com/babyblueviper1/invinoveritas

---

## License

Apache 2.0
