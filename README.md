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

## Payment Flow (L402)

1. User or agent calls `/reason` or `/decision`
2. API returns a Lightning invoice (L402)
3. Invoice is paid via Lightning Network
4. Request is repeated with the `Authorization` header: `L402 <payment_hash>:<preimage>`
5. AI response is unlocked instantly

---

## Agent Client (`agent_client.py`)

We provide a ready-to-use **Python client** for autonomous agents.

### Features:
- Automatically fetches current price via `/price/{endpoint}`
- Requests Lightning invoice
- Pays the invoice using **LND** or **Core Lightning (CLN)**
- Retries the request with proper `Authorization` header
- Returns the final AI output

### Example Usage:

```bash
python agent_client.py --endpoint reason --question "Explain Bitcoin as a long-term strategy"
```

or

```bash
python agent_client.py --endpoint decision \
  --goal "Grow capital safely" \
  --context "User holds BTC and cash" \
  --question "Should exposure be increased?"
```

The client will print:
- Current price in sats
- Generated BOLT11 invoice
- Payment preimage
- Final AI response

---

## Why This Exists

Most AI tools charge per user or via subscriptions.  
**invinoveritas** charges **per insight** using Bitcoin and the Lightning Network.

- No accounts  
- No bank subscriptions  
- No platform lock-in  
- Seamless support for both humans and autonomous agents

---

## Project Philosophy

An open-source project focused on **paid intelligence**, **agent-to-agent payments**, and **Lightning-powered APIs**.

Built for the emerging Bitcoin + AI economy where intelligence can be bought and sold atomically.

---

Would you like me to also create the content for `agent_client.py` next?
