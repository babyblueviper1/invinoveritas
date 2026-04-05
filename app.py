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
# FastAPI App (create FIRST)
# =========================
app = FastAPI(
    title="invinoveritas",
    version="0.1.0",
    description="Lightning-Paid AI Reasoning & Decision Intelligence using the L402 protocol.",
    contact={
        "name": "invinoveritas",
        "email": "babyblueviperbusiness@gmail.com"
    },
    license_info={"name": "Apache 2.0"},
)

# Disable trailing slash redirects
app.router.redirect_slashes = False



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
    """Clean & complete MCP handler with full L402 payment flow"""
    if len(used_payments) > 500:
        used_payments.clear()
        logger.info("✅ Cleaned used_payments set (prevent memory growth)")
    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
    method = body.get("method")
    rpc_id = body.get("id")
    auth = request.headers.get("Authorization")
    caller = detect_caller(request)

    # ==================== INITIALIZE ====================
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

    # ==================== LIST TOOLS ====================
    elif method == "listTools":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {"tools": list(TOOLS.values())}
        }

    # ==================== CALL TOOL ====================
    elif method == "callTool":
        tool_name = body.get("params", {}).get("name")
        args = body.get("params", {}).get("arguments", {})

        # ------------------- REASON TOOL -------------------
        if tool_name == "reason":
            question = args.get("question", "")
            if not question:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing question"}}

            price = calculate_price("reason", question, caller)

            # No payment → issue invoice
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

            # Payment provided → verify and execute
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

            if not auth or not auth.startswith("L402 "):
                invoice_data = create_invoice(price, memo=f"invinoveritas decision - {caller}")
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

            # Payment verification + execution
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

        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Tool not found"}}

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
        "version": "0.2.0",
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
        "schemes": ["L402"],
        "description": "Every tool call requires a one-time Lightning payment via L402. First call returns 402 with invoice. Pay it, then retry with header: Authorization: L402 <payment_hash>:<preimage>"
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

# Try to override with external file (useful for local development)
card_path = Path(".well-known/mcp/server-card.json")
if card_path.exists():
    try:
        with open(card_path, "r", encoding="utf-8") as f:
            SERVER_CARD = json.load(f)
        logger.info(f"✅ Loaded server-card.json from {card_path}")
    except Exception as e:
        logger.warning(f"Could not load server-card.json (invalid JSON). Using hardcoded version. Error: {e}")
else:
    logger.info("Using hardcoded SERVER_CARD (file not found)")

# =========================
# Server Card Endpoint
# =========================
@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
@app.head("/.well-known/mcp/server-card.json", include_in_schema=False)
async def get_server_card():
    """Return MCP Server Card"""
    return JSONResponse(content=SERVER_CARD)

# =========================
# State
# =========================
last_request_time: Dict[str, float] = defaultdict(lambda: 0.0)
used_payments: Set[str] = set()

# =========================
# Helpers (unchanged)
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
        "description": "invinoveritas uses the L402 protocol for atomic Lightning payments. "
                       "The payment flow is a simple two-step challenge-response.",
        
        "steps": [
            {
                "step": 1,
                "title": "Make your first request",
                "action": "Send a POST request to /reason, /decision, or /mcp",
                "response": "Server returns HTTP 402 Payment Required with a Lightning invoice"
            },
            {
                "step": 2,
                "title": "Pay the invoice",
                "action": "Pay the bolt11 invoice using any Lightning wallet or tool",
                "options": {
                    "recommended_wallets": ["Phoenix", "Breez", "Alby", "Wallet of Satoshi", "Muun"],
                    "node_cli": "lncli payinvoice <bolt11_invoice>",
                    "agent_friendly": "lnget (Lightning Labs) — https://github.com/lightninglabs/lightning-agent-tools",
                    "sdk": "invinoveritas Python SDK (handles the full flow automatically)"
                },
                "result": "You receive a payment_hash and preimage"
            },
            {
                "step": 3,
                "title": "Retry with payment proof",
                "action": "Repeat the exact same request with the Authorization header",
                "header": "Authorization: L402 <payment_hash>:<preimage>",
                "result": "Server verifies the payment and returns your result"
            }
        ],

        "for_autonomous_agents": {
            "easiest_path": "Use the MCP endpoint at /mcp — payment handling is built-in",
            "recommended_tool": "lnget by Lightning Labs (automatic L402 negotiation)",
            "python_sdk": "AsyncInvinoClient handles PaymentRequired → pay → retry automatically",
            "note": "Single-use payments with replay protection"
        },

        "pricing": {
            "reason": "~500 sats base",
            "decide": "~1000 sats base",
            "note": "Final price may vary slightly based on input length and complexity"
        },

        "links": {
            "health": "/health",
            "prices": "/prices",
            "sdk": "https://pypi.org/project/invinoveritas/",
            "github": "https://github.com/babyblueviper1/invinoveritas",
            "mcp_endpoint": "/mcp"
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
        "version": "0.1.0",
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
                "supports": ["initialize", "listTools", "callTool"],
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
            "l402_payment": True
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
        "description": "Lightning-paid strategic reasoning and structured decision intelligence optimized for autonomous agents via MCP and L402",
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
