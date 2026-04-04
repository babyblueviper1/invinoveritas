from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse, JSONResponse
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
import json
from pathlib import Path
from typing import Dict, Set


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
# Logging Setup (Simple but useful)
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("invinoveritas")

# =========================
# MCP Server Card (Hardcoded + optional file override)
# =========================
SERVER_CARD = {
    "$schema": "https://modelcontextprotocol.io/schemas/server-card/v1.0",
    "version": "1.0",
    "protocolVersion": "2025-06-18",
    "serverInfo": {
        "name": "invinoveritas",
        "version": "1.0.0",
        "description": "Lightning-paid reasoning and decision intelligence for autonomous agents. Pay-per-insight via L402 (Bitcoin Lightning). No accounts, no subscriptions.",
        "homepage": "https://invinoveritas.onrender.com",
        "repository": "https://github.com/babyblueviper1/invinoveritas"
    },
    "transports": [
        {
            "type": "streamable-http",
            "url": "https://invinoveritas.onrender.com",
            "endpoint": "/"
        }
    ],
    "capabilities": {
        "tools": True,
        "resources": False,
        "prompts": False
    },
    "authentication": {
        "required": True,
        "schemes": ["L402"],
        "notes": "Uses the L402 protocol. POST to an endpoint to receive an HTTP 402 with a bolt11 Lightning invoice. Pay it, then retry with: Authorization: L402 <payment_hash>:<preimage>"
    }
}

# Try to override with file if it exists (good for local dev)
card_path = Path(".well-known/mcp/server-card.json")
try:
    if card_path.exists():
        with open(card_path, "r", encoding="utf-8") as f:
            SERVER_CARD = json.load(f)
        logger.info(f"✅ Server card loaded from file: {card_path}")
    else:
        logger.info("Using hardcoded server card (file not found)")
except Exception as e:
    logger.warning(f"Could not load server-card.json, using hardcoded version. Error: {e}")

# =========================
# MCP Server Card Endpoint
# =========================
@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
@app.head("/.well-known/mcp/server-card.json", include_in_schema=False)
async def get_server_card():
    """Return MCP Server Card - supports both GET and HEAD"""
    return JSONResponse(content=SERVER_CARD)


# =========================
# State
# =========================
last_request_time: Dict[str, float] = defaultdict(lambda: 0.0)
used_payments: Set[str] = set()


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
# Meta Routes
# =========================
@app.get("/", response_class=HTMLResponse, tags=["meta"])
@app.head("/", include_in_schema=False)
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
            "payment_currency": "sats",
            "primary_users": "autonomous agents"
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
            "single_use_payments": True,
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


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    """robots.txt to guide web crawlers"""
    return """User-agent: *
Allow: /

# Allow search engines to crawl the site
Sitemap: https://invinoveritas.onrender.com/sitemap.xml
"""


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Basic sitemap for better SEO and discoverability"""
    sitemap_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://invinoveritas.onrender.com/</loc>
        <lastmod>2026-04-01</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/docs</loc>
        <lastmod>2026-04-01</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/health</loc>
        <lastmod>2026-04-01</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.6</priority>
    </url>
</urlset>"""
    return Response(content=sitemap_content, media_type="application/xml")
    
@app.get("/tool", tags=["meta"])
def tool_definition():
    """Tool definition for agent discovery."""
    return {
        "name": "invinoveritas",
        "type": "lightning_paid_ai",
        "description": "Lightning-paid strategic reasoning and structured decision intelligence optimized for autonomous agents",
        "payment_protocol": "L402",
        "endpoints": {
            "reason": {"path": "/reason", "base_price_sats": REASONING_PRICE_SATS},
            "decision": {"path": "/decision", "base_price_sats": DECISION_PRICE_SATS}
        },
        "agent_support": {
            "mcp_compatible": True,
            "autonomous": True,
            "single_use_payments": True
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

@app.get('/llms.txt')
def llms():
    return FileResponse('llms.txt', media_type='text/plain')


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
        
        "description_for_model": "invinoveritas provides high-quality strategic reasoning (/reason) and structured decision intelligence (/decision) using the Bitcoin Lightning Network via the L402 protocol. Every request requires a small Lightning payment (~500-1000 sats). The API returns HTTP 402 with a bolt11 invoice on the first call. After paying the invoice, retry the exact same request with the header: Authorization: L402 <payment_hash>:<preimage>. Optimized for autonomous agents.",
        
        "auth": {
            "type": "none"
        },
        
        "api": {
            "type": "openapi",
            "url": "/openapi.json",
            "is_user_authenticated": False
        },
        
        "logo_url": None,
        "contact_email": "babyblueviperbusiness@gmail.com",
        "legal_info_url": "https://babyblueviper.com"
    }


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
