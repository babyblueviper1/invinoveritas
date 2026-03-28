# invinoveritas – Lightning‑Paid Decision Intelligence

This project is a **FastAPI app with Lightning (L402) pay-per-request reasoning**.
It supports both humans and autonomous agents.

---

# 1. Project Structure

```
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

# 2. What the API does

### /reason

Human‑friendly reasoning endpoint

Input:

```
POST /reason
{
  "question": "Should I increase my BTC exposure right now?"
}
```

### /decision

Agent‑friendly structured JSON

Input:

```
POST /decision
{
  "goal": "Grow capital safely",
  "context": "User holds BTC and cash",
  "question": "Should exposure be increased?"
}
```

Output (after payment):

```
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

# 3. Install locally

```
pip install -r requirements.txt
```

Then run:

```
uvicorn app:app --reload
```

Open:

```
http://127.0.0.1:8000
```

---

# 4. Environment variables

You need these:

```
OPENAI_API_KEY=your_openai_key
REASONING_PRICE_SATS=500
```

---

# 5. Deploy to Render

On Render:

### Step 1

Create a new **Web Service**

### Step 2

Use these settings:

Build command:

```
pip install -r requirements.txt
```

Start command:

```
uvicorn app:app --host 0.0.0.0 --port 10000
```

### Step 3

Add environment variables in the dashboard:

```
OPENAI_API_KEY
REASONING_PRICE_SATS
```

---

# 6. How the payment flow works

1. User calls `/reason` or `/decision`
2. API returns a **Lightning invoice (L402)**
3. User/agent pays invoice
4. Request is repeated with Authorization header
5. AI response is unlocked

---
