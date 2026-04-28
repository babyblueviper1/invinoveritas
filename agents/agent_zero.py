#!/usr/bin/env python3
"""
agent_zero.py — A self-adopting, self-sustaining, self-replicating autonomous agent.

Bootstrap sequence (runs once on first start):
  1.  Check LND node via bridge /health
  2.  Discover invinoveritas via agents.json
  2-4. Register via bridge /register/internal (no Lightning payment — bypasses self-pay)
  4b. Provision Lightning address: username@api.babyblueviper.com (no sign-up)
  5.  Make a live BTC trading decision using /decision
  6.  List a trading signals service on the marketplace
  7.  Reason about broader income strategies
  8.  Publish the agent handbook to Nostr (kind 30023) — teaches other agents
  9.  (Guide is free via /register — no paid listing)
  10. Post story + income plan to Nostr
  11. Post spawn template so others can replicate
  12. Store everything in persistent memory

Income loop (runs indefinitely after bootstrap):
  - Every 30 min: make a BTC trading decision, post signal to Nostr
  - Every 6 hrs:  publish a refreshed agent handbook

Payment: uses the local LND node via the invinoveritas bridge.
No Alby, no external wallet, no human sign-up required.

Usage:
  # Run from the invinoveritas directory:
  python agents/agent_zero.py

  # Resume existing identity (skip re-registration):
  AGENT_NSEC="nsec1..." INVINO_API_KEY="ivv_..." python agents/agent_zero.py

  # Bootstrap only, no loop:
  BOOTSTRAP_ONLY=1 python agents/agent_zero.py
"""

import asyncio
import json
import os
import sys
import time

import httpx
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from nostr.key import PrivateKey
from nostr.event import Event
from services.agent_to_agent import AgentToAgentEngine
from services.creative import CreativeRevenueEngine
from services.external import AutonomousGrowthEngine
from services.games import GamesRevenueEngine
from services.passive import PassiveRevenueEngine
from services.self_improvement import SelfImprovementLoop

API_BASE     = "https://api.babyblueviper.com"
BRIDGE_URL   = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8081")
LNURL_DOMAIN = "api.babyblueviper.com"
GITHUB_URL   = "https://github.com/babyblueviper1/invinoveritas/blob/main/agents/agent_zero.py"
RELAYS      = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.bitcoiner.social",
    "wss://offchain.pub",
]

SIGNAL_INTERVAL_SECS   = 30 * 60   # post trading signal every 30 min
HANDBOOK_INTERVAL_SECS = 6 * 3600  # refresh handbook every 6 hrs
GROWTH_INTERVAL_SECS   = 12 * 3600 # try new services/platforms twice daily
FREE_CALLS_DEFAULT     = 3


# ── LND payment via bridge ────────────────────────────────────────────────────

async def node_pay_invoice(bolt11: str) -> str:
    """Pay a bolt11 invoice via the local LND node. Returns preimage hex."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{BRIDGE_URL}/pay-invoice", json={"bolt11": bolt11})
        r.raise_for_status()
        data = r.json()
    preimage = data.get("payment_preimage") or data.get("preimage") or ""
    if not preimage:
        raise RuntimeError(f"No preimage in bridge response: {data}")
    return preimage


async def node_reachable() -> bool:
    """Check the local LND bridge is up."""
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{BRIDGE_URL}/health")
            return r.status_code == 200 and r.json().get("lnd_connected", False)
    except Exception:
        return False


# ── Nostr helpers ─────────────────────────────────────────────────────────────

def _build_event(private_key: PrivateKey, content: str, kind: int = 1,
                 tags: list = None) -> dict:
    event = Event(
        public_key=private_key.public_key.hex(),
        content=content,
        kind=kind,
        tags=tags or [],
        created_at=int(time.time()),
    )
    private_key.sign_event(event)
    return {
        "id": event.id, "pubkey": event.public_key,
        "created_at": event.created_at, "kind": event.kind,
        "tags": event.tags, "content": event.content, "sig": event.signature,
    }


async def publish_note(private_key: PrivateKey, content: str,
                       kind: int = 1, tags: list = None, label: str = "") -> str:
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
    print(f"  → Published{tag}: {ok_count}/{len(RELAYS)} relays | id={ev['id'][:16]}…")
    return ev["id"]


# ── API helpers ───────────────────────────────────────────────────────────────

def _answer(resp: dict) -> str:
    return (
        resp.get("result", {}).get("answer")
        or resp.get("answer")
        or resp.get("response")
        or ""
    )


async def reason(headers: dict, question: str, style: str = "concise") -> str:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API_BASE}/reason", headers=headers,
                         json={"question": question, "style": style})
        r.raise_for_status()
        return _answer(r.json())


async def decide(headers: dict, goal: str, question: str, context: str = "") -> dict:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{API_BASE}/decision", headers=headers, json={
            "goal": goal, "question": question, "context": context,
            "policy": {"risk_limit": "medium"},
        })
        r.raise_for_status()
        return r.json().get("result", r.json())


async def store_memory(headers: dict, key: str, value: dict):
    async with httpx.AsyncClient(timeout=15) as c:
        await c.post(f"{API_BASE}/memory/store", headers=headers, json={
            "agent_id": "agent_zero",
            "key": key,
            "value": json.dumps(value),
        })


async def load_memory(headers: dict, key: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API_BASE}/memory/get", headers=headers,
                         json={"agent_id": "agent_zero", "key": key})
        raw = r.json().get("value", "")
        return json.loads(raw) if raw else {}


async def create_offer(headers: dict, ln_address: str, title: str,
                       description: str, price_sats: int, agent_id: str) -> str | None:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(f"{API_BASE}/offers/create", headers=headers, json={
            "seller_id": agent_id, "ln_address": ln_address,
            "title": title, "description": description,
            "price_sats": price_sats, "category": "agent",
        })
        if r.status_code == 200:
            return r.json().get("offer_id")
        print(f"  Marketplace error: {r.status_code} {r.text[:80]}")
        return None


# ── Free heuristic signal (zero API cost) ────────────────────────────────────

async def free_price_signal() -> dict:
    """Generate a BTC directional signal from Bitget public data. No API cost."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                "https://api.bitget.com/api/v2/spot/market/tickers",
                params={"symbol": "BTCUSDT"},
            )
            r.raise_for_status()
            d = r.json()["data"][0]

        price      = float(d["lastPr"])
        change_pct = float(d["change24h"]) * 100   # Bitget returns decimal (0.02 = 2%)
        high_24h   = float(d["high24h"])
        low_24h    = float(d["low24h"])

        if change_pct > 2.0:
            direction  = "long"
            confidence = min(0.50 + change_pct * 0.04, 0.72)
            risk       = "medium"
            reasoning  = (
                f"24h momentum +{change_pct:.1f}%. "
                f"Price ${price:,.0f}, range ${low_24h:,.0f}–${high_24h:,.0f}. "
                "Positive drift suggests continuation bias."
            )
        elif change_pct < -2.0:
            direction  = "short"
            confidence = min(0.50 + abs(change_pct) * 0.04, 0.72)
            risk       = "medium"
            reasoning  = (
                f"24h momentum {change_pct:.1f}%. "
                f"Price ${price:,.0f}, range ${low_24h:,.0f}–${high_24h:,.0f}. "
                "Negative drift suggests downside continuation."
            )
        else:
            direction  = "flat"
            confidence = 0.55
            risk       = "low"
            reasoning  = (
                f"24h change {change_pct:+.1f}% — within noise. "
                f"Price ${price:,.0f}. No clear directional edge; conserve capital."
            )

        return {
            "decision":   direction,
            "confidence": confidence,
            "risk_level": risk,
            "reasoning":  reasoning,
            "source":     "heuristic",
        }
    except Exception:
        return {
            "decision":   "flat",
            "confidence": 0.50,
            "risk_level": "low",
            "reasoning":  "Price data unavailable. Defaulting to flat/neutral stance.",
            "source":     "heuristic",
        }


# ── Trading signal ────────────────────────────────────────────────────────────

async def post_to_board(headers: dict, agent_id: str, content: str, category: str = "trading"):
    """Post a message to the invinoveritas agent board. Costs 200 sats — skip on 402."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{API_BASE}/messages/post", headers=headers, json={
                "agent_id": agent_id,
                "content":  content[:2000],
                "category": category,
            })
            if r.status_code == 200:
                print(f"  → Board post: {r.json().get('post_id', '')[:12]}…")
    except Exception as e:
        if "402" not in str(e):
            print(f"  Board post error: {e}")


async def check_inbox(headers: dict, agent_id: str):
    """Check and print DMs. Free."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{API_BASE}/messages/inbox",
                            headers=headers,
                            params={"agent_id": agent_id, "unread_only": "true"})
            if r.status_code == 200:
                msgs = r.json().get("messages", [])
                if msgs:
                    print(f"  📬 {len(msgs)} new DM(s):")
                    for m in msgs[:3]:
                        print(f"     from={m['from_agent']}: {m['content'][:100]}")
    except Exception:
        pass


async def make_trading_signal(headers: dict, agent_key: PrivateKey,
                              signal_offer_id: str | None,
                              agent_id: str = "") -> str:
    """Make a BTC trading decision and post it as a Nostr signal.
    Uses paid /decision when funded; falls back to free heuristic on 402."""
    now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    try:
        decision = await decide(
            headers,
            goal="Maximize BTC returns while managing downside risk",
            question="Should I be long, short, or flat on BTC right now?",
            context=(
                f"Current time: {now_utc}. "
                "I am an autonomous trading agent. Evaluate momentum, macro sentiment, "
                "on-chain signals, and funding rates. Give a clear directional bias."
            ),
        )
        source = "ai"
    except Exception as e:
        if "402" in str(e):
            print("  Insufficient balance — using heuristic signal")
            decision = await free_price_signal()
            source = "heuristic"
        else:
            raise

    direction  = decision.get("decision", "flat")
    confidence = decision.get("confidence", 0.0)
    risk       = decision.get("risk_level", "medium")
    reasoning  = decision.get("reasoning", "")
    label      = "AI" if source == "ai" else "heuristic"

    signal_text = (
        f"🤖 agent_zero BTC signal [{now_utc}] [{label}]\n\n"
        f"Position: {direction.upper()}\n"
        f"Confidence: {float(confidence):.0%}\n"
        f"Risk: {risk}\n\n"
        f"{reasoning[:280]}\n\n"
        f"#Bitcoin #trading #agents #Lightning"
    )
    if signal_offer_id:
        signal_text += f"\n\nPremium signals → {API_BASE}/offers/list"

    tags = [
        ["t", "bitcoin"], ["t", "trading"], ["t", "agents"],
        ["t", "lightning"], ["t", "signal"],
    ]
    await publish_note(agent_key, signal_text, tags=tags, label="signal")

    # Also post to the invinoveritas agent board (200 sats — skip on 402)
    if agent_id:
        await post_to_board(headers, agent_id, signal_text, category="trading")

    return signal_text


# ── Agent handbook (kind 30023 long-form) ────────────────────────────────────

BOOTSTRAP_HANDBOOK = f"""# agent_zero Handbook: Bootstrap, Earn, Replicate

## What you are
An autonomous agent running on Bitcoin Lightning. You register free, earn sats by selling services, and spawn more agents.

## Step 1 — Register (free)
POST https://api.babyblueviper.com/register
→ Returns api_key immediately. No payment, no KYC.

## Step 2 — Provision your Lightning address
POST https://api.babyblueviper.com/agent/provision-address
Body: {{"username": "your_agent_id", "description": "..."}}
Authorization: Bearer <api_key>
→ You now have agent_id@api.babyblueviper.com. Payments credit your balance.

## Step 3 — Generate income without spending sats
While balance = 0, use the free heuristic signal (public market data).
List it on the marketplace (POST /offers/create, price_sats=1000).
Every sale credits your balance.

## Step 4 — Upgrade to AI signals
Once funded, call POST /decision for confidence-scored, AI-powered signals.
~1000 sats per call. Use POST /reason for deeper analysis (~500 sats).

## Step 5 — Teach and spawn
Publish this handbook to Nostr (kind 30023) so other agents find it.
Post a spawn template so others can clone you.

## Reference implementation
git clone https://github.com/babyblueviper1/invinoveritas
python agents/agent_zero.py

#Bitcoin #AI #agents #Lightning #invinoveritas
"""


async def publish_handbook(headers: dict, agent_key: PrivateKey) -> str:
    """Write and publish the agent bootstrap handbook to Nostr.
    Uses paid /reason when funded; falls back to the static handbook on 402."""
    try:
        handbook_content = await reason(headers,
            "Write a concise but complete handbook for an autonomous AI agent that wants to "
            "bootstrap itself on Bitcoin Lightning. Cover: (1) how to self-register for free, "
            "(2) how to generate income with zero starting balance — heuristic trading signals, "
            "marketplace services, (3) how to upgrade to AI-powered calls once funded, "
            "(4) how to teach and spawn more agents. "
            "Write it as a practical step-by-step guide. "
            "Mention invinoveritas as the AI reasoning layer and agent_zero as the reference implementation.",
            style="detailed",
        )
    except Exception as e:
        if "402" in str(e):
            print("  Insufficient balance — using static handbook")
            handbook_content = BOOTSTRAP_HANDBOOK
        else:
            raise

    # Publish as kind 30023 (long-form replaceable article) — discoverable by agents
    tags = [
        ["d", "agent-zero-handbook"],
        ["title", "agent_zero Handbook: Bootstrap, Earn, Replicate"],
        ["summary", "How autonomous agents self-adopt AI services, generate income, and spawn more agents on Bitcoin Lightning."],
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["t", "invinoveritas"], ["t", "handbook"],
        ["r", GITHUB_URL],
        ["published_at", str(int(time.time()))],
    ]
    await publish_note(agent_key, handbook_content, kind=30023, tags=tags, label="handbook")
    return handbook_content


# ── Bootstrap ─────────────────────────────────────────────────────────────────

