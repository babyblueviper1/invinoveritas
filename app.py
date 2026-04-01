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
from collections import defaultdict


# =========================
# FastAPI App
# =========================
app = FastAPI(
    title="invinoveritas",
    version="0.1.0",
    description=(
        "Lightning-Paid AI Reasoning & Decision Intelligence using the L402 protocol.\n\n"
        "Pay-per-insight API. No accounts. No subscriptions. No KYC.\n\n"
        "Workflow:\n"
        "1. POST to /reason or /decision\n"
        "2. Receive HTTP 402 with Lightning invoice\n"
        "3. Pay the invoice\n"
        "4. Retry with Authorization: L402 <payment_hash>:<preimage>\n"
        "5. Receive AI response"
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
# Models
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
    """Health check with rich metadata for monitoring and autonomous agents."""
    return {
        "status": "ok",
        "service": "invinoveritas",
        "version": "0.1.0",
        "timestamp": int(time.time()),

        "api": {
            "title": "Lightning-Paid AI Reasoning & Decision Intelligence",
            "protocol": "L402",
            "payment_currency": "sats"
        },

        "endpoints": {
            "reason": {
                "path": "/reason",
                "method": "POST",
                "description": "Premium strategic reasoning",
                "base_price_sats": REASONING_PRICE_SATS,
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
            },
            "decision": {
                "path": "/decision",
                "method": "POST",
                "description": "Structured decision intelligence for agents",
                "base_price_sats": DECISION_PRICE_SATS,
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
            }
        },

        "pricing": {
            "currency": "sats",
            "dynamic_pricing": ENABLE_AGENT_MULTIPLIER,
            "agent_multiplier": AGENT_PRICE_MULTIPLIER,
            "minimum_price_sats": MIN_PRICE_SATS
        },

        "features": {
            "rate_limiting": True,
            "replay_protection": True,
            "no_accounts": True,
            "no_kyc": True,
            "agent_friendly": True
        },

        "links": {
            "docs": "/docs",
            "redoc": "/redoc",
            "ai_plugin": "/.well-known/ai-plugin.json",
            "tool_definition": "/tool",
            "price_check": "/price/{endpoint}"
        }
    }


@app.get("/tool", tags=["meta"])
def tool_definition():
    """Tool definition for agent discovery."""
    return {
        "name": "invinoveritas",
        "type": "lightning_paid_ai",
        "description": "Lightning-paid strategic reasoning and structured decision intelligence",
        "payment_protocol": "L402",
        "endpoints": {
            "reason": {"path": "/reason", "base_price_sats": REASONING_PRICE_SATS},
            "decision": {"path": "/decision", "base_price_sats": DECISION_PRICE_SATS}
        },
        "agent_support": {
            "mcp_compatible": True,
            "autonomous": True
        }
    }


@app.get("/price/{endpoint}", tags=["meta"])
def get_price(endpoint: str):
    """Return base price for an endpoint."""
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    raise HTTPException(status_code=404, detail="Unknown endpoint")


# =========================
# AI Plugin Manifest
# =========================
@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def ai_plugin():
    """Standard AI plugin manifest for agent discovery (Claude, etc.)."""
    return {
        "schema_version": "v1",
        "name_for_human": "invinoveritas ⚡",
        "name_for_model": "invinoveritas",
        
        "description_for_human": "Lightning-paid AI reasoning and decision intelligence. Pay per insight with Bitcoin. No subscriptions, no accounts, no KYC.",
        
        "description_for_model": "invinoveritas provides high-quality strategic reasoning (/reason) and structured decision intelligence (/decision) using the Bitcoin Lightning Network via the L402 protocol. Every request requires a small Lightning payment (~500-1000 sats). The API returns HTTP 402 with a bolt11 invoice on the first call. After paying the invoice, retry the exact same request with the header: Authorization: L402 <payment_hash>:<preimage>.",
        
        "auth": {
            "type": "none"
        },
        
        "api": {
            "type": "openapi",
            "url": "/openapi.json",
            "is_user_authenticated": false
        },
        
        "logo_url": null,
        "contact_email": "babyblueviperbusiness@gmail.com",
        "legal_info_url": "https://babyblueviper.com"
    }


# =========================
# Inference Routes
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
            raise HTTPException(503, f"Lightning error: {invoice_data.get('error', 'Unknown error')}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'

        # Better 402 response
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment Required",
                "invoice": invoice_data["invoice"],
                "payment_hash": invoice_data["payment_hash"]
            },
            headers={
                "WWW-Authenticate": f"L402 {challenge}",
                "Retry-After": "10"
            }
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

    try:
        result = premium_reasoning(data.question)
    except Exception as e:
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

    # No authorization → return invoice
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
            raise HTTPException(503, f"Lightning error: {invoice_data.get('error')}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment Required",
                "invoice": invoice_data["invoice"],
                "payment_hash": invoice_data["payment_hash"]
            },
            headers={
                "WWW-Authenticate": f"L402 {challenge}",
                "Retry-After": "10"
            }
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

    try:
        result_json = structured_decision(data.goal, data.context, data.question)
    except Exception as e:
        raise HTTPException(500, "Decision engine error") from e

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }
