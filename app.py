from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning, client
from config import REASONING_PRICE_SATS
import os

app = FastAPI(title="invinoveritas – Lightning-paid Decision Intelligence")

PRICE_SATS = REASONING_PRICE_SATS


# -------------------------
# Request Models
# -------------------------

class ReasoningRequest(BaseModel):
    question: str


class DecisionRequest(BaseModel):
    goal: str
    context: str
    question: str


# -------------------------
# Home / Health
# -------------------------

@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡🤖</h1>"


@app.get("/health")
def health():
    return {"status": "ok"}


# -------------------------
# Paid Reasoning Endpoint
# -------------------------

@app.post("/reason")
async def reason(request: Request, data: ReasoningRequest):

    # Protect cost
    if len(data.question) > 1200:
        raise HTTPException(400, "Prompt too long for this endpoint")

    auth = request.headers.get("Authorization")

    # Step 1: No payment → issue invoice
    if not auth or not auth.startswith("L402 "):

        invoice_data = create_invoice(PRICE_SATS)

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning node error: {invoice_data['error']}")

        invoice = invoice_data.get("invoice")
        payment_hash = invoice_data.get("payment_hash")

        if not invoice or not payment_hash:
            raise HTTPException(503, "Invalid response from Lightning node")

        macaroon = payment_hash
        challenge = f'token="{macaroon}", invoice="{invoice}"'

        raise HTTPException(
            status_code=402,
            detail="Payment Required – pay Lightning invoice to unlock premium reasoning",
            headers={
                "WWW-Authenticate": f'L402 {challenge}',
                "Retry-After": "10"
            }
        )

    # Step 2: Verify payment
    try:
        _, creds = auth.split(" ", 1)
        macaroon, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 credentials")

    if not check_payment(macaroon):
        raise HTTPException(403, "Invalid or unpaid credential")

    # Step 3: Paid → run reasoning
    try:
        result = premium_reasoning(data.question)
    except Exception:
        raise HTTPException(500, "Reasoning engine temporarily unavailable")

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }


# -------------------------
# Agent Decision Endpoint
# -------------------------

@app.post("/decision")
async def decision(request: Request, data: DecisionRequest):

    # Protect cost
    if len(data.question) > 1200:
        raise HTTPException(400, "Question too long for this endpoint")

    auth = request.headers.get("Authorization")

    # Step 1: No payment → issue invoice
    if not auth or not auth.startswith("L402 "):

        invoice_data = create_invoice(PRICE_SATS)

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning node error: {invoice_data['error']}")

        invoice = invoice_data.get("invoice")
        payment_hash = invoice_data.get("payment_hash")

        if not invoice or not payment_hash:
            raise HTTPException(503, "Invalid response from Lightning node")

        macaroon = payment_hash
        challenge = f'token="{macaroon}", invoice="{invoice}"'

        raise HTTPException(
            status_code=402,
            detail="Payment Required – pay Lightning invoice to unlock decision intelligence",
            headers={
                "WWW-Authenticate": f'L402 {challenge}',
                "Retry-After": "10"
            }
        )

    # Step 2: Verify payment
    try:
        _, creds = auth.split(" ", 1)
        macaroon, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 credentials")

    if not check_payment(macaroon):
        raise HTTPException(403, "Invalid or unpaid credential")

    # Step 3: Paid → structured JSON decision
    try:
        prompt = f"""
You are a strategic decision intelligence AI.

Goal:
{data.goal}

Context:
{data.context}

Question:
{data.question}

Return ONLY valid JSON in this exact format:

{{
  "decision": "",
  "confidence": 0.0,
  "reasoning": "",
  "risk_level": ""
}}
"""

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "decision_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "decision": {"type": "string"},
                            "confidence": {"type": "number"},
                            "reasoning": {"type": "string"},
                            "risk_level": {"type": "string"}
                        },
                        "required": ["decision", "confidence", "reasoning", "risk_level"]
                    }
                }
            }
        )

        result = response.output[0].content[0].text

    except Exception:
        raise HTTPException(500, "Decision engine temporarily unavailable")

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result
    }
