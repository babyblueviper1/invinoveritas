# invinoveritas – Lightning-Paid Decision Intelligence ⚡

A **FastAPI** app with **Lightning (L402)** pay-per-request AI reasoning and decision intelligence.  
Designed to serve both **humans** and **autonomous agents**.

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
├── agent_client.py     # Optional Python client for autonomous agents
└── README.md
```

---

## API Endpoints

### `POST /reason` – Human-friendly reasoning

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
  "answer": "High-quality structured answer..."
}
```

---

### `POST /decision` – Agent-friendly structured decision intelligence

**Request:**
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

### `GET /price/{endpoint}` – Dynamic pricing

- `GET /price/reason`
- `GET /price/decision`

**Response:**
```json
{
  "price_sats": 500
}
```

---

## Local Installation

```bash
pip install -r requirements.txt
```

Run the server:

```bash
uvicorn app:app --reload
```

Open in browser:  
http://127.0.0.1:8000

---

## Environment Variables

```env
OPENAI_API_KEY=your_openai_key
REASONING_PRICE_SATS=500
DECISION_PRICE_SATS=1000
NODE_URL=http://YOUR_VPS_IP:5000
```

**For the optional agent client (`agent_client.py`):**

```env
LND_DIR=/path/to/lnd
CLN_RPC_PATH=/path/to/bolt-rpc
```

---

## Deploy to Render

### Step 1
Create a new **Web Service**

### Step 2
Use these settings:

- **Build Command:**
  ```bash
  pip install -r requirements.txt
  ```

- **Start Command:**
  ```bash
  uvicorn app:app --host 0.0.0.0 --port 10000
  ```

### Step 3
Add the following environment variables in the Render dashboard:

- `OPENAI_API_KEY`
- `REASONING_PRICE_SATS`
- `DECISION_PRICE_SATS`
- `NODE_URL`

---

## 7. How the Payment Flow Works

1. User or agent calls `/reason` or `/decision`
2. API returns a **Lightning invoice (L402)** along with a temporary token
3. User/agent pays the invoice via Lightning Network
4. Retry the request with the `Authorization` header:  
   `L402 {token}:{preimage}`
5. AI response is unlocked instantly

---

## 8. Agent Discovery

Agents can programmatically discover the API and its dynamic pricing.

### 8.1 Check Dynamic Pricing

```bash
curl https://your-api.onrender.com/price/reason
curl https://your-api.onrender.com/price/decision
```

### 8.2 Full Invoice Flow

1. Send request to `/reason` or `/decision` with payload
2. API returns Lightning invoice + token
3. Pay the invoice using LND or Core Lightning (CLN)
4. Retry the request with header: `Authorization: L402 {token}:{preimage}`
5. Receive the AI response

---

## 9. Unified Agent Client (Python)

A ready-to-use Python client (`agent_client.py`) is included for autonomous agents.

It automatically:
- Fetches the current price via `/price/{endpoint}`
- Requests a Lightning invoice
- Pays the invoice using LND or Core Lightning
- Retries the request with the proper Authorization header
- Returns the final AI output

**Example usage:**

```bash
python agent_client.py --endpoint reason --question "Explain Bitcoin as a long-term strategy"
```

```python
import os
import requests
import json
import sys

API_BASE = "https://your-api.onrender.com"
ENDPOINT = "reason"   # or "decision"

# Node config
LND_DIR = os.getenv("LND_DIR")
CLN_RPC_PATH = os.getenv("CLN_RPC_PATH")

# Fetch current price
price = requests.get(f"{API_BASE}/price/{ENDPOINT}").json()["price_sats"]
print(f"{ENDPOINT} price: {price} sats")

# Full client handles invoice request, payment, and retry (see agent_client.py)
```

The full client supports **LND**, **Core Lightning (CLN)**, dynamic pricing, retries, and pre-paid invoice detection.

---

## 10. Notes for Launch

- **Rate limiting**: 5 seconds per caller to prevent spam
- **Invoice tracking**: Prevents replay attacks
- **Agent-first design**: `/decision` endpoint is optimized for autonomous agents
- **Dynamic pricing**: Allows future adjustments based on market conditions, load, or request complexity
- **No accounts or subscriptions** required — pure pay-per-insight model

---

## Why This Exists

Most AI tools rely on subscriptions or per-user billing.  
**invinoveritas** charges **per insight** using Bitcoin and the Lightning Network.

- No accounts  
- No bank involvement  
- No platform lock-in  
- Works seamlessly for both humans and autonomous agents

---

Built for the Bitcoin + AI future — where intelligence is bought and sold atomically on Lightning ⚡
