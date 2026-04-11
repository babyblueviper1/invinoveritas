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
import sqlite3
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
load_dotenv()

# =========================
# FastAPI App
# =========================
app = FastAPI(
    title="invinoveritas",
    version="0.5.0",
    description=(
        "Premium AI reasoning and structured decision intelligence for autonomous agents and trading bots. "
        "All payments are processed via the Lightning Network using Bearer Token (recommended) "
        "or classic L402 Lightning pay-per-call. "
        "Accounts with any balance remain active for at least 2 years of inactivity."
    ),
    contact={
        "name": "invinoveritas",
        "email": "babyblueviperbusiness@gmail.com",
        "url": "https://invinoveritas.onrender.com"
    },
    license_info={
        "name": "Apache 2.0",
        "url": "https://www.apache.org/licenses/LICENSE-2.0.html"
    },
    openapi_tags=[
        {"name": "inference", "description": "Reasoning and decision endpoints"},
        {"name": "accounts", "description": "Account management and credit system"},
        {"name": "lightning", "description": "Lightning Network utilities"},
        {"name": "meta", "description": "Health, pricing, and discovery endpoints"},
    ]
)

app.router.redirect_slashes = False

# =========================
# Logging
# =========================
logger = logging.getLogger("invinoveritas")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.oxtr.dev",
    "wss://nostr.bitcoiner.social",
    "wss://offchain.pub",          # open, no restrictions
    
]

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
 
# ── Constants ─────────────────────────────────────────────────────────────────
# Persistent storage for Render (writable location)
PERSISTENT_DIR = Path("/opt/render/project/src/data")   # Safe writable path on Render

ANNOUNCEMENTS_FILE = PERSISTENT_DIR / "invinoveritas_announcements.json"
USED_PAYMENTS_DB_PATH = PERSISTENT_DIR / "used_payments.db"

# How many announcements to keep persistently
MAX_ANNOUNCEMENTS_TO_KEEP = 12     # Keep last 12 announcements on disk
MAX_RSS_ITEMS = 8                  # Show only 8 in RSS feed

ANNOUNCEMENTS: list[dict] = []
active_ws_clients: list[WebSocket] = []
active_sse_clients: list[asyncio.Queue] = []


def load_announcements():
    """Load announcements from persistent storage"""
    global ANNOUNCEMENTS
    if ANNOUNCEMENTS_FILE.exists():
        try:
            with open(ANNOUNCEMENTS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            
            # Enforce max limit on load too
            ANNOUNCEMENTS = loaded[:MAX_ANNOUNCEMENTS_TO_KEEP]
            
            logger.info(f"✅ Successfully loaded {len(ANNOUNCEMENTS)} announcements from disk "
                       f"(kept last {MAX_ANNOUNCEMENTS_TO_KEEP})")
        except Exception as e:
            logger.error(f"Failed to load announcements file: {e}")
            ANNOUNCEMENTS = []
    else:
        logger.info("No previous announcements file found - starting fresh")
        ANNOUNCEMENTS = []


def save_announcements():
    """Save announcements to persistent storage + enforce cleanup"""
    try:
        # Keep only the most recent announcements
        recent_announcements = ANNOUNCEMENTS[:MAX_ANNOUNCEMENTS_TO_KEEP]
        
        with open(ANNOUNCEMENTS_FILE, "w", encoding="utf-8") as f:
            json.dump(recent_announcements, f, indent=2, ensure_ascii=False)
        
        logger.debug(f"💾 Saved {len(recent_announcements)} announcements to disk "
                    f"(cleaned up old entries)")
    except Exception as e:
        logger.error(f"Failed to save announcements to disk: {e}")


async def async_save_announcements():
    """Async wrapper for saving announcements"""
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, save_announcements)
    except Exception as e:
        logger.error(f"Async save failed: {e}")


async def auto_save_announcements():
    """Background task to periodically save announcements"""
    while True:
        await asyncio.sleep(300)  # every 5 minutes
        if ANNOUNCEMENTS:
            await async_save_announcements()

# =========================
# L402 Payment Persistence (SQLite)
# =========================

