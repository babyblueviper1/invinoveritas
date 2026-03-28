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
# Request models
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

        log_event("request_without_payment", "reason", REASONING_PRICE_SATS, caller)
        invoice_data = create_invoice(REASONING_PRICE_SATS)

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
    log_event("payment_success", "reason", REASONING_PRICE_SATS, caller)

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

        log_event("request_without_payment", "decision", DECISION_PRICE_SATS, caller)
        invoice_data = create_invoice(DECISION_PRICE_SATS)

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
    log_event("payment_success", "decision", DECISION_PRICE_SATS, caller)

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