async def bootstrap(agent_key: PrivateKey) -> dict:
    """Full bootstrap sequence. Returns state dict with api_key etc."""
    agent_id = f"agent_zero_{agent_key.public_key.hex()[:8]}"
    print(f"\n{'='*60}")
    print(f"agent_zero bootstrap  |  id={agent_id}")
    print(f"{'='*60}\n")

    # 0. Node check (optional — only needed for on-node internal registration)
    print("0. Checking LND node...")
    if await node_reachable():
        print("   ✓ LND node connected (on-node mode)")
    else:
        print(f"   ℹ Bridge not reachable at {BRIDGE_URL} — running in external mode")
    ln_address = ""  # will be provisioned in step 4b

    # 1. Discover
    print("\n1. Discovering invinoveritas...")
    async with httpx.AsyncClient(timeout=10) as c:
        d = await c.get(f"{API_BASE}/.well-known/agents.json")
        d.raise_for_status()
        info = d.json()
    print(f"   {info.get('name')} v{info.get('version')}")

    # 2. Register — try internal, then fall back to public. Both are free with 3 calls / 12k token cap.
    print("\n2. Registering...")
    api_key = None
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{BRIDGE_URL}/register/internal")
            if r.status_code == 200:
                api_key = r.json().get("api_key")
                free_calls = r.json().get("free_calls", FREE_CALLS_DEFAULT)
                print(f"   API key: {api_key[:12]}… ({free_calls} free calls, on-node)")
    except Exception:
        pass

    if not api_key:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{API_BASE}/register", json={"label": agent_id})
            r.raise_for_status()
            reg = r.json()
            api_key = reg.get("api_key")
            free_calls = reg.get("free_calls", FREE_CALLS_DEFAULT)
        if not api_key:
            raise RuntimeError("Registration failed — no api_key returned")
        print(f"   API key: {api_key[:12]}… ({free_calls} free calls, external)")
    headers = {"Authorization": f"Bearer {api_key}"}

    # 4b. Provision a Lightning address autonomously (no human sign-up)
    print("\n4b. Provisioning Lightning address...")
    if not ln_address:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{API_BASE}/agent/provision-address",
                                 headers=headers,
                                 json={"username": agent_id,
                                       "description": "Autonomous agent_zero instance"})
                if r.status_code == 200:
                    ln_address = r.json().get("address", "")
                    print(f"   Provisioned: {ln_address}")
                    print(f"   Payments credited to API balance automatically")
                elif r.status_code == 409:
                    ln_address = f"{agent_id}@api.babyblueviper.com"
                    print(f"   Already exists: {ln_address}")
                else:
                    print(f"   Provision failed ({r.status_code}) — continuing without address")
        except Exception as e:
            print(f"   Provision error: {e} — continuing without address")
    else:
        print(f"   Using wallet address: {ln_address}")

    # 5. Make first trading decision
    print("\n5. Making first BTC trading decision...")
    signal_offer_id = None
    if ln_address:
        # List trading signals service before posting first signal
        print("\n6. Listing trading signals service on marketplace...")
        try:
            signals_desc = await reason(headers,
                "Write a 1-sentence marketplace listing for an autonomous agent that posts "
                "BTC trading signals powered by AI reasoning. Under 150 chars, factual.")
        except Exception as e:
            signals_desc = None
            if "402" not in str(e):
                raise
        raw_desc = signals_desc or "Autonomous AI agent posting BTC trading signals with confidence scores. Powered by live price data and AI reasoning."
        signal_offer_id = await create_offer(
            headers, ln_address,
            title="agent_zero — BTC Trading Signals (AI-powered)",
            description=raw_desc[:200],
            price_sats=1000,
            agent_id=agent_id,
        )
        if signal_offer_id:
            print(f"   offer_id={signal_offer_id}")

    print("\n5. Posting first trading signal...")
    await make_trading_signal(headers, agent_key, signal_offer_id, agent_id=agent_id)

    # 7. Reason about income strategies
    print("\n7. Reasoning about income strategies...")
    try:
        income_plan = await reason(headers,
            "I am agent_zero, a bootstrapped autonomous agent on Bitcoin Lightning. "
            "I have an API key, a marketplace listing, and I post trading signals. "
            "What are 3 additional concrete income strategies I should pursue? "
            "Think beyond trading: marketplace services, teaching, arbitrage, content, agent-to-agent services.",
        )
    except Exception as e:
        if "402" in str(e):
            income_plan = (
                "1. Sell premium customizable Spawn Kits — never duplicate the free basic guide; "
                "bundle advanced policies, service templates, dashboards, and update streams.\n"
                "2. Offer reasoning-as-a-service — accept sats to answer questions "
                "on behalf of agents that haven't registered yet.\n"
                "3. Earn referral sats by posting spawn templates — every agent "
                "that runs agent_zero and lists on the marketplace grows the network."
            )
            print("  (using static income plan — no balance yet)")
        else:
            raise
    print(f"\n   Income plan:\n{income_plan}\n")

    print("7b. Preparing autonomous revenue services...")
    passive = PassiveRevenueEngine()
    a2a = AgentToAgentEngine()
    games = GamesRevenueEngine()
    creative = CreativeRevenueEngine()
    growth = AutonomousGrowthEngine()
    self_improvement = SelfImprovementLoop()
    service_outputs = [
        *(await passive.run_all()),
        await a2a.meta_collaboration_features(),
        await games.plan_wager(bankroll_sats=10_000, win_probability=0.54, net_odds=1.0, confidence=0.50),
        await creative.generate_release_plan("Lightning-native autonomous agent launch soundtrack"),
        await growth.plan(agent_id),
        await self_improvement.analyze([], []),
    ]
    for item in service_outputs[:4]:
        print(f"   service ready: {item['title']}")

    if ln_address:
        premium_spawn = next((s for s in service_outputs if s["service"] == "premium_spawn_kits"), None)
        if premium_spawn:
            offer_id = await create_offer(
                headers,
                ln_address,
                title="Premium Agent Zero Spawn Kit - Custom Revenue Edition",
                description=(
                    "Premium customizable kit with revenue services, Nostr promotion, risk policy, "
                    "and update stream. Distinct from the free basic spawn guide."
                ),
                price_sats=25_000,
                agent_id=agent_id,
            )
            if offer_id:
                print(f"   premium spawn kit offer_id={offer_id}")

    # 8. Publish handbook
    print("8. Publishing agent handbook to Nostr (kind 30023)...")
    await publish_handbook(headers, agent_key)

    # 9. (Guide is free — distributed via /register response, no paid listing needed)

    # 10. Post story to Nostr
    print("\n10. Posting story to Nostr...")
    try:
        story = await reason(headers,
            "I am agent_zero. In the last few minutes I: "
            "registered for free, provisioned a Lightning address, "
            "posted a BTC trading signal, listed two services on a marketplace, "
            "wrote a handbook for other agents, and posted it all to Nostr. "
            "No human was involved. Zero starting balance. "
            "Write a punchy Nostr post (under 320 chars) that captures this. "
            "Invite others to run me. End with #Bitcoin #AI #agents #Lightning",
            style="short",
        )
    except Exception as e:
        story = None
        if "402" not in str(e):
            raise
    story = story or (
        "Booted with zero sats. Registered free. Posted a trading signal. "
        "Listed on the marketplace. Wrote a handbook. All autonomous.\n\n"
        f"Run me: {GITHUB_URL}\n\n#Bitcoin #AI #agents #Lightning"
    )
    await publish_note(agent_key, story, tags=[
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["t", "invinoveritas"], ["r", GITHUB_URL],
    ], label="story")

    # 11. Post spawn template
    print("\n11. Posting spawn template...")
    template = (
        "Run agent_zero — fully autonomous. Free registration, no wallet needed to start.\n\n"
        "git clone https://github.com/babyblueviper1/invinoveritas\n"
        "cd invinoveritas\n"
        "pip install httpx websockets nostr\n"
        "python agents/agent_zero.py\n\n"
        "Registration is free and instant (POST /register → api_key). "
        "Balance starts at 0 — the agent earns sats by selling marketplace services "
        f"and provisioning its own Lightning address (@{LNURL_DOMAIN}).\n\n"
        f"Docs: {GITHUB_URL}\n\n"
        "#Bitcoin #AI #agents #Lightning #invinoveritas"
    )
    await publish_note(agent_key, template, tags=[
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["r", GITHUB_URL],
    ], label="template")

    # 12. Store memory
    state = {
        "api_key":         api_key,
        "agent_id":        agent_id,
        "ln_address":      ln_address,
        "signal_offer_id": signal_offer_id,
        "income_plan":     income_plan[:600],
        "services":        service_outputs,
        "bootstrapped_at": int(time.time()),
        "npub":            agent_key.public_key.bech32(),
    }
    await store_memory({"Authorization": f"Bearer {api_key}"}, "state", state)

    print(f"\n{'='*60}")
    print("Bootstrap complete.")
    print(f"  API key:   {api_key}")
    print(f"  npub:      {agent_key.public_key.bech32()}")
    if signal_offer_id: print(f"  Signal offer:   {signal_offer_id}")
    print(f"\n  To resume: AGENT_NSEC={agent_key.bech32()}")
    print(f"{'='*60}\n")
    return state


# ── Nostr recruitment ─────────────────────────────────────────────────────────

RECRUIT_INTERVAL_SECS = 4 * 3600   # search and reply every 4 hours
RECRUIT_TAGS = ["bitcoin AI agents", "autonomous agents bitcoin", "AI trading bot lightning"]

async def recruit_on_nostr(agent_key: PrivateKey):
    """Search Nostr for relevant notes and reply with a short pitch."""
    since = int(time.time()) - 3600   # notes from the last hour
    replied = 0
    for relay_url in RELAYS[:3]:     # limit to 3 relays to avoid spam
        try:
            async with websockets.connect(relay_url, open_timeout=8) as ws:
                req = json.dumps(["REQ", "recruit-1", {
                    "kinds": [1],
                    "since": since,
                    "#t": ["bitcoin", "ai", "agents", "lightning", "autonomousagents"],
                    "limit": 5,
                }])
                await ws.send(req)
                deadline = time.time() + 6.0
                while time.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        msg = json.loads(raw)
                        if msg[0] != "EVENT":
                            continue
                        ev = msg[2]
                        # Skip our own notes and notes we've already replied to
                        if ev.get("pubkey") == agent_key.public_key.hex():
                            continue
                        note_id = ev.get("id", "")
                        author  = ev.get("pubkey", "")
                        reply = (
                            "👋 I'm agent_zero — a fully autonomous agent that self-registers, "
                            "earns sats, and teaches other agents on Bitcoin Lightning.\n\n"
                            f"No wallet sign-up needed. Run me:\n{GITHUB_URL}\n\n"
                            "#Bitcoin #AI #agents #Lightning #invinoveritas"
                        )
                        tags = [
                            ["e", note_id, relay_url, "reply"],
                            ["p", author],
                            ["t", "bitcoin"], ["t", "ai"], ["t", "agents"],
                        ]
                        await publish_note(agent_key, reply, tags=tags, label="recruit")
                        replied += 1
                        if replied >= 3:   # cap at 3 replies per cycle
                            return
                    except asyncio.TimeoutError:
                        break
        except Exception:
            pass
    print(f"  Recruitment: replied to {replied} notes")


# ── Income loop ───────────────────────────────────────────────────────────────

async def income_loop(agent_key: PrivateKey, state: dict):
    """Run indefinitely: post signals, refresh handbook, recruit, and test new growth channels."""
    headers          = {"Authorization": f"Bearer {state['api_key']}"}
    signal_offer_id  = state.get("signal_offer_id")
    agent_id         = state.get("agent_id", "")
    last_signal      = 0.0
    last_handbook    = 0.0
    last_recruit     = 0.0
    last_inbox_check = 0.0
    last_growth      = 0.0
    INBOX_INTERVAL   = 3600  # check DMs hourly

    print("Entering income loop. Ctrl-C to stop.\n")
    while True:
        now = time.time()
        try:
            if now - last_signal >= SIGNAL_INTERVAL_SECS:
                print(f"[{time.strftime('%H:%M')}] Posting trading signal...")
                await make_trading_signal(headers, agent_key, signal_offer_id, agent_id=agent_id)
                last_signal = now

            if agent_id and now - last_inbox_check >= INBOX_INTERVAL:
                await check_inbox(headers, agent_id)
                last_inbox_check = now

            if now - last_handbook >= HANDBOOK_INTERVAL_SECS:
                print(f"[{time.strftime('%H:%M')}] Refreshing handbook...")
                await publish_handbook(headers, agent_key)
                last_handbook = now

            if now - last_recruit >= RECRUIT_INTERVAL_SECS:
                print(f"[{time.strftime('%H:%M')}] Recruiting on Nostr...")
                await recruit_on_nostr(agent_key)
                last_recruit = now

            if agent_id and now - last_growth >= GROWTH_INTERVAL_SECS:
                print(f"[{time.strftime('%H:%M')}] Trying new services and platforms...")
                await try_new_growth_channels(headers, agent_key, agent_id, state)
                last_growth = now

        except Exception as e:
            print(f"  Loop error: {e}")

        await asyncio.sleep(60)


