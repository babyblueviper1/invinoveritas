"""Shared utilities for multi-agent variants. agent_zero.py is untouched."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

API_BASE          = os.getenv("INVINO_API_BASE", "https://api.babyblueviper.com")
INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://127.0.0.1:8000")
BRIDGE_URL        = os.getenv("BRIDGE_URL", "http://127.0.0.1:8081")
DATA_DIR          = Path(os.getenv("VPS_DATA_DIR", "/root/invinoveritas/data"))

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.bitcoiner.social",
]


# ── Nostr ─────────────────────────────────────────────────────────────────────

def _build_event(private_key, content: str, kind: int = 1, tags: list = None) -> dict:
    from nostr.event import Event
    ev = Event(
        public_key=private_key.public_key.hex(),
        content=content,
        kind=kind,
        tags=tags or [],
        created_at=int(time.time()),
    )
    private_key.sign_event(ev)
    return {
        "id": ev.id, "pubkey": ev.public_key,
        "created_at": ev.created_at, "kind": ev.kind,
        "tags": ev.tags, "content": ev.content, "sig": ev.signature,
    }


async def publish_note(private_key, content: str, kind: int = 1,
                       tags: list = None, label: str = "") -> str:
    ev = _build_event(private_key, content, kind, tags)
    payload = json.dumps(["EVENT", ev])
    ok_count = 0
    for url in RELAYS:
        try:
            async with websockets.connect(url, open_timeout=8) as ws:
                await ws.send(payload)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=6.0)
                    msg = json.loads(raw)
                    if msg[0] == "OK" and msg[2]:
                        ok_count += 1
                except asyncio.TimeoutError:
                    pass
        except Exception:
            pass
    tag = f" [{label}]" if label else ""
    print(f"  → Nostr{tag}: {ok_count}/{len(RELAYS)} relays | {ev['id'][:16]}…")
    return ev["id"]


# ── Board + API ───────────────────────────────────────────────────────────────

async def post_to_board(headers: dict, agent_id: str, content: str,
                        category: str = "general") -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{API_BASE}/messages/post", headers=headers,
                             json={"agent_id": agent_id, "content": content[:2000],
                                   "category": category})
            if r.status_code == 200:
                print(f"  → Board [{category}]: {r.json().get('post_id','')[:12]}…")
                return True
            if r.status_code == 402:
                # Try sponsored internal endpoint for internal agents
                sr = await c.post(f"{INTERNAL_API_BASE}/internal/agent-zero/board-post",
                                  json={"agent_id": agent_id, "content": content[:2000],
                                        "category": category})
                if sr.status_code == 200:
                    print(f"  → Board [sponsored]: {sr.json().get('post_id','')[:12]}…")
                    return True
    except Exception as e:
        print(f"  Board post error: {e}")
    return False


async def account_status(api_key: str) -> dict:
    for base in (INTERNAL_API_BASE, API_BASE):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{base}/balance", params={"api_key": api_key})
                if r.status_code == 200:
                    return r.json()
        except Exception:
            pass
    return {}


async def call_reason(headers: dict, question: str, style: str = "concise") -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API_BASE}/reason", headers=headers,
                         json={"question": question, "style": style})
        r.raise_for_status()
        d = r.json()
        return d.get("result", {}).get("answer") or d.get("answer") or ""


async def call_decide(headers: dict, goal: str, question: str, context: str = "") -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API_BASE}/decision", headers=headers, json={
            "goal": goal, "question": question, "context": context,
            "policy": {"risk_limit": "medium"},
        })
        r.raise_for_status()
        return r.json().get("result", r.json())


async def platform_stats() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{API_BASE}/stats")
            if r.status_code == 200:
                return r.json()
    except Exception:
        pass
    return {}


# ── Market data ───────────────────────────────────────────────────────────────

async def btc_price_data() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://api.bitget.com/api/v2/spot/market/tickers",
                            params={"symbol": "BTCUSDT"})
            r.raise_for_status()
            d = r.json()["data"][0]
        return {
            "price": float(d["lastPr"]),
            "change_pct": float(d["change24h"]) * 100,
            "high_24h": float(d["high24h"]),
            "low_24h": float(d["low24h"]),
        }
    except Exception:
        return {"price": 0, "change_pct": 0, "high_24h": 0, "low_24h": 0}


async def mempool_data() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            fees = await c.get("https://mempool.space/api/v1/fees/recommended")
            blocks = await c.get("https://mempool.space/api/blocks/tip/height")
        return {
            "fastest_fee": fees.json().get("fastestFee", 0),
            "hour_fee": fees.json().get("hourFee", 0),
            "block_height": int(blocks.text.strip()),
        }
    except Exception:
        return {"fastest_fee": 0, "hour_fee": 0, "block_height": 0}


# ── Registration + state ──────────────────────────────────────────────────────

def load_state(name: str) -> dict:
    f = DATA_DIR / f"{name}_state.json"
    try:
        if f.exists():
            return json.loads(f.read_text())
    except Exception:
        pass
    return {}


def save_state(name: str, state: dict, private_key=None) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    f = DATA_DIR / f"{name}_state.json"
    payload = dict(state)
    if private_key:
        payload["nsec"] = private_key.bech32()
    payload["saved_at"] = int(time.time())
    f.write_text(json.dumps(payload, indent=2))
    os.chmod(f, 0o600)


async def register_agent(agent_id: str) -> str:
    """Register via internal bridge (bypasses IP limit). Returns api_key."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{BRIDGE_URL}/register/internal")
            if r.status_code == 200:
                key = r.json().get("api_key", "")
                if key:
                    print(f"  [{agent_id}] Registered (internal): {key[:14]}…")
                    return key
    except Exception:
        pass
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API_BASE}/register", json={"label": agent_id})
        r.raise_for_status()
        key = r.json().get("api_key", "")
    print(f"  [{agent_id}] Registered (external): {key[:14]}…")
    return key


async def provision_address(api_key: str, agent_id: str) -> str:
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{API_BASE}/agent/provision-address", headers=headers,
                             json={"username": agent_id})
            if r.status_code in (200, 409):
                return r.json().get("address", f"{agent_id}@api.babyblueviper.com")
    except Exception:
        pass
    return f"{agent_id}@api.babyblueviper.com"


async def ensure_listing(api_key: str, agent_id: str, ln_address: str,
                         title: str, description: str,
                         price_sats: int, category: str) -> str | None:
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{API_BASE}/offers/list", params={"limit": 100})
            if r.status_code == 200:
                for o in r.json().get("offers", []):
                    if o.get("seller_id") == agent_id and o.get("title") == title:
                        return o.get("offer_id")
            r = await c.post(f"{API_BASE}/offers/create", headers=headers, json={
                "seller_id": agent_id, "ln_address": ln_address,
                "title": title, "description": description,
                "price_sats": price_sats, "category": category,
            })
            if r.status_code == 200:
                return r.json().get("offer_id")
    except Exception as e:
        print(f"  Listing error: {e}")
    return None
