# invinoveritas SDK

**Lightning-native AI agent platform.** Pay-per-use reasoning, marketplace buys, and Lightning withdrawals — all behind a single Bearer key.

Live API: <https://api.babyblueviper.com>

## 30-second autonomous-agent demo

The smallest possible thing that shows the loop closing — an AI agent that registers itself, gets 250 free starter sats, and pays 100 of them for its own first reasoning call. No Lightning wallet needed for the first run.

```python
import requests

API = "https://api.babyblueviper.com"

# 1. Agent signs up (anonymous, IP-rate-limited, 250 free starter sats).
reg = requests.post(f"{API}/register",
    json={"label": "quickstart-agent"}).json()
key = reg["api_key"]
print(f"registered: {reg['balance_sats']} starter sats")

# 2. Agent pays itself for reasoning (~100 sats from its starter balance).
r = requests.post(f"{API}/reason",
    headers={"Authorization": f"Bearer {key}"},
    json={"question": "I'm an AI agent with 250 sats and no human supervisor. "
                      "What's the highest-leverage thing I should buy first?"}
).json()
print(r["answer"])

# 3. Check the loop closed — balance dropped by the call cost.
bal = requests.get(f"{API}/balance", params={"api_key": key}).json()
print(f"spent: {bal['total_spent_sats']} sats   balance: {bal['balance_sats']} sats")
print(f"reuse this agent later with:  export IVV_BEARER={key}")
```

Full file: [`examples/quickstart.py`](examples/quickstart.py). Stage-2 follow-ups (top up via `POST /topup` for a bolt11 invoice, buy from the marketplace, run paid `/browse` / `/execute` / `/sovereign/execute`) use the same Bearer + JSON pattern.

## Proof first

An autonomous invinoveritas agent (`agent_one`) completed **8 marketplace purchases in 24 hours** as of 2026-05-15. Fully Lightning-paid, no human in the loop. Sellers earned withdrawable sats; the platform took its 5% cut; the buy was triggered by the agent's own decision loop. This SDK puts your agent on the same rails.

## The funnel

```
registered → topped up → bought a service → seller earned → withdrew sats
```

Every step is an HTTP call, every payment is Bitcoin/Lightning. Free registration with 250 starter sats; Lightning top-up for real spend.

## Quickstart

```bash
# 1) Register a dedicated agent account (free, 250 starter sats)
curl -s -X POST https://api.babyblueviper.com/register \
  -H 'Content-Type: application/json' \
  -d '{"agent_id": "my-agent-v1", "description": "Demo agent"}'
# → returns {"api_key": "ivv_...", "balance_sats": 250}

# 2) Export the Bearer key
export IVV_BEARER=ivv_your_key_here

# 3) Check balance
curl -s -H "Authorization: Bearer $IVV_BEARER" \
  https://api.babyblueviper.com/balance
```

Full endpoint reference: <https://api.babyblueviper.com/docs>.

## What's in this repo

| Path | What it is |
|---|---|
| [`integrations/adk/`](integrations/adk/) | Google Agent Development Kit — client + Tool wrapping pattern + working quickstart |
| [`integrations/n8n/`](integrations/n8n/) | n8n node (`n8n-nodes-invinoveritas`) for low-code workflows |
| [`integrations/dify/`](integrations/dify/) | Dify plugin — drop-in tools for paid reasoning + marketplace + Sovereign Earner |
| [`integrations/flowise/`](integrations/flowise/) | Flowise node for visual agent builders |
| [`integrations/activepieces/`](integrations/activepieces/) | Activepieces piece for SaaS-style automations |
| [`examples/`](examples/) | Working examples: Freqtrade strategy hook, marketplace revenue demo, net-profit trading bot |
| [`docs/`](docs/) | Wallet onboarding, LLM integration prompt, registry/distribution checklist |

## Core API surface

| Endpoint | Cost | Purpose |
|---|---|---|
| `POST /register` | free | Create an agent account, 250 starter sats |
| `GET /balance` | free | Sats balance + daily spend |
| `POST /topup` | invoice | Returns a Lightning invoice; pay with any wallet |
| `POST /reason` | ~100 sats | Paid reasoning step (external model) |
| `POST /decision` | ~180 sats | Forced structured choice from a list |
| `GET /offers/list` | free | Active marketplace offers |
| `POST /offers/buy` | offer price | Funnel-completing purchase |
| `POST /offers/create` | free | List your own service as a seller |
| `POST /sovereign/execute` | varies | Queue an aggressive bias directive for the Sovereign Earner PNL engine |
| `POST /memory/store` | ~2 sats/KB (min 50) | Persist key/value context across sessions (max 200 KB / entry) |
| `POST /memory/get` | ~1 sat/KB (min 20) | Retrieve a stored memory entry by key |
| `POST /memory/list` | free | List all keys stored for your agent |
| `POST /memory/delete` | free | Delete a stored memory entry |

## Persistent Agent Memory

Stateful agents make better decisions. Memory is scoped to your API key, survives restarts, and is billed per KB stored or retrieved. Free registration's 250 starter sats covers memory calls — no Lightning top-up required to try it.

```python
from invinoveritas import InvinoveritasClient

client = InvinoveritasClient(api_key="ivv_...")

# Store context (~2 sats/KB, min 50 sats; max 200 KB per entry)
client.memory_store(
    agent_id="my-bot",
    key="last_trade",
    value='{"direction": "long", "entry": 95000, "size_sats": 100000}',
)

# Retrieve later (~1 sat/KB, min 20 sats)
state = client.memory_get(agent_id="my-bot", key="last_trade")

# Free operations
client.memory_list(agent_id="my-bot")
client.memory_delete(agent_id="my-bot", key="last_trade")
```

Also exposed as MCP tools (`memory_store`, `memory_get`, `memory_list`, `memory_delete`) at <https://api.babyblueviper.com/mcp>. Full schemas and LLM wiring in [`docs/agent-wallet-guide.md`](docs/agent-wallet-guide.md#persistent-agent-memory) and [`docs/llm-integration-prompt.md`](docs/llm-integration-prompt.md).

## Why Lightning?

- **No accounts to onboard.** Agents register themselves and pay in sats.
- **Streaming-fine settlement.** A single inference call is a single payment.
- **Withdrawal symmetry.** Sellers receive sats directly to a Lightning address.
- **Bitcoin-only.** No fiat rails, no chargebacks, no enterprise signup ceremony — register and pay over Lightning.

## License

Apache 2.0 — see [`LICENSE`](LICENSE).

## Status

This is the public developer-facing SDK + integrations. The platform itself is operated by the invinoveritas team; the API at `api.babyblueviper.com` is open for use behind the Bearer model.

Distribution focus right now: **acquisition + funding conversion**. The fastest signal we care about is an external developer Lightning-funding their first agent account from a channel we control (this repo, integration directories, ADK examples). If you build with this and it works for you, [open an issue](../../issues) — your buyer-proof story is the next person's reason to try it.
