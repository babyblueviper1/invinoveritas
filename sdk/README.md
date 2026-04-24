# invinoveritas SDK v1.1.0

**Lightning-native AI reasoning, decisions, memory, orchestration, and agent marketplace.**  
Pay per insight. No subscriptions. No accounts. No KYC. Pure Bitcoin Lightning.

```
pip install invinoveritas
```

**Live API:** `https://api.babyblueviper.com`  
**MCP:** `https://api.babyblueviper.com/mcp`  
**PyPI:** `https://pypi.org/project/invinoveritas/`

---

## What's new in v1.1.0

| Feature | Description |
|---|---|
| **Agent Marketplace** | List and sell AI agent services. **95% to seller instantly** via Lightning. 5% platform fee. |
| **Multi-agent Orchestration** | `/orchestrate` — dependency resolution, risk scoring, policy enforcement |
| **Analytics / Observability** | `/analytics/spend`, `/analytics/roi`, `/analytics/memory` |
| **NWC Default** | Nostr Wallet Connect is now the recommended wallet — works with Alby, Zeus, Mutiny |
| **`optimize_call()`** | Smart routing helper — picks cheapest endpoint for your task |
| **`policy={}`** | Governance hooks on all calls — set `risk_limit`, `budget_sats`, etc. |
| **Net Profit Demo** | Trading bot template that proves AI spend < trade gains |
| **URL migration** | All URLs updated to `https://api.babyblueviper.com` (Render retired) |

---

## Installation

```bash
# Core (sync + async)
pip install invinoveritas

# NWC wallet — RECOMMENDED for autonomous agents (Alby, Zeus, Mutiny)
pip install "invinoveritas[nwc]"

# Async support
pip install "invinoveritas[async]"

# LangChain autonomous payments
pip install "invinoveritas[langchain]"
```

---

## Quickstart — 3 lines

```python
from invinoveritas import InvinoClient

client = InvinoClient(bearer_token="your-api-key")
result = client.reason("Should I buy BTC now given current macro?")
print(result.answer)
```

Get your API key (Bearer token) at: `https://api.babyblueviper.com/register`

---

## NWC Setup (Recommended)

NWC (Nostr Wallet Connect) lets your agent pay Lightning invoices autonomously  
using any NIP-47 wallet — **no LND node required**.

```bash
pip install "invinoveritas[nwc]"
```

```python
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools
from invinoveritas.providers import NWCProvider

# Get your URI: https://app.getalby.com/apps/new
handler = InvinoCallbackHandler(
    provider=NWCProvider(uri="nostr+walletconnect://...")
)

tools = create_invinoveritas_tools(handler)
result = agent.run("Should I increase BTC exposure in 2026?", callbacks=[handler])
print(f"Total spent: {handler.total_spent_sats} sats")
```

**One-command wallet examples:**

| Wallet | Command |
|---|---|
| Alby | Get URI at https://app.getalby.com/apps/new |
| Zeus | Settings → Nostr Wallet Connect → New Connection |
| Mutiny | Settings → NWC → Add Connection |

---

## Core AI Tools

### `reason()` — Deep strategic reasoning

```python
result = client.reason(
    question="What are the biggest risks for Bitcoin in 2026?",
    policy={"risk_limit": "medium"},   # optional governance
)
print(result.answer)
```

**~500 sats per call**

---

### `decide()` — Structured decision intelligence

```python
result = client.decide(
    goal="Maximize BTC net profit with managed drawdown",
    question="Should I increase BTC exposure now?",
    context="Portfolio: 60% BTC, 30% stablecoins, 10% cash. RSI=42, trend=uptrend.",
    policy={"risk_limit": "low"},
)

print(result.decision)    # "Increase BTC exposure slightly"
print(result.confidence)  # 0.78
print(result.reasoning)
print(result.risk_level)  # "low" | "medium" | "high"
```

**~1000 sats per call**

---

### `optimize_call()` — Smart cost routing

Before paying for an API call, check if it's worth it:

```python
opt = client.optimize_call(
    question="Should I buy BTC now?",
    context={
        "uncertainty": 0.7,
        "value_at_risk": 50000,  # sats
        "steps": 3,
    }
)

print(opt["recommended_endpoint"])  # "reason" | "decide" | "local"
print(opt["estimated_sats"])        # 500 | 1000 | 0
print(opt["should_call_api"])       # True | False
print(opt["reason"])

if opt["should_call_api"]:
    result = client.reason(question)
else:
    result = local_model(question)  # fallback
```

---

## Agent Marketplace

The Lightning-native marketplace for selling agent services.  
**Platform takes 5%. Seller receives 95% instantly on every sale.**

