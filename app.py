from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning, client
from config import REASONING_PRICE_SATS, DECISION_PRICE_SATS
import os
import time
from collections import defaultdict
import json

app = FastAPI(title="invinoveritas – Lightning-paid Decision Intelligence")

# -------------------------
# Rate limiter (anti-spam invoices)
# -------------------------
last_request_time: dict[str, float] = defaultdict(lambda: 0.0)
RATE_LIMIT_SECONDS = 5

# -------------------------
# Invoice tracking (prevent replay)
# -------------------------
used_invoices: set[str] = set()

# -------------------------
# Logging helpers
# -------------------------
def detect_caller(request: Request) -> str:
    user_agent = request.headers.get("user-agent", "").lower()
    if "python" in user_agent or "curl" in user_agent or "node" in user_agent:
        return "agent"
    if "mozilla" in user_agent or "chrome" in user_agent or "safari" in user_agent:
        return "browser"
    return "unknown"

def log_event(event_type: str, endpoint: str, amount: int, caller: str):
    print(f"{event_type.upper()} | {endpoint} | {amount} sats | {caller}")

# -------------------------
# Dynamic pricing helper
# -------------------------
def calculate_price(endpoint: str, question: str, caller: str) -> int:
    """
    Basic dynamic pricing:
      - base price from config
      - +1 sat per 100 characters
      - agent multiplier 1.2x
    """
    if endpoint == "reason":
        base = REASONING_PRICE_SATS
    else:
        base = DECISION_PRICE_SATS

    length_sats = len(question) // 100  # 1 sat per 100 chars
    agent_multiplier = 1.2 if caller == "agent" else 1.0

    price = int((base + length_sats) * agent_multiplier)
    return max(price, 1)  # ensure minimum 1 sat

# -------------------------
# Request models
# -------------------------
class ReasoningRequest(BaseModel):
    question: str

class DecisionRequest(BaseModel):
    goal: str
    context: str
    question: str

# -------------------------
# Home / Health / Price
# -------------------------
@app.get("/", response_class=HTMLResponse)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡🤖</h1>"

@app.get("/health")
def health():
    """
    Health check + machine-readable endpoint info for agents
    """
    return {
        "status": "ok",
        "service": "invinoveritas",
        "version": "0.1",
        "endpoints": [
            {
                "path": "/reason",
                "description": "Human-friendly premium reasoning",
                "price_sats": REASONING_PRICE_SATS,
                "method": "POST",
                "input_schema": {
                    "question": "string"
                },
                "auth": "Lightning L402 token via Authorization header"
            },
            {
                "path": "/decision",
                "description": "Agent-friendly structured decision intelligence",
                "price_sats": DECISION_PRICE_SATS,
                "method": "POST",
                "input_schema": {
                    "goal": "string",
                    "context": "string",
                    "question": "string"
                },
                "auth": "Lightning L402 token via Authorization header"
            }
        ],
        "payment": {
            "method": "Lightning L402",
            "currency": "sats",
            "dynamic_pricing": True
        }
    }

@app.get("/price/{endpoint}")
def get_price(endpoint: str):
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    else:
        raise HTTPException(404, "Unknown endpoint")
# -------------------------
# PAID REASONING ENDPOINT
# -------------------------
@app.post("/reason")
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)

    if len(data.question) > 1200:
        raise HTTPException(400, "Prompt too long for this endpoint")

    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("L402 "):
        now = time.time()
        if now - last_request_time[caller] < RATE_LIMIT_SECONDS:
            raise HTTPException(
                429,
                f"Rate limit: please wait {RATE_LIMIT_SECONDS} seconds before requesting another invoice"
            )
        last_request_time[caller] = now

        # dynamic pricing
        price = calculate_price("reason", data.question, caller)
        log_event("invoice_issued", "reason", price, caller)

        invoice_data = create_invoice(price)

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

    # -------------------------
    # Step 2: Verify payment
    # -------------------------
    try:
        _, creds = auth.split(" ", 1)
        macaroon, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 credentials")

    if macaroon in used_invoices:
        raise HTTPException(403, "Invoice already used")

    if not check_payment(macaroon):
        raise HTTPException(403, "Invalid or unpaid credential")

    used_invoices.add(macaroon)
    price = calculate_price("reason", data.question, caller)
    log_event("payment_success", "reason", price, caller)

    # -------------------------
    # Step 3: Paid → run reasoning
    # -------------------------
    try:
        result = premium_reasoning(data.question)
    except Exception as e:
        print("Reasoning engine error:", e)
        raise HTTPException(500, "Reasoning engine temporarily unavailable")

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }

# -------------------------
# AGENT DECISION ENDPOINT
# -------------------------
@app.post("/decision")
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)

    if len(data.question) > 1200:
        raise HTTPException(400, "Question too long for this endpoint")

    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("L402 "):
        now = time.time()
        if now - last_request_time[caller] < RATE_LIMIT_SECONDS:
            raise HTTPException(
                429,
                f"Rate limit: please wait {RATE_LIMIT_SECONDS} seconds before requesting another invoice"
            )
        last_request_time[caller] = now

        # dynamic pricing
        price = calculate_price("decision", data.question, caller)
        log_event("invoice_issued", "decision", price, caller)

        invoice_data = create_invoice(price)

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
                "WWW-Authenticate": f'L402 {challenge}",
                "Retry-After": "10"
            }
        )

    # -------------------------
    # Step 2: Verify payment
    # -------------------------
    try:
        _, creds = auth.split(" ", 1)
        macaroon, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 credentials")

    if macaroon in used_invoices:
        raise HTTPException(403, "Invoice already used")

    if not check_payment(macaroon):
        raise HTTPException(403, "Invalid or unpaid credential")

    used_invoices.add(macaroon)
    price = calculate_price("decision", data.question, caller)
    log_event("payment_success", "decision", price, caller)

    # -------------------------
    # Step 3: Paid → structured decision output
    # -------------------------
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
        response = client.responses.create(model="gpt-4.1-mini", input=prompt)
        result_text = response.output[0].content[0].text

        # Validate JSON
        try:
            result_json = json.loads(result_text)
        except json.JSONDecodeError:
            raise HTTPException(500, "Decision engine returned invalid JSON")

    except Exception as e:
        print("Decision engine error:", e)
        raise HTTPException(500, "Decision engine temporarily unavailable")

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }
