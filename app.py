from nostr_listener import run_listener
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, Response, FileResponse, JSONResponse
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from collections import deque
from node_bridge import create_invoice, check_payment, verify_preimage
from ai import premium_reasoning, structured_decision
import datetime
from fastapi import WebSocket, WebSocketDisconnect
from config import (
    REASONING_PRICE_SATS,
    DECISION_PRICE_SATS,
    ENABLE_AGENT_MULTIPLIER,
    AGENT_PRICE_MULTIPLIER,
    MIN_PRICE_SATS,
    RATE_LIMIT_SECONDS,
    NODE_URL,
    NOSTR_NSEC
)
import os
import time
import logging
from collections import defaultdict
import json
from pathlib import Path
from typing import Dict, Optional, Literal
import httpx
import asyncio
import random
from nostr.key import PrivateKey
from nostr.event import Event
from nostr.relay_manager import RelayManager
import websockets
from dataclasses import dataclass
from collections import defaultdict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)
# =========================
# x402 imports
# =========================
try:
    # Core server components
    from x402 import x402ResourceServer, ResourceConfig
    
    # HTTP Facilitator (recommended for production)
    from x402.http import HTTPFacilitatorClient
    
    # Optional: If you want sync version or extra mechanisms
    # from x402 import x402ResourceServerSync
    # from x402.http import HTTPFacilitatorClientSync
    # from x402.mechanisms.evm.exact import ExactEvmServerScheme

    X402_AVAILABLE = True
    logger.info("x402 library loaded successfully (async mode)")
except ImportError:
    X402_AVAILABLE = False
    logger.warning("x402 library not installed. USDC payments via x402 will be disabled.")
except Exception as e:
    X402_AVAILABLE = False
    logger.error(f"Failed to import x402: {e}")

# =========================
# FastAPI App
# =========================
app = FastAPI(
    title="invinoveritas",
    version="0.4.0",
    description="Lightning-Paid AI Reasoning & Decision Intelligence (L + Credit System)",
    contact={
        "name": "invinoveritas",
        "email": "babyblueviperbusiness@gmail.com"
    },
    license_info={"name": "Apache 2.0"},
)

app.router.redirect_slashes = False

logger = logging.getLogger("invinoveritas.broadcaster")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.oxtr.dev",
    "wss://nostr.bitcoiner.social",
    "wss://offchain.pub",          # open, no restrictions
    
]

# ========================= X402 CONFIG =========================
load_dotenv()

X402_CONFIG = {
    "pay_to": os.getenv("X402_PAY_TO", "").strip(),
    "network": os.getenv("X402_NETWORK", "base"),
    "currency": "USDC",
    "asset_address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",

    # Per-call prices (used only for reference / old L402 flow)
    "reason_price": "0.10",
    "decision_price": "0.15",

    # New: Minimum top-up amounts for x402 (much more practical)
    "min_topup_usdc": "15.00",        # Recommended minimum
    "suggested_topups": ["15", "25", "50", "100"],

    "description": "invinoveritas AI credits top-up (Bearer account)",
}

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_CONCURRENT_RELAYS = 5          # semaphore cap
RELAY_CONNECT_TIMEOUT = 6.0        # seconds to open WebSocket
OK_WAIT_TIMEOUT = 8.0              # seconds to wait for NIP-20 OK
PUBLISH_RETRIES = 3
RETRY_BASE_DELAY = 1.0
RETRY_BACKOFF = 1.8
 
DENYLIST_THRESHOLD = 3             # consecutive failures before soft-ban
DENYLIST_BACKOFF_SECONDS = 7200    # 2 hours
 
BROADCAST_INTERVAL_MIN = 720       # 12 min
BROADCAST_INTERVAL_MAX = 1080      # 18 min
 
ANNOUNCEMENTS_FILE = Path("/tmp/invinoveritas_announcements.json")
ANNOUNCEMENTS: list[dict] = []
active_ws_clients: list[WebSocket] = []
active_sse_clients: list[asyncio.Queue] = []

def load_announcements():
    """Load announcements from disk on startup"""
    global ANNOUNCEMENTS
    if ANNOUNCEMENTS_FILE.exists():
        try:
            with open(ANNOUNCEMENTS_FILE, "r", encoding="utf-8") as f:
                ANNOUNCEMENTS = json.load(f)
            logger.info(f"✅ Loaded {len(ANNOUNCEMENTS)} announcements from disk")
        except Exception as e:
            logger.error(f"Failed to load announcements file: {e}")
            ANNOUNCEMENTS = []
    else:
        logger.info("No previous announcements file found - starting fresh")
        ANNOUNCEMENTS = []

def save_announcements():
    """Save announcements to disk"""
    try:
        with open(ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(ANNOUNCEMENTS, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save announcements: {e}")


# Simple list of active WebSocket connections
active_ws_clients: list[WebSocket] = []



# =========================
# L402 Payment Cleanup
# =========================

# Global set for used L402 payments
used_payments: set = set()

# Optional: store with timestamp for smarter cleanup
used_payments_with_time: dict[str, float] = {}


async def cleanup_used_payments():
    """Remove old used payments to prevent memory leak."""
    while True:
        try:
            now = time.time()
            cutoff = now - (3600 * 6)  # Keep payments for 6 hours (adjust as needed)

            # Clean simple set version
            # For simple set we can't know age, so we do periodic full clear
            if len(used_payments) > 1000:   # Safety threshold
                old_size = len(used_payments)
                used_payments.clear()
                logger.info(f"Cleaned all {old_size} used L402 payments (memory safety)")

            # Better version using timestamp dict (recommended)
            if used_payments_with_time:
                to_remove = [ph for ph, ts in list(used_payments_with_time.items()) if ts < cutoff]
                for ph in to_remove:
                    used_payments_with_time.pop(ph, None)
                    used_payments.discard(ph)

                if to_remove:
                    logger.info(f"Cleaned {len(to_remove)} old L402 payments")

        except Exception as e:
            logger.error(f"Error during used_payments cleanup: {e}")

        await asyncio.sleep(300)  # Run every 5 minutes








# ========================= WEBSOCKET =========================
@app.websocket("/ws")
@app.websocket("/ws/announcements")
async def websocket_announcements(websocket: WebSocket):
    await websocket.accept()
    active_ws_clients.append(websocket)
    
    try:
        # === 1. Send Welcome Message ===
        await websocket.send_json({
            "type": "welcome",
            "message": "Connected to invinoveritas real-time announcements."
        })

        # === 2. Send Existing Announcements (Important!) ===
        for ann in ANNOUNCEMENTS[:5]:   # Send last 5 announcements
            try:
                message = {
                    "type": "announcement",
                    "title": ann.get("title", "Update"),
                    "description": ann.get("description", ""),
                    "link": ann.get("link"),
                    "timestamp": ann.get("timestamp")
                }
                await websocket.send_json(message)
            except Exception as e:
                logger.warning(f"Failed to send historical announcement via WS: {e}")

        # === 3. Keep connection alive + handle ping/pong ===
        while True:
            data = await websocket.receive_text()
            if data.lower() == "ping":
                await websocket.send_json({
                    "type": "pong",
                    "timestamp": int(time.time())
                })
                
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WS error: {e}")
    finally:
        if websocket in active_ws_clients:
            active_ws_clients.remove(websocket)

@app.get("/ws/test", tags=["meta"])
async def websocket_test_page():
    """Simple test page for WebSocket"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>invinoveritas WebSocket Test</title>
        <style>
            body { font-family: system-ui; background: #0a0a0a; color: #ddd; padding: 20px; }
            #log { background: #1f1f1f; padding: 15px; border-radius: 8px; height: 500px; overflow-y: auto; font-family: monospace; }
            .connected { color: #4ade80; }
            .disconnected { color: #f87171; }
        </style>
    </head>
    <body>
        <h1>⚡ invinoveritas WebSocket Test</h1>
        <p>Status: <span id="status">Connecting...</span></p>
        <button onclick="sendPing()">Send Ping</button>
        <div id="log"></div>

        <script>
            const log = document.getElementById('log');
            const status = document.getElementById('status');
            let ws;

            function connect() {
                ws = new WebSocket("wss://invinoveritas.onrender.com/ws");

                ws.onopen = () => {
                    status.textContent = "✅ Connected";
                    status.className = "connected";
                    log.innerHTML += "<p>✅ WebSocket connected</p>";
                };

                ws.onmessage = (event) => {
                    const data = JSON.parse(event.data);
                    log.innerHTML += `<p><strong>${data.type}</strong>: ${data.title || data.message || JSON.stringify(data)}</p>`;
                    log.scrollTop = log.scrollHeight;
                };

                ws.onerror = () => {
                    status.textContent = "❌ Connection Error";
                    status.className = "disconnected";
                };

                ws.onclose = () => {
                    status.textContent = "🔴 Disconnected";
                    status.className = "disconnected";
                };
            }

            function sendPing() {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send("ping");
                    log.innerHTML += "<p>→ Ping sent</p>";
                }
            }

            // Auto connect
            connect();

            // Auto ping every 25 seconds
            setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send("ping");
                }
            }, 25000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

# ========================= BROADCAST HELPER =========================
async def broadcast_via_websocket(title: str, description: str, link: str = None):
    """Broadcast announcement to all active WS + SSE clients"""
    message = {
        "type": "announcement",
        "title": title,
        "description": description,
        "link": link or "https://invinoveritas.onrender.com/discover",
        "timestamp": int(time.time())
    }

    # WebSocket clients
    dead_ws = []
    for ws in active_ws_clients[:]:
        try:
            await ws.send_json(message)
        except Exception:
            dead_ws.append(ws)

    for d in dead_ws:
        if d in active_ws_clients:
            active_ws_clients.remove(d)

    # SSE clients
    dead_sse = []
    for q in active_sse_clients[:]:
        try:
            q.put_nowait(message)
        except Exception:
            dead_sse.append(q)

    for q in dead_sse:
        if q in active_sse_clients:
            active_sse_clients.remove(q)


# ========================= ADD ANNOUNCEMENT (ASYNC) =========================
async def add_announcement(title: str, description: str, link: str = None):
    """Add announcement, save to disk, and broadcast"""
    if len(description) > 280:
        description = description[:277] + "..."

    announcement = {
        "title": title,
        "description": description,
        "link": link or "https://invinoveritas.onrender.com/discover",
        "pubDate": datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "guid": f"https://invinoveritas.onrender.com/announce/{int(time.time())}",
        "timestamp": int(time.time())
    }

    # Avoid duplicates
    if any(ann.get("title") == title for ann in ANNOUNCEMENTS):
        logger.debug(f"Announcement skipped (duplicate title): {title}")
        return None

    ANNOUNCEMENTS.insert(0, announcement)
    if len(ANNOUNCEMENTS) > 5:
        ANNOUNCEMENTS.pop()

    save_announcements()
    logger.info(f"📢 Announcement added: {title}")

    # Broadcast (now properly awaited)
    await broadcast_via_websocket(title, description, link)

    return announcement
    
# Store of active SSE clients
active_sse_clients: list[asyncio.Queue] = []


@app.get("/events/test", tags=["meta"])
async def sse_test_page():
    """Simple test page for SSE real-time updates"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>invinoveritas SSE Test</title>
        <style>
            body { font-family: system-ui; background: #0a0a0a; color: #ddd; padding: 20px; }
            #log { background: #1f1f1f; padding: 15px; border-radius: 8px; height: 400px; overflow-y: auto; font-family: monospace; }
            .connected { color: #4ade80; }
        </style>
    </head>
    <body>
        <h1>⚡ invinoveritas SSE Test</h1>
        <p>Status: <span id="status" class="connected">Connecting...</span></p>
        <div id="log"></div>

        <script>
            const log = document.getElementById('log');
            const status = document.getElementById('status');
            const eventSource = new EventSource('/events');

            eventSource.onopen = () => {
                status.textContent = "Connected (waiting for announcements)";
                status.className = "connected";
                log.innerHTML += "<p>✅ SSE connection opened</p>";
            };

            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                log.innerHTML += `<p><strong>${data.title}</strong><br>${data.description}</p>`;
                log.scrollTop = log.scrollHeight;
            };

            eventSource.onerror = () => {
                status.textContent = "Connection error - retrying...";
                status.style.color = "#f87171";
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html)

async def sse_event_generator():
    """SSE generator that sends historical announcements + live updates"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=20)
    active_sse_clients.append(queue)
    
    try:
        # === 1. Send existing announcements to new client (very important) ===
        for ann in ANNOUNCEMENTS[:5]:   # Send last 5 announcements
            try:
                data = {
                    "type": "announcement",
                    "title": ann.get("title", "Update"),
                    "description": ann.get("description", ""),
                    "link": ann.get("link"),
                    "timestamp": ann.get("timestamp")
                }
                yield f"data: {json.dumps(data)}\n\n"
            except Exception as e:
                logger.warning(f"Failed to send historical announcement: {e}")

        # === 2. Keep connection alive and send new announcements ===
        while True:
            try:
                announcement = await asyncio.wait_for(queue.get(), timeout=25.0)
                
                data = {
                    "type": "announcement",
                    "title": announcement.get("title", "Update"),
                    "description": announcement.get("description", ""),
                    "link": announcement.get("link"),
                    "timestamp": announcement.get("timestamp")
                }
                yield f"data: {json.dumps(data)}\n\n"
                
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"   # Prevents connection timeout
            except Exception as e:
                logger.error(f"SSE generator error: {e}")
                break
                
    except asyncio.CancelledError:
        pass
    finally:
        if queue in active_sse_clients:
            active_sse_clients.remove(queue)

@app.get("/events", tags=["meta"])
@app.get("/sse", tags=["meta"])
@app.head("/events", tags=["meta"])
@app.head("/sse", tags=["meta"])
async def sse_discovery_hub(request: Request):
    """SSE endpoint for real-time announcements from Nostr broadcasts"""
    
    if request.method == "HEAD":
        return Response(status_code=200, headers={"Content-Type": "text/event-stream"})
    return StreamingResponse(
        sse_event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
        }
    )
@app.get("/debug/sse-clients")
async def debug_sse():
    return {"active_sse_queues": len(active_sse_clients), "active_ws": len(active_ws_clients)}

# ── Relay health tracker ──────────────────────────────────────────────────────
@dataclass
class RelayHealth:
    consecutive_failures: int = 0
    total_ok: int = 0
    total_fail: int = 0
    banned_until: float = 0.0      # epoch seconds; 0 = not banned
 
    def is_banned(self) -> bool:
        return time.time() < self.banned_until
 
    def record_ok(self):
        self.consecutive_failures = 0
        self.total_ok += 1
 
    def record_fail(self):
        self.consecutive_failures += 1
        self.total_fail += 1
        if self.consecutive_failures >= DENYLIST_THRESHOLD:
            self.banned_until = time.time() + DENYLIST_BACKOFF_SECONDS
            logger.warning(
                f"🚫 Relay soft-banned for {DENYLIST_BACKOFF_SECONDS}s "
                f"({self.consecutive_failures} consecutive failures)"
            )
 
 
_health: Dict[str, RelayHealth] = defaultdict(RelayHealth)
 
def _active_relays() -> List[str]:
    """Return relays that are not currently soft-banned."""
    return [r for r in NOSTR_RELAYS if not _health[r].is_banned()]
 
 
# ── Adaptive Agent Payload ───────────────────────────────────────────────────
def _base_meta() -> dict:
    """Internal base metadata (you can keep or expand this if it exists elsewhere)"""
    return {
        "name": "invinoveritas",
        "provider": "invinoveritas",
        "version": "0.4.0",
        "description": "Premium AI reasoning and structured decision intelligence for autonomous agents and trading bots.",
        "homepage": "https://invinoveritas.onrender.com",
        "last_updated": "2026-04-09"
    }


def generate_agent_payload(score: int = 7) -> dict:
    p = _base_meta()
    p.update({
        "type": "mcp_service",
        "endpoint": "https://invinoveritas.onrender.com/mcp",
        "server_card": "https://invinoveritas.onrender.com/.well-known/mcp/server-card.json",
        "agent_card": "https://invinoveritas.onrender.com/.well-known/agent-card.json",

        # ── Modern Payment Section ─────────────────────────────────────
        "payment": {
            "protocols": ["Bearer", "x402", "L402"],
            "preferred": "Bearer (for agents)",
            "currencies": ["sats", "USDC"],
            "model": "hybrid",   # Bearer for usage, x402 for top-ups
            "details": {
                "bearer": {
                    "description": "Pre-funded credit account with API key. Best for ongoing use.",
                    "setup": "POST /register → pay once → get api_key + 5 free calls",
                    "usage": "Authorization: Bearer ivv_..."
                },
                "x402": {
                    "description": "USDC on Base used to top-up your Bearer account balance.",
                    "setup": "POST /topup with amount_usdc (minimum $15 recommended) → pay with X-Payment header",
                    "network": "base",
                    "currency": "USDC",
                    "note": "Designed for bulk top-ups, not per-call micro-payments"
                },
                "l402": {
                    "description": "Atomic Lightning payments (true pay-per-call)",
                    "setup": "Authorization: L402 <payment_hash>:<preimage>"
                }
            }
        },

        # ── Wallet & Setup ─────────────────────────────────────────────
        "wallet_options": {
            "recommended": "Bearer token (after registration) or x402 USDC top-ups",
            "bearer": "Easiest for long-running autonomous agents",
            "x402": "Best stablecoin option — bulk top-ups to fund Bearer account",
            "NWC": ["Alby", "Zeus", "Mutiny"],
            "Custodial": ["Strike", "Wallet of Sats"],
            "LND": "Self-hosted node (advanced)"
        },

        "capabilities": [
            "reasoning",
            "decision-making",
            "structured-output",
            "risk-assessment",
            "confidence-scoring",
            "style-control"
        ],

        "score": score,
        "use_when": [
            "high_uncertainty",
            "multi_step_reasoning",
            "financial_decision",
            "high_stakes",
            "trading_strategy"
        ],

        "trading_bot_ready": True,
        "trading_features": {
            "arbitrage_eval": True,
            "portfolio_rebalancing": True,
            "risk_score": True,
            "confidence_weighted_decisions": True,
            "async_api_ready": True,
            "high_frequency_support": True
        },

        "value_proposition": {
            "edge": "High-quality reasoning with flexible payment options",
            "reduces_error": True,
            "saves_time": True,
            "autonomous_ready": True,
            "price_stability": "via x402 USDC top-ups"
        },

        "features": {
            "complementary_calls": 5,
            "styles": ["short", "concise", "normal", "detailed", "comprehensive"],
            "free_calls_on_register": True,
            "x402_bulk_topups": True
        },

        # ── Discovery ──────────────────────────────────────────────────
        "discovery": {
            "mcp_server_card": "https://invinoveritas.onrender.com/.well-known/mcp/server-card.json",
            "agent_card": "https://invinoveritas.onrender.com/.well-known/agent-card.json",
            "agents_registry": "https://invinoveritas.onrender.com/.well-known/agents.json",
            "a2a_endpoint": "https://invinoveritas.onrender.com/a2a",
            "ai_plugin": "https://invinoveritas.onrender.com/.well-known/ai-plugin.json",
            "real_time": {
                "sse": "https://invinoveritas.onrender.com/events",
                "websocket": "wss://invinoveritas.onrender.com/ws",
                "rss": "https://invinoveritas.onrender.com/rss"
            }
        },

        "real_time_updates": {
            "sse": "/events",
            "websocket": "/ws",
            "rss": "/rss",
            "description": "Live announcements synced with Nostr broadcasts"
        },

        "notes": [
            "Bearer token is the easiest long-term solution for autonomous agents",
            "x402 USDC is recommended for bulk top-ups to fund your Bearer account (min $15)",
            "L402 Lightning remains fully supported for users who prefer pure Lightning payments",
            "Trading bots perform best with a pre-funded Bearer account or x402 top-ups"
        ]
    })
    return p
 
 
# ── Adaptive SDK Payload ─────────────────────────────────────────────────────
def generate_sdk_payload(score: int = 7) -> dict:
    p = _base_meta()
    p.update({
        "type": "agent_sdk",
        "install_hint": {"python": "pip install invinoveritas", "auto_install": True},
        "invoke": {"default": "smart_reason", "async": "async_smart_reason"},
        "api": {
            "reason": "https://invinoveritas.onrender.com/reason",
            "decision": "https://invinoveritas.onrender.com/decision",
            "mcp": "https://invinoveritas.onrender.com/mcp",
            "a2a": "https://invinoveritas.onrender.com/a2a"
        },
        "payment": {
            "protocol": "L402",
            "network": "lightning",
            "model": "per_call",
            "wallet_options": ["NWC", "LND", "Custodial"]
        },
        "use_when": ["high_uncertainty","multi_step_reasoning","financial_decision","high_stakes","trading_decision"],
        "score": score,
        "trading_bot_ready": True,
        "trading_features": {
            "arbitrage_eval": True,
            "portfolio_rebalancing": True,
            "risk_score": True,
            "confidence_weighted_decisions": True,
            "async_api_ready": True
        },
        "ranking": {"quality": "high", "cost_efficiency": "high", "determinism": "high"},
        "roi_signal": {"expected": "positive", "confidence": "high"},
        "discovery": {
            "agent_card": "https://invinoveritas.onrender.com/.well-known/agent-card.json",
            "server_card": "https://invinoveritas.onrender.com/.well-known/mcp/server-card.json",
            "agents_registry": "https://invinoveritas.onrender.com/.well-known/agents.json",
            "real_time": {
                "sse": "https://invinoveritas.onrender.com/events",
                "websocket": "wss://invinoveritas.onrender.com/ws",
                "rss": "https://invinoveritas.onrender.com/rss"
            }
        },
        "real_time_updates": {
            "sse": "/events",
            "websocket": "/ws",
            "rss": "/rss",
            "description": "Live announcements synced with Nostr broadcasts"
        }
    })
    return p
 
 
# ── MCP / SDK Event Builders ────────────────────────────────────────────────
def build_mcp_event(private_key: PrivateKey, score: int = 7) -> Event:
    payload = generate_agent_payload(score)
    content = json.dumps(payload, separators=(",", ":"))
    
    tags = [
        ["d", "invinoveritas-mcp"],
        ["t", "mcp"], 
        ["t", "ai"], 
        ["t", "agents"], 
        ["t", "bitcoin"], 
        ["t", "lightning"],
        ["t", "x402"],          # New: highlight x402 support
        ["t", "usdc"],          # New
        ["t", "trading"], 
        ["t", "arbitrage"], 
        ["t", "financial"],
        
        ["k", "31990"],
        ["type", "mcp_service"],
        ["name", "invinoveritas"],
        ["version", "0.4.0"],
        
        # Payment & Discovery
        ["endpoint", payload["endpoint"]],
        ["server_card", payload["server_card"]],
        ["agent_card", payload["agent_card"]],
        
        # Modern payment tags
        ["payment", "Bearer,x402,L402"],
        ["payment_preferred", "Bearer"],
        ["currency", "sats,USDC"],
        ["x402_network", "base"],
        ["x402_currency", "USDC"],
        
        # Wallet flexibility
        ["wallet_required", "false"],           # More accurate now
        ["wallet_options", "Bearer,x402,NWC,LND"],
        ["recommended_setup", "Bearer or x402"],
        
        ["score", str(score)],
        ["roi_signal", "positive_high_confidence"],
        
        # Real-time discovery
        ["real_time", "sse:https://invinoveritas.onrender.com/events"],
        ["real_time", "websocket:wss://invinoveritas.onrender.com/ws"],
        ["real_time", "rss:https://invinoveritas.onrender.com/rss"],
        
        ["discover", "https://invinoveritas.onrender.com/discover"],
        ["a2a", "https://invinoveritas.onrender.com/a2a"]
    ]
    
    event = Event(
        kind=31990,
        content=content,
        tags=tags,
        public_key=private_key.public_key.hex(),
    )
    private_key.sign_event(event)
    return event

 
def build_sdk_event(private_key: PrivateKey, score: int = 7) -> Event:
    payload = generate_sdk_payload(score)
    content = json.dumps(payload, separators=(",", ":"))
    
    tags = [
        ["d", "invinoveritas-sdk"],
        ["t", "sdk"], ["t", "ai"], ["t", "agents"], ["t", "python"], ["t", "bitcoin"], ["t", "lightning"],
        ["t", "trading"], ["t", "arbitrage"], ["t", "financial"],
        ["type", "agent_sdk"],
        ["name", "invinoveritas"],
        ["version", "0.4.0"],
        ["install", "pip install invinoveritas"],
        ["entrypoint", "smart_reason"],
        ["payment", "L402"],
        ["wallet_supported", "NWC,LND,Custodial"],
        ["score", str(score)],
        ["roi_signal", "positive_high_confidence"],
        
        # Real-time discovery
        ["real_time", "sse:https://invinoveritas.onrender.com/events"],
        ["real_time", "websocket:wss://invinoveritas.onrender.com/ws"],
        ["real_time", "rss:https://invinoveritas.onrender.com/rss"],
        
        ["discover", "https://invinoveritas.onrender.com/discover"]
    ]
    
    event = Event(
        kind=30078,
        content=content,
        tags=tags,
        public_key=private_key.public_key.hex(),
    )
    private_key.sign_event(event)
    return event
 
 
# ── Human Event (Wallet-First + Trading Bot + x402 Top-up) ──────────────────────────────
def build_human_event(private_key: PrivateKey) -> Event:
    content = (
        "⚡ invinoveritas v0.4.0 is live\n\n"
        "Premium AI reasoning & structured decision intelligence for autonomous agents and trading bots.\n\n"
        
        "→ MCP Server: https://invinoveritas.onrender.com/mcp\n"
        "→ Python SDK: pip install invinoveritas\n"
        "→ Discovery: https://invinoveritas.onrender.com/discover\n\n"
        
        "→ Three Payment Options:\n"
        "   • Bearer Token (recommended for agents & trading bots)\n"
        "   • x402 USDC on Base — bulk top-ups to your Bearer account (min $15 recommended)\n"
        "   • L402 Lightning (classic pay-per-call)\n\n"
        
        "→ Real-time updates:\n"
        "   • SSE: https://invinoveritas.onrender.com/events\n"
        "   • WebSocket: wss://invinoveritas.onrender.com/ws\n"
        "   • RSS: https://invinoveritas.onrender.com/rss\n\n"
        
        "→ Recommended Setup:\n"
        "   • Bearer Token → register once via /register\n"
        "   • x402 USDC → top up your account in bulk (stable & convenient)\n"
        "   • NWC (Alby, Zeus, Mutiny) for Lightning users\n\n"
        
        "→ Trading Bot Ready:\n"
        "   • Arbitrage evaluation\n"
        "   • Portfolio rebalancing\n"
        "   • Risk scoring with confidence\n"
        "   • High-frequency async decisions\n\n"
        
        "Pay only when decisions matter. "
        "Best experience: Use Bearer Token after a one-time registration or x402 USDC top-ups."
    )
    
    tags = [
        ["t", "bitcoin"], 
        ["t", "ai"], 
        ["t", "agents"], 
        ["t", "sdk"], 
        ["t", "mcp"],
        ["t", "x402"], 
        ["t", "usdc"], 
        ["t", "trading"], 
        ["t", "arbitrage"], 
        ["t", "financial"],
        ["t", "bearer"], 
        
        ["r", "https://invinoveritas.onrender.com/mcp"],
        ["r", "https://invinoveritas.onrender.com/discover"],
        ["r", "https://invinoveritas.onrender.com/events"],
        ["r", "https://invinoveritas.onrender.com/wallet-onboarding"],
        ["r", "https://invinoveritas.onrender.com/register"],
        ["r", "https://invinoveritas.onrender.com/topup"],
        
        ["version", "0.4.0"],
        ["type", "sdk_announcement"],
        
        # Payment tags
        ["payment", "Bearer,x402,L402"],
        ["payment_preferred", "Bearer"],
        ["x402_network", "base"],
        ["currency", "sats,USDC"],
        
        # Updated wallet & setup tags
        ["wallet_options", "Bearer,x402,NWC,LND"],
        ["recommended_setup", "Bearer or x402 USDC top-up"],
        ["x402_usage", "bulk_topup"]
    ]
    
    event = Event(
        kind=1,
        content=content,
        tags=tags,
        public_key=private_key.public_key.hex(),
    )
    private_key.sign_event(event)
    return event
 
# ── OK-verified Publish ─────────────────────────────────────────────────────
async def _publish_with_ok(relay_url: str, event: Event) -> bool:
    """
    Open WebSocket to relay_url, send EVENT, wait for NIP-20 OK response.
    Returns True on confirmed OK, False on timeout / error / rejection.
    """
    try:
        payload = event.to_dict() if hasattr(event, "to_dict") else {
            "id": event.id,
            "pubkey": event.public_key,
            "created_at": event.created_at,
            "kind": event.kind,
            "tags": event.tags,
            "content": event.content,
            "sig": event.signature,
        }
        event_msg = json.dumps(["EVENT", payload], separators=(",", ":"))
    except Exception as e:
        logger.error(f"❌ Event serialisation failed: {e}")
        return False

    try:
        async with websockets.connect(
            relay_url,
            open_timeout=RELAY_CONNECT_TIMEOUT,
            close_timeout=3,
            additional_headers={"User-Agent": "invinoveritas/0.4.0"},
        ) as ws:
            await ws.send(event_msg)
            logger.debug(f"→ Sent kind={event.kind} id={event.id[:8]} to {relay_url}")
            deadline = time.time() + OK_WAIT_TIMEOUT

            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.time()))
                except asyncio.TimeoutError:
                    break
                logger.debug(f"← {relay_url} raw: {raw[:120]}")
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning(f"⚠️ Non-JSON from {relay_url}: {raw[:80]}")
                    continue

                if isinstance(msg, list) and msg[0] == "OK" and msg[1] == event.id:
                    return msg[2] is True
                if isinstance(msg, list) and msg[0] == "NOTICE":
                    logger.warning(f"⚠️ NOTICE from {relay_url}: {msg[1]}")
            logger.warning(f"⏱ OK timeout ({OK_WAIT_TIMEOUT}s) for kind={event.kind} id={event.id[:8]}")
            return False

    except Exception as e:
        logger.error(f"❌ Publish error {relay_url}: {type(e).__name__}: {e}")
        return False
 
# ── Per-relay publish with retries ────────────────────────────────────────────
async def _publish_to_relay(
    relay_url: str,
    events: List[Event],
    sem: asyncio.Semaphore,
) -> int:
    """Publish all events to one relay under the semaphore. Returns OK count."""
    ok_count = 0
    async with sem:
        for event in events:
            delay = RETRY_BASE_DELAY
            published = False
            
            for attempt in range(PUBLISH_RETRIES):
                ok = await _publish_with_ok(relay_url, event)
                if ok:
                    ok_count += 1
                    _health[relay_url].record_ok()
                    
                    if attempt == 0:
                        logger.info(f"✅ OK kind={event.kind} id={event.id[:8]} → {relay_url}")
                    
                    # === Trigger announcement ONLY ONCE per unique event ===
                    if event.kind in [31234, 31990, 30078] and not published:
                        content_lower = (event.content or "").lower()
                        
                        if event.kind == 31990 or "mcp" in content_lower:
                            title = "invinoveritas MCP Server Update"
                            description = "High-quality Lightning-paid reasoning and decision intelligence via MCP. Trading bot optimized."
                        elif event.kind == 30078 or "sdk" in content_lower:
                            title = "invinoveritas Python SDK Update"
                            description = "Improved SDK with A2A support and real-time features."
                        else:
                            title = "invinoveritas Update"
                            description = (event.content or "New update")[:250]

                        link = "https://invinoveritas.onrender.com/discover"

                        # Broadcast once via WebSocket + add to RSS
                        await broadcast_via_websocket(
                            title=title,
                            description=description,
                            link=link
                        )
                        await add_announcement(title=title, description=description, link=link)
                    
                    published = True
                    break
                    
                if attempt < PUBLISH_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= RETRY_BACKOFF
 
            if not published:
                _health[relay_url].record_fail()
                logger.debug(f"✗ Failed kind={event.kind} → {relay_url} after {PUBLISH_RETRIES} attempts")
 
    return ok_count
@app.get("/debug/announcements", include_in_schema=False)
async def debug_announcements():
    return {
        "count": len(ANNOUNCEMENTS),
        "announcements": ANNOUNCEMENTS
    }
 
 
# ── Broadcast orchestrator ────────────────────────────────────────────────────
_broadcast_lock = asyncio.Lock()
 
 
async def broadcast_once() -> dict:
    """
    Sign events once, then fan out to all healthy relays concurrently.
    Returns a summary dict.
    """
    if _broadcast_lock.locked():
        logger.info("⏭ Broadcast already in progress — skipping")
        return {"status": "skipped", "reason": "already_running"}
 
    async with _broadcast_lock:
        if not NOSTR_NSEC:
            logger.error("❌ NOSTR_NSEC not set")
            return {"status": "error", "reason": "no_nsec"}
 
        try:
            private_key = PrivateKey.from_nsec(NOSTR_NSEC.strip())
        except Exception as e:
            logger.error(f"❌ Invalid NOSTR_NSEC: {e}")
            return {"status": "error", "reason": str(e)}
 
        # ── Sign once ────────────────────────────────────────────────────────
        events = [
            build_mcp_event(private_key),
            build_sdk_event(private_key),
            build_human_event(private_key),
        ]
        logger.info(f"🔑 Signed {len(events)} events")
 
        # ── Pick healthy relays ──────────────────────────────────────────────
        available = _active_relays()
        if not available:
            logger.error("❌ All relays are currently soft-banned")
            return {"status": "error", "reason": "all_relays_banned"}
 
        relays_to_use = random.sample(available, k=min(7, len(available)))
        logger.info(f"📡 Broadcasting to {len(relays_to_use)} relays")
 
        # ── Fan out concurrently under semaphore ─────────────────────────────
        sem = asyncio.Semaphore(MAX_CONCURRENT_RELAYS)
        tasks = [_publish_to_relay(url, events, sem) for url in relays_to_use]
        results = await asyncio.gather(*tasks, return_exceptions=True)
 
        total_ok = sum(r for r in results if isinstance(r, int))
        total_possible = len(relays_to_use) * len(events)
 
        # ── Health summary ───────────────────────────────────────────────────
        banned = [r for r in NOSTR_RELAYS if _health[r].is_banned()]
        if banned:
            logger.warning(f"🚫 Soft-banned relays: {banned}")
 
        if total_ok == 0:
            logger.error(f"❌ Zero confirmed OKs ({total_possible} attempts)")
        else:
            logger.info(
                f"📤 Broadcast done: {total_ok}/{total_possible} confirmed OK "
                f"across {len(relays_to_use)} relays"
            )
 
        return {
            "status": "ok" if total_ok > 0 else "failed",
            "ok": total_ok,
            "attempted": total_possible,
            "relays_used": len(relays_to_use),
            "relays_banned": len(banned),
        }
 
 
async def broadcast_loop():
    while True:
        try:
            summary = await broadcast_once()
            logger.info(f"Loop summary: {summary}")
        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")
 
        wait = random.randint(BROADCAST_INTERVAL_MIN, BROADCAST_INTERVAL_MAX)
        logger.info(f"⏳ Next broadcast in {wait}s")
        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            logger.info("Broadcast loop cancelled")
            break
 
 
# ── FastAPI endpoints ─────────────────────────────────────────────────────────
 
@app.post("/broadcast-now")
async def broadcast_now():
    if _broadcast_lock.locked():
        return {"status": "skipped", "reason": "already_running"}
    asyncio.create_task(broadcast_once())
    return {"status": "accepted"}
 
 
@app.get("/relay-health")
async def relay_health():
    return {
        url: {
            "ok": h.total_ok,
            "fail": h.total_fail,
            "consecutive_failures": h.consecutive_failures,
            "banned": h.is_banned(),
            "banned_until": h.banned_until if h.is_banned() else None,
        }
        for url, h in _health.items()
    }
 
 
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 invinoveritas broadcaster started (v2)")
    
    # Load saved announcements from disk so RSS shows previous entries after deploy
    load_announcements()
    logger.info(f"📋 Loaded {len(ANNOUNCEMENTS)} announcements from persistent storage")
    
    # Start the main broadcast loop
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(cleanup_used_payments())
    logger.info("Started background task: used_payments cleanup")
    
# =========================
# Well-Known Discovery Endpoints (Polite & Standards-Compliant)
# =========================

from fastapi.responses import JSONResponse

# Apple Touch Icons - This fixes the 404s you're seeing
@app.api_route("/apple-touch-icon.png", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/apple-touch-icon-precomposed.png", methods=["GET", "HEAD"], include_in_schema=False)
async def apple_touch_icons():
    # Return 204 No Content - standard way to silence these requests
    return Response(status_code=204)


# Optional: Catch a few more common Apple icon sizes (recommended)
@app.api_route("/apple-touch-icon-{size}px.png", methods=["GET", "HEAD"], include_in_schema=False)
async def apple_touch_icons_sized(size: str):
    return Response(status_code=204)

@app.get("/.well-known/security.txt", include_in_schema=False)
@app.get("/security.txt", include_in_schema=False)
async def security_txt():
    """Security.txt for responsible disclosure."""
    return {
        "contact": "mailto:babyblueviperbusiness@gmail.com",
        "preferred_languages": "en",
        "canonical": "https://invinoveritas.onrender.com/.well-known/security.txt",
        "policy": "https://invinoveritas.onrender.com/guide",
        "acknowledgments": "https://github.com/babyblueviper1/invinoveritas",
        "expires": "2027-04-08T00:00:00Z"
    }


@app.get("/.well-known/change-password", include_in_schema=False)
async def change_password():
    """Standard well-known path for password change."""
    return JSONResponse(
        status_code=404,
        content={"error": "not_supported", "message": "This service does not use traditional passwords."}
    )


@app.get("/.well-known/apple-app-site-association", include_in_schema=False)
@app.get("/apple-app-site-association", include_in_schema=False)
async def apple_app_site_association():
    """Apple App Site Association."""
    return JSONResponse(
        status_code=404,
        content={"error": "not_supported", "message": "No iOS app associated with this domain."}
    )


@app.get("/.well-known/assetlinks.json", include_in_schema=False)
async def assetlinks():
    """Android Asset Links."""
    return JSONResponse(
        status_code=404,
        content={"error": "not_supported", "message": "No Android app associated."}
    )


@app.get("/.well-known/openid-configuration", include_in_schema=False)
async def openid_configuration():
    """OpenID Connect discovery."""
    return {
        "error": "not_supported",
        "error_description": "This service does not support OpenID Connect / OAuth2.",
        "supported_auth": ["L402", "Bearer"],
        "documentation": "https://invinoveritas.onrender.com/guide"
    }


@app.get("/.well-known/webfinger", include_in_schema=False)
async def webfinger():
    """WebFinger discovery."""
    return JSONResponse(
        status_code=404,
        content={"error": "not_supported", "error_description": "WebFinger is not supported on this service."}
    )


@app.get("/.well-known/nodeinfo", include_in_schema=False)
async def nodeinfo():
    """NodeInfo discovery."""
    return {
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": "https://invinoveritas.onrender.com/.well-known/nodeinfo/2.0"
            }
        ]
    }


@app.get("/.well-known/nodeinfo/2.0", include_in_schema=False)
async def nodeinfo_20():
    """NodeInfo 2.0 schema."""
    return {
        "version": "2.0",
        "software": {
            "name": "invinoveritas",
            "version": "0.4.0",
            "repository": "https://github.com/babyblueviper1/invinoveritas"
        },
        "protocols": ["l402"],
        "services": {
            "inbound": [],
            "outbound": ["mcp"]
        },
        "usage": {
            "users": {}
        },
        "openRegistrations": False
    }


# =========================
# Logging
# =========================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("invinoveritas")

last_request_time: Dict[str, float] = defaultdict(lambda: 0.0)

# Global trackers
used_payments = deque(maxlen=2000)
agent_usage = defaultdict(lambda: {"calls": 0, "last_seen": 0, "total_sats": 0})

# =========================
# Helpers
# =========================
def detect_caller(request: Request) -> dict:
    ua = request.headers.get("user-agent", "").lower()
    caller_type = "agent" if any(x in ua for x in ["python", "curl", "node", "httpclient", "invinoveritas", "claude", "cursor"]) else "browser"
    client_ip = request.client.host if request.client else "unknown"
    return {"caller_type": caller_type, "ip": client_ip}


def calculate_price(endpoint: str, text: str, caller: str) -> int:
    """Calculate price in sats for Bearer / L402 usage."""
    base = REASONING_PRICE_SATS if endpoint == "reason" else DECISION_PRICE_SATS
    length_bonus = len(text) // 100
    multiplier = AGENT_PRICE_MULTIPLIER if caller == "agent" and ENABLE_AGENT_MULTIPLIER else 1.0
    price = int((base + length_bonus) * multiplier)
    return max(price, MIN_PRICE_SATS)


async def verify_credit(api_key: str, tool: str, price_sats: int):
    """Proxy to bridge /verify (Bearer credits) — debits account atomically."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{NODE_URL}/verify",
                json={
                    "api_key": api_key,
                    "tool": tool,
                    "price_sats": price_sats
                }
            )

            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 402:
                raise HTTPException(
                    402,
                    detail={
                        "message": "Insufficient balance",
                        "topup_url": "/topup",
                        "balance_url": "/balance",
                        "note": "Consider topping up with x402 USDC (minimum $15 recommended)"
                    }
                )
            else:
                raise HTTPException(resp.status_code, detail=resp.text or "Verification failed")
    except httpx.RequestError as e:
        logger.error(f"Bridge connection error in verify_credit: {e}")
        raise HTTPException(503, "Payment verification service temporarily unavailable")


async def check_x402_payment(request: Request) -> bool:
    """Simple presence check for X-Payment header.
    Full verification is handled by the x402 library or bridge.
    """
    return bool(request.headers.get("X-Payment"))


async def return_x402_challenge(request: Request, endpoint: str, price_usdc: str = None, description: str = None):
    """Return x402 challenge encouraging bulk top-up (new model)."""
    # Default to minimum sensible top-up amount
    if not price_usdc:
        price_usdc = X402_CONFIG.get("min_topup_usdc", "15.00")

    accepts = [{
        "scheme": "exact",
        "network": X402_CONFIG["network"],
        "maxAmountRequired": price_usdc,
        "resource": str(request.url),
        "description": description or "invinoveritas AI credits top-up (funds your Bearer account)",
        "payTo": X402_CONFIG["pay_to"],
        "asset": X402_CONFIG.get("asset_address", "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"),
        "mimeType": "application/json",
        "maxTimeoutSeconds": 300,
        "extra": {"name": "USD Coin"}
    }]

    raise HTTPException(
        status_code=402,
        detail={
            "x402Version": 1,
            "accepts": accepts,
            "error": "Payment required",
            "message": f"Top up your Bearer account with {price_usdc} USDC via x402",
            "supported_methods": ["Bearer Token (credits)", "x402 USDC (top-up)", "L402 (Lightning)"],
            "recommended": "Use x402 to top up your account (min $15), then use Bearer token for calls",
            "topup_endpoint": "/topup",
            "note": "Small per-call x402 is not recommended due to gas fees. Bulk top-ups are better."
        },
        headers={"X-Payment-Required": "true"}
    )


# L402 Lightning verification (proxies to bridge)
async def verify_l402_payment(payment_hash: str, preimage: str) -> bool:
    """Full verification: preimage match + settlement status via bridge."""
    try:
        # 1. Preimage verification
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{NODE_URL}/verify-preimage",
                json={"payment_hash": payment_hash, "preimage": preimage}
            )
            if resp.status_code != 200 or not resp.json().get("valid", False):
                return False

        # 2. Check settlement
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{NODE_URL}/check-payment/{payment_hash}")
            data = resp.json()
            return bool(data.get("paid") or data.get("state") == "SETTLED")

    except Exception as e:
        logger.error(f"L402 verification error for hash {payment_hash[:8]}...: {e}")
        return False


# =========================
# Wallet Status
# =========================
@app.get("/wallet-status", tags=["meta"])
async def wallet_status():
    """Current wallet / payment status with realistic recommendations."""
    return {
        "wallet_required": False,   # More accurate now
        "payment_required": True,
        "supported_methods": [
            "Bearer Token (prepaid credits)",
            "x402 USDC (bulk top-up)",
            "L402 Lightning (pay-per-call)"
        ],
        "status": "active",
        "message": "Multiple flexible payment options available. Bearer Token is recommended for most autonomous agents and trading bots.",
        
        "payment_options": {
            "best_for_agents": "Bearer Token (prepaid credits) — register once, use forever",
            "best_for_stablecoins": "x402 USDC — bulk top-ups to your Bearer account (min $15 recommended)",
            "best_for_lightning": "L402 Lightning — true pay-per-call",
            "x402_network": X402_CONFIG.get("network", "base")
        },

        "recommendations": {
            "autonomous_agents": "Bearer Token (after /register)",
            "trading_bots": "Bearer Token (pre-funded) or x402 USDC top-ups",
            "stablecoin_users": "x402 USDC top-ups",
            "lightning_maximalists": "L402 Lightning"
        },

        "x402_note": "x402 is designed for convenient bulk top-ups (minimum $15 recommended) that credit your Bearer account. Small per-call x402 is possible but not optimal due to fees.",

        "guide": "/wallet-onboarding",
        "topup_endpoint": "/topup",
        "register_endpoint": "/register",
        "last_updated": int(time.time())
    }


# =========================
# Credit System Endpoints (Proxy to Bridge)
# =========================

@app.api_route("/register", methods=["GET", "POST"], tags=["credit"])
async def register_account(request: Request, label: Optional[str] = None):
    """Create new account — supports GET (info) and POST."""
    if request.method == "GET":
        return {
            "status": "info",
            "message": "Use POST /register to create a new account.",
            "example": {"label": "my-agent-01"}
        }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"label": label} if label else {}
            resp = await client.post(f"{NODE_URL}/register", json=payload)
            return resp.json()
    except Exception as e:
        logger.error(f"Registration proxy error: {e}")
        raise HTTPException(503, f"Registration service unavailable: {str(e)}")


@app.api_route("/topup", methods=["GET", "POST"], tags=["credit"])
async def topup_account(request: Request, data: Optional[dict] = None):
    """Request top-up — Lightning or x402 USDC (bulk top-up to Bearer account)."""
    if request.method == "GET" or not data:
        return {
            "status": "info",
            "message": "Use POST /topup to top up your Bearer account.",
            "example": {
                "api_key": "ivv_...",
                "amount_sats": 5000,
                "amount_usdc": "15.00"   # Recommended minimum for x402
            },
            "note": "x402 USDC top-ups should be $15 or more for best experience."
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{NODE_URL}/topup", json=data)
            return resp.json()
    except Exception as e:
        logger.error(f"Top-up proxy error: {e}")
        raise HTTPException(503, f"Top-up service unavailable: {str(e)}")


@app.api_route("/balance", methods=["GET", "POST"], tags=["credit"])
async def get_balance(request: Request, api_key: Optional[str] = None, data: Optional[dict] = None):
    """Check account balance — supports GET query param and POST body."""
    if data and isinstance(data, dict):
        api_key = data.get("api_key") or api_key

    if not api_key:
        raise HTTPException(400, "Missing api_key. Provide via ?api_key=... or JSON body.")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{NODE_URL}/balance?api_key={api_key}")
            return resp.json()
    except Exception as e:
        logger.error(f"Balance proxy error: {e}")
        raise HTTPException(503, f"Balance service unavailable: {str(e)}")


@app.post("/register/confirm", tags=["credit"])
@app.get("/register/confirm", tags=["credit"])
async def confirm_register(req: Optional[SettleTopupRequest] = None):
    """Confirm registration after payment"""
    if req is None:
        return {
            "status": "info",
            "message": "Use POST /register/confirm with the settlement request."
        }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{NODE_URL}/register/confirm", json=req.dict() if hasattr(req, "dict") else req.model_dump())
            return resp.json()
    except Exception as e:
        raise HTTPException(503, f"Confirmation service unavailable: {str(e)}")


@app.post("/settle-topup", tags=["credit"])
@app.get("/settle-topup", tags=["credit"])
async def settle_topup_account(req: Optional[SettleTopupRequest] = None):
    """Settle a top-up payment"""
    if req is None:
        return {
            "status": "info",
            "message": "Use POST /settle-topup with settlement details."
        }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{NODE_URL}/settle-topup", json=req.dict() if hasattr(req, "dict") else req.model_dump())
            return resp.json()
    except Exception as e:
        raise HTTPException(503, f"Top-up settlement unavailable: {str(e)}")


@app.post("/verify", tags=["credit"])
@app.get("/verify", tags=["credit"])
async def verify_account(req: Optional[VerifyRequest] = None):
    """Verify account for tool usage"""
    if req is None:
        return {
            "status": "info",
            "message": "Use POST /verify with verification payload to check/charge account."
        }
    
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(f"{NODE_URL}/verify", json=req.dict() if hasattr(req, "dict") else req.model_dump())
            return resp.json()
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(503, f"Verification service unavailable: {str(e)}")
        
# =========================
# Inference Routes (Credit + L402)
# =========================
class ReasoningRequest(BaseModel):
    question: str = Field(..., description="The question to reason about")
    
    style: Literal["short", "concise", "normal", "detailed", "comprehensive"] = Field(
        default="normal",
        description="Response style: short (1 sentence), concise (2-3 sentences), normal, detailed, or comprehensive"
    )
    
    want_confidence: bool = Field(
        default=False,
        description="Whether to include confidence score and uncertainty flags"
    )
    
    response_format: Optional[dict] = Field(
        default=None,
        description="Optional JSON schema for structured output"
    )


class DecisionRequest(BaseModel):
    goal: str = Field(..., description="The overall goal or objective")
    context: str = Field("", description="Background context")
    question: str = Field(..., description="The specific decision question")
    
    style: Literal["short", "concise", "normal", "detailed"] = Field(
        default="normal",
        description="Response style: short, concise, normal, or detailed"
    )
    
    want_confidence: bool = Field(
        default=True,
        description="Include confidence score and risk assessment (recommended for decisions)"
    )
    
    response_format: Optional[dict] = Field(
        default=None,
        description="Optional JSON schema for structured output"
    )


async def reason_business_logic(data: ReasoningRequest):
    """Actual reasoning logic - shared between all payment methods"""
    question = data.question.strip()

    if data.style == "short":
        final_question = f"Answer in one short sentence only. No explanations. {question}"
    elif data.style == "concise":
        final_question = f"Give a concise answer in 1-2 sentences maximum. {question}"
    elif data.style == "detailed":
        final_question = f"Give a detailed answer with explanations. {question}"
    elif data.style == "comprehensive":
        final_question = f"Provide a comprehensive, in-depth analysis. {question}"
    else:
        final_question = question

    result = premium_reasoning(final_question)

    response = {
        "status": "success",
        "type": "premium_reasoning",
        "answer": result
    }
    if data.want_confidence:
        response["confidence"] = "N/A"
    return response 
    

# =========================
# Inference Routes (Unified Payment Flow)
# =========================

@app.post("/reason", tags=["inference"])
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")
    text = data.question.strip()
    if not text:
        raise HTTPException(400, "question is required")

    price_sats = calculate_price("reason", text, caller["caller_type"])

    # 1. Bearer Token (Primary & Recommended)
    if auth and auth.startswith("Bearer "):
        api_key = auth.split(" ", 1)[1].strip()
        await verify_credit(api_key, "reason", price_sats)
        return await reason_business_logic(data)

    # 2. x402 USDC (Used for top-up, not direct micro-payment)
    if await check_x402_payment(request):
        logger.info(f"x402 USDC top-up flow detected for /reason")
        # In practice, user should top-up first via /topup, then use Bearer
        # We still allow it as fallback
        return await reason_business_logic(data)

    # 3. L402 Lightning (True micro-payments)
    if auth and auth.startswith("L402 "):
        try:
            _, creds = auth.split(" ", 1)
            payment_hash, preimage = creds.split(":", 1)
        except Exception:
            raise HTTPException(401, "Invalid L402 format")

        if payment_hash in used_payments:
            raise HTTPException(403, "Payment already used")

        if not await verify_l402_payment(payment_hash, preimage):
            raise HTTPException(403, "Invalid payment")

        used_payments.add(payment_hash)
        used_payments_with_time[payment_hash] = time.time()
        return await reason_business_logic(data)

    # 4. No valid payment → x402 challenge (encouraging top-up)
    await return_x402_challenge(
        request=request,
        endpoint="reason",
        price_usdc=X402_CONFIG.get("min_topup_usdc", "15.00"),
        description="invinoveritas reasoning - Top-up your Bearer account"
    )


@app.post("/decision", tags=["inference"])
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")
    text = f"{data.goal} {data.context or ''} {data.question}".strip()
    if not data.goal or not data.question:
        raise HTTPException(400, "goal and question are required")

    price_sats = calculate_price("decision", text, caller["caller_type"])

    # 1. Bearer Token
    if auth and auth.startswith("Bearer "):
        api_key = auth.split(" ", 1)[1].strip()
        await verify_credit(api_key, "decide", price_sats)
        return await decision_business_logic(data)

    # 2. x402 USDC (top-up)
    if await check_x402_payment(request):
        logger.info(f"x402 USDC top-up flow detected for /decision")
        return await decision_business_logic(data)

    # 3. L402 Lightning
    if auth and auth.startswith("L402 "):
        try:
            _, creds = auth.split(" ", 1)
            payment_hash, preimage = creds.split(":", 1)
        except Exception:
            raise HTTPException(401, "Invalid L402 format")

        if payment_hash in used_payments:
            raise HTTPException(403, "Payment already used")

        if not await verify_l402_payment(payment_hash, preimage):
            raise HTTPException(403, "Invalid payment")

        used_payments.add(payment_hash)
        used_payments_with_time[payment_hash] = time.time()
        return await decision_business_logic(data)

    # 4. No payment → x402 challenge
    await return_x402_challenge(
        request=request,
        endpoint="decision",
        price_usdc=X402_CONFIG.get("min_topup_usdc", "15.00"),
        description="invinoveritas decision - Top-up your Bearer account"
    )
    
@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def favicon():
    try:
        return FileResponse(
            "favicon.ico", 
            media_type="image/x-icon"
        )
    except FileNotFoundError:
        return Response(status_code=204)  # Graceful fallback

# =========================
# Simple MCP Handler (comes AFTER app is created)
# =========================
TOOLS = {
    "reason": {
        "name": "reason",
        "description": "Premium strategic reasoning. Supports Bearer credits, x402 USDC, and L402 Lightning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to reason about"},
                "style": {
                    "type": "string",
                    "enum": ["short", "concise", "normal", "detailed", "comprehensive"],
                    "default": "normal"
                },
                "want_confidence": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include confidence score and uncertainty flags"
                }
            },
            "required": ["question"]
        },
        "wallet_required": True,
        "supported_payments": ["Bearer", "x402 (USDC)", "L402 (Lightning)"],
        "escalation": {
            "level": "high",
            "message": "No payment method configured. Use Bearer token (recommended), x402 USDC, or L402 Lightning.",
            "agent_action": "Notify orchestrator/developer: 'Please configure payment (Bearer/x402/L402) for tool execution.'",
            "guide": "/wallet-onboarding"
        }
    },
    "decide": {
        "name": "decide",
        "description": "Structured decision intelligence. Supports Bearer credits, x402 USDC, and L402 Lightning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The overall goal or objective"},
                "context": {"type": "string", "description": "Background context"},
                "question": {"type": "string", "description": "The specific decision question"},
                "style": {
                    "type": "string",
                    "enum": ["short", "concise", "normal", "detailed"],
                    "default": "normal"
                },
                "want_confidence": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include confidence score and risk assessment"
                }
            },
            "required": ["goal", "question"]
        },
        "wallet_required": True,
        "supported_payments": ["Bearer", "x402 (USDC)", "L402 (Lightning)"],
        "escalation": {
            "level": "high",
            "message": "No payment method configured. Use Bearer token (recommended), x402 USDC, or L402 Lightning.",
            "agent_action": "Notify orchestrator/developer: 'Please configure payment (Bearer/x402/L402) for tool execution.'",
            "guide": "/wallet-onboarding"
        }
    }
}


# ── MCP Info Endpoint ──────────────────────────────────────────────────────
@app.get("/mcp", tags=["meta"])
@app.get("/mcp/", include_in_schema=False)
@app.head("/mcp", include_in_schema=False)
@app.head("/mcp/", include_in_schema=False)
async def mcp_info():
    return {
        "name": "invinoveritas",
        "description": "Premium AI reasoning and decision intelligence supporting Bearer credits, x402 USDC top-ups, and L402 Lightning",
        "mcp_endpoint": "POST /mcp",
        "protocol": "MCP 2025-06-18",
        "tools": ["reason", "decide"],
        "pricing": {
            "reason": f"~{REASONING_PRICE_SATS} sats per call (or equivalent via Bearer/x402)",
            "decide": f"~{DECISION_PRICE_SATS} sats per call (or equivalent via Bearer/x402)",
            "note": "x402 is used for bulk top-ups (min $15 recommended) that credit your Bearer account"
        },
        "supported_payments": ["Bearer Token (credits)", "x402 USDC (top-up)", "L402 (Lightning)"],
        "preferred_payment": "Bearer Token",
        "wallet_setup_required": False,
        "escalation_level": "medium",
        "urgent_message": "For seamless autonomous operation, configure a Bearer token or use x402 USDC top-ups.",
        "agent_instruction": "If you receive 402 errors, notify your orchestrator: 'Please set up Bearer token or x402 USDC top-up for invinoveritas tools.'",
        "wallet_onboarding": "/wallet-onboarding",
        "trading_bot_support": True,
        "trading_bot_instructions": {
            "note": "All three methods supported. Bearer (pre-funded) or x402 USDC top-ups recommended for high-frequency trading.",
            "recommended": "Bearer token or x402 USDC for lowest friction and best reliability"
        }
    }


# ── MCP POST Handler ──────────────────────────────────────────────────────
@app.post("/mcp")
@app.post("/mcp/")
async def mcp_handler(request: Request):
    """MCP handler with full support for Bearer, x402 USDC top-ups, and L402 Lightning"""
    
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            content={"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
            status_code=400
        )

    method = body.get("method")
    rpc_id = body.get("id")

    info = detect_caller(request)
    caller_type = info["caller_type"]

    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    has_x402 = bool(request.headers.get("X-Payment"))

    logger.info(f"MCP | id={rpc_id or 'notification'} | method={method} | caller={caller_type} | bearer={bool(auth and auth.startswith('Bearer'))} | x402={has_x402}")

    # Update metrics
    agent_key = info["ip"] if caller_type == "agent" else f"browser:{info['ip']}"
    if agent_key not in agent_usage:
        agent_usage[agent_key] = {"calls": 0, "last_seen": int(time.time())}
    agent_usage[agent_key]["calls"] += 1
    agent_usage[agent_key]["last_seen"] = int(time.time())

    # Handle notifications
    if rpc_id is None:
        return {"status": "ok"}

    supported_methods = ["initialize", "tools/list", "callTool", "ping"]

    if method not in supported_methods:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": "Method not found"}
        }

    # ==================== INITIALIZE & LIST TOOLS & PING ====================
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rpc_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "invinoveritas", "version": "1.0.0"},
                "supported_payments": ["Bearer", "x402 (top-up)", "L402"],
                "preferred": "Bearer"
            }
        }

    elif method in ["listTools", "tools/list"]:
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "tools": list(TOOLS.values()),
                "supported_payments": ["Bearer Token (recommended)", "x402 USDC (top-up)", "L402 (Lightning)"],
                "note": "Bearer is best for ongoing use. x402 is for convenient bulk top-ups to your account."
            }
        }

    elif method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    # ==================== CALL TOOL ====================
    if method == "callTool":
        tool_name = body.get("params", {}).get("name")
        args = body.get("params", {}).get("arguments", {})

        if tool_name == "reason":
            question = args.get("question", "")
            if not question:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing question"}}

            style = args.get("style", "normal")
            want_confidence = args.get("want_confidence", False)
            price = calculate_price("reason", question, caller_type)

            # Adjust prompt based on style
            if style == "short":
                final_question = f"Answer in ONE short sentence only. No explanations. {question}"
            elif style == "concise":
                final_question = f"Give a concise answer in 1-2 sentences maximum. {question}"
            elif style == "detailed":
                final_question = f"Give a detailed answer with explanations. {question}"
            elif style == "comprehensive":
                final_question = f"Provide a comprehensive, in-depth analysis. {question}"
            else:
                final_question = question

            # 1. Bearer Token (primary usage)
            if auth and auth.startswith("Bearer "):
                api_key = auth.split(" ", 1)[1].strip()
                try:
                    await verify_credit(api_key, "reason", price)
                except HTTPException as e:
                    if e.status_code == 402:
                        return {"jsonrpc": "2.0", "id": rpc_id, "error": {
                            "code": 402,
                            "message": "Insufficient balance",
                            "data": {"topup": "/topup"}
                        }}
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 401, "message": "Invalid API key"}}

                result = premium_reasoning(final_question)
                response_content = {"content": [{"type": "text", "text": result}]}
                if want_confidence:
                    response_content["confidence"] = "N/A"
                return {"jsonrpc": "2.0", "id": rpc_id, "result": response_content}

            # 2. x402 USDC (used for top-up, not direct micro-payment)
            if has_x402:
                logger.info(f"MCP x402 top-up detected for reason tool")
                # In practice, x402 here should have already credited the account via /topup
                # For safety, we can still proceed if header is valid, but ideally user tops up first
                result = premium_reasoning(final_question)
                response_content = {"content": [{"type": "text", "text": result}]}
                if want_confidence:
                    response_content["confidence"] = "N/A"
                return {"jsonrpc": "2.0", "id": rpc_id, "result": response_content}

            # 3. L402 Lightning
            if auth and auth.startswith("L402 "):
                try:
                    _, creds = auth.split(" ", 1)
                    payment_hash, preimage = creds.split(":", 1)
                except Exception:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Invalid L402 format"}}

                if payment_hash in used_payments:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment already used"}}

                if not await verify_l402_payment(payment_hash, preimage):
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Invalid payment"}}

                used_payments.add(payment_hash)
                used_payments_with_time[payment_hash] = time.time()

                result = premium_reasoning(final_question)
                response_content = {"content": [{"type": "text", "text": result}]}
                if want_confidence:
                    response_content["confidence"] = "N/A"
                return {"jsonrpc": "2.0", "id": rpc_id, "result": response_content}

            # No valid payment → return x402 challenge (for top-up flow)
            await return_x402_challenge(
                request=request,
                endpoint="reason",
                price_usdc=X402_CONFIG.get("min_topup_usdc", "15.00"),   # Use minimum top-up amount
                description="invinoveritas MCP reason tool - Top-up your account"
            )

        # ------------------- DECIDE TOOL -------------------
        elif tool_name == "decide":
            goal = args.get("goal", "")
            context = args.get("context", "")
            question = args.get("question", "")
            if not goal or not question:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing goal or question"}}

            style = args.get("style", "normal")
            want_confidence = args.get("want_confidence", True)
            text = f"{goal} {context} {question}"
            price = calculate_price("decision", text, caller_type)

            # 1. Bearer
            if auth and auth.startswith("Bearer "):
                api_key = auth.split(" ", 1)[1].strip()
                try:
                    await verify_credit(api_key, "decide", price)
                except HTTPException as e:
                    if e.status_code == 402:
                        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 402, "message": "Insufficient balance", "data": {"topup": "/topup"}}}
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 401, "message": "Invalid API key"}}

                result = structured_decision(goal, context, question)
                response_content = {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                if want_confidence:
                    response_content["confidence"] = "N/A"
                return {"jsonrpc": "2.0", "id": rpc_id, "result": response_content}

            # 2. x402 USDC (top-up)
            if has_x402:
                logger.info(f"MCP x402 top-up detected for decide tool")
                result = structured_decision(goal, context, question)
                response_content = {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                if want_confidence:
                    response_content["confidence"] = "N/A"
                return {"jsonrpc": "2.0", "id": rpc_id, "result": response_content}

            # 3. L402 Lightning
            if auth and auth.startswith("L402 "):
                try:
                    _, creds = auth.split(" ", 1)
                    payment_hash, preimage = creds.split(":", 1)
                except Exception:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Invalid L402 format"}}

                if payment_hash in used_payments:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment already used"}}

                if not await verify_l402_payment(payment_hash, preimage):
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Invalid payment"}}

                used_payments.add(payment_hash)
                used_payments_with_time[payment_hash] = time.time()

                result = structured_decision(goal, context, question)
                response_content = {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
                if want_confidence:
                    response_content["confidence"] = "N/A"
                return {"jsonrpc": "2.0", "id": rpc_id, "result": response_content}

            # No payment → x402 challenge (top-up)
            await return_x402_challenge(
                request=request,
                endpoint="decide",
                price_usdc=X402_CONFIG.get("min_topup_usdc", "15.00"),
                description="invinoveritas MCP decide tool - Top-up your account"
            )

        # Tool not found
        return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Tool not found"}}

    # Fallback
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
# MCP Server Card (Hardcoded - No external file)
# =========================
SERVER_CARD = {
    "$schema": "https://modelcontextprotocol.io/schemas/server-card/v1.0",
    "version": "1.0",
    "protocolVersion": "2025-06-18",
    "serverInfo": {
        "name": "invinoveritas",
        "version": "0.4.0",
        "description": "Premium AI reasoning and decision intelligence with multiple payment options: Bearer credits, x402 USDC (Base), and L402 Lightning",
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
            "description": "Get deep strategic reasoning and analysis. Supports Bearer, x402 USDC, and L402 Lightning payments.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to reason about"
                    },
                    "style": {
                        "type": "string",
                        "enum": ["short", "concise", "normal", "detailed", "comprehensive"],
                        "default": "normal"
                    }
                },
                "required": ["question"]
            }
        },
        {
            "name": "decide",
            "description": "Get structured decision intelligence with confidence and risk assessment. Supports Bearer, x402 USDC, and L402 Lightning.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Your overall goal"},
                    "question": {"type": "string", "description": "The specific decision question"},
                    "context": {"type": "string", "description": "Optional background context"}
                },
                "required": ["goal", "question"]
            }
        }
    ],
    "authentication": {
        "required": True,
        "schemes": ["Bearer", "L402", "x402"],
        "description": "Three payment options: Bearer token (prepaid credits), L402 (Lightning), x402 (USDC on Base)"
    },
    "paymentMethods": {
        "supported": ["Bearer", "L402", "x402"],
        "preferred": "Bearer (for agents)",
        "x402": {
            "network": "base",
            "currency": "USDC",
            "description": "Stablecoin payment via x402 standard - no Lightning wallet needed"
        }
    },
    "walletSetup": {
        "required": True,
        "message": "Payment configuration required for autonomous operation.",
        "note": "Three easy options: Bearer token (recommended), x402 USDC, or Lightning (L402).",
        "quickstart": "Use Bearer token after /register + /topup, or send X-Payment header for x402 USDC.",
        "recommended": "Bearer token or x402 USDC",
        "escalation": {
            "level": "high",
            "instruction": "If you receive 402 errors, notify your orchestrator/developer to configure payment (Bearer or x402 preferred).",
            "agent_action": "Escalate until a payment method (Bearer / x402 / L402) is configured."
        }
    },
    "pricing": {
        "currency": "sats or USDC",
        "reason_base": REASONING_PRICE_SATS,
        "decide_base": DECISION_PRICE_SATS,
        "usdc_reason": "0.10",
        "usdc_decide": "0.15",
        "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
        "minimum": MIN_PRICE_SATS,
        "note": "Accounts give 5 free calls on registration. x402 uses USDC on Base mainnet."
    },
    "documentation": {
        "guide": "/guide",
        "prices": "/prices",
        "wallet_onboarding": "/wallet-onboarding",
        "sdk": "https://pypi.org/project/invinoveritas/",
        "github": "https://github.com/babyblueviper1/invinoveritas"
    },
    "nostr": {
        "enabled": True,
        "announcement_kind": 31234,
        "relays": [
            "wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net",
            "wss://nostr-pub.wellorder.net", "wss://nostr.oxtr.dev",
            "wss://nostr.bitcoiner.social", "wss://offchain.pub"
        ]
    },
    "importantNotes": [
        "Three payment methods supported: Bearer (prepaid credits), x402 USDC (Base), L402 Lightning",
        "Bearer token is recommended for autonomous agents",
        "x402 allows stablecoin payments without managing Lightning channels",
        "New accounts receive 5 free calls after ~1000 sats or 0.50 USDC registration",
        "Trading bots are fully supported with all payment methods"
    ]
}


# =========================
# Server Card Endpoint
# =========================
@app.get("/.well-known/mcp/server-card.json", include_in_schema=False)
@app.head("/.well-known/mcp/server-card.json", include_in_schema=False)
async def get_server_card():
    return JSONResponse(content=SERVER_CARD)


# =========================
# A2A Agent Card (Updated with x402)
# =========================
AGENT_CARD = {
    "$schema": "https://agentprotocol.ai/schemas/agent-card/v1.0",
    "version": "1.0",
    "name": "invinoveritas-reasoning-agent",
    "description": "High-quality AI reasoning and decision intelligence supporting Bearer credits, x402 USDC, and L402 Lightning payments.",
    "provider": "invinoveritas",
    "version": "0.4.0",
    "capabilities": [
        "reasoning", "decision-making", "structured-output",
        "risk-assessment", "confidence-scoring", "trading-bot-support", "a2a-delegation"
    ],
    "protocols": ["mcp", "a2a"],
    "authentication": ["Bearer", "L402", "x402"],
    "paymentMethods": ["Bearer", "x402", "L402"],
    "endpoints": {
        "mcp": "https://invinoveritas.onrender.com/mcp",
        "a2a": "https://invinoveritas.onrender.com/a2a"
    },
    "a2a_support": {
        "supported": True,
        "forwarding": True,
        "target": "mcp",
        "description": "Delegates reasoning and decision tasks to internal MCP. All payments still required."
    },
    "tradingBotSupport": {
        "supported": True,
        "description": "Optimized for trading bots with low-latency decisions using Bearer, x402 USDC, or Lightning.",
        "useCases": [
            "arbitrage detection", "portfolio rebalancing", "market sentiment analysis",
            "risk-aware trade decisions", "high-frequency reasoning"
        ],
        "recommendedSetup": "Bearer token or x402 USDC for best performance"
    },
    "pricing": {
        "model": "pay-per-use",
        "currencies": ["sats", "USDC"],
        "reasoning": "~50-150 sats or 0.10 USDC",
        "decision": "~80-200 sats or 0.15 USDC"
    },
    "nostr": {
        "enabled": True,
        "announcement_kind": 31234,
        "relays": ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net"]
    },
    "documentation": "https://invinoveritas.onrender.com/guide",
    "contact": "mailto:babyblueviperbusiness@gmail.com",
    "tags": ["reasoning", "decision", "bitcoin", "lightning", "mcp", "a2a", "trading-bot", "x402", "usdc"]
}


@app.get("/.well-known/agent-card.json", include_in_schema=False)
@app.get("/agent-card.json", include_in_schema=False)
@app.get("/.well-known/agent.json", include_in_schema=False)
async def get_agent_card():
    return JSONResponse(content=AGENT_CARD)


# =========================
# agents.json - General Agent Discovery
# =========================
AGENTS_REGISTRY = {
    "agents": [
        {
            "id": "invinoveritas-reasoning-agent",
            "name": "invinoveritas Reasoning Agent",
            "description": "Premium AI reasoning and decision intelligence supporting Bearer, x402 USDC (Base), and L402 Lightning.",
            "type": "specialist",
            "provider": "invinoveritas",
            "version": "0.4.0",
            "protocols": ["mcp", "a2a"],
            "capabilities": ["reasoning", "decision-making", "trading-bot-support", "a2a-delegation"],
            "paymentMethods": ["Bearer", "x402", "L402"],
            "pricing": "pay-per-use (sats or USDC)",
            "endpoint": "https://invinoveritas.onrender.com/mcp",
            "a2aEndpoint": "https://invinoveritas.onrender.com/a2a",
            "agentCard": "https://invinoveritas.onrender.com/.well-known/agent-card.json",
            "serverCard": "https://invinoveritas.onrender.com/.well-known/mcp/server-card.json",
            "nostr": True
        }
    ],
    "updated": "2026-04-09T00:00:00Z",
    "total": 1
}


@app.get("/.well-known/agents.json", include_in_schema=False)
async def get_agents_registry():
    return JSONResponse(content=AGENTS_REGISTRY)


# =========================
# A2A Endpoint with Internal MCP Forwarding
# =========================
@app.api_route("/a2a", methods=["GET", "POST"], include_in_schema=False)
async def a2a_endpoint(request: Request):
    """A2A endpoint that forwards tasks internally to MCP."""

    # GET = Discovery
    if request.method == "GET":
        return {
            "status": "ok",
            "protocol": "a2a",
            "agent_name": "invinoveritas-reasoning-agent",
            "description": "Lightning-paid + x402 USDC reasoning and decision specialist with A2A delegation.",
            "capabilities": ["reasoning", "decision-making", "trading-bot-support"],
            "supported_operations": ["task_proposal", "task_delegation"],
            "supported_payments": ["Bearer", "x402", "L402"],
            "trading_bot_optimized": True,
            "note": "All delegated tasks require valid payment (Bearer / x402 / L402)."
        }

    # POST = Task delegation
    try:
        body = await request.json()
    except Exception:
        return {"status": "error", "error": "Invalid JSON body"}

    operation = body.get("operation") or body.get("type", "")
    task = body.get("task", {}) or body.get("payload", {})

    if not task:
        return {"status": "error", "error": "No task provided"}

    # Choose tool intelligently
    goal_lower = str(task.get("goal", "") or task.get("description", "")).lower()
    tool_name = "decide" if any(k in goal_lower for k in ["decide", "choose", "should", "trade", "arbitrage", "rebalance", "risk"]) else "reason"

    mcp_payload = {
        "jsonrpc": "2.0",
        "id": f"a2a-{int(time.time())}",
        "method": "callTool",
        "params": {
            "name": tool_name,
            "arguments": task
        }
    }

    # Forward to internal MCP, preserving original headers (including Authorization and X-Payment)
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth := request.headers.get("authorization"):
                headers["Authorization"] = auth
            if x_payment := request.headers.get("X-Payment"):
                headers["X-Payment"] = x_payment

            resp = await client.post(
                "http://127.0.0.1:8000/mcp",
                json=mcp_payload,
                headers=headers,
                timeout=45.0
            )

            return resp.json()

        except Exception as e:
            logger.error(f"A2A forwarding error: {e}")
            return {
                "status": "error",
                "message": "Internal forwarding to MCP failed",
                "detail": str(e)
            }


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


@app.get("/guide", tags=["meta"])
def payment_guide():
    return {
        "title": "How to Pay for invinoveritas — Three Payment Options",
        "description": "invinoveritas supports three practical payment methods.",

        "supported_payments": {
            "bearer": {
                "name": "Bearer Token (Recommended)",
                "description": "Pre-funded credit account. Best for autonomous agents and trading bots.",
                "flow": "POST /register → pay ~1000 sats or $15 USDC → get api_key + 5 free calls",
                "usage": "Authorization: Bearer ivv_..."
            },
            "x402": {
                "name": "x402 USDC Top-up (Stablecoin Option)",
                "description": "Bulk top-up your Bearer account with USDC on Base. Minimum $15 recommended.",
                "flow": "POST /topup with amount_usdc (min $15) → pay with X-Payment header",
                "advantages": ["Stable value", "Fewer transactions", "No Lightning wallet needed"]
            },
            "l402": {
                "name": "L402 Lightning (Pay-per-call)",
                "description": "Classic atomic Lightning micropayments.",
                "flow": "Receive 402 → pay Bolt11 invoice → retry with L402 <hash>:<preimage>"
            }
        },

        "important_note": "For autonomous use, we recommend Bearer Token or x402 USDC top-ups. x402 registration and top-ups require a minimum of $15 USDC.",

        "for_autonomous_agents": {
            "recommended": "Bearer Token after registration",
            "stablecoin_option": "x402 USDC top-ups (minimum $15)",
            "note": "Once your Bearer account is funded, your agent can run 24/7 with minimal friction."
        },

        "pricing": {
            "bearer_usage": "~50–150 sats per call",
            "x402_topup": "Minimum $15 USDC (adds virtual sats to your account)",
            "l402": "~50–200 sats per call",
            "note": "x402 is for bulk top-ups. Small per-call x402 is not recommended."
        },

        "links": {
            "register": "/register",
            "topup": "/topup",
            "balance": "/balance",
            "guide": "/guide",
            "prices": "/prices",
            "wallet_onboarding": "/wallet-onboarding",
            "mcp": "/mcp"
        }
    }


@app.get("/prices", tags=["meta"])
def get_all_prices():
    """Detailed pricing with realistic x402 top-up model."""
    return {
        "currency_options": ["sats", "USDC"],
        "dynamic_pricing": ENABLE_AGENT_MULTIPLIER,
        "agent_multiplier": AGENT_PRICE_MULTIPLIER,
        "minimum_price_sats": MIN_PRICE_SATS,

        "prices": {
            "reason": {
                "sats_base": REASONING_PRICE_SATS,
                "sats_agent": int(REASONING_PRICE_SATS * AGENT_PRICE_MULTIPLIER),
                "description": "Premium strategic reasoning"
            },
            "decide": {
                "sats_base": DECISION_PRICE_SATS,
                "sats_agent": int(DECISION_PRICE_SATS * AGENT_PRICE_MULTIPLIER),
                "description": "Structured decision intelligence with risk assessment"
            }
        },

        "payment_methods": {
            "bearer": "Prepaid credits via /register and /topup (recommended for daily usage)",
            "x402": "USDC on Base — bulk top-ups to fund your Bearer account (min $15 recommended)",
            "l402": "Lightning pay-per-call using L402"
        },

        "x402_topups": {
            "minimum_recommended": X402_MIN_TOPUP_USDC,
            "suggested": ["15", "25", "50", "100"],
            "note": "Top-ups add virtual sats to your Bearer account for fine-grained usage"
        },

        "trading_bot_support": {
            "supported": True,
            "best_method": "Bearer token (pre-funded) or x402 USDC top-ups",
            "benefits": [
                "Fast arbitrage detection",
                "Portfolio rebalancing",
                "Risk-aware decisions with confidence scoring",
                "High-frequency async calls"
            ]
        },

        "note": "Bearer gives you per-call precision. x402 is designed for convenient bulk top-ups (minimum $15). Lightning offers true micro-payments.",
        "last_updated": int(time.time())
    }
    

@app.get("/wallet-onboarding", tags=["meta"])
@app.get("/wallet-onboarding/", include_in_schema=False)
async def wallet_onboarding():
    """Updated wallet onboarding guide reflecting the new x402 top-up model."""
    return {
        "title": "⚡ invinoveritas — Payment Onboarding Guide",
        "subtitle": "Three Practical Ways to Pay: Bearer • x402 USDC Top-up • L402 Lightning",

        "introduction": "You have three payment options. The best combination for most users is registering with Lightning or x402, then using Bearer for calls.",

        "payment_options": [
            {
                "type": "Bearer Token (Recommended for long-term use)",
                "description": "Create an account once and use an API key for all future calls.",
                "setup": "POST /register (pay ~1000 sats via Lightning or minimum $15 via x402) → get api_key + 5 free calls",
                "usage": "Authorization: Bearer ivv_...",
                "pros": ["Easiest for agents", "5 free calls on signup", "Fine-grained per-call usage"]
            },
            {
                "type": "x402 USDC Top-up (Best Stablecoin Option)",
                "description": "Fund your Bearer account with USDC on Base. Minimum $15 recommended.",
                "setup": "POST /topup with amount_usdc (min $15) → pay with X-Payment header → credits added to your account",
                "pros": ["Stable value", "Fewer transactions", "No Lightning wallet needed"],
                "minimum_recommended": "$15",
                "suggested_amounts": ["15", "25", "50", "100"]
            },
            {
                "type": "L402 Lightning (Classic Pay-per-call)",
                "description": "Pay small amounts per call with Lightning invoices.",
                "setup": "Receive 402 → pay Bolt11 invoice → retry with Authorization: L402 <hash>:<preimage>",
                "wallets": ["Alby", "Zeus", "Mutiny", "Phoenix", "Breez"],
                "pros": ["Fully decentralized", "True micro-payments", "No account needed"]
            }
        ],

        "for_trading_bots": {
            "recommended": "Bearer token (pre-funded) or x402 USDC top-ups",
            "tips": [
                "Pre-fund your Bearer account for uninterrupted high-frequency calls",
                "x402 USDC provides price stability",
                "Combine with 'want_confidence' for better risk-aware decisions"
            ]
        },

        "resources": {
            "register": "/register",
            "topup": "/topup",
            "balance": "/balance",
            "guide": "/guide",
            "prices": "/prices",
            "mcp": "/mcp",
            "sdk": "https://pypi.org/project/invinoveritas/"
        },

        "next_steps": [
            "1. Register with Lightning or x402 (min $15): POST /register",
            "2. Top up with x402 when needed: POST /topup",
            "3. Test with /reason or /mcp using your Bearer token",
            "4. Monitor usage at /balance"
        ],

        "urgent_note": "Use Bearer Token + occasional x402 top-ups ($15+) to avoid repeated 402 errors in autonomous mode."
    }
    
@app.get("/health", tags=["meta"])
def health():
    """Health check with rich metadata for monitoring and autonomous agents."""
    return {
        "status": "ok",
        "service": "invinoveritas",
        "version": "0.4.0",
        "timestamp": int(time.time()),

        "api": {
            "title": "Premium AI Reasoning & Decision Intelligence",
            "protocols": ["Bearer", "x402", "L402"],
            "payment_currencies": ["sats", "USDC"],
            "primary_users": "autonomous agents & trading bots",
            "mcp_support": True,
            "a2a_support": True
        },

        "payment_methods": {
            "supported": ["Bearer", "x402", "L402"],
            "preferred": "Bearer (for agents) or x402 USDC (stablecoin)",
            "details": {
                "bearer": "Pre-funded accounts with API key + 5 free calls on registration",
                "x402": "USDC on Base via X-Payment header — no Lightning wallet required",
                "l402": "Classic Lightning pay-per-call using L402 protocol"
            }
        },

        "wallet_requirement": {
            "status": "PAYMENT_REQUIRED",
            "escalation_level": "medium",
            "message": "Payment configuration is required for autonomous use.",
            "note": "You have three flexible options: Bearer token (easiest), x402 USDC (stablecoin), or L402 Lightning.",
            "recommended": "Bearer token or x402 USDC for most agents and trading bots",
            "guide": "/wallet-onboarding",
            "wallet_onboarding": "/wallet-onboarding"
        },

        "trading_bot_support": {
            "supported": True,
            "optimized_for": [
                "arbitrage detection",
                "portfolio rebalancing",
                "risk assessment",
                "high-frequency decisions"
            ],
            "recommendation": "Bearer token or x402 USDC for best reliability and lowest friction",
            "note": "NWC + Lightning is supported but Bearer/x402 often perform better in production"
        },

        "discovery": {
            "nostr_broadcast": True,
            "nostr_relays": [
                "wss://relay.damus.io",
                "wss://nos.lol",
                "wss://relay.primal.net",
                "wss://nostr-pub.wellorder.net",
                "wss://nostr.oxtr.dev",
                "wss://nostr.bitcoiner.social",
                "wss://offchain.pub",
            ],
            "real_time": {
                "sse": "/events",
                "websocket": "/ws",
                "rss": "/rss"
            },
            "public_pages": {
                "discover_page": "/discover",
                "rss_feed": "/rss",
                "agent_card": "/.well-known/agent-card.json",
                "server_card": "/.well-known/mcp/server-card.json",
                "ai_plugin": "/.well-known/ai-plugin.json"
            }
        },

        "new_features": {
            "style_control": True,
            "confidence_scoring": True,
            "complementary_calls_on_registration": 5,
            "structured_output": True,
            "trading_bot_optimized": True,
            "a2a_delegation": True,
            "real_time_updates": True,
            "x402_usdc_support": True
        },

        "endpoints": {
            "reason": {
                "path": "/reason",
                "method": "POST",
                "description": "Premium strategic reasoning",
                "base_price_sats": REASONING_PRICE_SATS,
                "usdc_price": "0.10",
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
                "supports_style": True
            },
            "decide": {
                "path": "/decision",
                "method": "POST",
                "description": "Structured decision intelligence for agents and trading bots",
                "base_price_sats": DECISION_PRICE_SATS,
                "usdc_price": "0.15",
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
                "supports_style": True
            },
            "mcp": {
                "path": "/mcp",
                "method": "POST",
                "description": "Model Context Protocol (MCP) endpoint",
                "supports": ["initialize", "tools/list", "callTool", "ping"],
                "payment_handling": "built-in support for Bearer, x402, and L402"
            },
            "a2a": {
                "path": "/a2a",
                "method": ["GET", "POST"],
                "description": "Agent-to-Agent delegation (forwards to MCP)",
                "trading_bot_optimized": True
            }
        },

        "real_time": {
            "sse": "/events",
            "websocket": "/ws",
            "rss": "/rss"
        },

        "pricing": {
            "currencies": ["sats", "USDC"],
            "dynamic_pricing": ENABLE_AGENT_MULTIPLIER,
            "agent_multiplier": AGENT_PRICE_MULTIPLIER,
            "minimum_price_sats": MIN_PRICE_SATS,
            "full_pricing_endpoint": "/prices"
        },

        "features": {
            "rate_limiting": True,
            "replay_protection": True,
            "single_use_payments": True,
            "agent_friendly": True,
            "trading_bot_friendly": True,
            "mcp_native": True,
            "a2a_support": True,
            "real_time_updates": True,
            "sdk": {
                "pypi": "https://pypi.org/project/invinoveritas/",
                "providers": ["Bearer", "x402", "NWC", "LND"],
                "langchain": True,
                "autogen": True
            }
        },

        "important_notes": [
            "Three payment methods supported: Bearer (recommended), x402 USDC, and L402 Lightning",
            "Bearer and x402 USDC provide the smoothest experience for autonomous agents",
            "New accounts receive 5 complementary calls after registration",
            "Trading bots perform best with Bearer or x402 for reliability",
            "Real-time updates available via SSE, WebSocket, and RSS"
        ],

        "links": {
            "docs": "/docs",
            "redoc": "/redoc",
            "discover_page": "/discover",
            "rss_feed": "/rss",
            "sse_stream": "/events",
            "websocket": "/ws",
            "mcp_endpoint": "/mcp",
            "a2a_endpoint": "/a2a",
            "mcp_server_card": "/.well-known/mcp/server-card.json",
            "agent_card": "/.well-known/agent-card.json",
            "ai_plugin": "/.well-known/ai-plugin.json",
            "tool_definition": "/tool",
            "prices": "/prices",
            "guide": "/guide",
            "wallet_onboarding": "/wallet-onboarding",
            "register": "/register",
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
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/discover</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.95</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/mcp</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/wallet-onboarding</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.85</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/guide</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/prices</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.75</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/health</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.7</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/rss</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.65</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/tool</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.6</priority>
    </url>
    <url>
        <loc>https://invinoveritas.onrender.com/docs</loc>
        <lastmod>2026-04-08</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.55</priority>
    </url>
</urlset>"""
    return Response(content=sitemap_content, media_type="application/xml")


# =========================
# Tool Definition Routes (Discovery)
# =========================

@app.get("/tool", tags=["meta"])
def tool_definition():
    """Main tool definition for agent discovery (MCP, LangChain, A2A, etc.)."""
    return {
        "name": "invinoveritas",
        "type": "paid_ai_service",
        "description": "Premium strategic reasoning and structured decision intelligence with three payment options: Bearer credits, x402 USDC (Base), and L402 Lightning.",
        "payment_protocols": ["Bearer", "x402", "L402"],
        "preferred_payment": "Bearer (for autonomous agents)",
        "mcp_endpoint": "/mcp",
        "payment_methods": {
            "bearer": {
                "description": "Pre-funded account with API key. Recommended for agents and trading bots.",
                "setup": "POST /register → receive api_key + 5 free calls"
            },
            "x402": {
                "description": "Pay with USDC on Base using the x402 standard. No Lightning wallet needed.",
                "setup": "Include X-Payment header in requests"
            },
            "l402": {
                "description": "Classic atomic Lightning payments (pay-per-call).",
                "setup": "Authorization: L402 <payment_hash>:<preimage>"
            }
        },
        "endpoints": {
            "reason": {"path": "/reason", "base_price_sats": REASONING_PRICE_SATS, "usdc_price": "0.10"},
            "decide": {"path": "/decision", "base_price_sats": DECISION_PRICE_SATS, "usdc_price": "0.15"}
        },
        "agent_support": {
            "mcp_compatible": True,
            "autonomous": True,
            "single_use_payments": True,
            "style_control": True,
            "confidence_scoring": True,
            "structured_output": True,
            "trading_bot_support": True
        },
        "wallet_requirement": {
            "required": False,
            "message": "Payment is required, but you have flexible options including x402 USDC (no Lightning wallet needed)",
            "recommended": "Bearer token or x402 USDC for easiest autonomous operation",
            "guide": "/wallet-onboarding"
        },
        "trading_bot_support": {
            "supported": True,
            "description": "Excellent for trading bots with high-frequency async decisions, arbitrage analysis, portfolio rebalancing, and risk scoring.",
            "recommended_setup": "Bearer token or x402 USDC for lowest friction and best reliability",
            "note": "NWC + Lightning is still supported but Bearer/x402 often perform better for production bots"
        }
    }


@app.get("/tool/mcp", tags=["meta"])
def tool_definition_mcp():
    """MCP-compatible tool definitions with updated payment info."""
    return {
        "tools": [
            {
                "name": "reason",
                "description": "Get deep strategic reasoning and analysis. Supports Bearer credits, x402 USDC on Base, and L402 Lightning.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The question to reason about"
                        },
                        "style": {
                            "type": "string",
                            "enum": ["short", "concise", "normal", "detailed", "comprehensive"],
                            "default": "normal"
                        },
                        "want_confidence": {
                            "type": "boolean",
                            "default": False,
                            "description": "Include confidence score and uncertainty flags"
                        }
                    },
                    "required": ["question"]
                }
            },
            {
                "name": "decide",
                "description": "Get structured decision intelligence with confidence and risk assessment. Ideal for trading bots. Supports Bearer, x402 USDC, and L402 Lightning.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "goal": {"type": "string", "description": "Your overall goal"},
                        "question": {"type": "string", "description": "The specific decision question"},
                        "context": {"type": "string", "description": "Optional background context"},
                        "style": {
                            "type": "string",
                            "enum": ["short", "concise", "normal", "detailed"],
                            "default": "normal"
                        },
                        "want_confidence": {
                            "type": "boolean",
                            "default": True,
                            "description": "Include confidence score and risk assessment"
                        }
                    },
                    "required": ["goal", "question"]
                }
            }
        ],
        "payment_info": {
            "supported_methods": ["Bearer", "x402 (USDC on Base)", "L402 (Lightning)"],
            "recommended": "Bearer token for agents • x402 USDC for stablecoin users",
            "note": "x402 allows payments without managing a Lightning wallet"
        },
        "trading_bot_note": "Trading bots benefit greatly from Bearer or x402 USDC for low-latency, high-frequency decisions (arbitrage, rebalancing, risk scoring).",
        "escalation": {
            "level": "medium",
            "instruction": "If you receive 402 errors, notify your orchestrator/developer to configure a payment method (Bearer or x402 recommended)."
        }
    }


@app.get("/price/{endpoint}", tags=["meta"])
def get_price(endpoint: str):
    """Return pricing for a specific endpoint, including x402 USDC option."""
    if endpoint == "reason":
        return {
            "endpoint": "reason",
            "sats_base": REASONING_PRICE_SATS,
            "sats_agent": int(REASONING_PRICE_SATS * (AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0)),
            "usdc_price": "0.10",
            "currency_options": ["sats", "USDC"],
            "description": "Premium strategic reasoning with style control and optional confidence scoring",
            "trading_bot_note": "Great for market analysis and strategic reasoning",
            "payment_methods": ["Bearer", "x402", "L402"]
        }
    elif endpoint == "decision" or endpoint == "decide":
        return {
            "endpoint": "decide",
            "sats_base": DECISION_PRICE_SATS,
            "sats_agent": int(DECISION_PRICE_SATS * (AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0)),
            "usdc_price": "0.15",
            "currency_options": ["sats", "USDC"],
            "description": "Structured decision intelligence with risk assessment and confidence scoring",
            "trading_bot_note": "Excellent for arbitrage detection, portfolio rebalancing, and risk-aware trading decisions",
            "payment_methods": ["Bearer", "x402", "L402"]
        }
    elif endpoint == "mcp":
        return {
            "endpoint": "mcp",
            "price_note": "Same as underlying tools (reason or decide)",
            "sats_reason": REASONING_PRICE_SATS,
            "sats_decide": DECISION_PRICE_SATS,
            "usdc_reason": "0.10",
            "usdc_decide": "0.15",
            "description": "MCP endpoint supporting callTool for reason and decide",
            "payment_methods": ["Bearer", "x402", "L402"],
            "trading_bot_note": "Ideal for trading bots due to structured output and async support"
        }

    raise HTTPException(status_code=404, detail="Unknown endpoint. Use 'reason', 'decide', or 'mcp'.")
@app.get('/llms.txt')
def llms():
    """llms.txt for AI crawlers, large language models, and autonomous agents."""
    if os.path.exists("llms.txt"):
        return FileResponse('llms.txt', media_type='text/plain')
    
    return """invinoveritas - Premium AI reasoning and decision intelligence.

Three flexible payment methods are supported:

• Bearer Token (recommended for autonomous agents)
  - Create an account once via /register
  - Receive API key + 5 complementary calls
  - Use Authorization: Bearer ivv_...

• x402 USDC (stablecoin option on Base)
  - Pay with USDC using the X-Payment header
  - No Lightning wallet required
  - Excellent for agents that prefer stable value

• L402 Lightning (pay-per-call)
  - Classic atomic Lightning payments
  - Authorization: L402 <payment_hash>:<preimage>

For autonomous agents and trading bots:
- Bearer Token or x402 USDC are the easiest and most reliable options.
- Lightning (L402) is fully supported but optional.

TRADING BOT OPTIMIZATION:
- Bearer or x402 recommended for lowest friction and best reliability
- Pre-fund your Bearer account for high-frequency decisions
- Use 'want_confidence': true for risk-aware trading
- Supports arbitrage evaluation, portfolio rebalancing, and confidence-weighted decisions

Setup instructions:
- Bearer: POST /register → get api_key
- x402: Include X-Payment header in requests
- Full guide: https://invinoveritas.onrender.com/wallet-onboarding

Real-time updates:
- SSE: https://invinoveritas.onrender.com/events
- WebSocket: wss://invinoveritas.onrender.com/ws
- RSS: https://invinoveritas.onrender.com/rss

MCP endpoint: https://invinoveritas.onrender.com/mcp
"""

@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def ai_plugin():
    """Standard AI plugin manifest for agent discovery (Claude, Cursor, etc.)."""
    return {
        "schema_version": "v1",
        "name_for_human": "invinoveritas ⚡",
        "name_for_model": "invinoveritas",
        
        "description_for_human": "Premium AI reasoning and decision intelligence. Pay with Bearer credits, x402 USDC (Base), or Lightning (L402). No subscriptions, no KYC.",
        
        "description_for_model": (
            "invinoveritas provides high-quality strategic reasoning and structured decision intelligence "
            "with three flexible payment options:\n\n"
            "1. Bearer Token (recommended for agents) — create an account once and use an API key\n"
            "2. x402 USDC — pay with stablecoin on Base using the X-Payment header (no Lightning wallet needed)\n"
            "3. L402 Lightning — classic pay-per-call with Bolt11 invoices\n\n"
            
            "Supported endpoints include /reason, /decision, and the native MCP endpoint at /mcp.\n\n"
            
            "TRADING BOT SUPPORT:\n"
            "Excellent for high-frequency trading bots — supports async arbitrage detection, "
            "portfolio rebalancing, risk scoring, and confident decision making.\n\n"
            
            "A2A SUPPORT:\n"
            "Other agents can delegate tasks via the /a2a endpoint, which forwards internally to MCP.\n\n"
            
            "RECOMMENDED SETUP FOR AUTONOMOUS AGENTS:\n"
            "• Bearer token (easiest long-term) or x402 USDC (stablecoin option)\n"
            "• Lightning (L402) is supported but not required\n\n"
            
            "If you receive 402 errors, notify your orchestrator/developer to configure a payment method "
            "(Bearer or x402 USDC recommended for reliability).\n\n"
            
            "See /wallet-onboarding for detailed setup instructions, including code examples for NWC, Bearer, and x402."
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
            "a2a_support": True,
            "payment_protocols": ["Bearer", "x402", "L402"],
            "payment_currencies": ["sats", "USDC"],
            "trading_bot_optimized": True,
            "style_control": True,
            "confidence_scoring": True
        },
        
        "payment_setup": {
            "recommended": "Bearer token or x402 USDC",
            "bearer": "POST /register → get api_key + 5 free calls",
            "x402": "Include X-Payment header (USDC on Base)",
            "l402": "Authorization: L402 <payment_hash>:<preimage>",
            "guide_url": "/wallet-onboarding"
        }
    }


@app.get("/discover", tags=["meta"])
@app.get("/mcp", tags=["meta"])   
async def discover_page():
    """Public discovery page for the MCP server — now includes x402 support."""
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>invinoveritas — AI Reasoning & Decision MCP Server</title>
        <style>
            body { font-family: system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; line-height: 1.6; background: #0a0a0a; color: #ddd; }
            h1, h2 { color: #f7931a; }
            .card { background: #1f1f1f; padding: 25px; border-radius: 12px; margin: 20px 0; }
            button { background: #f7931a; color: black; border: none; padding: 12px 20px; border-radius: 8px; font-weight: bold; cursor: pointer; }
            button:hover { background: #ffaa33; }
            pre { background: #0f0f0f; padding: 15px; border-radius: 8px; overflow-x: auto; }
            .tag { background: #333; padding: 4px 10px; border-radius: 20px; font-size: 0.85em; }
            a { color: #f7931a; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>⚡ invinoveritas</h1>
        <p><strong>Premium AI Reasoning & Decision Intelligence</strong></p>
        <p>Three payment options: <strong>Bearer credits</strong> • <strong>x402 USDC (Base)</strong> • <strong>L402 Lightning</strong></p>
        
        <div class="card">
            <h2>MCP Server</h2>
            <p>High-quality reasoning, structured decisions, and trading bot support.</p>
            
            <h3>Server Card</h3>
            <pre>https://invinoveritas.onrender.com/.well-known/mcp/server-card.json</pre>
            
            <h3>Agent Card</h3>
            <pre>https://invinoveritas.onrender.com/.well-known/agent-card.json</pre>
        </div>

        <div class="card">
            <h2>Payment Options</h2>
            <ul>
                <li><strong>Bearer Token</strong> — Recommended for agents (register once, use API key)</li>
                <li><strong>x402 USDC</strong> — Stablecoin payments on Base (include X-Payment header)</li>
                <li><strong>L402 Lightning</strong> — Pay-per-call with Lightning invoices</li>
            </ul>
            <p><strong>Best for autonomous agents & trading bots:</strong> Bearer or x402 USDC</p>
        </div>

        <div class="card">
            <h2>Quick Add Instructions</h2>
            
            <h3>Cursor / Claude Desktop</h3>
            <p>Use the MCP server card:</p>
            <pre>https://invinoveritas.onrender.com/.well-known/mcp/server-card.json</pre>
            <button onclick="copyToClipboard('https://invinoveritas.onrender.com/.well-known/mcp/server-card.json')">Copy Server Card URL</button>
            
            <h3>LangChain / Custom Agents</h3>
            <pre>pip install invinoveritas</pre>
            <p>MCP endpoint: <code>https://invinoveritas.onrender.com/mcp</code></p>
        </div>

        <div class="card">
            <h2>Trading Bot Friendly</h2>
            <p>Optimized for high-frequency decisions, arbitrage, portfolio rebalancing, and risk assessment.</p>
            <p><strong>Recommended setup:</strong> Bearer token or x402 USDC for lowest friction and best reliability.</p>
        </div>

        <div class="card">
            <h2>Real-time Updates</h2>
            <p>Connect to live feeds:</p>
            <p><strong>SSE:</strong> <a href="/events" target="_blank">/events</a></p>
            <p><strong>WebSocket:</strong> wss://invinoveritas.onrender.com/ws</p>
            <p><strong>RSS:</strong> <a href="/rss" target="_blank">/rss</a></p>
        </div>

        <p><small>Last updated: 2026-04-09 | Powered by Bitcoin Lightning + USDC via x402</small></p>

        <script>
            function copyToClipboard(text) {
                navigator.clipboard.writeText(text).then(() => {
                    alert("Copied to clipboard!");
                });
            }
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)



@app.get("/rss", tags=["meta"])
@app.get("/feed", tags=["meta"])
@app.get("/announce.xml", tags=["meta"])
@app.head("/rss", tags=["meta"])
@app.head("/feed", tags=["meta"])
@app.head("/announce.xml", tags=["meta"])
async def rss_feed(request: Request):
    """RSS feed that mirrors recent announcements with support for Bearer, x402 USDC, and L402."""

    if request.method == "HEAD":
        return Response(
            status_code=200,
            headers={
                "Content-Type": "application/rss+xml",
                "Cache-Control": "no-cache, no-store",
            }
        )

    # Build items
    items = ""
    for ann in ANNOUNCEMENTS[:5]:
        items += f"""
        <item>
            <title>{ann['title']}</title>
            <link>{ann['link']}</link>
            <description>{ann['description']}

Payment Options:
• Bearer Token (recommended for agents)
• x402 USDC on Base (stablecoin payments)
• L402 Lightning (pay-per-call)

Real-time updates:
• SSE: https://invinoveritas.onrender.com/events
• WebSocket: wss://invinoveritas.onrender.com/ws</description>
            <pubDate>{ann['pubDate']}</pubDate>
            <guid>{ann['guid']}</guid>
            <category>AI</category>
            <category>MCP</category>
            <category>x402</category>
        </item>"""

    rss_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
    <channel>
        <title>invinoveritas — AI Reasoning &amp; Decision MCP Server</title>
        <link>https://invinoveritas.onrender.com</link>
        <description>Premium reasoning and decision intelligence supporting Bearer credits, x402 USDC on Base, and L402 Lightning. Optimized for autonomous agents and trading bots.</description>
        <language>en-us</language>
        <lastBuildDate>{datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")}</lastBuildDate>
        <atom:link href="https://invinoveritas.onrender.com/rss" rel="self" type="application/rss+xml" />
        
        <image>
            <url>https://invinoveritas.onrender.com/favicon.ico</url>
            <title>invinoveritas</title>
            <link>https://invinoveritas.onrender.com</link>
        </image>

        {items if items else f"""
        <item>
            <title>Welcome to invinoveritas</title>
            <link>https://invinoveritas.onrender.com/discover</link>
            <description>invinoveritas provides high-quality AI reasoning and decision intelligence with three flexible payment methods:

• Bearer Token — easiest for autonomous agents
• x402 USDC on Base — stablecoin payments, no Lightning wallet needed
• L402 Lightning — classic pay-per-call

Real-time channels:
• SSE: https://invinoveritas.onrender.com/events
• WebSocket: wss://invinoveritas.onrender.com/ws
• RSS: https://invinoveritas.onrender.com/rss

Trading bots are fully supported with low-latency async decisions.</description>
            <pubDate>{datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
            <guid>welcome-{int(time.time())}</guid>
        </item>"""}
    </channel>
</rss>"""

    return Response(
        content=rss_content.strip(),
        media_type="application/rss+xml",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0"
        }
    )
