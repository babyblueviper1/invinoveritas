# invinoveritas

**In vino veritas — in truth, clarity.**

`invinoveritas` is a minimal Lightning-powered **decision and reasoning endpoint** for AI agents.

Instead of selling access to models, this project sells **high-quality thinking on demand** — paid per request using the Lightning Network. No subscriptions. No accounts. No friction.

It is designed for developers building autonomous agents that need reliable reasoning at the exact moment a decision matters.

The goal is not to build another AI wrapper.

The goal is to create the simplest possible **paid intelligence endpoint** that works permissionlessly and respects value-for-value.

---

## What this project does

Instead of subscriptions, user accounts, Stripe, or dashboards, the flow is intentionally simple:

1. An agent sends a reasoning or decision request to the API
2. The server returns a Lightning invoice
3. The agent pays the invoice (via any Lightning wallet)
4. Once payment is confirmed, the full reasoning response is delivered instantly

No accounts. No platform lock-in. No middlemen.

This is not "pay per user".

This is **pay per decision**.

---

## What this is really for

Most AI APIs are built for apps.

`invinoveritas` is built for **autonomous agents**.

Examples of agents that benefit from this model:

* trading agents that need higher-quality reasoning before executing a position
* research agents that must verify a hypothesis before continuing
* decision agents that occasionally need stronger analysis than their base model
* tools that want to monetize high-signal reasoning instead of raw model access

This turns intelligence into something that can be purchased **only when it is actually needed**.

---

## Core idea

Instead of:

* paying monthly for unused intelligence
* exposing API keys everywhere
* forcing agents to rely on centralized subscriptions

`invinoveritas` enables:

* pay-per-insight using Bitcoin + Lightning
* machine-to-machine micro-payments
* permissionless premium reasoning
* monetization based on **value delivered**, not usage quotas

---

## Architecture

The stack is intentionally minimal so it can be deployed fast and tested in the real world.

```
                  ┌──────────────┐
                  │   Render     │
                  │   (public)   │
                  └──────┬───────┘
                         │
                 HTTP + Invoice
                         │
                  ┌──────▼───────┐
                  │ Lightning    │
                  │ Bridge API   │
                  └──────┬───────┘
                         │
                   gRPC / REST
                         │
                  ┌──────▼───────┐
                  │     LND      │
                  │ (on VPS)     │
                  └──────┬───────┘
                         │
                   Bitcoin Mainnet
```

* **Render** → FastAPI backend + AI reasoning (OpenAI or compatible)
* **VPS** → Bitcoin full node + LND + lightweight bridge endpoint
* No database
* No background workers
* No sessions
* No complex infrastructure

The focus is not features.

The focus is a clean bridge between **AI reasoning and real payments**.

---

## Why this exists

Most AI APIs today are:

* centralized
* subscription-locked
* tied to user accounts
* not built for autonomous agents
* designed for apps, not machines

`invinoveritas` explores a different direction:

**Paid intelligence that works natively on Bitcoin.**

---

## Use cases

* Autonomous AI agents that pay for stronger reasoning only when needed
* Trading or strategy agents that want a higher-confidence decision before acting
* Research tools that monetize insight instead of model access
* Developers experimenting with AI-to-AI payments
* Paid reasoning endpoints behind Lightning paywalls
* Experiments in Bitcoin ⚡ + AI integration

---

## Project structure

```
.
├── app.py              # Main FastAPI application
├── ai.py               # AI reasoning logic
├── node_bridge.py      # Lightning node communication (LND)
├── config.py           # Environment variables & settings
├── requirements.txt    # Dependencies
└── README.md
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and fill in:

* OpenAI (or compatible) API key
* LND gRPC host, port, cert, macaroon
* Optional: preferred model and base price

### 3. Run locally

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 4. Test a request

```bash
curl -X POST http://localhost:8000/subscribe \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain why Bitcoin is the hardest money ever created."}'
```

You will receive a Lightning invoice (bolt11 string).

Pay it with any Lightning wallet and the full response will be returned after confirmation.

---

## Philosophy

Intelligence should be **paid directly**, not bundled inside platforms.

Instead of monetizing attention → monetize insight
Instead of subscriptions → use atomic payments
Instead of accounts → use value transfer
Instead of platforms → use Bitcoin

Lightning makes this practical at machine scale.

---

## Positioning

This is not an AI product.

This is an **intelligence endpoint with real pricing**.

It exists to explore a simple but powerful idea:

> When an agent truly needs better reasoning, it should be able to pay for it instantly.

---

## Roadmap (rough)

* Dynamic pricing based on prompt complexity
* Agent identity / reputation via Lightning keys
* Multi-model reasoning (fallback + premium modes)
* Reusable payment credentials (L402-compatible flow)
* AI-to-AI payment handoff patterns
* Better invoice status handling
* Additional high-signal endpoints

---

## License

MIT — fork it, modify it, deploy it, sell access to it, break it, improve it.

Built to be used and extended.

---

## Final note

This project is deliberately small.

The objective is not to build the most features.

The objective is to prove a clean bridge between:

**Bitcoin ⚡ + AI + paid decision-making**

If this resonates with you — clone it, test it, improve it, and build something real with it.

Cheers
⚡🤖
