from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment, verify_preimage
from ai import premium_reasoning
from config import (
    REASONING_PRICE_SATS,
    DECISION_PRICE_SATS,
    ENABLE_DYNAMIC_PRICING
)
import os
import time
from collections import defaultdict

# =========================
# App
# =========================
app = FastAPI(
    title="invinoveritas",
    description=(
        "## Lightning-Paid AI Reasoning & Decision Intelligence ⚡\n\n"
        "Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning Network). "
        "No accounts, no subscriptions, no KYC.\n\n"
        "### Payment flow\n"
        "1. POST to `/reason` or `/decision` — receive HTTP **402** with a bolt11 invoice "
        "in the `WWW-Authenticate: L402` header.\n"
        "2. Pay the invoice with any Lightning wallet.\n"
        "3. Retry the same request with header:\n"
        "   `Authorization: L402 <payment_hash>:<preimage>`\n"
        "4. Receive the AI response.\n\n"
        "### Pricing\n"
        "- `/reason` — ~500 sats base (dynamic)\n"
        "- `/decision` — ~1000 sats base (dynamic)\n"
        "- Check current price: `GET /price/{endpoint}`\n\n"
        "### For autonomous agents\n"
        "Use the included `agent_client.py` or the MCP server."
    ),
    version="0.1.0",
    contact={"name": "invinoveritas", "url": "https://your-api.onrender.com"},
    openapi_tags=[
        {"name": "inference", "description": "AI reasoning and decision endpoints. All require Lightning payment."},
        {"name": "meta", "description": "Pricing, health, and discovery endpoints. Always free."}
    ]
)

# Rate limiter (per IP + endpoint)
last_request_time: dict[str, float] = defaultdict(lambda: 0.0)
RATE_LIMIT_SECONDS = 5

# Track used payment hashes (in-memory for now)
used_payments: set[str] = set()


# =========================
# Helpers
# =========================
def detect_caller(request: Request) -> str:
    ua = request.headers.get("user-agent", "").lower()
    if any(x in ua for x in ["python", "curl", "node", "httpclient", "invinoveritas-mcp"]):
        return "agent"
    return "browser"


def get_client_ip(request: Request) -> str:
    """Use IP for better rate limiting"""
    return request.client.host if request.client else "unknown"


def calculate_price(endpoint: str, text: str, caller: str) -> int:
    base = REASONING_PRICE_SATS if endpoint == "reason" else DECISION_PRICE_SATS
    length_bonus = len(text) // 100
    multiplier = 1.2 if caller == "agent" and ENABLE_DYNAMIC_PRICING else 1.0
    price = int((base + length_bonus) * multiplier)
    return max(price, 50)


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
# Meta Routes
# =========================
@app.get("/", response_class=HTMLResponse, tags=["meta"])
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡</h1>"


@app.get("/health", tags=["meta"])
def health():
    return {
        "status": "ok",
        "service": "invinoveritas",
        "version": "0.1",
        "payment": "Lightning L402"
    }


@app.get("/price/{endpoint}", tags=["meta"])
def get_price(endpoint: str):
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    raise HTTPException(404, "Unknown endpoint")


# =========================
# Inference Routes
# =========================
@app.post("/reason", tags=["inference"])
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    ip = get_client_ip(request)
    auth = request.headers.get("Authorization")

    # === No auth → Return invoice ===
    if not auth or not auth.startswith("L402 "):
        now = time.time()
        rate_key = f"{ip}:reason"
        if now - last_request_time[rate_key] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[rate_key] = now

        price = calculate_price("reason", data.question, caller)
        invoice_data = create_invoice(price, memo=f"invinoveritas reason - {caller}")

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={
                "WWW-Authenticate": f"L402 {challenge}",
                "Retry-After": "10"
            }
        )

    # === Payment verification ===
    try:
        _, creds = auth.split(" ", 1)
        payment_hash, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")

    if payment_hash in used_payments:
        raise HTTPException(403, "Invoice already used")

    if not check_payment(payment_hash):
        raise HTTPException(403, "Payment not settled yet")

    if not verify_preimage(payment_hash, preimage):
        raise HTTPException(403, "Invalid payment proof (preimage mismatch)")

    used_payments.add(payment_hash)

    # === Process request ===
    try:
        result = premium_reasoning(data.question)
    except Exception as e:
        raise HTTPException(500, "Reasoning engine error")

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }


@app.post("/decision", tags=["inference"])
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)
    ip = get_client_ip(request)
    auth = request.headers.get("Authorization")

    # === No auth → Return invoice ===
    if not auth or not auth.startswith("L402 "):
        now = time.time()
        rate_key = f"{ip}:decision"
        if now - last_request_time[rate_key] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[rate_key] = now

        # Use all fields for length calculation
        text_length = data.goal + data.context + data.question
        price = calculate_price("decision", text_length, caller)

        invoice_data = create_invoice(price, memo=f"invinoveritas decision - {caller}")

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={
                "WWW-Authenticate": f"L402 {challenge}",
                "Retry-After": "10"
            }
        )

    # === Payment verification (same as /reason) ===
    try:
        _, creds = auth.split(" ", 1)
        payment_hash, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")

    if payment_hash in used_payments:
        raise HTTPException(403, "Invoice already used")

    if not check_payment(payment_hash):
        raise HTTPException(403, "Payment not settled yet")

    if not verify_preimage(payment_hash, preimage):
        raise HTTPException(403, "Invalid payment proof (preimage mismatch)")

    used_payments.add(payment_hash)

    # === Process decision request ===
    try:
        prompt = f"""
You are a strategic decision intelligence AI.

Goal: {data.goal}
Context: {data.context}
Question: {data.question}

Return ONLY valid JSON:
{{
  "decision": "short recommended action",
  "confidence": 0.XX,
  "reasoning": "clear explanation",
  "risk_level": "low|medium|high"
}}
"""

        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=800,
        )
        result_text = response.choices[0].message.content.strip()
        result_json = json.loads(result_text)

    except Exception as e:
        print("Decision engine error:", e)
        raise HTTPException(500, "Decision engine error")

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }
