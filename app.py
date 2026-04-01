from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from node_bridge import create_invoice, check_payment, verify_preimage
from ai import premium_reasoning, structured_decision
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
import logging
from collections import defaultdict

# =========================
# Logging Setup (Simple but useful)
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("invinoveritas")


# =========================
# FastAPI App
# =========================
app = FastAPI(
    title="invinoveritas",
    version="0.1.0",
    description=(
        "Lightning-Paid AI Reasoning & Decision Intelligence using the L402 protocol.\n\n"
        "Pay-per-insight API optimized for autonomous agents."
    ),
    contact={
        "name": "invinoveritas",
        "email": "babyblueviperbusiness@gmail.com"
    },
    license_info={"name": "MIT"},
)


# =========================
# State
# =========================
last_request_time: dict[str, float] = defaultdict(lambda: 0.0)
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
# Models (unchanged)
# =========================
class ReasoningRequest(BaseModel):
    question: str

class DecisionRequest(BaseModel):
    goal: str
    context: str
    question: str

class ReasoningResponse(BaseModel):
    status: str
    type: str
    answer: str

class DecisionResult(BaseModel):
    decision: str
    confidence: float
    reasoning: str
    risk_level: str

class DecisionResponse(BaseModel):
    status: str
    type: str
    result: DecisionResult


# =========================
# Meta Routes (unchanged for brevity)
# =========================
# ... (your current /, /health, /tool, /price, /.well-known/ai-plugin.json remain the same)


# =========================
# Inference Routes - Optimized + Logging
# =========================
@app.post("/reason", response_model=ReasoningResponse, tags=["inference"])
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    ip = get_client_ip(request)
    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("L402 "):
        now = time.time()
        rate_key = f"{ip}:reason"
        if now - last_request_time[rate_key] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[rate_key] = now

        price = calculate_price("reason", data.question, caller)
        invoice_data = create_invoice(price, memo=f"invinoveritas reason - {caller}")

        if "error" in invoice_data:
            logger.error(f"Invoice creation failed for {caller} | IP: {ip}")
            raise HTTPException(503, f"Lightning error: {invoice_data.get('error')}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'

        logger.info(f"Invoice issued | Caller: {caller} | Amount: {price}sats | Hash: {invoice_data['payment_hash'][:12]}...")

        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment Required",
                "description": "Pay the Lightning invoice to receive reasoning",
                "payment_hash": invoice_data["payment_hash"],
                "invoice": invoice_data["invoice"],
                "amount_sats": price
            },
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "15"}
        )

    # Payment verification
    try:
        _, creds = auth.split(" ", 1)
        payment_hash, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")

    if payment_hash in used_payments:
        logger.warning(f"Replay attempt | Hash: {payment_hash[:12]}... | Caller: {caller}")
        raise HTTPException(403, "This invoice has already been used")

    if not check_payment(payment_hash):
        raise HTTPException(403, "Payment not settled yet")

    if not verify_preimage(payment_hash, preimage):
        logger.warning(f"Invalid preimage | Hash: {payment_hash[:12]}...")
        raise HTTPException(403, "Invalid payment proof (preimage mismatch)")

    used_payments.add(payment_hash)

    try:
        result = premium_reasoning(data.question)
        logger.info(f"Reasoning delivered | Caller: {caller} | Amount: {calculate_price('reason', data.question, caller)} sats | Hash: {payment_hash[:12]}...")
    except Exception as e:
        logger.error(f"Reasoning engine failed | {e}")
        raise HTTPException(500, "Reasoning engine error") from e

    return {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }


@app.post("/decision", response_model=DecisionResponse, tags=["inference"])
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)
    ip = get_client_ip(request)
    auth = request.headers.get("Authorization")

    if not auth or not auth.startswith("L402 "):
        now = time.time()
        rate_key = f"{ip}:decision"
        if now - last_request_time[rate_key] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")

        last_request_time[rate_key] = now

        text = f"{data.goal} {data.context} {data.question}"
        price = calculate_price("decision", text, caller)

        invoice_data = create_invoice(price, memo=f"invinoveritas decision - {caller}")

        if "error" in invoice_data:
            logger.error(f"Invoice creation failed for decision | Caller: {caller}")
            raise HTTPException(503, f"Lightning error: {invoice_data.get('error')}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'

        logger.info(f"Decision invoice issued | Caller: {caller} | Amount: {price}sats")

        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment Required",
                "description": "Pay the Lightning invoice to receive structured decision",
                "payment_hash": invoice_data["payment_hash"],
                "invoice": invoice_data["invoice"],
                "amount_sats": price
            },
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "15"}
        )

    # Payment verification (same secure logic)
    try:
        _, creds = auth.split(" ", 1)
        payment_hash, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")

    if payment_hash in used_payments:
        logger.warning(f"Replay attempt on decision | Hash: {payment_hash[:12]}...")
        raise HTTPException(403, "This invoice has already been used")

    if not check_payment(payment_hash):
        raise HTTPException(403, "Payment not settled yet")

    if not verify_preimage(payment_hash, preimage):
        logger.warning(f"Invalid preimage on decision | Hash: {payment_hash[:12]}...")
        raise HTTPException(403, "Invalid payment proof")

    used_payments.add(payment_hash)

    try:
        result_json = structured_decision(data.goal, data.context, data.question)
        logger.info(f"Decision delivered | Caller: {caller} | Amount: {calculate_price('decision', f'{data.goal} {data.context} {data.question}', caller)} sats")
    except Exception as e:
        logger.error(f"Decision engine failed | {e}")
        raise HTTPException(500, "Decision engine error") from e

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }
