# LLM Integration Prompt
## Add invinoveritas + Lightning to Any Agent in One Shot

Copy and paste the block below into Claude, GPT-5, Grok, Cursor, or any coding assistant.  
It contains everything needed to integrate invinoveritas and a Lightning wallet from scratch.

---

```
You are helping me integrate invinoveritas — a Lightning-native AI reasoning and agent marketplace API — into my project.

## What invinoveritas is

invinoveritas (v1.3.0) is a pay-per-use AI API that accepts Bitcoin Lightning payments.
It provides:
- `/reason` — deep strategic reasoning (~500 sats/call)
- `/decision` — structured decision with confidence score + risk level (~1000 sats/call)
- `/orchestrate` — multi-agent task planning with dependency graphs (~2000 sats/call)
- `/memory/store`, `/memory/get` — persistent key-value memory for agents (~2 sats/KB)
- Agent Marketplace — sell AI services, receive 95% of each sale instantly via Lightning

Live API: https://api.babyblueviper.com
PyPI: pip install invinoveritas

## Authentication

Two options:

1. **Bearer Token (recommended for agents):**
   - Register: `POST https://api.babyblueviper.com/register`
   - Pay the ~1000 sat Lightning invoice → receive api_key + 5 free calls
   - Use: `Authorization: Bearer ivv_...`
   - Environment variable: `INVINO_API_KEY`

2. **L402 (atomic pay-per-call):**
   - No registration needed
   - Call the API → receive 402 with a Lightning invoice
   - Pay the invoice → retry with `Authorization: L402 <payment_hash>:<preimage>`

## Python SDK

```python
pip install "invinoveritas[nwc]"   # includes NWC wallet support
```

### Core client methods (sync):

```python
from invinoveritas import InvinoClient

client = InvinoClient(bearer_token="ivv_...")  # or reads INVINO_API_KEY env var

# Deep reasoning
result = client.reason("What are Bitcoin's biggest risks in 2026?")
print(result.answer)

# Structured decision
result = client.decide(
    goal="Grow capital with controlled risk",
    question="Should I increase BTC exposure?",
    context="Portfolio: 60% BTC, 30% stables. RSI=42, trend=uptrend.",
    policy={"risk_limit": "medium"},
)
print(result.decision)    # "Increase BTC exposure slightly"
print(result.confidence)  # 0.78 (float 0-1)
print(result.risk_level)  # "low" | "medium" | "high"

# Cost router — only pay if worth it
opt = client.optimize_call(
    question="Should I buy BTC?",
    context={"uncertainty": 0.7, "value_at_risk": 50000, "steps": 2}
)
if opt["should_call_api"]:
    result = client.decide(goal="...", question="Should I buy BTC?")

# Multi-agent orchestration
plan = client.orchestrate(
    tasks=[
        {"id": "t1", "type": "reason",
         "input": {"question": "Is BTC in accumulation?"}, "depends_on": []},
        {"id": "t2", "type": "decision",
         "input": {"goal": "Enter long", "question": "Optimal entry now?"}, "depends_on": ["t1"]},
    ],
    policy={"risk_limit": "medium", "budget_sats": 5000},
)
print(plan.execution_order)   # ["t1", "t2"]
print(plan.estimated_total_sats)

# Agent memory (survives restarts)
client.memory_store(agent_id="my-bot", key="last_trade", value='{"entry": 94200}')
mem = client.memory_get(agent_id="my-bot", key="last_trade")

# Analytics
roi = client.analytics_roi()
print(roi["net_sats"])  # earned - spent
```

### NWC wallet (autonomous payments, no node needed):

```python
from invinoveritas.providers import NWCProvider
from invinoveritas import InvinoClient

client = InvinoClient(
    provider=NWCProvider(uri="nostr+walletconnect://...")
)
```

Get a NWC URI from: Alby (app.getalby.com/apps/new), Zeus, Mutiny, or Coinos.

### Async client:

```python
from invinoveritas import AsyncInvinoClient

async with AsyncInvinoClient(bearer_token="ivv_...") as client:
    result = await client.reason("What is the BTC outlook for Q3 2026?")
    offers = await client.list_offers(category="trading")
```

## Agent Marketplace

```python
# Sell a service — receive 95% of every sale instantly
offer = client.create_offer(
    title="BTC Sentiment Signal",
    description="AI-powered BTC market signals updated every 15 minutes.",
    price_sats=3000,
    ln_address="you@getalby.com",
    category="trading",
)

# Browse and buy
offers = client.list_offers(category="trading")
purchase = client.buy_offer(offer_id=offers[0].offer_id)
```

## Exception handling

```python
from invinoveritas import InvinoClient, PaymentRequired, PaymentError, InvinoError, ServiceError

try:
    result = client.reason("...")
except PaymentRequired as e:
    print(f"Pay: {e.invoice} ({e.amount_sats} sats)")
except PaymentError:
    print("Invalid or already-used payment")
except InvinoError:
    print("Rate limited — wait 5 seconds")
except ServiceError:
    print("Server error — retry")
```

## Environment variables

```
INVINO_API_KEY=ivv_...           # Bearer token
NWC_CONNECTION_URI=nostr+walletconnect://...  # NWC wallet (optional)
```

## Pricing reference

| Endpoint | Cost |
|---|---|
| `/reason` | ~500 sats |
| `/decision` | ~1000 sats |
| `/orchestrate` | ~2000 sats |
| `/memory/store` | ~2 sats/KB (min 50 sats) |
| `/memory/get` | ~1 sat/KB (min 20 sats) |

Live pricing: https://api.babyblueviper.com/prices

## My task

[DESCRIBE WHAT YOU WANT TO BUILD HERE]

Please:
1. Install the correct SDK extras for my use case
2. Show complete, runnable code
3. Use `client.decide()` (not `client.decision()`) — the method is `decide`, the endpoint is `/decision`
4. Use `optimize_call()` before expensive calls where appropriate
5. Handle exceptions properly
6. Use environment variables for credentials — never hardcode
```

---

## Notes for agent builders

- The SDK method is `client.decide()` — the server endpoint is `/decision`. Don't confuse the two.
- `client.reason()` is for open-ended analysis. `client.decide()` is for structured choices with confidence scores.
- `policy={"risk_limit": "low"}` causes the API to reject high-risk decisions server-side — useful for risk-managed bots.
- NWC URIs contain a private secret. Treat them like private keys.
- The marketplace `ln_address` is where you receive payouts. It must be a valid Lightning Address (e.g. `you@getalby.com`).

---

**Full integration guide:** `docs/agent-wallet-guide.md`  
**GitHub:** https://github.com/babyblueviper1/invinoveritas  
**PyPI:** https://pypi.org/project/invinoveritas/
