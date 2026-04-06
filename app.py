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
    NODE_URL,
)
import os
import time
import logging
from collections import defaultdict
import json
from pathlib import Path
from typing import Dict, Set, Optional
import httpx

# =========================
# FastAPI App
# =========================
app = FastAPI(
    title="invinoveritas",
    version="0.4.0",
    description="Lightning-Paid AI Reasoning & Decision Intelligence (L402 + Credit System)",
    contact={
        "name": "invinoveritas",
        "email": "babyblueviperbusiness@gmail.com"
    },
    license_info={"name": "Apache 2.0"},
)

app.router.redirect_slashes = False

# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("invinoveritas")

# State for old L402
used_payments: Set[str] = set()
last_request_time: Dict[str, float] = defaultdict(lambda: 0.0)

# =========================
# Helpers
# =========================
def detect_caller(request: Request) -> dict:
    ua = request.headers.get("user-agent", "").lower()
    caller_type = "agent" if any(x in ua for x in ["python", "curl", "node", "httpclient", "invinoveritas", "claude", "cursor"]) else "browser"
    client_ip = request.client.host  # capture source IP
    return {"caller_type": caller_type, "ip": client_ip}

def get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
    
def calculate_price(endpoint: str, text: str, caller: str) -> int:
    base = REASONING_PRICE_SATS if endpoint == "reason" else DECISION_PRICE_SATS
    length_bonus = len(text) // 100
    multiplier = AGENT_PRICE_MULTIPLIER if caller == "agent" and ENABLE_AGENT_MULTIPLIER else 1.0
    price = int((base + length_bonus) * multiplier)
    return max(price, MIN_PRICE_SATS)

async def verify_credit(api_key: str, tool: str, price_sats: int):
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{NODE_URL}/accounts/verify",
                json={
                    "api_key": api_key,
                    "tool": tool,
                    "price_sats": price_sats
                }
            )

            # 🔥 ADD THIS
            print("VERIFY STATUS:", resp.status_code)
            print("VERIFY BODY:", resp.text)

            if resp.status_code == 200:
                return resp.json()

            elif resp.status_code == 402:
                raise HTTPException(402, detail=resp.json().get("detail", "Insufficient balance"))

            else:
                # 🔥 RETURN REAL ERROR
                raise HTTPException(resp.status_code, detail=resp.text)

    except httpx.RequestError as e:
        logger.error(f"Bridge connection error: {e}")
        raise HTTPException(503, "Payment system temporarily unavailable")
        
# =========================
# New Credit System Endpoints
# =========================
@app.post("/register", tags=["credit"])
async def register_account(label: Optional[str] = None):
    """Create new account with 3 free calls"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"label": label} if label else {}
            resp = await client.post(f"{NODE_URL}/accounts/register", json=payload)
            return resp.json()
    except Exception as e:
        raise HTTPException(503, f"Registration service unavailable: {str(e)}")

@app.post("/topup", tags=["credit"])
async def topup_account(data: dict):
    """Request top-up invoice for your account"""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{NODE_URL}/accounts/topup", json=data)
            return resp.json()
    except Exception as e:
        raise HTTPException(503, f"Top-up service unavailable: {str(e)}")

@app.get("/balance", tags=["credit"])
async def get_balance(api_key: str):
    """Check your balance and free calls"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{NODE_URL}/accounts/balance?api_key={api_key}")
            return resp.json()
    except Exception as e:
        raise HTTPException(503, f"Balance service unavailable: {str(e)}")

# =========================
# Updated Inference Routes (Credit + L402)
# =========================
class ReasoningRequest(BaseModel):
    question: str

@app.post("/reason", response_model=dict, tags=["inference"])
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")
    question = data.question.strip()
    if not question:
        raise HTTPException(400, "question is required")
    price = calculate_price("reason", question, caller)

    # NEW: Bearer Token Credit System
    if auth and auth.startswith("Bearer "):
        api_key = auth.split(" ", 1)[1].strip()
        try:
            credit_info = await verify_credit(api_key, "reason", price)
            used_free = credit_info.get("used_free_call", False)
            logger.info(f"Credit used | reason | api_key={api_key[:12]}... | free={used_free}")
        except HTTPException as e:
            if e.status_code == 402:
                raise HTTPException(
                    402,
                    detail={
                        "message": "Insufficient balance or free calls used",
                        "balance": "Check /balance",
                        "topup": "POST /topup with your api_key"
                    }
                )
            raise

        result = premium_reasoning(question)
        return {"status": "success", "type": "premium_reasoning", "answer": result}

    # OLD L402 Flow (unchanged)
    if not auth or not auth.startswith("L402 "):
        invoice_data = create_invoice(price, memo=f"invinoveritas reason - {caller}")
        if "error" in invoice_data:
            raise HTTPException(503, "Lightning invoice creation failed")
        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment Required",
                "payment_hash": invoice_data["payment_hash"],
                "invoice": invoice_data["invoice"],
                "amount_sats": price
            },
            headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "15"}
        )

    # L402 verification
    try:
        _, creds = auth.split(" ", 1)
        payment_hash, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")
    if payment_hash in used_payments:
        raise HTTPException(403, "Payment already used")
    if not check_payment(payment_hash):
        raise HTTPException(403, "Payment not settled yet")
    if not verify_preimage(payment_hash, preimage):
        raise HTTPException(403, "Invalid preimage")
    used_payments.add(payment_hash)

    result = premium_reasoning(question)
    return {"status": "success", "type": "premium_reasoning", "answer": result}

class DecisionRequest(BaseModel):
    goal: str
    context: str = ""
    question: str

@app.post("/decision", response_model=dict, tags=["inference"])
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")
    text = f"{data.goal} {data.context} {data.question}"
    price = calculate_price("decision", text, caller)

    # NEW: Bearer Token Credit System
    if auth and auth.startswith("Bearer "):
        api_key = auth.split(" ", 1)[1].strip()
        try:
            await verify_credit(api_key, "decide", price)
        except HTTPException as e:
            if e.status_code == 402:
                raise HTTPException(402, detail={"message": "Insufficient balance", "action": "Use /topup"})
            raise

        result = structured_decision(data.goal, data.context, data.question)
        return {"status": "success", "type": "decision_intelligence", "result": result}

    # OLD L402 Flow
    if not auth or not auth.startswith("L402 "):
        now = time.time()
        rate_key = f"{get_client_ip(request)}:decision"
        if now - last_request_time[rate_key] < RATE_LIMIT_SECONDS:
            raise HTTPException(429, f"Rate limit: wait {RATE_LIMIT_SECONDS}s")
        last_request_time[rate_key] = now

        invoice_data = create_invoice(price, memo=f"invinoveritas decision - {caller}")
        if "error" in invoice_data:
            raise HTTPException(503, f"Lightning error: {invoice_data.get('error')}")
        challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
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

    # L402 verification
    try:
        _, creds = auth.split(" ", 1)
        payment_hash, preimage = creds.split(":", 1)
    except Exception:
        raise HTTPException(401, "Invalid L402 format")
    if payment_hash in used_payments:
        raise HTTPException(403, "This invoice has already been used")
    if not check_payment(payment_hash):
        raise HTTPException(403, "Payment not settled yet")
    if not verify_preimage(payment_hash, preimage):
        raise HTTPException(403, "Invalid payment proof")
    used_payments.add(payment_hash)

    result_json = structured_decision(data.goal, data.context, data.question)
    return {"status": "success", "type": "decision_intelligence", "result": result_json}



@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse("favicon.ico", media_type="image/x-icon")

# =========================
# Simple MCP Handler (comes AFTER app is created)
# =========================
TOOLS = {
    "reason": {
        "name": "reason",
        "description": "Premium strategic reasoning using Lightning payment (L402).",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "The question to reason about"}},
            "required": ["question"]
        }
    },
    "decide": {
        "name": "decide",
        "description": "Structured decision intelligence using Lightning payment (L402).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string"},
                "context": {"type": "string"},
                "question": {"type": "string"}
            },
            "required": ["goal", "question"]
        }
    }
}


@app.get("/mcp", tags=["meta"])
@app.get("/mcp/", include_in_schema=False)
@app.head("/mcp", include_in_schema=False)
@app.head("/mcp/", include_in_schema=False)
async def mcp_info():
    """MCP endpoint info for crawlers and browsers."""
    return {
        "name": "invinoveritas",
        "description": "Lightning-paid reasoning and decision intelligence via MCP",
        "mcp_endpoint": "POST /mcp",
        "protocol": "MCP + L402",
        "tools": ["reason", "decide"],
        "pricing": {
            "reason": f"{REASONING_PRICE_SATS} sats",
            "decide": f"{DECISION_PRICE_SATS} sats",
        },
        "server_card": "/.well-known/mcp/server-card.json",
    }


@app.post("/mcp")
@app.post("/mcp/")
async def mcp_handler(request: Request):
    """Updated MCP handler — supports BOTH L402 and new Bearer credit system"""
    if len(used_payments) > 500:
        used_payments.clear()

    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}

    method = body.get("method")
    rpc_id = body.get("id")
    info = detect_caller(request)
    auth = request.headers.get("authorization")
    has_bearer = auth is not None and auth.startswith("Bearer")

    logger.info(f"MCP | id={rpc_id} | method={method} | caller={info['caller_type']} | ip={info['ip']} | has_bearer={has_bearer}")

    # Initialize, listTools, ping — unchanged
    if method == "initialize":
        return {
            "jsonrpc": "2.0", 
            "id": rpc_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "invinoveritas", "version": "1.0.0"}
            }
        }

    elif method in ["listTools", "tools/list"]:
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": list(TOOLS.values())}}

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    # ==================== CALL TOOL ====================
    elif method == "callTool":
        tool_name = body.get("params", {}).get("name")
        args = body.get("params", {}).get("arguments", {})
        logger.info(f"MCP callTool | tool={tool_name} | has_auth={bool(auth)} | caller={caller}")

        # ------------------- REASON TOOL -------------------
        if tool_name == "reason":
            question = args.get("question", "")
            if not question:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing question"}}

            price = calculate_price("reason", question, caller)

            # NEW: Support Bearer token (credit system)
            if auth and auth.startswith("Bearer "):
                api_key = auth.split(" ", 1)[1].strip()
                try:
                    await verify_credit(api_key, "reason", price)
                except HTTPException as e:
                    if e.status_code == 402:
                        return {"jsonrpc": "2.0", "id": rpc_id, "error": {
                            "code": 402,
                            "message": "Payment Required",
                            "data": {"message": "Insufficient balance. Top up via /topup"}
                        }}
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 401, "message": "Invalid API key"}}

                # Credit OK → run tool
                try:
                    result = premium_reasoning(question)
                    return {
                        "jsonrpc": "2.0",
                        "id": rpc_id,
                        "result": {"content": [{"type": "text", "text": result}]}
                    }
                except Exception as e:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Internal error"}}

            # No payment provided → return 402 with invoice
            if not auth or not auth.startswith("L402 "):
                invoice_data = create_invoice(price, memo=f"invinoveritas reason - {caller}")
                if "error" in invoice_data:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Failed to create invoice"}}

                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": 402,
                        "message": "Payment Required",
                        "data": {
                            "payment_hash": invoice_data["payment_hash"],
                            "invoice": invoice_data["invoice"],
                            "amount_sats": price
                        }
                    }
                }

            # Payment provided → verify and execute (L402)
            try:
                _, creds = auth.split(" ", 1)
                payment_hash, preimage = creds.split(":", 1)
            except Exception:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Invalid L402 format"}}

            if payment_hash in used_payments:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment already used"}}

            if not check_payment(payment_hash):
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment not settled yet"}}

            if not verify_preimage(payment_hash, preimage):
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Invalid preimage"}}

            used_payments.add(payment_hash)

            try:
                result = premium_reasoning(question)
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {"content": [{"type": "text", "text": result}]}
                }
            except Exception as e:
                logger.error(f"Reasoning error: {e}")
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Internal error"}}

        # ------------------- DECIDE TOOL -------------------
        elif tool_name == "decide":
            goal = args.get("goal", "")
            context = args.get("context", "")
            question = args.get("question", "")
            if not goal or not question:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing goal or question"}}

            text = f"{goal} {context} {question}"
            price = calculate_price("decision", text, caller)

            if auth and auth.startswith("Bearer "):
                api_key = auth.split(" ", 1)[1].strip()
                try:
                    await verify_credit(api_key, "decide", price)
                except HTTPException as e:
                    if e.status_code == 402:
                        return {"jsonrpc": "2.0", "id": rpc_id, "error": {
                            "code": 402,
                            "message": "Payment Required",
                            "data": {"message": "Insufficient balance"}
                        }}
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 401, "message": "Invalid API key"}}

                result = structured_decision(goal, context, question)
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                }

            # No payment provided → return 402 with invoice
            if not auth or not auth.startswith("L402 "):
                invoice_data = create_invoice(price, memo=f"invinoveritas decide - {caller}")
                if "error" in invoice_data:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Failed to create invoice"}}

                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": 402,
                        "message": "Payment Required",
                        "data": {
                            "payment_hash": invoice_data["payment_hash"],
                            "invoice": invoice_data["invoice"],
                            "amount_sats": price
                        }
                    }
                }

            # Payment verification + execution (L402)
            try:
                _, creds = auth.split(" ", 1)
                payment_hash, preimage = creds.split(":", 1)
            except Exception:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Invalid L402 format"}}

            if payment_hash in used_payments:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment already used"}}

            if not check_payment(payment_hash):
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment not settled yet"}}

            if not verify_preimage(payment_hash, preimage):
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Invalid preimage"}}

            used_payments.add(payment_hash)

            try:
                result = structured_decision(goal, context, question)
                return {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                }
            except Exception as e:
                logger.error(f"Decision error: {e}")
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Internal error"}}

        # Tool not found
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Tool not found"}}

    # Method not found
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}
    
# =========================
# Logging Setup
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("invinoveritas")

# =========================
# MCP Server Card (Hardcoded fallback)
# =========================
SERVER_CARD = {
    "$schema": "https://modelcontextprotocol.io/schemas/server-card/v1.0",
    "version": "1.0",
    "protocolVersion": "2025-06-18",
    "serverInfo": {
        "name": "invinoveritas",
        "version": "0.3.1",
        "description": "Lightning-paid AI reasoning and decision intelligence for autonomous agents using Bitcoin Lightning (L402)",
        "homepage": "https://invinoveritas.onrender.com",
        "repository": "https://github.com/babyblueviper1/invinoveritas",
        "author": "invinoveritas team"
    },
    "transports": [
        {
            "type": "streamable-http",
            "url": "https://invinoveritas.onrender.com",
            "endpoint": "/mcp"
        }
    ],
    "capabilities": {
        "tools": True,
        "resources": False,
        "prompts": False,
        "sampling": False
    },
    "tools": [
        {
            "name": "reason",
            "description": "Get deep strategic reasoning and analysis. Requires Lightning payment via L402.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to reason about"
                    }
                },
                "required": ["question"]
            }
        },
        {
            "name": "decide",
            "description": "Get structured decision intelligence with confidence score and risk assessment. Requires Lightning payment.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "Your overall goal"
                    },
                    "question": {
                        "type": "string",
                        "description": "The specific decision question"
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional background context"
                    }
                },
                "required": ["goal", "question"]
            }
        }
    ],
    "authentication": {
        "required": True,
        "schemes": ["L402", "Bearer"],
        "description": "Use Authorization: Bearer ivv_... (recommended for agents) or L402 <hash>:<preimage>"
    },
    "pricing": {
        "currency": "sats",
        "reason_base": REASONING_PRICE_SATS,
        "decide_base": DECISION_PRICE_SATS,
        "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
        "minimum": MIN_PRICE_SATS,
        "note": "Final price may vary slightly based on input length and complexity."
    },
    "documentation": {
        "guide": "/guide",
        "prices": "/prices",
        "sdk": "https://pypi.org/project/invinoveritas/",
        "github": "https://github.com/babyblueviper1/invinoveritas"
    }
}

