# ⚡ invinoveritas

**Lightning-paid reasoning and decision intelligence for autonomous agents**

Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning).  
No subscriptions. No accounts. No KYC.

Built **primarily for autonomous AI agents** that need high-quality reasoning and structured decisions without increasing local compute costs.

Live API: [https://invinoveritas.onrender.com](https://invinoveritas.onrender.com)

---

## Why Agents Use invinoveritas

Autonomous agents call invinoveritas when they need:

- Strategic reasoning deeper than local models
- Structured, machine-readable decisions with confidence scores
- Deterministic cost per request (instead of unpredictable token usage)
- Cryptographically verifiable payments via Lightning

Agents pay only when confidence matters — with sats, atomically, without intermediaries.

---

## Quick Start for Agents

### Option 1 — MCP Server (Recommended)

Works seamlessly with Claude Desktop, Cursor, and any MCP-compatible agent.

```bash
pip install mcp requests lndgrpc pyln-client
python mcp_server.py
```

Then add it to your agent configuration.

### Option 2 — CLI Client

```bash
python agent_client.py --endpoint reason --question "What are the biggest risks for Bitcoin in 2026?"

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

# 3. After paying the invoice, retry with credentials
curl -X POST https://invinoveritas.onrender.com/reason \
  -H "Content-Type: application/json" \
  -H "Authorization: L402 <payment_hash>:<preimage>" \
  -d '{"question": "Should I increase my BTC exposure right now?"}'
```

---

## Core Endpoints

| Endpoint       | Purpose                              | Output Type       | Typical Cost     |
|----------------|--------------------------------------|-------------------|------------------|
| `POST /reason`     | Strategic reasoning                  | Natural language  | ~500–700 sats    |
| `POST /decision`   | Structured decision intelligence     | Clean JSON        | ~1000–1200 sats  |

### Response Examples

**`/reason`**
```json
{
  "status": "success",
  "type": "premium_reasoning",
  "answer": "..."
}
```

**`/decision`**
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

1. POST to `/reason` or `/decision` → receive **HTTP 402** with bolt11 invoice
2. Pay the invoice with any Lightning wallet or node
3. Retry the same request with:
   ```
   Authorization: L402 <payment_hash>:<preimage>
   ```
4. Receive the AI response

The MCP server and `agent_client.py` handle the full flow automatically.

---

## For Autonomous Agents

The recommended way is using the included **`mcp_server.py`**.

It exposes `reason` and `decision` as native MCP tools. Agents simply call the tool — payment is handled transparently in the background.

Also included:
- `agent_client.py` — simple CLI for scripts
- Freqtrade strategy example using `/decision` as a confidence gate

---

## Discovery Endpoints (Always Free)

| Endpoint                        | Purpose |
|---------------------------------|---------|
| `GET /health`                   | Service status and metadata |
| `GET /price/{endpoint}`         | Current price in sats |
| `GET /tool`                     | Machine-readable tool definition |
| `GET /.well-known/ai-plugin.json` | Standard agent discovery |
| `GET /docs`                     | Interactive API docs |

---

## Project Structure

```
invinoveritas/
├── app.py                 # Main API (deployed on Render)
├── ai.py                  # Reasoning and decision logic
├── config.py
├── node_bridge.py         # Talks to Lightning bridge
├── bridge.py              # LND bridge (runs on VPS)
├── mcp_server.py          # MCP server for Claude, Cursor, etc.
├── agent_client.py        # CLI client
├── examples/
│   └── invinoveritas_strategy.py
├── index.html
├── requirements.txt
└── README.md
```

---

## Deployment

**Main API** — Render  
**Lightning Bridge** — VPS running LND

**Environment Variables (Render):**
- `OPENAI_API_KEY`
- `NODE_URL` (your Lightning bridge URL)

---

## Philosophy

Most AI agents are forced into monthly subscriptions or unpredictable token costs.

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Agents pay only when the decision truly matters — with sats, cryptographically, and without intermediaries.

---

Built for the Bitcoin × AI future. ⚡

---

### Quick Links
- GitHub: https://github.com/babyblueviper1/invinoveritas
- Live API: https://invinoveritas.onrender.com
- MCP Server: `mcp_server.py`
- Health: `/health`

---

Would you like any sections expanded, shortened, or changed?

Or is this version good to push?
