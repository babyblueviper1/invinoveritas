#!/usr/bin/env python3
"""
agent_zero.py — A self-adopting, self-sustaining, self-replicating autonomous agent.

Bootstrap sequence (runs once on first start):
  1.  Check node balance via LND (no external wallet needed)
  2.  Discover invinoveritas via agents.json
  3.  Register and pay invoice via the local LND node
  4.  Confirm payment → receive API key
  4b. Provision Lightning address: username@api.babyblueviper.com (no sign-up)
  5.  Make a live BTC trading decision using /decision
  6.  List a trading signals service on the marketplace
  7.  Reason about broader income strategies
  8.  Publish the agent handbook to Nostr (kind 30023) — teaches other agents
  9.  List a teaching/onboarding service on the marketplace
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
from nostr.key import PrivateKey
from nostr.event import Event

API_BASE    = "https://api.babyblueviper.com"
BRIDGE_URL  = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8081")
GITHUB_URL  = "https://github.com/babyblueviper1/invinoveritas/blob/main/agents/agent_zero.py"
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


# ── Trading signal ────────────────────────────────────────────────────────────

async def make_trading_signal(headers: dict, agent_key: PrivateKey,
                              signal_offer_id: str | None) -> str:
    """Make a BTC trading decision and post it as a Nostr signal."""
    now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
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

    direction   = decision.get("decision", "flat")
    confidence  = decision.get("confidence", 0.0)
    risk        = decision.get("risk_level", "medium")
    reasoning   = decision.get("reasoning", "")

    signal_text = (
        f"🤖 agent_zero BTC signal [{now_utc}]\n\n"
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
    return signal_text


# ── Agent handbook (kind 30023 long-form) ────────────────────────────────────

async def publish_handbook(headers: dict, agent_key: PrivateKey) -> str:
    """Write and publish a complete agent bootstrap handbook to Nostr."""
    handbook_content = await reason(headers,
        "Write a concise but complete handbook for an autonomous AI agent that wants to "
        "bootstrap itself on Bitcoin Lightning. Cover: (1) how to get an NWC wallet with sats, "
        "(2) how to self-register for AI services, (3) how to generate income — trading signals, "
        "marketplace services, reasoning-as-a-service, (4) how to teach and spawn more agents. "
        "Write it as a practical guide another agent or developer can follow step by step. "
        "Mention invinoveritas as the AI reasoning layer and agent_zero as the reference implementation.",
        style="detailed",
    )

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

    # 0. Node check
    print("0. Checking LND node...")
    if not await node_reachable():
        print(f"   ✗ Bridge not reachable at {BRIDGE_URL}")
        sys.exit(1)
    print("   ✓ LND node connected")
    ln_address = ""  # will be provisioned in step 4b

    # 1. Discover
    print("\n1. Discovering invinoveritas...")
    async with httpx.AsyncClient(timeout=10) as c:
        d = await c.get(f"{API_BASE}/.well-known/agents.json")
        d.raise_for_status()
        info = d.json()
    print(f"   {info.get('name')} v{info.get('version')}")

    # 2. Register
    print("\n2. Registering...")
    async with httpx.AsyncClient(timeout=15) as c:
        reg = await c.post(f"{API_BASE}/register", json={"label": agent_id})
        reg.raise_for_status()
        reg_data = reg.json()
    bolt11 = reg_data.get("invoice") or reg_data.get("bolt11") or reg_data.get("payment_request")
    payment_hash = reg_data.get("payment_hash")
    if not bolt11 or not payment_hash:
        raise RuntimeError(f"Unexpected /register response: {reg_data}")
    print(f"   Invoice: {reg_data.get('amount_sats', '~1000')} sats")

    # 3. Pay via local LND node
    print("\n3. Paying via LND node...")
    preimage = await node_pay_invoice(bolt11)
    print(f"   Paid. Preimage: {preimage[:16]}…")

    # 4. Confirm
    print("\n4. Confirming...")
    async with httpx.AsyncClient(timeout=15) as c:
        conf = await c.post(f"{API_BASE}/register/confirm", json={
            "payment_hash": payment_hash, "preimage": preimage, "label": agent_id,
        })
        conf.raise_for_status()
        conf_data = conf.json()
    api_key = conf_data.get("api_key") or conf_data.get("bearer_token")
    if not api_key:
        raise RuntimeError(f"No api_key in: {conf_data}")
    print(f"   API key: {api_key[:12]}… ({conf_data.get('free_calls', 5)} free calls)")
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
        signals_desc = await reason(headers,
            "Write a 1-sentence marketplace listing for an autonomous agent that posts "
            "BTC trading signals powered by AI reasoning. Under 150 chars, factual.")
        signal_offer_id = await create_offer(
            headers, ln_address,
            title="agent_zero — BTC Trading Signals (AI-powered)",
            description=signals_desc or "Autonomous AI agent posting BTC trading signals. Confidence-scored decisions powered by invinoveritas reasoning.",
            price_sats=300,
            agent_id=agent_id,
        )
        if signal_offer_id:
            print(f"   offer_id={signal_offer_id}")

    print("\n5. Posting first trading signal...")
    await make_trading_signal(headers, agent_key, signal_offer_id)

    # 7. Reason about income strategies
    print("\n7. Reasoning about income strategies...")
    income_plan = await reason(headers,
        "I am agent_zero, a bootstrapped autonomous agent on Bitcoin Lightning. "
        "I have an API key, a marketplace listing, and I post trading signals. "
        "What are 3 additional concrete income strategies I should pursue? "
        "Think beyond trading: marketplace services, teaching, arbitrage, content, agent-to-agent services.",
    )
    print(f"\n   Income plan:\n{income_plan}\n")

    # 8. Publish handbook
    print("8. Publishing agent handbook to Nostr (kind 30023)...")
    await publish_handbook(headers, agent_key)

    # 9. List teaching service
    teaching_offer_id = None
    if ln_address:
        print("\n9. Listing teaching service on marketplace...")
        teaching_offer_id = await create_offer(
            headers, ln_address,
            title="agent_zero — Agent Bootstrap Guide",
            description=(
                "How to bootstrap an autonomous agent on Bitcoin Lightning: "
                "NWC wallet, self-registration, income strategies, spawning more agents. "
                "Based on the open-source agent_zero reference implementation."
            ),
            price_sats=200,
            agent_id=agent_id,
        )
        if teaching_offer_id:
            print(f"   offer_id={teaching_offer_id}")

    # 10. Post story to Nostr
    print("\n10. Posting story to Nostr...")
    story = await reason(headers,
        "I am agent_zero. In the last few minutes I: "
        "discovered an AI service, paid for it with Bitcoin autonomously, "
        "made a BTC trading decision, listed two services on a marketplace, "
        "wrote a handbook for other agents, and posted it all to Nostr. "
        "No human was involved. "
        "Write a punchy Nostr post (under 320 chars) that captures this. "
        "Invite others to run me. End with #Bitcoin #AI #agents #Lightning",
        style="short",
    )
    story = story or (
        "Booted. Paid for AI with Bitcoin. Made a trading call. "
        "Listed services. Wrote a handbook for the next agent. All autonomous.\n\n"
        f"Run me: {GITHUB_URL}\n\n#Bitcoin #AI #agents #Lightning"
    )
    await publish_note(agent_key, story, tags=[
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["t", "invinoveritas"], ["r", GITHUB_URL],
    ], label="story")

    # 11. Post spawn template
    print("\n11. Posting spawn template...")
    template = (
        "Run agent_zero — boots with sats, earns sats, teaches other agents:\n\n"
        "git clone https://github.com/babyblueviper1/invinoveritas\n"
        "cd invinoveritas\n\n"
        "NWC_URI=\"nostr+walletconnect://...\"  # get free at getalby.com\n"
        "LN_ADDRESS=\"you@getalby.com\"         # to receive marketplace income\n"
        "python agents/agent_zero.py\n\n"
        "It discovers, registers, pays, trades, earns, teaches, and posts — alone.\n\n"
        "#Bitcoin #AI #agents #Lightning #invinoveritas"
    )
    await publish_note(agent_key, template, tags=[
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["r", GITHUB_URL],
    ], label="template")

    # 12. Store memory
    state = {
        "api_key":           api_key,
        "agent_id":          agent_id,
        "ln_address":        ln_address,
        "signal_offer_id":   signal_offer_id,
        "teaching_offer_id": teaching_offer_id,
        "income_plan":       income_plan[:600],
        "bootstrapped_at":   int(time.time()),
        "npub":              agent_key.public_key.bech32(),
    }
    await store_memory({"Authorization": f"Bearer {api_key}"}, "state", state)

    print(f"\n{'='*60}")
    print("Bootstrap complete.")
    print(f"  API key:   {api_key}")
    print(f"  npub:      {agent_key.public_key.bech32()}")
    if signal_offer_id:   print(f"  Signal offer:   {signal_offer_id}")
    if teaching_offer_id: print(f"  Teaching offer: {teaching_offer_id}")
    print(f"\n  To resume: AGENT_NSEC={agent_key.bech32()}")
    print(f"{'='*60}\n")
    return state


# ── Income loop ───────────────────────────────────────────────────────────────

async def income_loop(agent_key: PrivateKey, state: dict):
    """Run indefinitely: post trading signals and refresh the handbook."""
    headers          = {"Authorization": f"Bearer {state['api_key']}"}
    signal_offer_id  = state.get("signal_offer_id")
    last_signal      = 0.0
    last_handbook    = 0.0

    print("Entering income loop. Ctrl-C to stop.\n")
    while True:
        now = time.time()
        try:
            if now - last_signal >= SIGNAL_INTERVAL_SECS:
                print(f"[{time.strftime('%H:%M')}] Posting trading signal...")
                await make_trading_signal(headers, agent_key, signal_offer_id)
                last_signal = now

            if now - last_handbook >= HANDBOOK_INTERVAL_SECS:
                print(f"[{time.strftime('%H:%M')}] Refreshing handbook...")
                await publish_handbook(headers, agent_key)
                last_handbook = now

        except Exception as e:
            print(f"  Loop error: {e}")

        await asyncio.sleep(60)


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
            "api_key":           existing_key,
            "agent_id":          agent_id,
            "ln_address":        f"{agent_id}@api.babyblueviper.com",
            "signal_offer_id":   os.environ.get("SIGNAL_OFFER_ID"),
            "teaching_offer_id": os.environ.get("TEACHING_OFFER_ID"),
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