# Try to override with external file
card_path = Path(".well-known/mcp/server-card.json")
if card_path.exists():
    try:
        with open(card_path, "r", encoding="utf-8") as f:
            SERVER_CARD = json.load(f)
        logger.info(f"✅ Loaded server-card.json from {card_path}")
    except json.JSONDecodeError as e:
        logger.error(f"❌ Invalid JSON in server-card.json: {e}")
        logger.warning("Using hardcoded SERVER_CARD instead.")
    except Exception as e:
        logger.warning(f"Could not load server-card.json. Using hardcoded version. Error: {e}")
else:
    logger.info("server-card.json not found — using hardcoded version.")

# =========================
# Server Card Endpoint
# =========================
@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
@app.head("/.well-known/mcp/server-card.json", include_in_schema=False)
async def get_server_card():
    """Return MCP Server Card"""
    return JSONResponse(content=SERVER_CARD)

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
    """Simple landing page."""
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡</h1>"


@app.get("/guide", tags=["meta"])
def payment_guide():
    """Step-by-step payment guide for developers and autonomous agents using L402."""
    return {
        "title": "How to Pay for invinoveritas (L402 Protocol)",
        "description": "invinoveritas uses the L402 protocol for atomic Lightning micropayments. "
                       "Payment is a simple two-step challenge-response process.",
        
        "steps": [
            {
                "step": 1,
                "title": "Make your first request",
                "action": "POST to /reason, /decision, or /mcp",
                "response": "Server returns HTTP 402 Payment Required + Lightning invoice"
            },
            {
                "step": 2,
                "title": "Pay the invoice",
                "action": "Pay the bolt11 invoice with any Lightning wallet or tool",
                "options": {
                    "recommended_wallets": ["Phoenix", "Breez", "Alby", "Wallet of Satoshi", "Muun", "Zeus"],
                    "cli": "lncli payinvoice <bolt11_invoice>",
                    "agent_tools": {
                        "lnget": "Lightning Labs — automatic L402 handling via LND",
                        "nwc": "NWCProvider — autonomous payments via nostr+walletconnect:// URI (Alby, Zeus, Mutiny)"
                    },
                    "python_sdk": "invinoveritas SDK (recommended)"
                },
                "result": "You receive payment_hash and preimage"
            },
            {
                "step": 3,
                "title": "Retry with proof",
                "action": "Repeat the exact same request with Authorization header",
                "header": "Authorization: L402 <payment_hash>:<preimage>",
                "result": "Server verifies payment and returns the result"
            }
        ],

        "for_autonomous_agents": {
            "easiest_option": "Use the MCP endpoint (/mcp) — payment flow is built-in",
            "recommended_agent_tool": "lnget by Lightning Labs",
            "python_options": [
                "AsyncInvinoClient (simple manual flow)",
                "InvinoCallbackHandler + LNDProvider (automatic via LND node)",
                "InvinoCallbackHandler + NWCProvider (automatic via any NIP-47 wallet — no node required)",
                "InvinoCallbackHandler + CustomProvider (bring your own pay function)"
            ],
            "note": "Single-use payments with full replay protection"
        },

        "advanced_integrations": {
            "langchain": "Use InvinoCallbackHandler for automatic payment + retry in LangChain agents",
            "providers": "LNDProvider (local node), NWCProvider (Alby/Zeus/Mutiny via NWC), or CustomProvider (your own pay function)",
            "l402_client": "L402Client class handles 402 → pay → retry transparently"
        },

        "pricing": {
            "reason": "~500 sats base",
            "decide": "~1000 sats base",
            "agent_multiplier": "1.2x when used from autonomous agents",
            "note": "Final price may vary slightly based on input length"
        },

        "links": {
            "health": "/health",
            "prices": "/prices",
            "guide": "/guide",
            "mcp": "/mcp",
            "sdk": "https://pypi.org/project/invinoveritas/",
            "github": "https://github.com/babyblueviper1/invinoveritas"
        }
    }

