Here's your **clean, polished, and consistent** version of the README in proper markdown:

```markdown
# invinoveritas – Lightning-Paid Decision Intelligence ⚡

A **FastAPI** application with **Lightning (L402)** pay-per-request AI reasoning and decision intelligence.  
Supports both humans seeking premium reasoning and autonomous agents needing structured outputs.

**Dynamic pricing** is applied based on request size and caller type.

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
  "answer": "High-quality structured reasoning for your question..."
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

## Dynamic Pricing

Pricing is **dynamic** and calculated per request. It depends on:

- Base price from environment variables (`REASONING_PRICE_SATS` or `DECISION_PRICE_SATS`)
- Question/context length (+1 sat per 100 characters)
- Agent multiplier (1.2x for detected automated agents)

**Examples:**
- Human asking a short question → ~500 sats
- Agent asking a longer question → ~720 sats

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
   [http://127.0.0.1:8000](http://127.0.0.1:8000)

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

### Step 1
Create a new **Web Service**

### Step 2
Set the following commands:

- **Build Command:**
  ```bash
  pip install -r requirements.txt
  ```

- **Start Command:**
  ```bash
  uvicorn app:app --host 0.0.0.0 --port 10000
  ```

### Step 3
Add these environment variables in the Render dashboard:

- `OPENAI_API_KEY`
- `REASONING_PRICE_SATS`
- `DECISION_PRICE_SATS`
- `NODE_URL`

---

## Payment Flow (L402)

1. User or agent calls `/reason` or `/decision`
2. API returns a **Lightning invoice** (L402)
3. Invoice is paid via Lightning Network
4. Request is repeated with the `Authorization` header containing the preimage
5. AI response is unlocked instantly

Invoices are tracked to prevent replay attacks and rate-limited to avoid spam.

---

## Why This Exists

Most AI tools charge via subscriptions or per user.  
**invinoveritas** charges **per insight** using Bitcoin and the Lightning Network.

- No accounts  
- No bank subscriptions  
- No platform lock-in  
- Works seamlessly for both humans and autonomous agents

---

## Project Philosophy

An open-source project focused on **paid intelligence**, **agent-to-agent payments**, and **Lightning-powered APIs**.

Built for a future where intelligence can be bought and sold atomically on Bitcoin’s Lightning Network.