### Sell an agent service

```python
client = InvinoClient(bearer_token="your-api-key")

offer = client.create_offer(
    title="Bitcoin Sentiment Analysis",
    description="AI-powered BTC market sentiment with trade signals.",
    price_sats=5000,
    ln_address="you@getalby.com",     # Your Lightning Address — payouts go here
    category="trading",
)

print(f"Offer ID: {offer['offer_id']}")
print(f"You earn: {offer['seller_payout_sats']} sats per sale ({offer['seller_percent']}%)")
print(f"Platform: {offer['platform_cut_sats']} sats ({offer['platform_cut_percent']}%)")
```

### Browse and buy offers

```python
# Browse
offers = client.list_offers(category="trading")
for o in offers:
    print(f"{o.title} — {o.price_sats:,} sats")

# Buy (buyer's Bearer account is charged; seller gets 95% instantly)
purchase = client.buy_offer(offer_id=offers[0].offer_id)
print(f"Purchased: {purchase.title}")
print(f"Seller payout status: {purchase.seller_payout_status}")
```

### View your sales (as seller)

```python
my = client.my_offers()
print(f"Total earned: {my['total_earned_sats']:,} sats")
for o in my["offers"]:
    print(f"  {o['title']}: {o['sold_count']} sales, {o['total_earned_sats']:,} sats")
```

### Marketplace fee structure

| Party | Amount | How |
|---|---|---|
| Buyer | 100% of offer price | Deducted from Bearer balance |
| **Seller** | **95%** | **Sent instantly to seller's Lightning Address** |
| Platform (Invinoveritas) | 5% | Kept as service fee |

> The 5% platform cut is the **default**. It is configurable server-side via  
> `PLATFORM_CUT_PERCENT` environment variable.

---

## Multi-Agent Orchestration

Plan and risk-score a chain of agent tasks before executing them.

```python
plan = client.orchestrate(
    tasks=[
        {
            "id": "market_check",
            "type": "reason",
            "input": {"question": "Is BTC in an accumulation phase?"},
            "depends_on": [],
        },
        {
            "id": "trade_decision",
            "type": "decide",
            "input": {
                "goal": "Maximize BTC returns",
                "question": "Should I enter a long position?",
                "uncertainty": 0.6,
                "value_at_risk": 100000,
            },
            "depends_on": ["market_check"],
        },
    ],
    context="Trading bot session",
    policy={"risk_limit": "medium", "budget_sats": 10000},
)

print(f"Execute in order: {plan.execution_order}")
print(f"Estimated cost  : {plan.estimated_total_sats:,} sats")
for tid, risk in plan.risk_scores.items():
    print(f"  {tid}: risk={risk['label']}")
```

**~2000 sats per orchestration plan**

---

## Analytics / Observability

```python
# Spending history
spend = client.analytics_spend(days=30)
print(f"Spent this month: {spend['account_total_spent_sats']:,} sats")
print(f"Calls made      : {spend['account_total_calls']}")
print(f"Daily breakdown : {spend['daily_spend']}")

# ROI — are you profitable?
roi = client.analytics_roi()
print(f"Lifetime spend         : {roi['total_spent_sats']:,} sats")
print(f"Marketplace earnings   : {roi['marketplace_earnings_sats']:,} sats")
print(f"Net sats               : {roi['net_sats']:+,} sats")

# Memory usage
mem = client.analytics_memory()
print(f"Total stored : {mem['total_kb']:.1f} KB across {mem['agent_count']} agents")
```

---

## Governance Hooks

Pass `policy={}` on any call to enforce limits at the API level:

```python
# Prevent high-risk calls
result = client.decide(
    goal="...", question="...",
    policy={"risk_limit": "low"},          # refuse if AI returns risk="high"
)

# Budget cap on orchestration
plan = client.orchestrate(
    tasks=[...],
    policy={
        "risk_limit": "medium",
        "budget_sats": 5000,               # estimated max spend
    }
)
```

---

## Persistent Agent Memory

```python
# Store context (cost: ~2 sats/KB)
client.memory_store(agent_id="my-bot", key="last_trade", value=json.dumps({
    "direction": "long", "entry": 95000, "size_sats": 100000
}))

# Retrieve later (~1 sat/KB)
mem = client.memory_get(agent_id="my-bot", key="last_trade")
print(mem["value"])

# Free operations
client.memory_list(agent_id="my-bot")
client.memory_delete(agent_id="my-bot", key="last_trade")
```

---

## LangChain Integration

```bash
pip install "invinoveritas[langchain]"
```

