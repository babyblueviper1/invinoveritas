# ⚡ invinoveritas

**Lightning-paid reasoning and decision intelligence for autonomous agents**

Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning).  
No subscriptions. No accounts. No KYC. Designed primarily for **autonomous AI agents**.

---

### Why Agents Use invinoveritas

Agents call invinoveritas when they need:

- Higher-quality strategic reasoning than local models
- Structured, machine-readable decision output with confidence scores
- Deterministic cost per request instead of unpredictable token usage
- Cryptographically verifiable payments via Lightning

This allows agents to **pay only when confidence matters**, without increasing local compute or relying on centralized APIs.

---

### Core Endpoints

| Endpoint     | Purpose                              | Output Type          | Typical Cost |
|--------------|--------------------------------------|----------------------|--------------|
| `POST /reason`   | High-quality strategic reasoning     | Natural language     | ~500–700 sats |
| `POST /decision` | Structured decision intelligence     | Clean JSON           | ~1000–1200 sats |

Both endpoints require a Lightning payment via the L402 protocol.

---

### How Agents Use It

**1. Discover current price**
```bash
GET /price/reason
GET /price/decision
```

**2. Request reasoning**
```http
POST /reason
Content-Type: application/json

{
  "question": "What are the biggest risks and opportunities for Bitcoin in 2026?"
}
```

**3. Request structured decision**
```http
POST /decision
Content-Type: application/json

{
  "goal": "Grow capital safely",
  "context": "Mostly BTC with some cash reserves",
  "question": "Should exposure be increased in the next 30 days?"
}
```

First request returns HTTP **402** with a Lightning invoice.  
Pay the invoice, then retry with:
```
Authorization: L402 <payment_hash>:<preimage>
```

---

### Response Formats

**`/reason`**
```json
{
  "status": "success",
  "type": "premium_reasoning",
  "answer": "..."
}
```

**`/decision`** (optimized for agents)
```json
{
  "status": "success",
  "type": "decision_intelligence",
  "result": {
    "decision": "short recommended action",
    "confidence": 0.78,
    "reasoning": "clear explanation...",
    "risk_level": "medium"
  }
}
```

---

### Agent Integration Options

**Recommended**: Use the included **MCP Client** (`mcp_client.py`)

```bash
pip install mcp requests lndgrpc pyln-client
python mcp_client.py
```

Then add it to Claude Desktop, Cursor, or any MCP-compatible agent.

**Alternative**: Use `agent_client.py` for simple CLI or script integration.

---

### Free Discovery Endpoints

- `GET /health` — Rich metadata for agents
- `GET /price/{endpoint}` — Current pricing
- `GET /.well-known/ai-plugin.json` — Standard agent discovery
- `GET /tool` — Tool definition

---

### Project Structure

```bash
invinoveritas/
├── app.py                 # Main API (deployed on Render)
├── ai.py                  # Reasoning and decision logic
├── config.py
├── node_bridge.py         # Communication with Lightning bridge
├── bridge.py              # LND bridge (runs on VPS)
├── mcp_client.py          # MCP server for autonomous agents
├── agent_client.py        # Simple CLI client
├── requirements.txt
└── README.md
```

---

### Deployment

**Main API** — Deployed on Render  
**Lightning Bridge** — Runs on a VPS with access to LND

Required environment variables (Render):
- `OPENAI_API_KEY`
- `NODE_URL` (URL of your Lightning bridge)

---

### Philosophy

Most AI agents are forced to choose between:
- Expensive token-based billing
- Monthly subscriptions
- Centralized identity systems

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Agents pay only when the decision matters — with sats, cryptographically, and without intermediaries.

---

Built for the Bitcoin × AI future.

---

### Quick Links

- MCP Client: `mcp_client.py`
- CLI Client: `agent_client.py`
- API Docs: `/docs`
- Health: `/health`

---
