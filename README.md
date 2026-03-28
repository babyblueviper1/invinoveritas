# invinoveritas – Lightning-Paid Decision Intelligence ⚡

A **FastAPI** app with **Lightning (L402)** pay-per-request reasoning and agent decision intelligence.  
Built for both humans and autonomous agents.

---

## Project Structure

```bash
invinoveritas/
│
├── app.py
├── index.html
├── ai.py
├── node_bridge.py
├── config.py
├── requirements.txt
└── README.md
```

---

## API Overview

### Endpoints

| Endpoint              | Type                          | Base Price     | Description                                                              |
|-----------------------|-------------------------------|----------------|--------------------------------------------------------------------------|
| `/reason`             | Human-friendly reasoning      | 500 sats       | High-quality structured reasoning response                               |
| `/decision`           | Agent-friendly decision JSON  | 1000 sats      | Strategic decision output with confidence, reasoning & risk level        |
| `/price/{endpoint}`   | Price query                   | Free           | Returns current sats price for `/reason` or `/decision`                  |

---

## Request Examples

### `POST /reason`

**Input:**
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
  "answer": "High-quality structured reasoning output..."
}
```

---

### `POST /decision`

**Input:**
```json
{
  "goal": "Grow capital safely",
  "context": "User holds BTC and cash",
  "question": "Should exposure be increased?"
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

---

### `GET /price/{endpoint}`

Agents can check the current price before calling:

```python
import requests

API_URL = "https://your-api.onrender.com"

reason_price = requests.get(f"{API_URL}/price/reason").json()["price_sats"]
decision_price = requests.get(f"{API_URL}/price/decision").json()["price_sats"]

print(f"Reasoning cost: {reason_price} sats")
print(f"Decision cost: {decision_price} sats")
```

---

## Local Installation

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the server:
   ```bash
   uvicorn app:app --reload
   ```

3. Open in browser:  
   http://127.0.0.1:8000

---

## Environment Variables

```env
OPENAI_API_KEY=your_openai_key
REASONING_PRICE_SATS=500
DECISION_PRICE_SATS=1000
NODE_URL=http://YOUR_VPS_IP:5000
```

---

## Deploy to Render

### Step 1: Create a new Web Service

### Step 2: Set commands

- **Build Command:**
  ```bash
  pip install -r requirements.txt
  ```

- **Start Command:**
  ```bash
  uvicorn app:app --host 0.0.0.0 --port 10000
  ```

### Step 3: Add Environment Variables

Add in the Render dashboard:

- `OPENAI_API_KEY`
- `REASONING_PRICE_SATS`
- `DECISION_PRICE_SATS`
- `NODE_URL`

---

## Payment Flow (L402)

1. User/agent calls `/reason` or `/decision`
2. API returns a **Lightning invoice** (bolt11) if unpaid
3. Pay the invoice via Lightning Network
4. Repeat the request with header: `Authorization: L402 <payment_hash>:<preimage>`
5. AI response unlocks instantly

---

## Agent Considerations

- Use `/price/{endpoint}` to check cost before calling
- Rate-limiting applied (minimum 5s per caller to prevent spam)
- Invoices are tracked — once used, they cannot be reused

---

## Why This Exists

- No accounts required
- No bank subscriptions
- Fully open-source and Bitcoin-powered
- Designed for both human users and autonomous agents

---

## Launch Pricing

- **`/reason`** (reasoning): **500 sats**
- **`/decision`** (decision intelligence): **1000 sats**

Pricing can evolve into fully dynamic logic based on node load, question length, or agent type in the future.

---

Built for the Bitcoin + AI future — where intelligence is paid for atomically on Lightning.
