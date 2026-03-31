# invinoveritas ⚡

**Lightning-Paid AI Reasoning & Decision Intelligence**

Pay-per-insight API. No subscriptions. No accounts. Just Bitcoin via Lightning.

Designed for both **humans** and **autonomous agents**.

---

## Features

- Pay with Lightning (L402 protocol)
- Two endpoints: `/reason` (human-friendly) and `/decision` (structured JSON for agents)
- Dynamic pricing
- Rate limiting & replay protection
- Full support for autonomous agents
- Easy deployment on Render

---

## API Endpoints

### `POST /reason` – Strategic Reasoning

**Request:**
```json
{
  "question": "Should I increase my BTC exposure right now?"
}
```

**Response (after payment):**
```json
{
  "status": "success",
  "type": "premium_reasoning",
  "answer": "High-quality structured strategic answer..."
}
```

### `POST /decision` – Structured Decision Intelligence

**Request:**
```json
{
  "goal": "Grow capital safely",
  "context": "User holds mostly BTC and some cash",
  "question": "Should exposure be increased in the next 30 days?"
}
```

**Response (after payment):**
```json
{
  "status": "success",
  "type": "decision_intelligence",
  "result": {
    "decision": "Increase exposure slightly",
    "confidence": 0.72,
    "reasoning": "Market structure improving while risk remains moderate.",
    "risk_level": "medium"
  }
}
```

### `GET /price/{endpoint}` – Current Pricing

- `GET /price/reason`
- `GET /price/decision`

Returns:
```json
{
  "price_sats": 500
}
```

---

## Quick Start (Local)

```bash
pip install -r requirements.txt
uvicorn app:app --reload
```

Open: http://127.0.0.1:8000

---

## Environment Variables

| Variable                  | Description                              | Required |
|--------------------------|------------------------------------------|----------|
| `OPENAI_API_KEY`         | Your OpenAI key                          | Yes      |
| `LND_REST_URL`           | LND REST endpoint (usually `http://127.0.0.1:8080`) | Yes      |
| `LND_MACAROON_HEX`       | Restricted invoice macaroon              | Yes      |
| `REASONING_PRICE_SATS`   | Base price for `/reason` (default 500)   | No       |
| `DECISION_PRICE_SATS`    | Base price for `/decision` (default 1000)| No       |

For the **agent client** (`agent_client.py`):

- `LND_DIR` or `CLN_RPC_PATH`

---

## Deployment on Render

1. Create a new **Web Service**
2. Build Command:
   ```bash
   pip install -r requirements.txt
   ```
3. Start Command:
   ```bash
   uvicorn app:app --host 0.0.0.0 --port 10000
   ```
4. Add environment variables:
   - `OPENAI_API_KEY`
   - `LND_REST_URL`
   - `LND_MACAROON_HEX`
   - `REASONING_PRICE_SATS` (optional)
   - `DECISION_PRICE_SATS` (optional)

---

## Payment Flow (L402)

1. Client sends request to `/reason` or `/decision`
2. Server returns HTTP 402 + Lightning invoice
3. Client pays the invoice
4. Client retries with header:
   ```http
   Authorization: L402 <payment_hash>:<preimage>
   ```
5. AI response is returned

---

## For Autonomous Agents

Use the included `agent_client.py`:

```bash
python agent_client.py --endpoint reason --question "Explain Bitcoin as a long-term strategy"
```

The client automatically handles price discovery, invoice payment (via LND or CLN), and retry.

---

## Project Structure

```bash
invinoveritas/
├── app.py
├── index.html
├── ai.py
├── node_bridge.py
├── config.py
├── agent_client.py
├── requirements.txt
└── README.md
```

---

## Why This Project Exists

Most AI tools charge monthly subscriptions through banks.  
**invinoveritas** lets anyone buy intelligence **atomically** with sats on the Lightning Network.

- No accounts  
- No subscriptions  
- No KYC  
- Works perfectly with autonomous agents

---

Built for the Bitcoin + AI future ⚡

---
