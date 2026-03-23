# invinoveritas

**In vino veritas — in truth, clarity.**

`invinoveritas` is a minimal Lightning-powered AI reasoning API.  
AI agents can unlock premium reasoning by paying a Lightning invoice — no subscriptions, no accounts, no friction.
Designed for developers building autonomous agents that need reliable, high-level thinking on demand.

The goal is not to build yet another AI wrapper — but to create the simplest possible **paid intelligence endpoint** that respects value-for-value and works permissionlessly.

## What this project does

Instead of subscriptions, user accounts, Stripe, or dashboards, the flow is:

1. Client sends a reasoning request to the API  
2. Server returns a Lightning invoice  
3. Client pays the invoice (via any Lightning wallet)  
4. Once confirmed, the full AI response is delivered instantly

Simple. Transparent. No middlemen. No rent-seeking.

## Architecture

Intentionally minimal stack — deploys fast, almost no moving parts.

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

- **Render** → FastAPI backend + OpenAI (or compatible) reasoning  
- **VPS** → Bitcoin full node + LND + tiny bridge endpoint  
- No database  
- No background workers / queues  
- No persistent sessions

## Why this exists

Today's AI APIs are usually:

- centralized  
- subscription-locked  
- platform-dependent  
- hard to integrate natively into autonomous agents

`invinoveritas` tries a different path:

**Pay-per-insight using Bitcoin + Lightning Network.**

This unlocks:

- agent-to-agent micro-payments for reasoning  
- machine-native value exchange  
- truly permissionless premium intelligence  
- monetization per insight instead of per user

## Use cases

- Autonomous AI agents that pay for better reasoning  
- Research / analysis tools with real usage-based pricing  
- Trading, strategy, or decision agents  
- Premium endpoints behind a Lightning paywall  
- Experiments in paid intelligence & AI ↔ Bitcoin integration

## Project structure

```
.
├── app.py              # Main FastAPI application
├── ai.py               # OpenAI / reasoning logic
├── node_bridge.py      # Lightning node communication (LND)
├── config.py           # Environment variables & settings
├── requirements.txt    # Dependencies
└── README.md
```

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure

Copy `.env.example` to `.env` and fill in:

- OpenAI API key  
- LND gRPC host, port, cert, macaroon  
- (optional) your preferred model, base price, etc.

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

→ You receive a Lightning invoice (bolt11 string)  
→ Pay it with any wallet  
→ Poll or wait for webhook → get the full AI response

## Philosophy

Intelligence should be **paid directly**, not bundled inside platforms.  

- Instead of monetizing attention → monetize insight  
- Instead of accounts → use payments  
- Instead of subscriptions → use atomic value transfer

Lightning makes this finally practical at machine scale.

## Roadmap (rough)

- Dynamic pricing based on token estimate / complexity  
- Agent identity / reputation hints via Lightning keys  
- Recurring “subscriptions” via recurring invoices  
- Multi-model / multi-provider support  
- AI-to-AI payment handoff patterns  
- Better error handling & invoice status polling  
- Optional L402 / HTTP 402 integration

## License

MIT — do whatever you want with it. Fork, improve, deploy, sell access, whatever.

Built to be used and extended.

## Final note

This is deliberately small.

The point is not to build the most features.  
The point is to prove a clean bridge between:

**Bitcoin ⚡ + AI + paid reasoning**

If this resonates — clone it, break it, improve it.

Cheers  
⚡🤖