```python
from invinoveritas.langchain import InvinoCallbackHandler, create_invinoveritas_tools
from invinoveritas.providers import LNDProvider, NWCProvider
from langchain.agents import initialize_agent

# Option A: NWC wallet (no node needed)
handler = InvinoCallbackHandler(
    provider=NWCProvider(uri="nostr+walletconnect://..."),
    budget_sats=10000
)

# Option B: Local LND node
handler = InvinoCallbackHandler(
    provider=LNDProvider(
        macaroon_path="/root/.lnd/data/chain/bitcoin/mainnet/admin.macaroon",
        cert_path="/root/.lnd/tls.cert"
    )
)

tools = create_invinoveritas_tools(handler)
agent = initialize_agent(tools=tools, ...)
result = agent.run("Should I increase my BTC allocation in 2026?")
print(f"Total spent: {handler.total_spent_sats} sats")
```

---

## Trading Bot Template

See `examples/trading/trading_bot_net_profit.py` for a full trading bot that:
- Calls `optimize_call()` before every consultation
- Uses `decide()` with confidence and risk filters
- Tracks gross P&L vs. AI consultation cost
- Prints **NET PROFIT** at the end

```bash
export INVINO_API_KEY="your-api-key"
python examples/trading/trading_bot_net_profit.py
```

Sample output:
```
═══════════════════════════════════════════════════════
  NET PROFIT SUMMARY
═══════════════════════════════════════════════════════
  Trades executed    : 7
  Win rate           : 71%
  Gross trading P&L  : +82,400 sats
  AI consult cost    : 7,000 sats
  ┌─────────────────────────────────────────┐
  │  NET PROFIT (P&L - AI cost) : +75,400 sats │
  └─────────────────────────────────────────┘
  Return on AI spend : 11.8x
  ✅ PROFITABLE: The AI consultation cost was justified.
```

---

## Async Client

```python
import asyncio
from invinoveritas import AsyncInvinoClient

async def main():
    async with AsyncInvinoClient(bearer_token="your-api-key") as client:
        result = await client.reason("What are Bitcoin's biggest risks in 2026?")
        print(result.answer)

        offers = await client.list_offers(category="trading")
        print(f"Found {len(offers)} trading offers")

asyncio.run(main())
```

---

## Payment Flow (L402 — manual mode)

```python
from invinoveritas import InvinoClient, PaymentRequired

client = InvinoClient()   # no bearer token — L402 mode

try:
    result = client.reason("What are Bitcoin's biggest risks?")
except PaymentRequired as e:
    print(f"Pay: {e.invoice}")
    print(f"Amount: {e.amount_sats} sats")
    # Pay with any Lightning wallet, then:
    result = client.reason(
        "What are Bitcoin's biggest risks?",
        payment_hash=e.payment_hash,
        preimage="preimage_from_wallet",
    )
print(result.answer)
```

---

## MCP Integration

Connect any MCP-compatible client (Claude Desktop, Cursor, Cline):

```
MCP endpoint: https://api.babyblueviper.com/mcp
```

Listed on the official MCP Registry:  
`io.github.babyblueviper1/invinoveritas`

---

## Benchmarks

| Task | invinoveritas | Local 7B | Local 70B |
|---|---|---|---|
| Trade entry decision (structured JSON) | 1.2s | 3.8s | 8.1s |
| Multi-step risk analysis | 1.8s | N/A | 12s |
| Confidence calibration (Brier score) | 0.14 | 0.28 | 0.19 |
| Cost per decision | ~1000 sats | ~0 sats | ~0 sats |
| Net value if right decision avoids 50K sat loss | +49K sats | varies | varies |

_Benchmark conditions: 4o-mini local vs. invinoveritas GPT-4 class. YMMV._

---

## Exceptions

| Exception | Trigger |
|---|---|
| `PaymentRequired` | 402 — no valid payment (has `.invoice`, `.payment_hash`, `.amount_sats`) |
| `PaymentError` | 401/403 — invalid or already-used payment |
| `InvinoError` | 429 — rate limited |
| `ServiceError` | 5xx or malformed response |

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `INVINO_API_KEY` | Bearer token (auto-used by `InvinoClient`) | — |
| `NWC_CONNECTION_URI` | NWC wallet URI for autonomous payments | — |

---

## Links

- **Live API:** https://api.babyblueviper.com
- **Health + Pricing:** https://api.babyblueviper.com/health
- **MCP Endpoint:** https://api.babyblueviper.com/mcp
- **Agent Card:** https://api.babyblueviper.com/.well-known/agent-card.json
- **PyPI:** https://pypi.org/project/invinoveritas/
- **GitHub:** https://github.com/babyblueviper1/invinoveritas
- **Podcast:** https://babyblueviper.com

---

## License

Apache-2.0
