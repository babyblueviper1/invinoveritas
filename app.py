from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning, client
from config import (
    REASONING_PRICE_SATS,
    DECISION_PRICE_SATS,
    ENABLE_DYNAMIC_PRICING
)
import os
import time
import json
from collections import defaultdict

app = FastAPI(title="invinoveritas – Lightning-paid Decision Intelligence ⚡")

# Rate limiter (simple in-memory)
last_request_time: dict[str, float] = defaultdict(lambda: 0.0)
RATE_LIMIT_SECONDS = 5

# Track used payment hashes to prevent replay
used_payments: set[str] = set()


def detect_caller(request: Request) -> str:
    ua = request.headers.get("user-agent", "").lower()
    if any(x in ua for x in ["python", "curl", "node", "httpclient"]):
        return "agent"
    return "browser"


def calculate_price(endpoint: str, text: str, caller: str) -> int:
    if endpoint == "reason":
        base = REASONING_PRICE_SATS
    else:
        base = DECISION_PRICE_SATS

    # Simple dynamic pricing
    length_bonus = len(text) // 100
    multiplier = 1.2 if caller == "agent" and ENABLE_DYNAMIC_PRICING else 1.0

    price = int((base + length_bonus) * multiplier)
    return max(price, 50)  # minimum 50 sats


# =========================
# Models
# =========================
class ReasoningRequest(BaseModel):
    question: str

class DecisionRequest(BaseModel):
    goal: str
    context: str
    question: str


# =========================
# Basic Routes
# =========================
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡</h1>"


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "invinoveritas",
        "payment_method": "Lightning L402"
    }


@app.get("/price/{endpoint}")
def get_price(endpoint: str):
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    raise HTTPException(404, "Unknown endpoint")


# =========================
# PAID REASONING ENDPOINT
# =========================
@app.post("/reason")
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")

    # Step 1: No valid payment → return invoice (402)
    if not auth or not auth.startswith("L402 "):
        now = time.time()
        if now - last_request_time[caller] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[caller] = now

        price = calculate_price("reason", data.question, caller)

        invoice_data = create_invoice(price, memo=f"invinoveritas reason - {caller}")

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        invoice = invoice_data["invoice"]
        payment_hash = invoice_data["payment_hash"]

        # Return L402 challenge
        challenge = f'token="{payment_hash}", invoice="{invoice}"'

        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={
                "WWW-Authenticate": f"L402 {challenge}",
                "Retry-After": "10"
            }
        )

    # Step 2: Has Authorization header → verify payment
    try:
        _, creds = auth.split(" ", 1)
        token, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")

    if token in used_payments:
        raise HTTPException(403, "Invoice already used")

    if not check_payment(token):
        raise HTTPException(403, "Payment not settled yet")

    used_payments.add(token)

    # Step 3: Payment verified → deliver content
    try:
        result = premium_reasoning(data.question)
    except Exception as e:
        raise HTTPException(500, "Reasoning engine error")

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }


# =========================
# PAID DECISION ENDPOINT
# =========================
@app.post("/decision")
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("L402 "):
        now = time.time()
        if now - last_request_time[caller] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[caller] = now

        price = calculate_price("decision", data.question, caller)

        invoice_data = create_invoice(price, memo=f"invinoveritas decision - {caller}")

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        invoice = invoice_data["invoice"]
        payment_hash = invoice_data["payment_hash"]

        challenge = f'token="{payment_hash}", invoice="{invoice}"'

        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={
                "WWW-Authenticate": f"L402 {challenge}",
                "Retry-After": "10"
            }
        )

    # Verify payment
    try:
        _, creds = auth.split(" ", 1)
        token, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")

    if token in used_payments:
        raise HTTPException(403, "Invoice already used")

    if not check_payment(token):
        raise HTTPException(403, "Payment not settled")

    used_payments.add(token)

    # Run decision logic
    try:
        prompt = f"""
You are a strategic decision intelligence AI.

Goal: {data.goal}
Context: {data.context}
Question: {data.question}

Return ONLY valid JSON:
{{
  "decision": "short answer",
  "confidence": 0.XX,
  "reasoning": "clear explanation",
  "risk_level": "low|medium|high"
}}
"""
        response = client.responses.create(model="gpt-4o-mini", input=prompt)  # adjust model if needed
        result_text = response.output[0].content[0].text
        result_json = json.loads(result_text)

    except Exception as e:
        print("Decision error:", e)
        raise HTTPException(500, "Decision engine error")

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }
