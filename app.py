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
        "version": "0.1.0",
        "timestamp": int(time.time()),

        "api": {
            "title": "Lightning-Paid AI Reasoning & Decision Intelligence",
            "protocol": "L402 (Lightning Network)",
            "payment_currency": "sats"
        },

        "endpoints": {
            "reason": {
                "path": "/reason",
                "method": "POST",
                "description": "Premium strategic reasoning",
                "base_price_sats": REASONING_PRICE_SATS,
                "input_schema": {"question": "string"}
            },
            "decision": {
                "path": "/decision",
                "method": "POST",
                "description": "Structured decision intelligence optimized for agents",
                "base_price_sats": DECISION_PRICE_SATS,
                "input_schema": {
                    "goal": "string",
                    "context": "string",
                    "question": "string"
                }
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
    return {
        "name": "invinoveritas",
        "type": "lightning_paid_reasoning",
        "description": "Lightning-paid reasoning and structured decision intelligence using the L402 protocol.",

        "endpoints": {
            "reason": {
                "path": "/reason",
                "method": "POST",
                "purpose": "High-quality strategic reasoning",
                "input": {"question": "string"},
                "output": {
                    "status": "success",
                    "type": "premium_reasoning",
                    "answer": "string"
                },
                "base_price_sats": REASONING_PRICE_SATS
            },

            "decision": {
                "path": "/decision",
                "method": "POST",
                "purpose": "Structured decision intelligence optimized for autonomous agents",
                "input": {
                    "goal": "string",
                    "context": "string",
                    "question": "string"
                },
                "output": {
                    "status": "success",
                    "type": "decision_intelligence",
                    "result": {
                        "decision": "string",
                        "confidence": "float",
                        "reasoning": "string",
                        "risk_level": "low | medium | high"
                    }
                },
                "base_price_sats": DECISION_PRICE_SATS
            }
        },

        "payment": {
            "protocol": "L402",
            "currency": "sats",
            "pricing_type": "pay_per_request",
            "no_accounts": True,
            "no_kyc": True
        },

        "agent_support": {
            "mcp_compatible": True,
            "autonomous_agents_supported": True
        }
    }


@app.get("/price/{endpoint}", tags=["meta"])
def get_price(endpoint: str):
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    raise HTTPException(status_code=404, detail="Unknown endpoint")


# =========================
# Inference Routes
# =========================
@app.post("/reason", tags=["inference"])
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
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "10"}
        )

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

    result = premium_reasoning(data.question)

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
            raise HTTPException(503, f"Lightning error: {invoice_data['error']}")

        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail="Payment Required",
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "10"}
        )

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

    result_json = structured_decision(data.goal, data.context, data.question)

    return {
        "status": "success",
        "type": "decision_intelligence",
        "result": result_json
    }

from fastapi.responses import FileResponse

@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def ai_plugin():
    return FileResponse(".well-known/ai-plugin.json", media_type="application/json")