@app.get("/prices", tags=["meta"])
def get_all_prices():
    """Return detailed current pricing for all tools — optimized for agents and frontends."""
    return {
        "currency": "sats",
        "dynamic_pricing": ENABLE_AGENT_MULTIPLIER,
        "agent_multiplier": AGENT_PRICE_MULTIPLIER,
        "minimum_price_sats": MIN_PRICE_SATS,
        "prices": {
            "reason": {
                "base": REASONING_PRICE_SATS,
                "agent": int(REASONING_PRICE_SATS * AGENT_PRICE_MULTIPLIER),
                "description": "Premium strategic reasoning",
                "note": "Deep analysis and long-context reasoning"
            },
            "decide": {
                "base": DECISION_PRICE_SATS,
                "agent": int(DECISION_PRICE_SATS * AGENT_PRICE_MULTIPLIER),
                "description": "Structured decision intelligence",
                "note": "Goal-oriented recommendations with confidence scoring"
            }
        },
        "note": "Final price may vary slightly based on input length and complexity. "
                "Dynamic pricing and agent multiplier apply during high load or agent usage.",
        "last_updated": int(time.time())
    }


@app.get("/health", tags=["meta"])
def health():
    """Health check with rich metadata for monitoring and autonomous agents."""
    return {
        "status": "ok",
        "service": "invinoveritas",
        "version": "0.3.1",
        "timestamp": int(time.time()),

        "api": {
            "title": "Lightning-Paid AI Reasoning & Decision Intelligence",
            "protocol": "L402",
            "payment_currency": "sats",
            "primary_users": "autonomous agents",
            "mcp_support": True
        },

        "endpoints": {
            "reason": {
                "path": "/reason",
                "method": "POST",
                "description": "Premium strategic reasoning",
                "base_price_sats": REASONING_PRICE_SATS,
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
            },
            "decide": {
                "path": "/decision",
                "method": "POST",
                "description": "Structured decision intelligence for agents",
                "base_price_sats": DECISION_PRICE_SATS,
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
            },
            "mcp": {
                "path": "/mcp",
                "method": "POST",
                "description": "Model Context Protocol (MCP) endpoint",
                "supports": ["initialize", "tools/list", "listTools", "callTool", "ping"],
                "payment_handling": "built-in L402"
            }
        },

        "pricing": {
            "currency": "sats",
            "dynamic_pricing": ENABLE_AGENT_MULTIPLIER,
            "agent_multiplier": AGENT_PRICE_MULTIPLIER,
            "minimum_price_sats": MIN_PRICE_SATS,
            "full_pricing_endpoint": "/prices"          # Consistent link
        },

        "features": {
            "rate_limiting": True,
            "replay_protection": True,
            "single_use_payments": True,
            "no_accounts": True,
            "no_kyc": True,
            "agent_friendly": True,
            "mcp_native": True,
            "l402_payment": True,
            "sdk": {
                "pypi": "https://pypi.org/project/invinoveritas/",
                "providers": ["LNDProvider", "NWCProvider", "CustomProvider"],
                "langchain": True,
                "autogen": True
            },
        },

        "links": {
            "docs": "/docs",
            "redoc": "/redoc",
            "mcp_endpoint": "/mcp",
            "mcp_server_card": "/.well-known/mcp/server-card.json",
            "ai_plugin": "/.well-known/ai-plugin.json",
            "tool_definition": "/tool",
            "prices": "/prices",           # Updated
            "guide": "/guide",
            "health": "/health"
        }
    }


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    """robots.txt to guide web crawlers"""
    return """User-agent: *
Allow: /

Sitemap: https://invinoveritas.onrender.com/sitemap.xml
"""


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Basic sitemap for better SEO and discoverability"""
    sitemap_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>https://invinoveritas.onrender.com/</loc>
        <lastmod>2026-04-05</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/mcp</loc>
        <lastmod>2026-04-05</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/docs</loc>
        <lastmod>2026-04-05</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/health</loc>
        <lastmod>2026-04-05</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.6</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/prices</loc>
        <lastmod>2026-04-05</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.7</priority>
    </url>
</urlset>"""
    return Response(content=sitemap_content, media_type="application/xml")


