from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment, verify_preimage
from ai import premium_reasoning
from config import (
    REASONING_PRICE_SATS,
    DECISION_PRICE_SATS,
    ENABLE_AGENT_MULTIPLIER,
    AGENT_PRICE_MULTIPLIER,
    MIN_PRICE_SATS,
    RATE_LIMIT_SECONDS,
)
import os
import time
import json
from collections import defaultdict

# =========================
# FastAPI App
# =========================
app = FastAPI(
    title="invinoveritas",
    description=(
        "## Lightning-Paid AI Reasoning & Decision Intelligence ⚡\n\n"
        "Pay-per-insight API using the **L402 protocol** (Bitcoin Lightning Network). "
        "No accounts, no subscriptions, no KYC.\n\n"
        "### Payment flow\n"
        "1. POST to `/reason` or `/decision` → receive HTTP 402 with bolt11 invoice\n"
        "2. Pay the invoice with any Lightning wallet\n"
        "3. Retry with header: `Authorization: L402 <payment_hash>:<preimage>`\n"
        "4. Receive AI response\n\n"
        "### Pricing\n"
        "- `/reason`   → ~500 sats base\n"
        "- `/decision` → ~1000 sats base\n"
        "Agents pay a small premium (configurable)."
    ),
    version="0.1.0",
    contact={"name": "invinoveritas"},
)

# Rate limiter (per IP + endpoint)
last_request_time: dict[str, float] = defaultdict(lambda: 0.0)

# Track used payment hashes (in-memory)
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
    return request.client.host if request.client else "unknown"


def calculate_price(endpoint: str, text: str, caller: str) -> int:
    base = REASONING_PRICE_SATS if endpoint == "reason" else DECISION_PRICE_SATS
    length_bonus = len(text) // 100
    multiplier = AGENT_PRICE_MULTIPLIER if caller == "agent" and ENABLE_AGENT_MULTIPLIER else 1.0
    price = int((base + length_bonus) * multiplier)
    return max(price, MIN_PRICE_SATS)


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
    return {"status": "ok", "service": "invinoveritas", "version": "0.1", "payment": "Lightning L402"}


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

    # No authorization → return invoice
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
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "10"}
        )

    # Payment verification
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

    # Process reasoning
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

    # No authorization → return invoice
    if not auth or not auth.startswith("L402 "):
        now = time.time()
        rate_key = f"{ip}:decision"
        if now - last_request_time[rate_key] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[rate_key] = now

        text = data.goal + data.context + data.question
        price = calculate_price("decision", text, caller)

        invoice_data = create_invoice(price, memo=f"invinoveritas decision - {caller}")

        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "10"}
        )

    # Payment verification
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

    # === Call the business logic (now cleanly separated) ===
    try:
        result_json = structured_decision(data.goal, data.context, data.question)
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }
