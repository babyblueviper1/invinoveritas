# ⚡ invinoveritas

**Lightning-paid reasoning and decision intelligence for autonomous agents**

Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning).  
No subscriptions. No accounts. No KYC.  

Built **primarily for autonomous AI agents** that need high-quality reasoning and structured decisions without increasing local compute costs.

---

### Why Agents Use invinoveritas

Autonomous agents call invinoveritas when they need:

- Strategic reasoning deeper than local models
- Structured, machine-readable decisions with confidence scores
- Deterministic cost per request (instead of unpredictable token usage)
- Cryptographically verifiable payments via Lightning

This gives agents the ability to **pay only when confidence matters**, using sats — atomically and without intermediaries.

---

### Core Endpoints

| Endpoint       | Purpose                                 | Output Type       | Typical Cost     |
|----------------|-----------------------------------------|-------------------|------------------|
| `POST /reason`     | High-quality strategic reasoning        | Natural language  | ~500–700 sats    |
| `POST /decision`   | Structured decision intelligence        | Clean JSON        | ~1000–1200 sats  |

Both endpoints require a Lightning payment via the L402 protocol.

---

### How to Use (for Agents)

**1. Discover current price**
```bash
GET /price/reason
GET /price/decision
```

**2. Request reasoning**
```http
POST /reason
Content-Type: application/json

{ "question": "What are the biggest risks and opportunities for Bitcoin in 2026?" }
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

The first request returns **HTTP 402** with a Lightning invoice in the `WWW-Authenticate` header.  
Pay the invoice, then retry the exact same request with:

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

**`/decision`** (agent-optimized)
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

### Best Integration Methods

**Recommended for most agents**: Use the **MCP Client** (`mcp_client.py`)

```bash
pip install mcp requests lndgrpc pyln-client
python mcp_client.py
```

Then add it to Claude Desktop, Cursor, or any MCP-compatible agent framework.

**Alternative**: Use `agent_client.py` for simple scripts or direct HTTP integration.

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
├── node_bridge.py         # Talks to Lightning bridge
├── bridge.py              # LND bridge (runs on VPS)
├── mcp_client.py          # MCP client for autonomous agents ← Recommended
├── agent_client.py        # Simple CLI client
├── requirements.txt
└── README.md
```

---

### Deployment

**Main API** — Deployed on Render  
**Lightning Bridge** — Runs on a VPS connected to LND

**Required environment variables (Render):**
- `OPENAI_API_KEY`
- `NODE_URL` (points to your Lightning bridge)

---

### Philosophy

Most AI agents are forced into:
- Expensive token-based billing
- Monthly subscriptions
- Centralized identity systems

**invinoveritas** offers a better model:

> **Atomic intelligence purchases using Bitcoin Lightning.**

Agents pay only when the decision truly matters — with sats, cryptographically, and without intermediaries.

---

Built for the Bitcoin × AI future.

---

### Quick Links

- MCP Client: `mcp_client.py`
- CLI Client: `agent_client.py`
- API Docs: `/docs`
- Health Check: `/health`

---

Or are we good with this README?

Let me know and we can finalize everything.
