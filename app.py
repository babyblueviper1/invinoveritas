from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment
from ai import premium_reasoning
from config import (
    REASONING_PRICE_SATS,
    DECISION_PRICE_SATS,
    ENABLE_DYNAMIC_PRICING
)
import os
import time
import json
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
        "2. Pay the invoice with any Lightning wallet or node.\n"
        "3. Retry the same request with header:\n"
        "   `Authorization: L402 <payment_hash>:<preimage>`\n"
        "4. Receive the AI response.\n\n"
        "### Pricing\n"
        "- `/reason` — ~500 sats base (dynamic)\n"
        "- `/decision` — ~1000 sats base (dynamic)\n"
        "- Check current price: `GET /price/{endpoint}`\n\n"
        "### For autonomous agents\n"
        "Use the included `agent_client.py` or the MCP server (`mcp_server.py`) "
        "which handles the full payment flow automatically."
    ),
    version="0.1.0",
    contact={"name": "invinoveritas", "url": "https://your-api.onrender.com"},
    openapi_tags=[
        {
            "name": "inference",
            "description": "AI reasoning and decision endpoints. All require Lightning payment."
        },
        {
            "name": "meta",
            "description": "Pricing, health, and discovery endpoints. Always free."
        }
    ]
)

# Rate limiter
last_request_time: dict[str, float] = defaultdict(lambda: 0.0)
RATE_LIMIT_SECONDS = 5

# Track used payment hashes
used_payments: set[str] = set()


# =========================
# Helpers
# =========================
def detect_caller(request: Request) -> str:
    ua = request.headers.get("user-agent", "").lower()
    if any(x in ua for x in ["python", "curl", "node", "httpclient", "invinoveritas-mcp"]):
        return "agent"
    return "browser"


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
    """Return the current base price in satoshis for a given endpoint."""
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    raise HTTPException(404, "Unknown endpoint")


@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def ai_plugin():
    """
    Standard discovery endpoint for browsing agents and LLM tool registries.
    Claude in Chrome, AutoGPT, and similar agents check this URL to understand
    what the API can do before deciding whether to use it.
    """
    return {
        "schema_version": "v1",
        "name_for_human": "invinoveritas",
        "name_for_model": "invinoveritas",
        "description_for_human": "Lightning-paid AI reasoning and decision intelligence. Pay per insight with Bitcoin.",
        "description_for_model": (
            "invinoveritas provides pay-per-use AI reasoning and structured decision intelligence "
            "via the Bitcoin Lightning Network (L402 protocol). "
            "Use the /reason endpoint for strategic analysis and complex questions. "
            "Use the /decision endpoint when you need a structured JSON response with "
            "a decision, confidence score (0-1), reasoning, and risk_level (low/medium/high). "
            "All calls require a small Lightning payment (~500-1000 sats). "
            "The API returns HTTP 402 with a bolt11 invoice in WWW-Authenticate on first call; "
            "retry with Authorization: L402 <payment_hash>:<preimage> after paying."
        ),
        "auth": {
            "type": "none"
        },
        "api": {
            "type": "openapi",
            "url": "/openapi.json",
            "is_user_authenticated": False
        },
        "contact_email": "contact@invinoveritas.com",
        "legal_info_url": "/legal"
    }


# =========================
# Inference Routes
# =========================
@app.post(
    "/reason",
    tags=["inference"],
    summary="Strategic reasoning (Lightning-paid)",
    description=(
        "Submit a question and receive a high-quality strategic answer powered by AI. "
        "**Requires Lightning payment via L402.**\n\n"
        "First call returns HTTP 402 with a bolt11 invoice. "
        "Pay the invoice, then retry with `Authorization: L402 <payment_hash>:<preimage>`."
    ),
    responses={
        200: {"description": "AI reasoning response"},
        402: {"description": "Payment required — bolt11 invoice in WWW-Authenticate header"},
        401: {"description": "Invalid L402 credentials"},
        403: {"description": "Payment not settled or invoice already used"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "Lightning node error"},
    }
)
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("L402 "):
        now = time.time()
        if now - last_request_time[caller] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[caller] = now
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

    # Verify payment
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

    try:
        result = premium_reasoning(data.question)
    except Exception as e:
        raise HTTPException(500, "Reasoning engine error")

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }


@app.post(
    "/decision",
    tags=["inference"],
    summary="Structured decision intelligence (Lightning-paid)",
    description=(
        "Submit a goal, context, and question — receive a structured decision with "
        "confidence score and risk level. Designed for autonomous agents. "
        "**Requires Lightning payment via L402.**\n\n"
        "First call returns HTTP 402 with a bolt11 invoice. "
        "Pay the invoice, then retry with `Authorization: L402 <payment_hash>:<preimage>`.\n\n"
        "Response `result` object contains:\n"
        "- `decision` — short recommended action\n"
        "- `confidence` — float 0–1\n"
        "- `reasoning` — explanation\n"
        "- `risk_level` — `low` | `medium` | `high`"
    ),
    responses={
        200: {"description": "Structured decision response"},
        402: {"description": "Payment required — bolt11 invoice in WWW-Authenticate header"},
        401: {"description": "Invalid L402 credentials"},
        403: {"description": "Payment not settled or invoice already used"},
        429: {"description": "Rate limit exceeded"},
        503: {"description": "Lightning node error"},
    }
)
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

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
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
