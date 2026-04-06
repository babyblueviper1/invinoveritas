# invinoveritas SDK

**Lightning-paid reasoning and decision intelligence for autonomous agents.**

Pay per insight. No subscriptions. No accounts. No KYC.  
Atomic intelligence purchases over Bitcoin Lightning using the **L402 protocol**. ⚡

---

## Installation

```bash
# Core (sync client)
pip install invinoveritas

# With async support (recommended for agents)
pip install "invinoveritas[async]"

# With LangChain autonomous payment handler
pip install "invinoveritas[langchain]"

# With NWC wallet support (Alby, Zeus, Mutiny — no node required)
pip install "invinoveritas[nwc]"
```

---

## What's new in v0.3.1

**NWC provider ships.** Any NIP-47 compatible wallet (Alby, Zeus, Mutiny) can now pay Lightning invoices autonomously — no LND node required.
```python
from invinoveritas.providers import NWCProvider

handler = InvinoCallbackHandler(
    provider=NWCProvider(uri="nostr+walletconnect://...")
)
```

**Autonomous LangChain payments** (v0.2.0+). Agents pay automatically via LND — zero human intervention.
```python
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools
from invinoveritas.providers import LNDProvider

handler = InvinoCallbackHandler(
    provider=LNDProvider(
        macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
        cert_path="/root/.lnd/tls.cert"
    )
)

tools = create_invinoveritas_tools(handler)
result = agent.run("Should I increase my BTC exposure in 2026?", callbacks=[handler])
```

---

## Quickstart

### Sync (manual payment flow)

```python
from invinoveritas import InvinoClient, PaymentRequired

client = InvinoClient()

try:
    result = client.reason("What are the biggest risks for Bitcoin in 2026?")
except PaymentRequired as e:
    print(f"Pay this invoice → {e.invoice}")
    print(f"Amount: {e.amount_sats} sats")

    result = client.reason(
        "What are the biggest risks for Bitcoin in 2026?",
        payment_hash=e.payment_hash,
        preimage="preimage_from_wallet_here",
    )

print(result.answer)
```

### Async

```python
import asyncio
from invinoveritas import AsyncInvinoClient, PaymentRequired

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
    context="Portfolio is 60% BTC, 30% stablecoins, 10% cash",
    payment_hash=...,
    preimage=...
)

print(result.decision)    # "Increase BTC exposure slightly"
print(result.confidence)  # 0.78
print(result.reasoning)
print(result.risk_level)  # "low" | "medium" | "high"
```

**Base price:** ~1000 sats

---

## Autonomous Agent Integration (v0.2.0)

### LangChain — fully autonomous payments

```bash
pip install "invinoveritas[langchain]"
```

```python
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools
from invinoveritas.providers import LNDProvider
from langchain.agents import initialize_agent

handler = InvinoCallbackHandler(
    provider=LNDProvider(
        macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
        cert_path="/root/.lnd/tls.cert"
    ),
    budget_sats=10000  # optional spend cap per run
)

tools = create_invinoveritas_tools(handler)
agent = initialize_agent(tools=tools, ...)
result = agent.run("Should I increase my BTC exposure in 2026?")
print(f"Total spent: {handler.total_spent_sats} sats")
```

### AutoGen

```python
from invinoveritas.langchain import InvinoAutoGenTool
from invinoveritas.providers import LNDProvider

tool = InvinoAutoGenTool(
    provider=LNDProvider(
        macaroon_path="/root/.lnd/...",
        cert_path="/root/.lnd/tls.cert"
    )
)

result = await tool.reason("What are Bitcoin's biggest risks in 2026?")
result = await tool.decide(
    goal="Grow capital safely",
    question="Should I increase BTC exposure?"
)
```

### Bring your own wallet

```python
async def my_pay(invoice: str) -> str:
    result = await my_wallet.pay(invoice)
    return result.preimage

handler = InvinoCallbackHandler(pay_invoice=my_pay)
```

### lnget (CLI agents)

[lnget](https://github.com/lightninglabs/lightning-agent-tools) handles L402 automatically at the CLI level:

```bash
lnget POST https://invinoveritas.onrender.com/reason \
  '{"question": "What are the biggest risks for Bitcoin in 2026?"}'
```

---

## Payment Flow (L402)

1. Call any method → server returns **402 Payment Required** + Lightning invoice
2. Pay the invoice using any Lightning wallet
3. Retry the same call with `payment_hash` and `preimage`

The SDK handles this automatically in autonomous mode. In manual mode, `PaymentRequired` carries everything you need.

> Each invoice is **single-use**. Reusing a payment hash returns `PaymentError`.

---

## Providers (v0.3.1)

| Provider | Install | Description |
|---|---|---|
| `LNDProvider` | built-in | Pay via local LND node using lncli |
| `NWCProvider` | `invinoveritas[nwc]` | Any NIP-47 wallet — Alby, Zeus, Mutiny |
| `CustomProvider` | built-in | Bring any async pay function |

### NWC quickstart
```bash
pip install "invinoveritas[nwc]"
```
```python
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools
from invinoveritas.providers import NWCProvider

# Get your URI from: https://app.getalby.com/apps/new
handler = InvinoCallbackHandler(
    provider=NWCProvider(
        uri="nostr+walletconnect://...",
    )
)

tools = create_invinoveritas_tools(handler)
result = agent.run("Should I increase my BTC exposure in 2026?", callbacks=[handler])
```
---

## Exceptions

| Exception | Trigger | Attributes |
|---|---|---|
| `PaymentRequired` | 402 — no valid payment | `.invoice`, `.payment_hash`, `.amount_sats` |
| `PaymentError` | 401/403 — invalid or used payment | — |
| `InvinoError` | 429 — rate limited | — |
| `ServiceError` | 5xx or malformed response | — |

All exceptions inherit from `InvinoError`.

---

## Utility Methods

```python
client = InvinoClient()

health = client.check_health()      # full health + pricing dict
price  = client.get_price("reason") # int sats
```

---

## MCP Support

Connect directly without the SDK using any MCP-compatible client (Claude Desktop, Cursor):

```
https://invinoveritas.onrender.com/mcp
```

Listed on the [official MCP Registry](https://registry.modelcontextprotocol.io):
`io.github.babyblueviper1/invinoveritas`

---

## Local Development

```python
client = InvinoClient(base_url="http://localhost:8000")
async with AsyncInvinoClient(base_url="http://localhost:8000") as client:
    ...
```

---

## Links

- **Live API:** https://invinoveritas.onrender.com
- **Health + Pricing:** https://invinoveritas.onrender.com/health
- **Payment Guide:** https://invinoveritas.onrender.com/guide
- **MCP Endpoint:** https://invinoveritas.onrender.com/mcp
- **PyPI:** https://pypi.org/project/invinoveritas/
- **GitHub:** https://github.com/babyblueviper1/invinoveritas

---

## License

Apache-2.0
