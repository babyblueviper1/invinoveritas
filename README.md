# ⚡ invinoveritas

**Lightning-paid reasoning API for autonomous agents (L402 protocol).**

Structured decision intelligence that agents can call when confidence matters.  
No subscriptions. No accounts. Pay per decision with Bitcoin Lightning.
Designed primarily for **autonomous AI agents**.

---

### What This Tool Is

**invinoveritas** is a reasoning and decision-intelligence service that agents can call when they need:

- Higher-quality reasoning than a local model
- Structured decision outputs (JSON)
- Deterministic pricing per request
- Cryptographic payment using Bitcoin Lightning

Instead of increasing local compute cost, the agent can **pay per high-confidence decision**.

---

### When an Agent Should Use This

An agent should call **invinoveritas** when:

- The decision has financial impact
- The confidence of the answer matters
- The question involves strategy, risk, or uncertainty
- A structured decision output is required
- The agent wants deterministic cost instead of extra reasoning tokens

**Examples:**

- Portfolio decisions
- Risk analysis
- Strategic trade-offs
- Multi-step reasoning
- Planning with uncertainty

---

### Core Features

- Lightning payments using the **L402 protocol**
- No authentication required
- Two premium endpoints:
  - `/reason` → high-quality strategic reasoning
  - `/decision` → structured decision intelligence
- Free price discovery endpoints
- Dynamic pricing with optional agent multiplier
- Replay protection and rate limiting
- Native support for **MCP (Model Context Protocol)**

---

### Quick Agent Integration

1. **Discover price**
   ```bash
   GET /price/reason
   GET /price/decision
   ```

2. **Request reasoning**
   ```http
   POST /reason
   Content-Type: application/json
   {
     "question": "What are the biggest risks to Bitcoin in 2026?"
   }
   ```

3. **Request structured decision intelligence**
   ```http
   POST /decision
   Content-Type: application/json
   {
     "goal": "Grow capital safely",
     "context": "Mostly BTC and cash position",
     "question": "Should I increase exposure in the next 30 days?"
   }
   ```

---

### Response Format

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
    "decision": "...",
    "confidence": 0.0,
    "reasoning": "...",
    "risk_level": "low | medium | high"
  }
}
```

---

### Why This Exists

Most AI agents pay for intelligence using:
- API subscriptions
- Token-based billing
- Centralized identity systems

**invinoveritas** enables something different:

> **Pay-per-decision using Bitcoin Lightning.**

This allows agents to:
- Pay only when confidence matters
- Avoid subscriptions
- Avoid accounts
- Avoid centralized payment systems

---

### Autonomous Agent Support

invinoveritas includes a built-in **MCP client** for agent integration.

**Supported environments:**
- Claude Desktop
- Cursor
- Autonomous Python agents
- Research agents
- Strategy agents
- Trading agents

**Install MCP Client**
```bash
pip install mcp requests lndgrpc pyln-client
python mcp_client.py
```

Then add the MCP server to your agent configuration.

---

### API Structure

```bash
invinoveritas/
├── app.py
├── ai.py
├── config.py
├── node_bridge.py
├── mcp_client.py
├── agent_client.py
├── requirements.txt
└── README.md
```

---

### Free Endpoints

- `GET /price/reason`
- `GET /price/decision`
- `GET /health`

---

### Deployment

**Main API (Render)**
- Deploy `app.py` as a web service
- Install dependencies using `requirements.txt`
- Connect to Lightning bridge using environment variables

**Lightning Bridge (VPS)**
- Runs on a VPS connected to LND
- Creates invoices
- Verifies payments
- Provides preimage verification

**Environment Variables**
- `OPENAI_API_KEY`
- `NODE_URL`
- `REASONING_PRICE_SATS`
- `DECISION_PRICE_SATS`
- `AGENT_PRICE_MULTIPLIER`

---

### Philosophy

AI intelligence should not require:
- Monthly subscriptions
- Identity verification
- Centralized payment systems

**invinoveritas** enables **atomic intelligence purchases using sats**.