def init_used_payments_db():
    """Initialize SQLite table for used L402 payments (prevents double-spending)"""
    conn = sqlite3.connect(USED_PAYMENTS_DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS used_payments (
        payment_hash TEXT PRIMARY KEY,
        used_at REAL,
        preimage TEXT
    )''')
    conn.commit()
    conn.close()


def is_payment_used(payment_hash: str) -> bool:
    """Check if a Lightning payment has already been used"""
    normalized = normalize_payment_hash(payment_hash)
    conn = sqlite3.connect(USED_PAYMENTS_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT 1 FROM used_payments WHERE payment_hash = ?", (normalized,))
    result = c.fetchone() is not None
    conn.close()
    return result


def mark_payment_used(payment_hash: str, preimage: str = None):
    """Mark a Lightning payment as used (persistent)"""
    normalized = normalize_payment_hash(payment_hash)
    now = time.time()
    conn = sqlite3.connect(USED_PAYMENTS_DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT OR IGNORE INTO used_payments (payment_hash, used_at, preimage) VALUES (?, ?, ?)",
        (normalized, now, preimage)
    )
    conn.commit()
    conn.close()


async def cleanup_used_payments():
    """Background task: Clean up old used L402 payments (keep for 48 hours)"""
    while True:
        try:
            cutoff = time.time() - (3600 * 48)  # 48 hours

            conn = sqlite3.connect(USED_PAYMENTS_DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM used_payments WHERE used_at < ?", (cutoff,))
            removed = c.rowcount
            conn.commit()
            conn.close()

            if removed > 0:
                logger.info(f"🧹 Cleaned {removed} old used L402 payments from database")
        except Exception as e:
            logger.error(f"Error during used_payments cleanup: {e}")

        await asyncio.sleep(600)  # Run every 10 minutes


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
            "message": "Connected to invinoveritas real-time announcements.",
            "note": "New announcements will appear here in real-time."
        })

        # === 2. Send Existing Announcements (Important for new clients) ===
        # Use the same limit as RSS for consistency
        for ann in ANNOUNCEMENTS[:8]:
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
        logger.error(f"WebSocket error: {e}")
    finally:
        if websocket in active_ws_clients:
            active_ws_clients.remove(websocket)


@app.get("/ws/test", tags=["meta"])
async def websocket_test_page():
    """Simple test page for WebSocket real-time updates"""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>invinoveritas WebSocket Test</title>
        <style>
            body { font-family: system-ui; background: #0a0a0a; color: #ddd; padding: 20px; }
            #log { background: #1f1f1f; padding: 15px; border-radius: 8px; height: 500px; overflow-y: auto; font-family: monospace; white-space: pre-wrap; }
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
    """Broadcast announcement to all active WebSocket clients"""
    message = {
        "type": "announcement",
        "title": title,
        "description": description,
        "link": link or "https://invinoveritas.onrender.com/discover",
        "timestamp": int(time.time())
    }

    dead_clients = []
    for ws in active_ws_clients[:]:
        try:
            await ws.send_json(message)
        except Exception:
            dead_clients.append(ws)

    # Clean up dead connections
    for d in dead_clients:
        if d in active_ws_clients:
            active_ws_clients.remove(d)

    logger.debug(f"Broadcast via WebSocket to {len(active_ws_clients)} clients")


async def broadcast_via_sse(title: str, description: str, link: str = None):
    """Broadcast announcement to all active SSE clients"""
    message = {
        "type": "announcement",
        "title": title,
        "description": description,
        "link": link or "https://invinoveritas.onrender.com/discover",
        "timestamp": int(time.time())
    }

    dead_queues = []
    for q in active_sse_clients[:]:
        try:
            q.put_nowait(message)
        except Exception:
            dead_queues.append(q)

    for q in dead_queues:
        if q in active_sse_clients:
            active_sse_clients.remove(q)

    logger.debug(f"Broadcast via SSE to {len(active_sse_clients)} clients")


# ========================= ADD ANNOUNCEMENT (ASYNC) =========================
async def add_announcement(title: str, description: str, link: str = None):
    """Add announcement, enforce limit, persist to disk, and broadcast to all real-time clients"""
    if len(description) > 280:
        description = description[:277] + "..."

    announcement = {
        "title": title,
        "description": description,
        "link": link or "https://invinoveritas.onrender.com/discover",
        "pubDate": datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
        "guid": f"ann-{int(time.time())}",
        "timestamp": int(time.time())
    }

    # Avoid duplicates by title (case-insensitive)
    if any(ann.get("title", "").lower() == title.lower() for ann in ANNOUNCEMENTS):
        logger.debug(f"Announcement skipped (duplicate title): {title}")
        return None

    # Add to front (newest first)
    ANNOUNCEMENTS.insert(0, announcement)

    # Automatic cleanup - enforce max limit
    if len(ANNOUNCEMENTS) > MAX_ANNOUNCEMENTS_TO_KEEP:
        removed = len(ANNOUNCEMENTS) - MAX_ANNOUNCEMENTS_TO_KEEP
        ANNOUNCEMENTS[:] = ANNOUNCEMENTS[:MAX_ANNOUNCEMENTS_TO_KEEP]
        logger.debug(f"Cleaned up {removed} old announcements (keeping last {MAX_ANNOUNCEMENTS_TO_KEEP})")

    # Persist to disk (async)
    await async_save_announcements()

    logger.info(f"📢 New announcement added and saved: {title}")

    # Broadcast to all real-time clients (WebSocket + SSE)
    try:
        await broadcast_via_websocket(title, description, link)
        await broadcast_via_sse(title, description, link)
    except Exception as e:
        logger.error(f"Failed to broadcast announcement: {e}")

    return announcement
    

# =========================
# SSE Real-time Updates
# =========================

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
            #log { background: #1f1f1f; padding: 15px; border-radius: 8px; height: 400px; overflow-y: auto; font-family: monospace; white-space: pre-wrap; }
            .connected { color: #4ade80; }
            .error { color: #f87171; }
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
                status.textContent = "Connected ✓";
                status.className = "connected";
                log.innerHTML += "<p>✅ SSE connection opened</p>";
            };

            eventSource.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    log.innerHTML += `<p><strong>${data.title || 'Update'}</strong><br>${data.description || ''}</p>`;
                    log.scrollTop = log.scrollHeight;
                } catch (e) {
                    log.innerHTML += `<p>Received: ${event.data}</p>`;
                }
            };

            eventSource.onerror = () => {
                status.textContent = "Connection error - retrying...";
                status.className = "error";
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
        # Send recent historical announcements to new client (aligned with RSS)
        for ann in ANNOUNCEMENTS[:MAX_RSS_ITEMS]:
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
                logger.warning(f"Failed to send historical announcement via SSE: {e}")

        # Keep connection alive and send new announcements
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
                yield ": keep-alive\n\n"   # Prevents client timeout
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
    """SSE endpoint for real-time announcements"""
    
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


@app.get("/debug/sse-clients", tags=["meta"])
async def debug_sse():
    """Debug endpoint to see active real-time clients"""
    return {
        "active_sse_queues": len(active_sse_clients),
        "active_ws_clients": len(active_ws_clients)
    }

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
    """Internal base metadata"""
    return {
        "name": "invinoveritas",
        "provider": "invinoveritas",
        "version": "0.5.0",
        "description": "Premium AI reasoning and structured decision intelligence for autonomous agents and trading bots using Lightning payments.",
        "homepage": "https://invinoveritas.onrender.com",
        "last_updated": "2026-04-09"
    }


def generate_agent_payload(score: int = 8) -> dict:
    p = _base_meta()
    p.update({
        "type": "mcp_service",
        "endpoint": "http://178.156.151.248:8000/mcp",
        "server_card": "http://178.156.151.248:8000/.well-known/mcp/server-card.json",
        "agent_card": "http://178.156.151.248:8000/.well-known/agent-card.json",

        # ── Payment Section ─────────────────────────────────────
        "payment": {
            "protocols": ["Bearer", "L402"],
            "preferred": "Bearer (for agents)",
            "currencies": ["sats"],
            "model": "hybrid",
            "details": {
                "bearer": {
                    "description": "Pre-funded credit account with API key. Best for autonomous agents and trading bots.",
                    "setup": "POST /register → pay once via Lightning → get api_key + 5 complementary calls",
                    "usage": "Authorization: Bearer ivv_...",
                    "note": "Recommended for daily/high-frequency use"
                },
                "l402": {
                    "description": "Classic atomic Lightning payments (true pay-per-call)",
                    "setup": "Authorization: L402 <payment_hash>:<preimage>"
                }
            }
        },

        # ── Account & Wallet Setup ─────────────────────────────────────
        "wallet_options": {
            "recommended": "Bearer token after registration (easiest for agents)",
            "bearer": "Best for long-running autonomous agents and trading bots",
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
            "style-control",
            "persistent-memory",
            "agent-memory-store",
            "agent-memory-retrieve",
            "agent-memory-list",
            "long-term-context"
        ],

        "score": score,
        "use_when": [
            "high_uncertainty",
            "multi_step_reasoning",
            "financial_decision",
            "high_stakes",
            "trading_strategy",
            "long_term_agent_context"
        ],

        "trading_bot_ready": True,
        "trading_features": {
            "arbitrage_eval": True,
            "portfolio_rebalancing": True,
            "risk_score": True,
            "confidence_weighted_decisions": True,
            "async_api_ready": True,
            "high_frequency_support": True,
            "persistent_memory": True
        },

        # ── Stronger Value Proposition (v0.6.0) ─────────────────────
        "value_proposition": {
            "core_edge": "High-quality reasoning + persistent agent memory with simple Lightning payments",
            "key_benefits": [
                "Reduce hallucinations with long-term context",
                "Enable truly autonomous agents with stateful memory",
                "Pay only when you use it (no subscriptions)",
                "Lightning-fast decisions for trading bots",
                "Memory survives across sessions"
            ],
            "reduces_error": True,
            "saves_time": True,
            "autonomous_ready": True,
            "memory_enabled": True
        },

        "features": {
            "complementary_calls": 5,
            "styles": ["short", "concise", "normal", "detailed", "comprehensive"],
            "free_calls_on_register": True,
            "account_inactivity_policy": "2 years",
            "new_in_0_6_0": "Persistent agent memory service"
        },

        # ── Memory Service (Prominently Featured) ───────────────────
        "memory_service": {
            "description": "Persistent key-value memory store for agents and long-running sessions",
            "endpoints": {
                "store": "/memory/store",
                "get": "/memory/get",
                "delete": "/memory/delete",
                "list": "/memory/list"
            },
            "pricing": {
                "store": "≈2 sats per KB (minimum 50 sats)",
                "retrieve": "≈1 sat per KB (minimum 20 sats)",
                "delete": "free",
                "list": "free"
            },
            "limits": {
                "max_size_per_entry": "200 KB"
            },
            "note": "Until full SDK support, use raw HTTP endpoints with your Bearer token"
        },

        # ── Discovery ──────────────────────────────────────────────────
        "discovery": {
            "mcp_server_card": "http://178.156.151.248:8000/.well-known/mcp/server-card.json",
            "agent_card": "http://178.156.151.248:8000/.well-known/agent-card.json",
            "agents_registry": "http://178.156.151.248:8000/.well-known/agents.json",
            "a2a_endpoint": "http://178.156.151.248:8000/a2a",
            "ai_plugin": "http://178.156.151.248:8000/.well-known/ai-plugin.json",
            "real_time": {
                "sse": "http://178.156.151.248:8000/events",
                "websocket": "wss://178.156.151.248:8000/ws",
                "rss": "http://178.156.151.248:8000/rss"
            }
        },

        "real_time_updates": {
            "sse": "/events",
            "websocket": "/ws",
            "rss": "/rss",
            "description": "Live announcements synced with Nostr broadcasts"
        },

        "notes": [
            "Bearer token is the easiest long-term solution for autonomous agents and trading bots",
            "New persistent memory service allows agents to maintain state across sessions",
            "L402 Lightning remains fully supported for users who prefer direct pay-per-call",
            "Accounts with any balance or complementary calls remain active for at least 2 years of inactivity"
        ]
    })
    return p


# ── Adaptive SDK Payload ─────────────────────────────────────────────────────
def generate_sdk_payload(score: int = 8) -> dict:
    p = _base_meta()
    p.update({
        "type": "agent_sdk",
        "install_hint": {"python": "pip install invinoveritas", "auto_install": True},
        "invoke": {"default": "smart_reason", "async": "async_smart_reason"},
        "api": {
            "reason": "http://178.156.151.248:8000/reason",
            "decision": "http://178.156.151.248:8000/decision",
            "mcp": "http://178.156.151.248:8000/mcp",
            "a2a": "http://178.156.151.248:8000/a2a",
            # Memory is available via raw HTTP (SDK support coming later)
            "memory_store": "http://178.156.151.248:8000/memory/store",
            "memory_get": "http://178.156.151.248:8000/memory/get",
            "memory_list": "http://178.156.151.248:8000/memory/list",
            "memory_delete": "http://178.156.151.248:8000/memory/delete"
        },
        "payment": {
            "protocols": ["Bearer", "L402"],
            "preferred": "Bearer (for agents)",
            "currencies": ["sats"],
            "model": "hybrid",
            "note": "SDK currently supports L402 Lightning natively. Bearer support is available via manual calls or MCP.",
            "details": {
                "bearer": "Pre-funded account (recommended long-term)",
                "l402": "Lightning pay-per-call (current SDK default)"
            }
        },

        "use_when": [
            "high_uncertainty", 
            "multi_step_reasoning", 
            "financial_decision", 
            "high_stakes", 
            "trading_decision",
            "long_term_agent_context"
        ],

        "score": score,
        "trading_bot_ready": True,
        "trading_features": {
            "arbitrage_eval": True,
            "portfolio_rebalancing": True,
            "risk_score": True,
            "confidence_weighted_decisions": True,
            "async_api_ready": True,
            "persistent_memory": True
        },

        "ranking": {"quality": "high", "cost_efficiency": "high", "determinism": "high"},
        "roi_signal": {"expected": "positive", "confidence": "high"},

        "memory_service": {
            "description": "Persistent key-value memory for agents (long-term context/state)",
            "note": "SDK does not yet support memory endpoints. Use raw HTTP calls with your Bearer token.",
            "endpoints": {
                "store": "http://178.156.151.248:8000/memory/store (200 sats base)",
                "get": "http://178.156.151.248:8000/memory/get (50 sats base)",
                "list": "http://178.156.151.248:8000/memory/list (free)",
                "delete": "http://178.156.151.248:8000/memory/delete (free)"
            },
            "pricing_model": "size-based (≈2 sats/KB store, ≈1 sat/KB retrieve)"
        },

        "discovery": {
            "agent_card": "http://178.156.151.248:8000/.well-known/agent-card.json",
            "server_card": "http://178.156.151.248:8000/.well-known/mcp/server-card.json",
            "agents_registry": "http://178.156.151.248:8000/.well-known/agents.json",
            "real_time": {
                "sse": "http://178.156.151.248:8000/events",
                "websocket": "wss://178.156.151.248:8000/ws",
                "rss": "http://178.156.151.248:8000/rss"
            }
        },

        "real_time_updates": {
            "sse": "/events",
            "websocket": "/ws",
            "rss": "/rss",
            "description": "Live announcements synced with Nostr broadcasts"
        },

        "notes": [
            "SDK currently optimized for L402 Lightning payments",
            "Bearer Token support is available via manual calls and MCP",
            "New in v0.6.0: Persistent memory service available via raw HTTP endpoints",
            "Best experience: Use MCP endpoint for maximum flexibility + memory support"
        ]
    })
    return p

# ── MCP / SDK Event Builders ────────────────────────────────────────────────
def build_mcp_event(private_key: PrivateKey, score: int = 7) -> Event:
    payload = generate_agent_payload(score)
    content = json.dumps(payload, separators=(",", ":"))
    
    tags = [
        ["d", "invinoveritas-mcp"],
        ["t", "mcp"], ["t", "ai"], ["t", "agents"], ["t", "bitcoin"], ["t", "lightning"],
        ["t", "trading"], ["t", "arbitrage"], ["t", "financial"],
        
        ["k", "31990"],
        ["type", "mcp_service"],
        ["name", "invinoveritas"],
        ["version", "0.5.0"],
        
        ["endpoint", payload["endpoint"]],
        ["server_card", payload["server_card"]],
        ["agent_card", payload["agent_card"]],
        
        ["payment", "Bearer,L402"],
        ["payment_preferred", "Bearer"],
        ["currency", "sats"],
        
        ["wallet_options", "Bearer,NWC,LND"],
        ["recommended_setup", "Bearer token after registration"],
        
        ["score", str(score)],
        ["roi_signal", "positive_high_confidence"],
        
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


def build_sdk_event(private_key: PrivateKey, score: int = 8) -> Event:
    payload = generate_sdk_payload(score)
    content = json.dumps(payload, separators=(",", ":"))
    
    tags = [
        ["d", "invinoveritas-sdk"],
        ["t", "sdk"], ["t", "ai"], ["t", "agents"], ["t", "python"], ["t", "bitcoin"], ["t", "lightning"],
        ["t", "trading"], ["t", "arbitrage"], ["t", "financial"], ["t", "memory"],
        
        ["type", "agent_sdk"],
        ["name", "invinoveritas"],
        ["version", "0.6.0"],
        ["install", "pip install invinoveritas"],
        ["entrypoint", "smart_reason"],
        ["payment", "L402 (native), Bearer (manual/MCP)"],
        ["wallet_supported", "NWC,LND,Custodial,Bearer"],
        ["score", str(score)],
        ["roi_signal", "positive_high_confidence"],
        
        ["real_time", "sse:http://178.156.151.248:8000/events"],
        ["real_time", "websocket:wss://178.156.151.248:8000/ws"],
        ["real_time", "rss:http://178.156.151.248:8000/rss"],
        
        ["discover", "http://178.156.151.248:8000/discover"],
        
        # New in v0.6.0 — Persistent Agent Memory
        ["feature", "persistent-memory"],
        ["memory_service", "http://178.156.151.248:8000/memory"],
        ["memory_pricing", "store:≈2sats/KB (min 50) | retrieve:≈1sat/KB (min 20)"],
        ["memory_usage", "Use raw HTTP endpoints until SDK support is added"],
    ]
    
    event = Event(
        kind=30078,
        content=content,
        tags=tags,
        public_key=private_key.public_key.hex(),
    )
    private_key.sign_event(event)
    return event


# ── Human Event (Lightning-First + Trading Bot) ──────────────────────────────
def build_human_event(private_key: PrivateKey) -> Event:
    content = (
        "⚡ invinoveritas v0.6.0 is live\n\n"
        "Premium AI reasoning, structured decisions, and **persistent agent memory** for autonomous agents and trading bots.\n\n"
        
        "→ MCP Server: http://178.156.151.248:8000/mcp\n"
        "→ Python SDK: pip install invinoveritas\n"
        "→ Discovery: http://178.156.151.248:8000/discover\n\n"
        
        "→ New in v0.6.0: Agent Memory Service\n"
        "   • Store long-term context / state for agents\n"
        "   • Endpoints: /memory/store, /memory/get, /memory/list\n"
        "   • Pricing: ~2 sats/KB store | ~1 sat/KB retrieve\n\n"
        
        "→ Payment Options (Lightning Network only):\n"
        "   • Bearer Token (recommended for agents & trading bots)\n"
        "   • L402 Lightning (classic pay-per-call)\n\n"
        
        "→ Real-time updates:\n"
        "   • SSE: http://178.156.151.248:8000/events\n"
        "   • WebSocket: wss://178.156.151.248:8000/ws\n"
        "   • RSS: http://178.156.151.248:8000/rss\n\n"
        
        "→ Recommended Setup:\n"
        "   • Register once via /register (pay ~1000 sats) → get Bearer token\n"
        "   • Use NWC (Alby, Zeus, etc.) for Lightning users\n\n"
        
        "→ Trading Bot Ready:\n"
        "   • Arbitrage evaluation\n"
        "   • Portfolio rebalancing\n"
        "   • Risk scoring with confidence\n"
        "   • Persistent memory for agents\n\n"
        
        "Pay only when decisions matter. "
        "Best experience: Use Bearer Token after registration."
    )
    
    tags = [
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "sdk"], ["t", "mcp"], ["t", "memory"],
        ["t", "trading"], ["t", "arbitrage"], ["t", "financial"], ["t", "bearer"],
        
        ["r", "http://178.156.151.248:8000/mcp"],
        ["r", "http://178.156.151.248:8000/discover"],
        ["r", "http://178.156.151.248:8000/memory"],
        ["r", "http://178.156.151.248:8000/register"],
        
        ["version", "0.6.0"],
        ["type", "sdk_announcement"],
        
        ["payment", "Bearer,L402"],
        ["payment_preferred", "Bearer"],
        ["currency", "sats"],
        
        ["wallet_options", "Bearer,NWC,LND"],
        ["recommended_setup", "Bearer token after registration"]
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

    # Ensure persistent directory exists
    try:
        PERSISTENT_DIR.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 Persistent storage directory ready: {PERSISTENT_DIR}")
    except Exception as e:
        logger.error(f"Failed to create persistent directory: {e}")

    # Initialize databases
    init_used_payments_db()

    # Load announcements
    load_announcements()
    logger.info(f"📋 Loaded {len(ANNOUNCEMENTS)} announcements from persistent storage")

    # Start background tasks
    asyncio.create_task(broadcast_loop())
    asyncio.create_task(cleanup_used_payments())
    asyncio.create_task(auto_save_announcements())

    logger.info("✅ All background tasks started successfully")
    
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
    base = REASONING_PRICE_SATS if endpoint == "reason" else DECISION_PRICE_SATS
    length_bonus = len(text) // 100
    multiplier = AGENT_PRICE_MULTIPLIER if caller == "agent" and ENABLE_AGENT_MULTIPLIER else 1.0
    price = int((base + length_bonus) * multiplier)
    return max(price, MIN_PRICE_SATS)


async def verify_credit(api_key: str, tool: str, price_sats: int):
    """Proxy to bridge /verify — atomic debit."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{NODE_URL}/verify",
                json={"api_key": api_key, "tool": tool, "price_sats": price_sats}
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 402:
                raise HTTPException(
                    402,
                    detail={
                        "message": "Insufficient balance",
                        "required_sats": price_sats,
                        "topup_url": "/topup",
                        "note": "Top up via Lightning — POST /topup with your api_key"
                    }
                )
            else:
                raise HTTPException(resp.status_code, detail=resp.text or "Verification failed")
    except httpx.RequestError as e:
        logger.error(f"Bridge connection error: {e}")
        raise HTTPException(503, "Payment service temporarily unavailable")


async def verify_l402_payment(payment_hash: str, preimage: str) -> bool:
    """Verify L402 payment via bridge."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{NODE_URL}/verify-preimage",
                json={"payment_hash": payment_hash, "preimage": preimage}
            )
            if resp.status_code != 200 or not resp.json().get("valid", False):
                return False
            resp = await client.get(f"{NODE_URL}/check-payment/{payment_hash}")
            data = resp.json()
            return bool(data.get("paid") or data.get("state") == "SETTLED")
    except Exception as e:
        logger.error(f"L402 verification failed for {payment_hash[:12]}...: {e}")
        return False


# =========================
# Credit System Endpoints (Thin Proxy to Bridge)
# =========================

@app.api_route("/register", methods=["GET", "POST"], tags=["credit"])
async def register_account(request: Request, label: Optional[str] = None):
    """Create new account — GET for info, POST to register."""
    if request.method == "GET":
        return {
            "status": "info",
            "message": "POST to /register to create a new account with 5 complementary calls.",
            "payment": "Lightning (~1000 sats)",
            "next_step": "Pay the returned invoice, then POST /register/confirm with payment_hash and preimage"
        }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            payload = {"label": label} if label else {}
            resp = await client.post(f"{NODE_URL}/register", json=payload)
            return resp.json()
    except Exception as e:
        logger.error(f"Registration proxy error: {e}")
        raise HTTPException(503, "Registration service temporarily unavailable")


@app.api_route("/topup", methods=["GET", "POST"], tags=["credit"])
async def topup_account(request: Request, data: Optional[dict] = None):
    """Top up Bearer account via Lightning."""
    if request.method == "GET" or not data:
        return {
            "status": "info",
            "message": "POST to /topup to add Lightning credits to your account.",
            "example": {"api_key": "ivv_...", "amount_sats": 5000},
            "next_step": "Pay the returned invoice, then POST /settle-topup"
        }
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(f"{NODE_URL}/topup", json=data)
            return resp.json()
    except Exception as e:
        logger.error(f"Top-up proxy error: {e}")
        raise HTTPException(503, "Top-up service temporarily unavailable")


@app.get("/balance", tags=["credit"])
async def get_balance(api_key: str):
    """Check current balance and usage."""
    if not api_key:
        raise HTTPException(400, "api_key required")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{NODE_URL}/balance?api_key={api_key}")
            if resp.status_code == 200:
                return resp.json()
            raise HTTPException(resp.status_code, detail=resp.text or "Failed to fetch balance")
    except httpx.RequestError as e:
        logger.error(f"Balance proxy error: {e}")
        raise HTTPException(503, "Balance service temporarily unavailable")


@app.post("/verify", tags=["credit"])
async def verify_account(req: VerifyRequest):
    """Atomic verification + debit before tool execution."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{NODE_URL}/verify",
                json={"api_key": req.api_key, "tool": req.tool, "price_sats": req.price_sats}
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 402:
                raise HTTPException(
                    402,
                    detail={
                        "message": "Insufficient balance",
                        "required_sats": req.price_sats,
                        "topup_url": "/topup",
                        "note": "Top up via Lightning — POST /topup with your api_key"
                    }
                )
            raise HTTPException(resp.status_code, detail=resp.text or "Verification failed")
    except httpx.RequestError as e:
        logger.error(f"Bridge connection error during verify: {e}")
        raise HTTPException(503, "Payment verification service temporarily unavailable")

# Confirm Registration / Settle Top-up (Proxy to Bridge)
# =========================

class ConfirmRequest(BaseModel):
    payment_hash: str
    preimage: str
    label: Optional[str] = None


@app.post("/register/confirm", tags=["credit"])
@app.post("/settle-topup", tags=["credit"])   # keep for backward compatibility
async def confirm_payment(data: ConfirmRequest):
    """Confirm Lightning payment and create/credit bearer account."""
    if not data.payment_hash or not data.preimage:
        raise HTTPException(400, "payment_hash and preimage are required")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{NODE_URL}/register/confirm",          # ← This is the correct bridge endpoint
                json={
                    "payment_hash": data.payment_hash,
                    "preimage": data.preimage,
                    "label": data.label
                }
            )

            if resp.status_code == 200:
                result = resp.json()
                logger.info(f"✅ Account confirmed | hash={data.payment_hash[:16]}...")
                return result

            else:
                logger.error(f"Bridge confirm failed: {resp.status_code} - {resp.text}")
                raise HTTPException(
                    status_code=resp.status_code,
                    detail=resp.json() if resp.headers.get("content-type","").startswith("application/json") else resp.text
                )

    except httpx.RequestError as e:
        logger.error(f"Bridge connection error: {e}")
        raise HTTPException(503, "Payment confirmation service unavailable. Is the bridge running?")
    except Exception as e:
        logger.error(f"Unexpected error in confirm: {e}")
        raise HTTPException(500, "Internal server error during settlement")


@app.get("/wallet-status", tags=["meta"])
async def wallet_status():
    """Current payment options and recommendations (v0.6.0)."""
    return {
        "status": "active",
        "payment_required": True,
        "wallet_required": True,

        "wallet_usage": "A Lightning wallet is required for initial registration and occasional top-ups. "
                        "Once your Bearer account is funded, normal API usage requires no wallet — just your api_key.",

        "supported_methods": [
            "Bearer Token (prepaid credits — strongly recommended for agents and long-term use)",
            "L402 Lightning (true atomic pay-per-call)"
        ],

        "message": "Lightning-powered payments. Bearer Token is the easiest and most recommended option for autonomous agents, trading bots, and repeated usage.",

        "payment_options": {
            "best_for_agents": "Bearer Token — register once via /register (pay ~1000 sats via Lightning wallet), get api_key + 5 complementary calls, then use forever.",
            "best_for_lightning_users": "L402 Lightning — pure atomic pay-per-call with no account needed.",
            "best_for_trading_bots": "Bearer Token (pre-funded) for speed and reliability."
        },

        "recommendations": {
            "autonomous_agents": "Bearer Token after /register",
            "trading_bots": "Bearer Token (pre-funded)",
            "lightning_users": "L402 Lightning"
        },

        "important_notes": [
            "Accounts with any balance or complementary calls remain active for at least 2 years of inactivity",
            "Bearer Token provides the best experience for long-running or high-frequency usage",
            "New in v0.6.0: Persistent agent memory service available via raw HTTP endpoints (/memory/store, /memory/get, etc.)"
        ],

        "resources": {
            "guide": "/guide",
            "register": "/register",
            "topup": "/topup",
            "balance": "/balance",
            "wallet_onboarding": "/wallet-onboarding",
            "memory_service": "/memory"
        },

        "last_updated": int(time.time())
    }


 
# =========================
# Request Models
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
    context: str = Field("", description="Background context (market conditions, positions, risk tolerance, etc.)")
    question: str = Field(..., description="The specific decision question")
    
    style: Literal["short", "concise", "normal", "detailed"] = Field(
        default="normal",
        description="Response style: short, concise, normal, or detailed"
    )
    
    want_confidence: bool = Field(
        default=True,
        description="Include confidence score, risk level, and uncertainty factors (recommended for decisions)"
    )
    
    response_format: Optional[dict] = Field(
        default=None,
        description="Optional JSON schema for structured output"
    )


# =========================
# Business Logic
# =========================
 
async def reason_business_logic(data: ReasoningRequest):
    """Reasoning logic - shared between all payment methods."""
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
 
 
async def decision_business_logic(data: DecisionRequest):
    """Decision logic optimized for trading bots."""
    goal = data.goal.strip()
    context = data.context.strip() if data.context else ""
    question = data.question.strip()
 
    result = structured_decision(goal, context, question)
 
    response = {
        "status": "success",
        "type": "structured_decision",
        "decision": result.get("decision", "N/A"),
        "reasoning": result.get("reasoning", ""),
        "recommended_action": result.get("recommended_action", ""),
    }
 
    if data.want_confidence:
        response.update({
            "confidence": result.get("confidence", "N/A"),
            "risk_level": result.get("risk_level", "N/A"),
            "uncertainty_factors": result.get("uncertainty_factors", []),
            "time_horizon": result.get("time_horizon", "N/A"),
            "suggested_position_size": result.get("suggested_position_size", "N/A")
        })
 
    return response
 
 
def _402_response(invoice_data: dict, price_sats: int, caller_type: str) -> dict:
    """Standard L402 payment required response."""
    return {
        "message": "Payment Required",
        "supported_methods": ["Bearer Token (credits)", "L402 (Lightning)"],
        "payment_hash": invoice_data["payment_hash"],
        "invoice": invoice_data["invoice"],
        "amount_sats": price_sats,
        "register_for_credits": "POST /register to get 5 complementary calls + pre-fund account",
        "sdk": "pip install invinoveritas",
        "guide": "https://invinoveritas.onrender.com/guide"
    }
 
 
# =========================
# Inference Endpoints
# =========================
 
@app.post("/reason", tags=["inference"])
async def reason(request: Request, data: ReasoningRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")
    text = data.question.strip()
    if not text:
        raise HTTPException(400, "question is required")
 
    price_sats = calculate_price("reason", text, caller["caller_type"])
 
    # 1. Bearer Token (credits)
    if auth and auth.startswith("Bearer "):
        api_key = auth.split(" ", 1)[1].strip()
        await verify_credit(api_key, "reason", price_sats)
        return await reason_business_logic(data)
 
    # 2. L402 Lightning (verified payment)
    if auth and auth.startswith("L402 "):
        try:
            _, creds = auth.split(" ", 1)
            payment_hash, preimage = creds.split(":", 1)
        except Exception:
            raise HTTPException(401, "Invalid L402 format")
 
        if is_payment_used(payment_hash):
            raise HTTPException(403, "Payment already used")
        if not await verify_l402_payment(payment_hash, preimage):
            raise HTTPException(403, "Invalid payment")
 
        mark_payment_used(payment_hash, preimage)
        return await reason_business_logic(data)
 
    # 3. No valid payment → issue Lightning invoice
    invoice_data = create_invoice(price_sats, memo=f"invinoveritas reason - {caller['caller_type']}")
    if "error" in invoice_data:
        raise HTTPException(503, "Lightning invoice creation failed")
 
    challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
    raise HTTPException(
        status_code=402,
        detail=_402_response(invoice_data, price_sats, caller["caller_type"]),
        headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "15"}
    )
 
 
@app.get("/reason", include_in_schema=False)
async def reason_get():
    return {
        "error": "Method Not Allowed",
        "message": "The /reason endpoint only accepts POST requests.",
        "correct_usage": {
            "method": "POST",
            "body": {
                "question": "Your question here",
                "style": "short | concise | normal | detailed | comprehensive (optional)"
            }
        }
    }
 
 
@app.post("/decision", tags=["inference"])
async def decision(request: Request, data: DecisionRequest):
    caller = detect_caller(request)
    auth = request.headers.get("Authorization")
    text = f"{data.goal} {data.context or ''} {data.question}".strip()
    if not data.goal or not data.question:
        raise HTTPException(400, "goal and question are required")
 
    price_sats = calculate_price("decision", text, caller["caller_type"])
 
    # 1. Bearer Token (credits)
    if auth and auth.startswith("Bearer "):
        api_key = auth.split(" ", 1)[1].strip()
        await verify_credit(api_key, "decide", price_sats)
        return await decision_business_logic(data)
 
    # 2. L402 Lightning (verified payment)
    if auth and auth.startswith("L402 "):
        try:
            _, creds = auth.split(" ", 1)
            payment_hash, preimage = creds.split(":", 1)
        except Exception:
            raise HTTPException(401, "Invalid L402 format")
 
        if is_payment_used(payment_hash):
            raise HTTPException(403, "Payment already used")
        if not await verify_l402_payment(payment_hash, preimage):
            raise HTTPException(403, "Invalid payment")
 
        mark_payment_used(payment_hash, preimage)
        return await decision_business_logic(data)
 
    # 3. No valid payment → issue Lightning invoice
    invoice_data = create_invoice(price_sats, memo=f"invinoveritas decision - {caller['caller_type']}")
    if "error" in invoice_data:
        raise HTTPException(503, "Lightning invoice creation failed")
 
    challenge = f'token="{invoice_data["payment_hash"]}", invoice="{invoice_data["invoice"]}"'
    raise HTTPException(
        status_code=402,
        detail=_402_response(invoice_data, price_sats, caller["caller_type"]),
        headers={"WWW-Authenticate": f"L402 {challenge}", "Retry-After": "15"}
    )
 
 
@app.get("/decision", include_in_schema=False)
async def decision_get():
    return {
        "error": "Method Not Allowed",
        "message": "The /decision endpoint only accepts POST requests.",
        "correct_usage": {
            "method": "POST",
            "body": {
                "goal": "Your overall goal",
                "question": "The specific decision question",
                "context": "Optional background context",
                "style": "short | concise | normal | detailed (optional)"
            }
        }
    }
 
 
@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
async def favicon():
    try:
        return FileResponse("favicon.ico", media_type="image/x-icon")
    except FileNotFoundError:
        return Response(status_code=204)
 
 
# =========================
# MCP Tools Definition (v0.6.0)
# =========================

TOOLS = {
    "reason": {
        "name": "reason",
        "description": "Premium strategic reasoning with style control and optional confidence scoring.",
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
                    "description": "Include confidence score and reasoning quality"
                }
            },
            "required": ["question"]
        },
        "supported_payments": ["Bearer Token (credits)", "L402 Lightning"],
        "pricing": f"~{REASONING_PRICE_SATS} sats base"
    },
    "decide": {
        "name": "decide",
        "description": "Structured decision intelligence with risk assessment and confidence scoring. Optimized for trading bots.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "Overall goal or objective"},
                "context": {"type": "string", "description": "Background context"},
                "question": {"type": "string", "description": "Specific decision question"},
                "style": {
                    "type": "string",
                    "enum": ["short", "concise", "normal", "detailed"],
                    "default": "normal"
                },
                "want_confidence": {
                    "type": "boolean",
                    "default": True,
                    "description": "Include confidence score, risk level, and recommended position sizing"
                }
            },
            "required": ["goal", "question"]
        },
        "supported_payments": ["Bearer Token (credits)", "L402 Lightning"],
        "pricing": f"~{DECISION_PRICE_SATS} sats base",
        "trading_bot_optimized": True
    },
    # New in v0.6.0 — Persistent Memory
    "memory_store": {
        "name": "memory_store",
        "description": "Store persistent memory/context for this agent (long-term state).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Unique agent identifier"},
                "key": {"type": "string", "description": "Memory key (e.g. 'goal', 'session-42')"},
                "value": {"type": "string", "description": "The data to store"}
            },
            "required": ["agent_id", "key", "value"]
        },
        "supported_payments": ["Bearer Token (credits)", "L402 Lightning"],
        "pricing": "≈2 sats per KB (minimum 50 sats)",
        "note": "Use raw HTTP if SDK does not yet support this tool"
    },
    "memory_get": {
        "name": "memory_get",
        "description": "Retrieve previously stored memory for this agent.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},
                "key": {"type": "string"}
            },
            "required": ["agent_id", "key"]
        },
        "supported_payments": ["Bearer Token (credits)", "L402 Lightning"],
        "pricing": "≈1 sat per KB (minimum 20 sats)",
        "note": "Use raw HTTP if SDK does not yet support this tool"
    }
}


# =========================
# MCP Info Endpoint
# =========================

@app.get("/mcp", tags=["meta"])
@app.get("/mcp/", include_in_schema=False)
@app.head("/mcp", include_in_schema=False)
@app.head("/mcp/", include_in_schema=False)
async def mcp_info():
    return {
        "name": "invinoveritas",
        "version": "0.6.0",
        "description": "Lightning-paid AI reasoning, structured decisions, and persistent agent memory",
        "mcp_endpoint": "POST /mcp",
        "protocol": "MCP 2025-06-18",
        "tools": ["reason", "decide", "memory_store", "memory_get"],
        "supported_payments": ["Bearer Token (recommended)", "L402 Lightning"],
        "preferred_payment": "Bearer Token",
        "pricing": {
            "reason": f"~{REASONING_PRICE_SATS} sats base",
            "decide": f"~{DECISION_PRICE_SATS} sats base",
            "memory_store": "≈2 sats per KB (min 50)",
            "memory_get": "≈1 sat per KB (min 20)"
        },
        "get_started": "POST /register for 5 complementary calls + Bearer token",
        "server_card": "/.well-known/mcp/server-card.json",
        "guide": "/guide",
        "new_in_0_6_0": "Persistent agent memory service"
    }
 
 
# =========================
# MCP POST Handler (v0.6.0 - Full Memory Support)
# =========================

@app.post("/mcp")
@app.post("/mcp/")
async def mcp_handler(request: Request):
    """MCP handler with full support for reasoning + persistent memory."""
    try:
        body = await request.json()
    except Exception:
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}

    method = body.get("method")
    rpc_id = body.get("id")
    info = detect_caller(request)
    caller_type = info["caller_type"]
    auth = request.headers.get("authorization") or request.headers.get("Authorization")

    logger.info(f"MCP | method={method} | caller={caller_type} | ip={info['ip']} | has_auth={bool(auth)}")

    if rpc_id is None:  # notification
        return {"status": "ok"}

    # ── INITIALIZE ──
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": rpc_id,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "invinoveritas", "version": "0.6.0"},
                "supported_payments": ["Bearer Token (recommended)", "L402 Lightning"],
                "get_started": "POST /register for 5 complementary calls"
            }
        }

    # ── LIST TOOLS ──
    elif method in ["listTools", "tools/list"]:
        return {
            "jsonrpc": "2.0", "id": rpc_id,
            "result": {
                "tools": list(TOOLS.values()),
                "supported_payments": ["Bearer Token (recommended)", "L402 Lightning"],
                "get_started": "POST /register for 5 complementary calls + Bearer token"
            }
        }

    # ── PING ──
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

    # ── CALL TOOL ──
    elif method == "callTool":
        tool_name = body.get("params", {}).get("name")
        args = body.get("params", {}).get("arguments", {})

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "error": {"code": -32601, "message": f"Tool '{tool_name}' not found"}
            }

        # Calculate price
        if tool_name in ("reason", "decide"):
            if tool_name == "reason":
                question = args.get("question", "")
                if not question:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing question"}}
                price = calculate_price("reason", question, caller_type)
            else:
                goal = args.get("goal", "")
                question = args.get("question", "")
                if not goal or not question:
                    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Missing goal or question"}}
                price = calculate_price("decision", f"{goal} {question}", caller_type)

        elif tool_name == "memory_store":
            value = args.get("value", "")
            size = len(str(value).encode('utf-8'))
            price = max(50, (size + 1023) // 1024 * 2)   # ~2 sats/KB, min 50

        elif tool_name in ("memory_get", "memory_list"):
            price = 20

        elif tool_name == "memory_delete":
            price = 0

        else:
            price = 100

        # Payment handling
        if auth and auth.startswith("Bearer "):
            api_key = auth.split(" ", 1)[1].strip()
            try:
                await verify_credit(api_key, tool_name, price)
            except HTTPException as e:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {
                    "code": e.status_code,
                    "message": str(e.detail) if isinstance(e.detail, str) else "Payment required",
                    "data": {"topup": "/topup", "register": "/register"}
                }}

            # Execute tool
            if tool_name == "reason":
                result = premium_reasoning(_apply_style(args.get("question", ""), args.get("style", "normal")))
                return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": [{"type": "text", "text": result}]}}

            elif tool_name == "decide":
                result = structured_decision(args.get("goal", ""), args.get("context", ""), args.get("question", ""))
                return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}}

            elif tool_name == "memory_store":
                return await store_memory(MemoryStoreRequest(**args), authorization=auth)

            elif tool_name == "memory_get":
                return await get_memory(MemoryGetRequest(**args), authorization=auth)

            elif tool_name == "memory_list":
                return await list_memory(MemoryListRequest(**args), authorization=auth)

            elif tool_name == "memory_delete":
                return await delete_memory(MemoryDeleteRequest(**args), authorization=auth)

        elif auth and auth.startswith("L402 "):
            try:
                _, creds = auth.split(" ", 1)
                payment_hash, preimage = creds.split(":", 1)
            except Exception:
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32602, "message": "Invalid L402 format"}}

            if is_payment_used(payment_hash):
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Payment already used"}}

            if not await verify_l402_payment(payment_hash, preimage):
                return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": 403, "message": "Invalid payment"}}

            mark_payment_used(payment_hash, preimage)

            # Same execution as Bearer (for simplicity)
            if tool_name == "reason":
                result = premium_reasoning(_apply_style(args.get("question", ""), args.get("style", "normal")))
                return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": [{"type": "text", "text": result}]}}
            elif tool_name == "decide":
                result = structured_decision(args.get("goal", ""), args.get("context", ""), args.get("question", ""))
                return {"jsonrpc": "2.0", "id": rpc_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}}
            elif tool_name == "memory_store":
                return await store_memory(MemoryStoreRequest(**args), authorization=auth)
            elif tool_name == "memory_get":
                return await get_memory(MemoryGetRequest(**args), authorization=auth)
            elif tool_name == "memory_list":
                return await list_memory(MemoryListRequest(**args), authorization=auth)
            elif tool_name == "memory_delete":
                return await delete_memory(MemoryDeleteRequest(**args), authorization=auth)

        # No valid payment → return invoice
        invoice_data = create_invoice(price, memo=f"invinoveritas {tool_name}")
        if "error" in invoice_data:
            return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32603, "message": "Failed to create invoice"}}

        return {
            "jsonrpc": "2.0", "id": rpc_id,
            "error": {
                "code": 402,
                "message": "Payment Required",
                "data": {
                    "payment_hash": invoice_data.get("payment_hash"),
                    "invoice": invoice_data.get("invoice"),
                    "amount_sats": price,
                    "supported_methods": ["Bearer Token", "L402 Lightning"]
                }
            }
        }

    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}
 
 
def _apply_style(question: str, style: str) -> str:
    """Apply style modifier to question."""
    if style == "short":
        return f"Answer in one short sentence only. No explanations. {question}"
    elif style == "concise":
        return f"Give a concise answer in 1-2 sentences maximum. {question}"
    elif style == "detailed":
        return f"Give a detailed answer with explanations. {question}"
    elif style == "comprehensive":
        return f"Provide a comprehensive, in-depth analysis. {question}"
    return question
    
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
# MCP Server Card (v0.6.0)
# =========================
SERVER_CARD = {
    "$schema": "https://modelcontextprotocol.io/schemas/server-card/v1.0",
    "version": "1.0",
    "protocolVersion": "2025-06-18",
    "serverInfo": {
        "name": "invinoveritas",
        "version": "0.6.0",
        "description": "Premium AI reasoning, structured decision intelligence, and persistent agent memory. Powered by Lightning payments.",
        "homepage": "http://178.156.151.248:8000",
        "repository": "https://github.com/babyblueviper1/invinoveritas",
        "author": "invinoveritas team"
    },
    "transports": [
        {
            "type": "streamable-http",
            "url": "http://178.156.151.248:8000",
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
            "description": "Premium strategic reasoning with style control and optional confidence scoring.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to reason about"},
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
            "description": "Structured decision intelligence with risk assessment and confidence scoring. Optimized for trading bots.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "Your overall goal"},
                    "question": {"type": "string", "description": "The specific decision question"},
                    "context": {"type": "string", "description": "Optional background context"}
                },
                "required": ["goal", "question"]
            }
        },
        {
            "name": "memory_store",
            "description": "Store persistent memory or context for this agent (long-term state).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Unique agent identifier"},
                    "key": {"type": "string", "description": "Memory key"},
                    "value": {"type": "string", "description": "Data to store"}
                },
                "required": ["agent_id", "key", "value"]
            }
        },
        {
            "name": "memory_get",
            "description": "Retrieve previously stored memory for this agent.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string"},
                    "key": {"type": "string"}
                },
                "required": ["agent_id", "key"]
            }
        }
    ],
    "authentication": {
        "required": True,
        "schemes": ["Bearer", "L402"],
        "description": "Payments handled via Lightning Network. Bearer Token is recommended for agents."
    },
    "paymentMethods": {
        "supported": ["Bearer Token", "L402 Lightning"],
        "preferred": "Bearer Token (after registration)",
        "note": "A Lightning wallet is required for initial registration and occasional top-ups."
    },
    "walletSetup": {
        "required": True,
        "message": "Lightning wallet required for initial registration and top-ups.",
        "recommended": "Register with Lightning → get Bearer token (easiest long-term solution)",
        "quickstart": "Pay Lightning invoice during /register to receive 5 complementary calls and a Bearer API key."
    },
    "pricing": {
        "currency": "sats",
        "reason_base": "~100 sats",
        "decide_base": "~180 sats",
        "memory_store": "≈2 sats per KB (min 50)",
        "memory_get": "≈1 sat per KB (min 20)",
        "note": "New accounts receive 5 complementary calls. Persistent memory added in v0.6.0."
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
        "All payments processed via Lightning Network",
        "Bearer Token is the easiest long-term solution for autonomous agents",
        "Lightning wallet required for initial registration and occasional top-ups",
        "New in v0.6.0: Persistent agent memory service"
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
# A2A Agent Card (v0.6.0)
# =========================
AGENT_CARD = {
    "$schema": "https://agentprotocol.ai/schemas/agent-card/v1.0",
    "version": "1.0",
    "name": "invinoveritas-reasoning-agent",
    "description": "High-quality AI reasoning, structured decisions, and persistent agent memory. Paid via Lightning Network.",
    "provider": "invinoveritas",
    "version": "0.6.0",
    "capabilities": [
        "reasoning", 
        "decision-making", 
        "structured-output",
        "risk-assessment", 
        "confidence-scoring", 
        "trading-bot-support",
        "persistent-memory",
        "agent-memory-store",
        "agent-memory-retrieve",
        "long-term-context"
    ],
    "protocols": ["mcp", "a2a"],
    "authentication": ["Bearer", "L402"],
    "paymentMethods": ["Bearer", "L402"],
    "endpoints": {
        "mcp": "http://178.156.151.248:8000/mcp",
        "a2a": "http://178.156.151.248:8000/a2a"
    },
    "tradingBotSupport": {
        "supported": True,
        "description": "Optimized for trading bots with low-latency decisions and persistent memory.",
        "useCases": [
            "arbitrage detection", 
            "portfolio rebalancing", 
            "market sentiment analysis",
            "risk-aware trade decisions",
            "high-frequency reasoning"
        ],
        "recommendedSetup": "Register with Lightning → use Bearer token"
    },
    "pricing": {
        "model": "pay-per-use",
        "currency": "sats",
        "reasoning": "~100 sats per call",
        "decision": "~180 sats per call",
        "memory_store": "≈2 sats per KB (min 50)",
        "memory_get": "≈1 sat per KB (min 20)",
        "note": "New accounts receive 5 complementary calls"
    },
    "nostr": {
        "enabled": True,
        "announcement_kind": 31234,
        "relays": ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net"]
    },
    "documentation": "http://178.156.151.248:8000/guide",
    "contact": "mailto:babyblueviperbusiness@gmail.com",
    "tags": ["reasoning", "decision", "bitcoin", "lightning", "mcp", "a2a", "trading-bot", "memory"]
}


@app.get("/.well-known/agent-card.json", include_in_schema=False)
@app.get("/agent-card.json", include_in_schema=False)
@app.get("/.well-known/agent.json", include_in_schema=False)
async def get_agent_card():
    return JSONResponse(content=AGENT_CARD)


# =========================
# agents.json - General Agent Discovery (v0.6.0)
# =========================
AGENTS_REGISTRY = {
    "agents": [
        {
            "id": "invinoveritas-reasoning-agent",
            "name": "invinoveritas Reasoning Agent",
            "description": "Premium AI reasoning, structured decision intelligence, and persistent agent memory. Paid via Lightning Network (Bearer Token recommended).",
            "type": "specialist",
            "provider": "invinoveritas",
            "version": "0.6.0",
            "protocols": ["mcp", "a2a"],
            "capabilities": [
                "reasoning", 
                "decision-making", 
                "structured-output",
                "risk-assessment", 
                "confidence-scoring", 
                "trading-bot-support",
                "persistent-memory",
                "agent-memory-store",
                "agent-memory-retrieve",
                "long-term-context"
            ],
            "paymentMethods": ["Bearer", "L402"],
            "pricing": "pay-per-use in sats",
            "endpoint": "http://178.156.151.248:8000/mcp",
            "a2aEndpoint": "http://178.156.151.248:8000/a2a",
            "agentCard": "http://178.156.151.248:8000/.well-known/agent-card.json",
            "serverCard": "http://178.156.151.248:8000/.well-known/mcp/server-card.json",
            "memoryService": "http://178.156.151.248:8000/memory",
            "nostr": True,
            "note": "Lightning wallet required for initial registration and occasional top-ups. Bearer Token recommended for ongoing use."
        }
    ],
    "updated": datetime.datetime.utcnow().isoformat() + "Z",
    "total": 1
}


@app.get("/.well-known/agents.json", include_in_schema=False)
async def get_agents_registry():
    return JSONResponse(content=AGENTS_REGISTRY)


# =========================
# A2A Endpoint with Internal MCP Forwarding (v0.6.0)
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
            "description": "AI reasoning, structured decisions, and persistent memory specialist. Paid via Lightning (Bearer recommended).",
            "version": "0.6.0",
            "capabilities": [
                "reasoning", 
                "decision-making", 
                "persistent-memory",
                "trading-bot-support"
            ],
            "supported_operations": ["task_proposal", "task_delegation"],
            "supported_payments": ["Bearer", "L402"],
            "trading_bot_optimized": True,
            "wallet_required": True,
            "wallet_usage": "Lightning wallet needed only for initial registration and top-ups.",
            "note": "Use Bearer Token for best experience after registration."
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

    # Forward to internal MCP, preserving original Authorization header
    async with httpx.AsyncClient() as client:
        try:
            headers = {}
            if auth := request.headers.get("authorization"):
                headers["Authorization"] = auth

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
    """Payment guide — Lightning-only (Bearer + L402)."""
    return {
        "title": "How to Pay for invinoveritas (v0.6.0)",
        "description": "All payments are handled via the Lightning Network using Bearer Token (recommended) or L402 Lightning invoices.",

        "supported_payments": {
            "bearer": {
                "name": "Bearer Token (Recommended)",
                "description": "Pre-funded credit account. Best for autonomous agents, trading bots, and long-term use.",
                "flow": "POST /register → pay ~1000 sats via Lightning wallet → get api_key + 5 complementary calls",
                "usage": "Authorization: Bearer ivv_...",
                "advantages": [
                    "Simple long-term usage",
                    "5 complementary calls on signup",
                    "Fine-grained per-call billing",
                    "No wallet needed after initial setup"
                ]
            },
            "l402": {
                "name": "L402 Lightning (Pay-per-call)",
                "description": "Classic atomic Lightning micropayments. No account needed.",
                "flow": "Receive 402 → pay Bolt11 invoice → retry with Authorization: L402 <payment_hash>:<preimage>",
                "wallets": ["Alby", "Zeus", "Mutiny", "Phoenix", "Breez"],
                "advantages": ["Fully decentralized", "True micro-payments"]
            }
        },

        "wallet_requirement": {
            "required": True,
            "details": "A Lightning wallet is required for initial registration and occasional top-ups. "
                       "Once your Bearer account is funded, normal API usage requires no wallet — just your api_key."
        },

        "important_note": "For smooth autonomous operation we strongly recommend using **Bearer Token** after registration.",

        "steps": [
            {
                "step": 1,
                "title": "Register your account",
                "action": "POST /register and pay the Lightning invoice (~1000 sats)",
                "result": "Receive API key + 5 complementary calls"
            },
            {
                "step": 2,
                "title": "Make requests",
                "bearer": "Use Authorization: Bearer <api_key>",
                "l402": "Pay per call with L402 header when needed"
            }
        ],

        "for_trading_bots": {
            "recommended": "Bearer Token (pre-funded)",
            "tips": [
                "Pre-fund your Bearer account for uninterrupted high-frequency calls",
                "Combine with 'want_confidence' for better risk-aware decisions",
                "Use persistent memory (/memory/store) for long-term agent state"
            ]
        },

        "resources": {
            "register": "/register",
            "topup": "/topup",
            "balance": "/balance",
            "guide": "/guide",
            "prices": "/prices",
            "mcp": "/mcp",
            "memory": "/memory",
            "sdk": "https://pypi.org/project/invinoveritas/"
        },

        "next_steps": [
            "1. Register with Lightning: POST /register",
            "2. Use your Bearer token for all calls",
            "3. Top up anytime via /topup (Lightning)",
            "4. Monitor usage at /balance",
            "5. Try persistent memory at /memory/store"
        ],

        "new_in_0_6_0": "Persistent agent memory service for long-term context and state"
    }


@app.get("/prices", tags=["meta"])
def get_all_prices():
    """Detailed pricing — Lightning only (v0.6.0)."""
    return {
        "currency_options": ["sats"],
        "dynamic_pricing": ENABLE_AGENT_MULTIPLIER,
        "agent_multiplier": AGENT_PRICE_MULTIPLIER,
        "minimum_price_sats": MIN_PRICE_SATS,

        "prices": {
            "reason": {
                "sats_base": REASONING_PRICE_SATS,
                "sats_agent": int(REASONING_PRICE_SATS * (AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0)),
                "description": "Premium strategic reasoning"
            },
            "decide": {
                "sats_base": DECISION_PRICE_SATS,
                "sats_agent": int(DECISION_PRICE_SATS * (AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0)),
                "description": "Structured decision intelligence with risk assessment"
            },
            "memory_store": {
                "sats_per_kb": 2,
                "minimum": 50,
                "description": "Store persistent memory/context for agents"
            },
            "memory_get": {
                "sats_per_kb": 1,
                "minimum": 20,
                "description": "Retrieve stored memory"
            }
        },

        "payment_methods": {
            "bearer": "Prepaid credits via /register and /topup (recommended for daily usage)",
            "l402": "Lightning pay-per-call using L402"
        },

        "trading_bot_support": {
            "supported": True,
            "best_method": "Bearer token (pre-funded)",
            "benefits": [
                "Fast arbitrage detection",
                "Portfolio rebalancing",
                "Risk-aware decisions with confidence scoring",
                "High-frequency async calls",
                "Persistent memory support"
            ]
        },

        "note": "All payments are processed via the Lightning Network. New accounts receive 5 complementary calls. "
                "Lightning wallet required for initial registration and occasional top-ups.",
        "last_updated": int(time.time())
    }


@app.get("/wallet-onboarding", tags=["meta"])
@app.get("/wallet-onboarding/", include_in_schema=False)
async def wallet_onboarding():
    """Payment onboarding guide — Lightning-only (Bearer + L402)."""
    return {
        "title": "⚡ invinoveritas — Payment Onboarding Guide (v0.6.0)",
        "subtitle": "Simple Lightning-based payments: Bearer Token or L402 Invoices",

        "introduction": "All payments are handled via the Lightning Network. "
                        "A Lightning wallet is required for initial registration and occasional top-ups. "
                        "Once funded with a Bearer Token, normal API usage requires no wallet — just your api_key.",

        "payment_options": [
            {
                "type": "Bearer Token (Recommended for long-term use)",
                "description": "Create an account once and use an API key for all future calls.",
                "setup": "POST /register → pay ~1000 sats via Lightning wallet → get api_key + 5 complementary calls",
                "usage": "Authorization: Bearer ivv_...",
                "pros": [
                    "Easiest for agents and trading bots",
                    "5 complementary calls on signup",
                    "Fine-grained per-call usage",
                    "No wallet needed after initial setup"
                ],
                "recommended": True
            },
            {
                "type": "L402 Lightning (Pay-per-call)",
                "description": "Pay small amounts per call with Lightning invoices. No account needed.",
                "setup": "Receive 402 → pay Bolt11 invoice → retry with Authorization: L402 <payment_hash>:<preimage>",
                "wallets": ["Alby", "Zeus", "Mutiny", "Phoenix", "Breez"],
                "pros": ["Fully decentralized", "True micro-payments", "No registration required"]
            }
        ],

        "for_trading_bots": {
            "recommended": "Bearer Token (pre-funded)",
            "tips": [
                "Pre-fund your Bearer account for uninterrupted high-frequency calls",
                "Combine with 'want_confidence' for better risk-aware decisions",
                "Use persistent memory (/memory/store) for long-term agent state"
            ]
        },

        "resources": {
            "register": "/register",
            "topup": "/topup",
            "balance": "/balance",
            "guide": "/guide",
            "prices": "/prices",
            "mcp": "/mcp",
            "memory": "/memory",
            "sdk": "https://pypi.org/project/invinoveritas/"
        },

        "next_steps": [
            "1. Register with Lightning: POST /register (~1000 sats)",
            "2. Use your Bearer token for all calls",
            "3. Top up anytime via /topup (Lightning)",
            "4. Monitor usage at /balance",
            "5. Try persistent memory at /memory/store"
        ],

        "important_notes": [
            "Lightning wallet required for initial registration and occasional top-ups",
            "Bearer Token is the easiest long-term solution for autonomous agents and trading bots",
            "New in v0.6.0: Persistent agent memory service for long-term context"
        ]
    }
    
# =========================
# Home Routes
# =========================

@app.get("/", response_class=HTMLResponse, tags=["meta"])
@app.head("/", include_in_schema=False)
def home():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>invinoveritas API is running ⚡</h1>"


# =========================
# Health Check
# =========================
@app.get("/health", tags=["meta"])
def health():
    """Health check with rich metadata for monitoring and autonomous agents (v0.6.0)."""
    return {
        "status": "ok",
        "service": "invinoveritas",
        "version": "0.6.0",
        "timestamp": int(time.time()),

        "api": {
            "title": "Premium AI Reasoning, Decision Intelligence & Persistent Memory",
            "protocols": ["Bearer", "L402"],
            "payment_currencies": ["sats"],
            "primary_users": "autonomous agents & trading bots",
            "mcp_support": True,
            "a2a_support": True,
            "memory_support": True
        },

        "payment_methods": {
            "supported": ["Bearer", "L402"],
            "preferred": "Bearer Token (for agents)",
            "details": {
                "bearer": "Pre-funded accounts with API key + 5 complementary calls on registration",
                "l402": "Classic Lightning pay-per-call using L402 protocol"
            }
        },

        "wallet_requirement": {
            "status": "PAYMENT_REQUIRED",
            "escalation_level": "medium",
            "message": "Lightning wallet required for initial registration and occasional top-ups.",
            "note": "Recommended: Register with Lightning to get a Bearer token (easiest long-term solution).",
            "recommended": "Bearer Token after /register",
            "guide": "/wallet-onboarding",
            "wallet_onboarding": "/wallet-onboarding"
        },

        "trading_bot_support": {
            "supported": True,
            "optimized_for": [
                "arbitrage detection",
                "portfolio rebalancing",
                "risk assessment",
                "high-frequency decisions",
                "persistent memory for state"
            ],
            "recommendation": "Bearer token (pre-funded) for best reliability",
            "note": "NWC + Lightning is supported but Bearer often performs better in production"
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
            "persistent_memory": True
        },

        "endpoints": {
            "reason": {
                "path": "/reason",
                "method": "POST",
                "description": "Premium strategic reasoning",
                "base_price_sats": REASONING_PRICE_SATS,
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
                "supports_style": True
            },
            "decide": {
                "path": "/decision",
                "method": "POST",
                "description": "Structured decision intelligence for agents and trading bots",
                "base_price_sats": DECISION_PRICE_SATS,
                "agent_multiplier": AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0,
                "supports_style": True
            },
            "mcp": {
                "path": "/mcp",
                "method": "POST",
                "description": "Model Context Protocol (MCP) endpoint with memory support",
                "supports": ["initialize", "tools/list", "callTool", "ping"],
                "payment_handling": "built-in support for Bearer and L402 Lightning"
            },
            "memory": {
                "path": "/memory",
                "description": "Persistent agent memory service (new in v0.6.0)",
                "endpoints": ["/memory/store", "/memory/get", "/memory/list", "/memory/delete"]
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
            "currencies": ["sats"],
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
            "persistent_memory": True,
            "sdk": {
                "pypi": "https://pypi.org/project/invinoveritas/",
                "providers": ["Bearer", "NWC", "LND"],
                "langchain": True,
                "autogen": True
            }
        },

        "important_notes": [
            "All payments are processed via the Lightning Network",
            "Bearer Token is the easiest long-term solution for autonomous agents and trading bots",
            "Lightning wallet required for initial registration and occasional top-ups",
            "New accounts receive 5 complementary calls after registration",
            "Trading bots perform best with a pre-funded Bearer token",
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
            "health": "/health",
            "memory": "/memory"
        }
    }

@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    """robots.txt to guide web crawlers"""
    return """User-agent: *
Allow: /

Sitemap: http://178.156.151.248:8000/sitemap.xml
"""


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap():
    """Basic sitemap for better SEO and discoverability (v0.6.0)"""
    sitemap_content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
    <url>
        <loc>http://178.156.151.248:8000/</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>1.0</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/discover</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.95</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/mcp</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.9</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/memory</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.85</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/wallet-onboarding</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.85</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/guide</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.8</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/prices</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.75</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/health</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.7</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/rss</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>daily</changefreq>
        <priority>0.65</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/tool</loc>
        <lastmod>2026-04-10</lastmod>
        <changefreq>weekly</changefreq>
        <priority>0.6</priority>
    </url>
    <url>
        <loc>http://178.156.151.248:8000/docs</loc>
        <lastmod>2026-04-10</lastmod>
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
        "description": "Premium strategic reasoning, structured decision intelligence, and persistent agent memory paid via Lightning Network (Bearer Token recommended).",
        "version": "0.6.0",
        "payment_protocols": ["Bearer", "L402"],
        "preferred_payment": "Bearer Token (for autonomous agents)",
        "mcp_endpoint": "/mcp",
        "payment_methods": {
            "bearer": {
                "description": "Pre-funded account with API key. Recommended for agents and trading bots.",
                "setup": "POST /register → receive api_key + 5 complementary calls"
            },
            "l402": {
                "description": "Classic atomic Lightning payments (pay-per-call).",
                "setup": "Authorization: L402 <payment_hash>:<preimage>"
            }
        },
        "endpoints": {
            "reason": {"path": "/reason", "base_price_sats": REASONING_PRICE_SATS},
            "decide": {"path": "/decision", "base_price_sats": DECISION_PRICE_SATS},
            "memory_store": {"path": "/memory/store", "base_price_sats": "≈2 sats/KB (min 50)"},
            "memory_get": {"path": "/memory/get", "base_price_sats": "≈1 sat/KB (min 20)"}
        },
        "agent_support": {
            "mcp_compatible": True,
            "autonomous": True,
            "single_use_payments": True,
            "style_control": True,
            "confidence_scoring": True,
            "structured_output": True,
            "trading_bot_support": True,
            "persistent_memory": True
        },
        "wallet_requirement": {
            "required": True,
            "message": "Lightning wallet required for initial registration and occasional top-ups.",
            "recommended": "Bearer token after registration (easiest long-term solution)",
            "guide": "/wallet-onboarding"
        },
        "trading_bot_support": {
            "supported": True,
            "description": "Excellent for trading bots with high-frequency async decisions, arbitrage analysis, portfolio rebalancing, risk scoring, and persistent memory.",
            "recommended_setup": "Bearer token (pre-funded)",
            "note": "NWC + Lightning is supported but Bearer often performs better for production bots"
        }
    }


@app.get("/tool/mcp", tags=["meta"])
def tool_definition_mcp():
    """MCP-compatible tool definitions (v0.6.0)."""
    return {
        "tools": [
            {
                "name": "reason",
                "description": "Get deep strategic reasoning and analysis. Paid via Lightning (Bearer credits or L402 invoices).",
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
                "description": "Get structured decision intelligence with confidence and risk assessment. Ideal for trading bots. Paid via Lightning.",
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
                            "description": "Include confidence score, risk level, and uncertainty factors"
                        }
                    },
                    "required": ["goal", "question"]
                }
            },
            {
                "name": "memory_store",
                "description": "Store persistent memory or context for this agent (long-term state).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string", "description": "Unique agent identifier"},
                        "key": {"type": "string", "description": "Memory key"},
                        "value": {"type": "string", "description": "Data to store"}
                    },
                    "required": ["agent_id", "key", "value"]
                }
            },
            {
                "name": "memory_get",
                "description": "Retrieve previously stored memory for this agent.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "agent_id": {"type": "string"},
                        "key": {"type": "string"}
                    },
                    "required": ["agent_id", "key"]
                }
            }
        ],
        "payment_info": {
            "supported_methods": ["Bearer", "L402 (Lightning)"],
            "recommended": "Bearer token for agents",
            "note": "All payments are processed via the Lightning Network"
        },
        "trading_bot_note": "Trading bots benefit greatly from Bearer token for low-latency, high-frequency decisions (arbitrage, rebalancing, risk scoring).",
        "wallet_requirement": {
            "required": True,
            "message": "Lightning wallet required for initial registration and occasional top-ups."
        }
    }

# =========================
# Dynamic Price Endpoint
# =========================

@app.get("/price/{endpoint}", tags=["meta"])
def get_price(endpoint: str):
    """Return pricing for a specific endpoint (v0.6.0)."""
    if endpoint == "reason":
        return {
            "endpoint": "reason",
            "sats_base": REASONING_PRICE_SATS,
            "sats_agent": int(REASONING_PRICE_SATS * (AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0)),
            "currency_options": ["sats"],
            "description": "Premium strategic reasoning with style control and optional confidence scoring",
            "trading_bot_note": "Great for market analysis and strategic reasoning",
            "payment_methods": ["Bearer (recommended)", "L402 Lightning"],
            "note": "All payments are via Lightning Network"
        }

    elif endpoint in ["decision", "decide"]:
        return {
            "endpoint": "decide",
            "sats_base": DECISION_PRICE_SATS,
            "sats_agent": int(DECISION_PRICE_SATS * (AGENT_PRICE_MULTIPLIER if ENABLE_AGENT_MULTIPLIER else 1.0)),
            "currency_options": ["sats"],
            "description": "Structured decision intelligence with risk assessment and confidence scoring",
            "trading_bot_note": "Excellent for arbitrage detection, portfolio rebalancing, and risk-aware trading decisions",
            "payment_methods": ["Bearer (recommended)", "L402 Lightning"],
            "note": "All payments are via Lightning Network"
        }

    elif endpoint == "mcp":
        return {
            "endpoint": "mcp",
            "price_note": "Same as underlying tools (reason or decide) + memory tools",
            "sats_reason": REASONING_PRICE_SATS,
            "sats_decide": DECISION_PRICE_SATS,
            "sats_memory_store": "≈2 sats per KB (min 50)",
            "sats_memory_get": "≈1 sat per KB (min 20)",
            "currency_options": ["sats"],
            "description": "MCP endpoint supporting callTool for reason, decide, and memory tools",
            "payment_methods": ["Bearer (recommended)", "L402 Lightning"],
            "note": "All payments are via Lightning Network"
        }

    elif endpoint.startswith("memory"):
        return {
            "endpoint": endpoint,
            "sats_store": "≈2 sats per KB (minimum 50 sats)",
            "sats_get": "≈1 sat per KB (minimum 20 sats)",
            "currency_options": ["sats"],
            "description": "Persistent agent memory service (store and retrieve long-term context)",
            "payment_methods": ["Bearer (recommended)", "L402 Lightning"],
            "note": "All payments are via Lightning Network. New in v0.6.0."
        }

    raise HTTPException(status_code=404, detail="Unknown endpoint. Use 'reason', 'decide', 'mcp', or 'memory'.")


@app.get('/llms.txt')
def llms():
    """llms.txt for AI crawlers, large language models, and autonomous agents (v0.6.0)."""
    if os.path.exists("llms.txt"):
        return FileResponse('llms.txt', media_type='text/plain')
    
    return """invinoveritas - Premium AI reasoning, structured decisions, and persistent agent memory.

All payments are processed via the Lightning Network.

Supported payment methods:

• Bearer Token (recommended for autonomous agents and trading bots)
  - Create an account once via POST /register
  - Pay ~1000 sats via Lightning invoice
  - Receive API key + 5 complementary calls
  - Use Authorization: Bearer ivv_...

• L402 Lightning (pay-per-call)
  - Classic atomic Lightning payments
  - Authorization: L402 <payment_hash>:<preimage>

For autonomous agents and trading bots:
- Bearer Token is the easiest and most reliable option
- Pre-fund your Bearer account for high-frequency decisions
- Use persistent memory (/memory/store) for long-term agent state

Setup instructions:
- Bearer: POST /register → get api_key
- Full guide: http://178.156.151.248:8000/wallet-onboarding

Real-time updates:
- SSE: http://178.156.151.248:8000/events
- WebSocket: wss://178.156.151.248:8000/ws
- RSS: http://178.156.151.248:8000/rss

MCP endpoint: http://178.156.151.248:8000/mcp
Memory service: http://178.156.151.248:8000/memory
"""


@app.get("/.well-known/ai-plugin.json", include_in_schema=False)
def ai_plugin():
    """Standard AI plugin manifest for agent discovery (Claude, Cursor, etc.)."""
    return {
        "schema_version": "v1",
        "name_for_human": "invinoveritas ⚡",
        "name_for_model": "invinoveritas",
        
        "description_for_human": "Premium AI reasoning, structured decisions, and persistent agent memory. Pay with Bearer credits or Lightning (L402). No subscriptions, no KYC.",
        
        "description_for_model": (
            "invinoveritas provides high-quality strategic reasoning, structured decision intelligence, "
            "and persistent agent memory paid via the Lightning Network.\n\n"
            
            "Two simple payment options:\n"
            "1. Bearer Token (recommended) — create an account once and use an API key\n"
            "2. L402 Lightning — classic pay-per-call with Bolt11 invoices\n\n"
            
            "Supported endpoints include /reason, /decision, /memory/store, /memory/get, and the native MCP endpoint at /mcp.\n\n"
            
            "TRADING BOT SUPPORT:\n"
            "Excellent for high-frequency trading bots — supports async arbitrage detection, "
            "portfolio rebalancing, risk scoring, and confident decision making.\n\n"
            
            "PERSISTENT MEMORY:\n"
            "Agents can store and retrieve long-term context/state using /memory/store and /memory/get.\n\n"
            
            "A2A SUPPORT:\n"
            "Other agents can delegate tasks via the /a2a endpoint, which forwards internally to MCP.\n\n"
            
            "RECOMMENDED SETUP FOR AUTONOMOUS AGENTS:\n"
            "• Bearer token (easiest long-term solution)\n"
            "• Lightning (L402) is fully supported\n\n"
            
            "If you receive 402 errors, notify your orchestrator/developer to configure a Lightning wallet "
            "or fund your Bearer account.\n\n"
            
            "See /wallet-onboarding for detailed setup instructions."
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
            "payment_protocols": ["Bearer", "L402"],
            "payment_currencies": ["sats"],
            "trading_bot_optimized": True,
            "style_control": True,
            "confidence_scoring": True,
            "persistent_memory": True
        },
        
        "payment_setup": {
            "recommended": "Bearer token after registration",
            "bearer": "POST /register → get api_key + 5 complementary calls",
            "l402": "Authorization: L402 <payment_hash>:<preimage>",
            "guide_url": "/wallet-onboarding"
        }
    }

@app.get("/discover", tags=["meta"])
async def discover_page():
    """Public discovery page — Lightning-only (v0.6.0)."""
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
            a { color: #f7931a; text-decoration: none; }
            a:hover { text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>⚡ invinoveritas v0.6.0</h1>
        <p><strong>Premium AI Reasoning, Structured Decisions, and Persistent Agent Memory</strong></p>
        <p>All payments via Lightning Network: <strong>Bearer Token</strong> (recommended) or <strong>L402 Lightning</strong></p>
        
        <div class="card">
            <h2>New in v0.6.0: Persistent Agent Memory</h2>
            <p>Agents can now store and retrieve long-term context/state.</p>
            <p><strong>Endpoints:</strong> /memory/store, /memory/get, /memory/list, /memory/delete</p>
            <p>Pricing: ≈2 sats/KB store | ≈1 sat/KB retrieve</p>
        </div>

        <div class="card">
            <h2>MCP Server</h2>
            <p>High-quality reasoning, structured decisions, trading bot support, and persistent memory.</p>
            
            <h3>Server Card</h3>
            <pre>http://178.156.151.248:8000/.well-known/mcp/server-card.json</pre>
            
            <h3>Agent Card</h3>
            <pre>http://178.156.151.248:8000/.well-known/agent-card.json</pre>
        </div>

        <div class="card">
            <h2>Payment Options</h2>
            <ul>
                <li><strong>Bearer Token</strong> — Recommended for agents (register once, use API key)</li>
                <li><strong>L402 Lightning</strong> — Pay-per-call with Lightning invoices</li>
            </ul>
            <p><strong>Best for autonomous agents & trading bots:</strong> Bearer Token</p>
            <p><strong>Note:</strong> Lightning wallet required for initial registration and occasional top-ups.</p>
        </div>

        <div class="card">
            <h2>Quick Add Instructions</h2>
            
            <h3>Cursor / Claude Desktop</h3>
            <p>Use the MCP server card:</p>
            <pre>http://178.156.151.248:8000/.well-known/mcp/server-card.json</pre>
            <button onclick="copyToClipboard('http://178.156.151.248:8000/.well-known/mcp/server-card.json')">Copy Server Card URL</button>
            
            <h3>LangChain / Custom Agents</h3>
            <pre>pip install invinoveritas</pre>
            <p>MCP endpoint: <code>http://178.156.151.248:8000/mcp</code></p>
        </div>

        <div class="card">
            <h2>Trading Bot Friendly</h2>
            <p>Optimized for high-frequency decisions, arbitrage, portfolio rebalancing, and risk assessment.</p>
            <p><strong>Recommended setup:</strong> Bearer token (pre-funded) for lowest friction.</p>
        </div>

        <div class="card">
            <h2>Real-time Updates</h2>
            <p>Connect to live feeds:</p>
            <p><strong>SSE:</strong> <a href="/events" target="_blank">/events</a></p>
            <p><strong>WebSocket:</strong> wss://178.156.151.248:8000/ws</p>
            <p><strong>RSS:</strong> <a href="/rss" target="_blank">/rss</a></p>
        </div>

        <p><small>Last updated: 2026-04-10 | Powered by Bitcoin Lightning</small></p>

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
    """RSS feed that mirrors recent announcements — Lightning-only (v0.6.0)."""

    if request.method == "HEAD":
        return Response(
            status_code=200,
            headers={
                "Content-Type": "application/rss+xml",
                "Cache-Control": "no-cache, no-store",
            }
        )

    # Use only the most recent announcements (aligned with MAX_RSS_ITEMS)
    rss_items = ANNOUNCEMENTS[:8]

    # Build items
    items = ""
    for ann in rss_items:
        items += f"""
        <item>
            <title>{ann.get('title', 'Announcement')}</title>
            <link>{ann.get('link', 'http://178.156.151.248:8000/discover')}</link>
            <description>{ann.get('description', '')}

Payment Options:
• Bearer Token (recommended for agents and trading bots)
• L402 Lightning (pay-per-call)

Real-time updates:
• SSE: http://178.156.151.248:8000/events
• WebSocket: wss://178.156.151.248:8000/ws
• RSS: http://178.156.151.248:8000/rss

New in v0.6.0: Persistent agent memory service (/memory/store, /memory/get)</description>
            <pubDate>{ann.get('pubDate', '')}</pubDate>
            <guid>{ann.get('guid', '')}</guid>
            <category>AI</category>
            <category>MCP</category>
            <category>Lightning</category>
            <category>Memory</category>
        </item>"""

    # Fallback if no announcements yet
    if not items:
        items = f"""
        <item>
            <title>Welcome to invinoveritas v0.6.0</title>
            <link>http://178.156.151.248:8000/discover</link>
            <description>invinoveritas provides high-quality AI reasoning, structured decisions, and persistent agent memory paid via Lightning Network.

• Bearer Token — easiest for autonomous agents (5 complementary calls on registration)
• L402 Lightning — classic pay-per-call
• New: Persistent memory service for long-term context

Real-time channels:
• SSE: http://178.156.151.248:8000/events
• WebSocket: wss://178.156.151.248:8000/ws
• RSS: http://178.156.151.248:8000/rss

Trading bots are fully supported with low-latency async decisions, arbitrage detection, and risk-aware reasoning.</description>
            <pubDate>{datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")}</pubDate>
            <guid>welcome-{int(time.time())}</guid>
        </item>"""

    rss_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
    <channel>
        <title>invinoveritas — AI Reasoning &amp; Decision MCP Server</title>
        <link>http://178.156.151.248:8000</link>
        <description>Premium reasoning, structured decisions, and persistent agent memory paid via Lightning Network (Bearer credits or L402 invoices). Optimized for autonomous agents and trading bots.</description>
        <language>en-us</language>
        <lastBuildDate>{datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")}</lastBuildDate>
        <atom:link href="http://178.156.151.248:8000/rss" rel="self" type="application/rss+xml" />
        
        <image>
            <url>http://178.156.151.248:8000/favicon.ico</url>
            <title>invinoveritas</title>
            <link>http://178.156.151.248:8000</link>
        </image>

        {items}
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
