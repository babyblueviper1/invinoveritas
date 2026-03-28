Here’s your **clean, polished, and ready-to-use** markdown README:

```markdown
# invinoveritas – Lightning-Paid Decision Intelligence ⚡

A **FastAPI** backend with **Lightning L402** pay-per-request reasoning.  
Built for both **humans** seeking premium reasoning and **autonomous agents** that need structured, reliable decision intelligence.

---

## Final Launch Pricing

```env
REASONING_PRICE_SATS = 500
DECISION_PRICE_SATS = 250
```

**Why this pricing?**

- **500 sats** for `/reason` — premium long-form reasoning (primarily used by humans)
- **250 sats** for `/decision` — structured, machine-readable decisions (primarily used by agents)
- Lower price on `/decision` intentionally encourages early adoption by autonomous agents
- Simple, transparent, and serious enough to signal quality

---

## API Endpoints

### `POST /reason`

**Human-friendly** premium reasoning.

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
  "answer": "Long-form, high-quality reasoning response here..."
}
```

**Price:** 500 sats

---

### `POST /decision`

**Agent-friendly** structured decision intelligence.

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

**Price:** 250 sats

---

## Project Structure

```
invinoveritas/
├── app.py
├── index.html
├── ai.py
├── node_bridge.py
├── config.py
├── requirements.txt
└── README.md
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

3. Open your browser at:  
   [http://127.0.0.1:8000](http://127.0.0.1:8000)

---

## Environment Variables

```env
OPENAI_API_KEY=your_openai_key_here
NODE_URL=http://YOUR_VPS_IP:5000

REASONING_PRICE_SATS=500
DECISION_PRICE_SATS=250
```

---

## Deploy to Render

1. Create a new **Web Service** on Render
2. Use the following settings:

   - **Build Command:**
     ```bash
     pip install -r requirements.txt
     ```

   - **Start Command:**
     ```bash
     uvicorn app:app --host 0.0.0.0 --port 10000
     ```

3. Add the following environment variables in the Render dashboard:
   - `OPENAI_API_KEY`
   - `NODE_URL`
   - `REASONING_PRICE_SATS`
   - `DECISION_PRICE_SATS`

---

## Payment Flow (L402)

1. Client (human or agent) calls `/reason` or `/decision`
2. Server returns a **Lightning invoice** (L402 challenge)
3. Invoice is paid
4. Client repeats the request with the `Authorization` header containing the preimage
5. AI response is delivered

---

## Who This Is For

- Autonomous AI agents
- Financial automation tools
- Strategic decision engines
- Humans who want high-quality reasoning on demand

---

## Launch Philosophy

This is not another chatbot.

It is **pay-per-decision intelligence powered by Bitcoin** — designed from the ground up for the agent economy.

---

Made with ⚡ for the Bitcoin + AI future.
