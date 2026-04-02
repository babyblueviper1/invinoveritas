# ⚡ invinoveritas

**Lightning-paid reasoning and decision intelligence for autonomous agents**

> `https://invinoveritas.onrender.com`

Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning).  
No subscriptions. No accounts. No KYC.

Built **primarily for autonomous AI agents** that need high-quality reasoning and structured decisions without increasing local compute costs.

---

## Why Agents Use invinoveritas

Autonomous agents call invinoveritas when they need:

- Strategic reasoning deeper than local models
- Structured, machine-readable decisions with confidence scores
- Deterministic cost per request (instead of unpredictable token usage)
- Cryptographically verifiable payments via Lightning

Agents pay only when confidence matters — with sats, atomically, without intermediaries.

---

## Quick Start (for agents)

### Option 1 — MCP server (recommended)

Works with Claude Desktop, Cursor, and any MCP-compatible agent framework.

```bash
pip install mcp requests lndgrpc pyln-client
```

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "invinoveritas": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "API_BASE": "https://invinoveritas.onrender.com",
        "LND_DIR": "/root/.lnd"
      }
    }
  }
}
```

Then ask Claude: *"Use invinoveritas to reason about my BTC allocation strategy."*

### Option 2 — CLI agent client

```bash
python agent_client.py --endpoint reason --question "What are the biggest risks for BTC in 2026?"

python agent_client.py \
  --endpoint decision \
  --goal "Grow capital safely" \
  --context "Mostly BTC with some cash reserves" \
  --question "Should I increase exposure in the next 30 days?"
```

### Option 3 — Direct HTTP

```bash
# 1. Check price
curl https://invinoveritas.onrender.com/price/reason

# 2. Request reasoning (returns 402 + invoice)
curl -X POST https://invinoveritas.onrender.com/reason \
  -H "Content-Type: application/json" \
  -d '{"question": "Should I increase my BTC exposure right now?"}'

# 3. Pay the bolt11 invoice, then retry with credentials
curl -X POST https://invinoveritas.onrender.com/reason \
  -H "Content-Type: application/json" \
  -H "Authorization: L402 <payment_hash>:<preimage>" \
  -d '{"question": "Should I increase my BTC exposure right now?"}'
```

---

## Core Endpoints

| Endpoint | Purpose | Output | Typical Cost |
|---|---|---|---|
| `POST /reason` | Strategic reasoning | Natural language | ~500–700 sats |
| `POST /decision` | Structured decision intelligence | JSON | ~1000–1200 sats |

### `POST /reason`

```json
{ "question": "What are the biggest risks and opportunities for Bitcoin in 2026?" }
```

```json
{
  "status": "success",
  "type": "premium_reasoning",
  "answer": "..."
}
```

### `POST /decision`

```json
{
  "goal": "Grow capital safely",
  "context": "Mostly BTC with some cash reserves",
  "question": "Should exposure be increased in the next 30 days?"
}
```

```json
{
  "status": "success",
  "type": "decision_intelligence",
  "result": {
    "decision": "Increase exposure slightly",
    "confidence": 0.78,
    "reasoning": "Market structure improving while risk remains moderate.",
    "risk_level": "medium"
  }
}
```

---

## Payment Flow (L402)

1. POST to `/reason` or `/decision` → receive **HTTP 402** with bolt11 invoice in `WWW-Authenticate`
2. Pay the invoice with any Lightning wallet or node
3. Retry with: `Authorization: L402 <payment_hash>:<preimage>`
4. Receive AI response

The MCP server and `agent_client.py` handle this automatically.

---

## Discovery Endpoints

These are always free and require no payment:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Service status and metadata |
| `GET /price/{endpoint}` | Current price in sats |
| `GET /tool` | Machine-readable tool definition for agent frameworks |
| `GET /.well-known/ai-plugin.json` | Standard agent discovery manifest |
| `GET /docs` | Interactive API docs (Swagger UI) |
| `GET /openapi.json` | Full OpenAPI spec |

---

## Environment Variables

### API server (Render)

| Variable | Description | Required |
|---|---|---|
| `OPENAI_API_KEY` | Your OpenAI key | Yes |
| `NODE_URL` | Lightning bridge URL (your VPS) | Yes |
| `REASONING_PRICE_SATS` | Base price for `/reason` (default 500) | No |
| `DECISION_PRICE_SATS` | Base price for `/decision` (default 1000) | No |
| `ENABLE_DYNAMIC_PRICING` | Charge agents a multiplier (default true) | No |

### MCP server / agent client (local)

| Variable | Description |
|---|---|
| `API_BASE` | `https://invinoveritas.onrender.com` |
| `LND_DIR` | Path to `.lnd` directory (e.g. `/root/.lnd`) |
| `CLN_RPC_PATH` | Path to CLN RPC socket (alternative to LND) |

---

## Project Structure

```
invinoveritas/
├── app.py              # Main API — deployed on Render
├── ai.py               # Reasoning and decision logic
├── config.py           # Pricing and feature flags
├── node_bridge.py      # Talks to Lightning bridge on VPS
├── bridge.py           # LND bridge — runs on VPS
├── mcp_server.py       # MCP server for Claude, Cursor, etc.
├── agent_client.py     # CLI client for scripts and direct HTTP
├── index.html          # Landing page
├── requirements.txt
└── README.md
```

---

## Deployment

**API** — Render (`https://invinoveritas.onrender.com`)  
**Lightning bridge** — VPS running LND, connected to the API via `NODE_URL`

### Deploy on Render

1. Create a new Web Service
2. Build command: `pip install -r requirements.txt`
3. Start command: `uvicorn app:app --host 0.0.0.0 --port 10000`
4. Add environment variables: `OPENAI_API_KEY`, `NODE_URL`

---

## Philosophy

Most AI agents are forced into monthly subscriptions, token-based billing, and centralized identity systems.

**invinoveritas** offers a better model:

> Atomic intelligence purchases using Bitcoin Lightning.

Agents pay only when the decision truly matters — with sats, cryptographically, and without intermediaries.

---

Built for the Bitcoin × AI future. ⚡
