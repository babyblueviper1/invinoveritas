Here's your **clean, consistent, and polished** version of the README in proper markdown:

```markdown
# invinoveritas – Lightning-Paid AI Reasoning & Decision Intelligence ⚡

A **FastAPI** application with **Lightning (L402)** pay-per-request AI reasoning and decision intelligence.  
Designed for both **humans** who want premium reasoning and **autonomous agents** that need structured, machine-readable decisions.

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

**Price at launch:** 500 sats per request

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

**Price at launch:** 750 sats per request

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
DECISION_PRICE_SATS=750
NODE_URL=http://YOUR_VPS_IP:5000
```

- `OPENAI_API_KEY` – Your OpenAI API key  
- `REASONING_PRICE_SATS` – Price per `/reason` request  
- `DECISION_PRICE_SATS` – Price per `/decision` request  
- `NODE_URL` – Lightning node bridge endpoint

---

## Deploy to Render

### Step 1: Create a new Web Service

### Step 2: Configure build & start commands

- **Build Command:**
  ```bash
  pip install -r requirements.txt
  ```

- **Start Command:**
  ```bash
  uvicorn app:app --host 0.0.0.0 --port 10000
  ```

### Step 3: Add Environment Variables

Add the following in the Render dashboard:

- `OPENAI_API_KEY`
- `REASONING_PRICE_SATS`
- `DECISION_PRICE_SATS`
- `NODE_URL`

### Step 4: Add `index.html`

Place `index.html` in the root of your project for the landing page / interactive demo.

---

## Payment Flow (L402)

1. Client calls `/reason` or `/decision`
2. API returns a Lightning invoice (L402)
3. Pay the invoice via Lightning Network
4. Repeat the request with the `Authorization` header: `L402 <payment_hash>:<preimage>`
5. AI response is unlocked instantly

---

## Example Usage (curl)

**Reasoning request:**
```bash
curl -X POST https://your-api.onrender.com/reason \
  -H "Content-Type: application/json" \
  -d '{"question": "Explain Bitcoin as a long-term strategy"}'
```

**Decision intelligence request:**
```bash
curl -X POST https://your-api.onrender.com/decision \
  -H "Content-Type: application/json" \
  -d '{
    "goal": "Grow capital safely",
    "context": "User holds BTC and cash",
    "question": "Should exposure be increased?"
  }'
```

---

## Why This Project Exists

Most AI tools rely on subscriptions or per-user billing.  
**invinoveritas** charges **per insight** using Bitcoin and Lightning.

- No accounts  
- No subscriptions  
- No bank involvement  
- Instant payment + unlock for both humans and agents  

Perfect for the emerging **agent economy** where AI agents can pay autonomously.

---

## Philosophy

Open-source project focused on **paid intelligence**, **agent-to-agent payments**, and **Lightning-powered APIs**.

Built for a future where intelligence is bought and sold atomically on the Lightning Network.
This version is clean, consistent in formatting, uses proper code blocks, and maintains a professional tone while clearly distinguishing the two endpoints and their pricing. 

Would you like me to also prepare an updated `app.py` snippet or the `index.html` landing page to match this README?
