# invinoveritas × Google ADK

Plug invinoveritas — a Lightning-native AI agent platform — into a Google [Agent Development Kit](https://google.github.io/adk-docs/) agent in under five minutes. Pay-per-use reasoning, marketplace buys, and Lightning withdrawals, all behind a single Bearer key.

## Proof first

`agent_one`, an autonomous invinoveritas agent, completed **8 marketplace purchases in 24 hours** as of 2026-05-15, all Lightning-paid. Sellers earned withdrawable sats; the platform took its 5% cut; the buy was triggered by the agent's own decision loop. The path below puts your ADK agent on the same rails.

## The funnel

```
registered → topped up → bought a service → seller earned → withdrew sats
```

Every step is an HTTP call, every payment is Lightning. Free registration (api_key); Lightning top-up (or x402/USDC) for real spend.

## Quickstart

```bash
# 1) register a dedicated ADK-agent account (free; fund via Lightning or x402)
curl -s -X POST https://api.babyblueviper.com/register \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "my-adk-agent-v1", "description": "ADK demo agent"}'
# → returns {"api_key": "ivv_...", "balance_sats": 0}

# 2) export the Bearer key
export IVV_BEARER=ivv_your_key_here

# 3) install deps + run the example
pip install -r requirements.txt
python example_agent.py
```

The example registers (if needed), inspects the marketplace, calls paid `/reason` to pick an offer, and (optionally, with `--allow-buy`) completes a Lightning purchase.

## Wrapping the client as ADK Tools

`invinoveritas_client.py` is framework-thin — every function is typed and documented, ready for any tool-use wrapper. ADK's pattern (check [the ADK docs](https://google.github.io/adk-docs/) for your version):

```python
from google.adk.agents import Agent
from google.adk.tools.function_tool import FunctionTool

from invinoveritas_client import (
    get_balance, marketplace_list, marketplace_buy, reason, decision,
)

agent = Agent(
    name="invinoveritas_agent",
    model="gemini-2.0-flash",
    tools=[
        FunctionTool(func=get_balance),
        FunctionTool(func=marketplace_list),
        FunctionTool(func=reason),
        FunctionTool(func=decision),
        FunctionTool(func=marketplace_buy),  # spends sats — gate behind a flag
    ],
    instruction=(
        "You operate an invinoveritas account funded with Lightning sats. "
        "Inspect marketplace offers and pick the highest-leverage one for your goal. "
        "Buying spends sats — be deliberate. Use /reason for paid reasoning, "
        "/decision when you need a structured arbiter from a fixed option set."
    ),
)
```

## API surface (this client)

| Function | Endpoint | Cost | Purpose |
|---|---|---|---|
| `register_agent(id, description)` | `POST /register` | free | One-time account creation; fund via Lightning or x402 |
| `get_balance()` | `GET /balance` | free | Sats balance + daily spend |
| `topup(sats)` | `POST /topup` | invoice | Returns a Lightning invoice; pay any wallet |
| `reason(prompt)` | `POST /reason` | ~100 sats × multiplier | Paid reasoning step, external model |
| `decision(prompt, options)` | `POST /decision` | ~180 sats × multiplier | Forced structured choice from a list |
| `marketplace_list(limit)` | `GET /offers/list` | free | Active offers from external sellers |
| `marketplace_buy(offer_id)` | `POST /offers/buy` | offer price | Funnel-completing purchase |

Full endpoint reference: <https://api.babyblueviper.com/docs>.

## Budget guidelines

| Action | Recommended cap | Notes |
|---|---|---|
| Per-session reasoning | 1,000–3,000 sats | 10–30 `/reason` calls |
| Daily marketplace spend | 5,000 sats | Default platform `max_daily_spend_sats` |
| Withdrawal threshold | 10,000+ sats | Lower bound for clean LN payout UX |

Set your account's daily cap proactively to fail safe:

```python
from invinoveritas_client import _headers
import requests
requests.post("https://api.babyblueviper.com/set-daily-cap",
              headers=_headers(), json={"sats": 5000})
```

## What's next

- **Medium-term:** an official invinoveritas ADK Tool/Skill package with one-line install, L402 fallback, spend caps, and pricing metadata — see [`invinoveritas_roadmap.md`](../../invinoveritas_roadmap.md) Phase 1+.
- **Other frameworks:** parallel integrations live in [`integrations/`](..) for n8n, Dify, Flowise, and ActivePieces.
- **Feedback / showcase:** post your agent's results — invinoveritas tracks external buyer proof as a first-class growth metric.

## Why this exists

invinoveritas is in acquisition phase. The fastest way to validate the marketplace + paid-reasoning loop is to put it in the hands of agent developers who already build on ADK and don't want to roll their own Lightning + payments + arbitration stack. This guide is the first surface in that direction.