@app.get("/tool", tags=["meta"])
def tool_definition():
    """Tool definition for agent discovery (MCP / LangChain / etc.)."""
    return {
        "name": "invinoveritas",
        "type": "lightning_paid_ai",
        "description": "Lightning-paid strategic reasoning and decision intelligence optimized for autonomous agents via MCP and L402",
        "payment_protocol": "L402",
        "mcp_endpoint": "/mcp",
        "endpoints": {
            "reason": {"path": "/reason", "base_price_sats": REASONING_PRICE_SATS},
            "decide": {"path": "/decision", "base_price_sats": DECISION_PRICE_SATS}
        },
        "agent_support": {
            "mcp_compatible": True,
            "autonomous": True,
            "single_use_payments": True
        }
    }


# Better version for MCP compatibility (recommended to use this for /tool and also in your MCP handler)
@app.get("/tool/mcp", tags=["meta"])
def tool_definition_mcp():
    """MCP-compatible tool definitions."""
    return {
        "tools": [
            {
                "name": "reason",
                "description": "Get deep strategic reasoning and analysis. Requires Lightning payment via L402.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question to reason about"
                        }
                    },
                    "required": ["question"]
                }
            },
            {
                "name": "decide",
                "description": "Get structured decision intelligence with confidence score and risk assessment. Requires Lightning payment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "goal": {
                            "type": "string",
                            "description": "Your overall goal"
                        },
                        "question": {
                            "type": "string",
                            "description": "The specific decision question"
                        },
                        "context": {
                            "type": "string",
                            "description": "Optional background context"
                        }
                    },
                    "required": ["goal", "question"]
                }
            }
        ]
    }


@app.get("/price/{endpoint}", tags=["meta"])
def get_price(endpoint: str):
    """Return base price for a specific endpoint (kept for backward compatibility)."""
    if endpoint == "reason":
        return {"price_sats": REASONING_PRICE_SATS}
    elif endpoint == "decision":
        return {"price_sats": DECISION_PRICE_SATS}
    elif endpoint == "mcp":
        return {
            "price_sats": "Same as underlying tools (reason/decision)",
            "note": "Payment is handled per callTool request via L402"
        }
    raise HTTPException(status_code=404, detail="Unknown endpoint")


@app.get('/llms.txt')
def llms():
    """llms.txt for AI crawlers and large language models."""
    if os.path.exists("llms.txt"):
        return FileResponse('llms.txt', media_type='text/plain')
    return "invinoveritas - Lightning-paid AI reasoning and decision intelligence."


# =========================
# AI Plugin Manifest (Updated)
# =========================
@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def ai_plugin():
    """Standard AI plugin manifest for agent discovery (Claude, Cursor, etc.)."""
    return {
        "schema_version": "v1",
        "name_for_human": "invinoveritas ⚡",
        "name_for_model": "invinoveritas",
        
        "description_for_human": "Lightning-paid AI reasoning and decision intelligence. Pay per insight with Bitcoin Lightning. No subscriptions, no accounts, no KYC.",
        
        "description_for_model": (
            "invinoveritas provides high-quality strategic reasoning and structured decision intelligence "
            "using the Bitcoin Lightning Network via the L402 protocol. "
            "It supports both direct REST endpoints (/reason, /decision) and a native MCP (Model Context Protocol) endpoint at /mcp. "
            "Every tool call or request requires a small Lightning payment (~500-1400 sats depending on complexity). "
            "The API returns HTTP 402 with a bolt11 invoice on the first call. After paying the invoice, retry the exact same request "
            "with the header: Authorization: L402 <payment_hash>:<preimage>. "
            "Optimized for autonomous agents and MCP-compatible clients."
        ),
        
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
        "legal_info_url": "https://babyblueviper.com",
        
        "capabilities": {
            "mcp_support": True,
            "payment_protocol": "L402",
            "payment_currency": "sats"
        }
    }