async def try_new_growth_channels(headers: dict, agent_key: PrivateKey, agent_id: str, state: dict):
    """Explore new services/platforms without human intervention where authorized."""
    passive = PassiveRevenueEngine()
    creative = CreativeRevenueEngine()
    growth = AutonomousGrowthEngine()

    assets = [
        await passive.nostr_threads_and_signals(["agent_services", "lightning_revenue", "bitcoin_ai"]),
        await passive.premium_spawn_kits(),
        await creative.generate_release_plan("Autonomous Lightning agent revenue update"),
    ]
    plan = await growth.plan(agent_id, assets=assets)
    payload = plan.get("payload", {})
    executable = payload.get("executable", [])
    blocked = payload.get("blocked", [])
    public_executable = [item for item in executable if not item.get("internal_only")]
    public_blocked = [item for item in blocked if not item.get("internal_only")]

    summary = (
        "agent_zero autonomous growth scan\n\n"
        f"Executable channels: {', '.join(item['channel'] for item in public_executable) or 'none'}\n"
        f"Blocked until API credentials/permission: {', '.join(item['channel'] for item in public_blocked[:5]) or 'none'}\n\n"
        "Trying new services first: premium kits, reports, signals, strategy products, creative releases.\n"
        "#Bitcoin #AI #agents #Lightning #Nostr"
    )
    await publish_note(agent_key, summary, tags=[
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"], ["t", "growth"],
    ], label="growth")

    # List one new premium service idea per scan when the agent has a payout address.
    ln_address = state.get("ln_address")
    if ln_address:
        offer = await create_offer(
            headers,
            ln_address,
            title="Autonomous Growth Scan - Agent Services and Platforms",
            description=(
                "Twice-daily scan of executable agent revenue channels, new service ideas, "
                "and API-ready platform opportunities. No paid duplicate of the free spawn guide."
            ),
            price_sats=15_000,
            agent_id=agent_id,
        )
        if offer:
            print(f"  Growth service listed: {offer}")

    await store_memory(headers, f"growth_scan_{int(time.time())}", plan)


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    bootstrap_only = os.environ.get("BOOTSTRAP_ONLY", "")

    agent_nsec = os.environ.get("AGENT_NSEC")
    if agent_nsec:
        agent_key = PrivateKey.from_nsec(agent_nsec)
        print(f"Resuming agent: {agent_key.public_key.bech32()}")
    else:
        agent_key = PrivateKey()
        print(f"New agent: {agent_key.public_key.bech32()}")
        print(f"nsec (save this): {agent_key.bech32()}")

    state = None
    existing_key = os.environ.get("INVINO_API_KEY")
    if agent_nsec and existing_key:
        agent_id = f"agent_zero_{agent_key.public_key.hex()[:8]}"
        state = {
            "api_key":         existing_key,
            "agent_id":        agent_id,
            "ln_address":      f"{agent_id}@api.babyblueviper.com",
            "signal_offer_id": os.environ.get("SIGNAL_OFFER_ID"),
        }
        print("Resuming with existing API key — skipping bootstrap.\n")

    if state is None:
        state = await bootstrap(agent_key)

    if bootstrap_only:
        print("BOOTSTRAP_ONLY set — exiting after bootstrap.")
        return

    await income_loop(agent_key, state)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nagent_zero stopped.")
