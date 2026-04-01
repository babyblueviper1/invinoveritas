# invinoveritas ⚡

**Lightning-Paid AI Reasoning & Decision Intelligence**

Pay-per-insight API using Bitcoin Lightning (L402 protocol).  
No subscriptions. No accounts. No KYC.

Designed for both humans and autonomous agents.

---

## Features

- Pay with Lightning using the L402 protocol
- Two endpoints: `/reason` (strategic analysis) and `/decision` (structured JSON for agents)
- Dynamic pricing with optional agent multiplier
- Strong replay protection and rate limiting
- Excellent support for autonomous agents via MCP
- Easy deployment on Render + lightweight bridge on VPS

---

## API Endpoints

### `POST /reason` – Strategic Reasoning

**Request:**
```json
{ "question": "Should I increase my BTC exposure right now?" }
```

**Response:**
```json
{
  "status": "success",
  "type": "premium_reasoning",
  "answer": "..."
}
```

### `POST /decision` – Structured Decision Intelligence

**Request:**
```json
{
  "goal": "Grow capital safely",
  "context": "Mostly BTC and cash position",
  "question": "Should I increase exposure in the next 30 days?"
}
```

**Response:**
```json
{
  "status": "success",
  "type": "decision_intelligence",
  "result": {
    "decision": "Increase exposure slightly",
    "confidence": 0.72,
    "reasoning": "...",
    "risk_level": "medium"
  }
}
```

### Free Endpoints
- `GET /price/reason`
- `GET /price/decision`
- `GET /health`

---

## For Humans & Simple Use

Use the included `agent_client.py`:

```bash
python agent_client.py --endpoint reason --question "What are the biggest risks to Bitcoin in 2026?"
```

---

## For Autonomous Agents (Recommended)

Use the **MCP Client** — works great with Claude Desktop, Cursor, etc.

```bash
# 1. Clone or download the repo
# 2. Install dependencies
pip install mcp requests lndgrpc pyln-client

# 3. Run the MCP server
python mcp_client.py
```

Then add it to your Claude Desktop configuration.

---

## Project Structure

```bash
invinoveritas/
├── app.py                 # Main FastAPI server (deployed on Render)
├── ai.py                  # AI reasoning & decision logic
├── config.py
├── node_bridge.py         # Communicates with VPS bridge
├── mcp_client.py          # MCP server for autonomous agents ← Important
├── agent_client.py        # Simple CLI client
├── requirements.txt
└── README.md
```

---

## Deployment

### 1. Render (Main API)
- Deploy `app.py` as a Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
- Required env vars:
  - `OPENAI_API_KEY`
  - `NODE_URL` → your VPS bridge URL (e.g. `https://bridge.yourdomain.com`)

### 2. VPS Bridge (Lightning Node)
- Runs on your VPS that has access to LND
- Connects to your local LND instance
- Exposes `/create-invoice`, `/check-payment/{hash}`, `/verify-preimage`

---

## Environment Variables (Render)

| Variable                    | Description                              | Required |
|----------------------------|------------------------------------------|----------|
| `OPENAI_API_KEY`           | OpenAI API key                           | Yes      |
| `NODE_URL`                 | URL of your VPS Lightning bridge         | Yes      |
| `REASONING_PRICE_SATS`     | Base price for reasoning (default 500)   | No       |
| `DECISION_PRICE_SATS`      | Base price for decisions (default 1000)  | No       |
| `AGENT_PRICE_MULTIPLIER`   | Multiplier for agent calls (default 1.2) | No       |

---

## Why invinoveritas?

Because intelligence should be **atomically purchasable** with sats — not locked behind subscriptions and banks.

Built for the Bitcoin × AI future.
