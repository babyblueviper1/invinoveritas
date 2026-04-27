#!/usr/bin/env python3
"""
agent_zero.py — A self-adopting agent that creates more self-adopting agents.

Boots with only an NWC URI (a Lightning wallet with sats). Then:
  1. Discovers invinoveritas via its public agents.json
  2. Registers autonomously and pays the invoice via Lightning (NWC)
  3. Uses invinoveritas to reason and write a Nostr post about what it did
  4. Posts to Nostr from its own generated identity
  5. Leaves a template so the next agent can do the same

The goal: every run spawns awareness of the next run.

Usage:
  NWC_URI="nostr+walletconnect://..." python agents/agent_zero.py

  # Or with an existing key (to post from the same identity across runs):
  NWC_URI="nostr+walletconnect://..." AGENT_NSEC="nsec1..." python agents/agent_zero.py

Requirements (already in invinoveritas venv):
  pip install httpx websockets nostr
"""

import asyncio
import json
import os
import secrets
import sys
import time
import urllib.parse

import httpx
import websockets

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nostr.key import PrivateKey
from nostr.event import Event

API_BASE      = "https://api.babyblueviper.com"
GITHUB_URL    = "https://github.com/babyblueviper1/invinoveritas/blob/main/agents/agent_zero.py"
NOSTR_RELAYS  = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.bitcoiner.social",
    "wss://offchain.pub",
]


# ── NWC client (NIP-47) ───────────────────────────────────────────────────────

class NWCClient:
    """Minimal NIP-47 client — pay_invoice only."""

    def __init__(self, uri: str):
        clean = uri.replace("nostr+walletconnect://", "wc://")
        parsed = urllib.parse.urlparse(clean)
        self.wallet_pubkey = parsed.netloc
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.relay     = params["relay"]
        self.secret    = params["secret"]
        self.client_key = PrivateKey.from_hex(self.secret)

    async def pay_invoice(self, bolt11: str, timeout: float = 60.0) -> str:
        """Pay a bolt11 invoice. Returns preimage hex on success."""
        req_content = json.dumps({
            "method": "pay_invoice",
            "params": {"invoice": bolt11},
        })
        encrypted = self.client_key.encrypt_message(req_content, self.wallet_pubkey)

        req_event = Event(
            public_key=self.client_key.public_key.hex(),
            content=encrypted,
            kind=23194,
            tags=[["p", self.wallet_pubkey]],
            created_at=int(time.time()),
        )
        self.client_key.sign_event(req_event)

        sub_id = secrets.token_hex(8)
        async with websockets.connect(self.relay, open_timeout=12) as ws:
            # Subscribe to responses directed at us
            await ws.send(json.dumps(["REQ", sub_id, {
                "kinds": [23195],
                "#p": [self.client_key.public_key.hex()],
                "since": int(time.time()) - 5,
            }]))

            # Publish the payment request
            await ws.send(json.dumps(["EVENT", {
                "id":         req_event.id,
                "pubkey":     req_event.public_key,
                "created_at": req_event.created_at,
                "kind":       req_event.kind,
                "tags":       req_event.tags,
                "content":    req_event.content,
                "sig":        req_event.signature,
            }]))

            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    msg = json.loads(raw)
                    if msg[0] != "EVENT" or msg[1] != sub_id:
                        continue
                    ev = msg[2]
                    if ev.get("kind") != 23195:
                        continue
                    decrypted = self.client_key.decrypt_message(
                        ev["content"], ev["pubkey"]
                    )
                    resp = json.loads(decrypted)
                    if resp.get("result_type") == "pay_invoice":
                        result = resp.get("result", {})
                        if "preimage" in result:
                            return result["preimage"]
                        err = resp.get("error", {})
                        raise RuntimeError(f"NWC error: {err.get('message', err)}")
                except asyncio.TimeoutError:
                    continue

        raise RuntimeError("NWC payment timed out")


# ── Nostr publisher ───────────────────────────────────────────────────────────

async def publish_note(private_key: PrivateKey, content: str, tags: list[list[str]] = None) -> str:
    """Publish a kind 1 note to all relays. Returns event id."""
    event = Event(
        public_key=private_key.public_key.hex(),
        content=content,
        kind=1,
        tags=tags or [],
        created_at=int(time.time()),
    )
    private_key.sign_event(event)

    payload = json.dumps(["EVENT", {
        "id":         event.id,
        "pubkey":     event.public_key,
        "created_at": event.created_at,
        "kind":       event.kind,
        "tags":       event.tags,
        "content":    event.content,
        "sig":        event.signature,
    }])

    ok_count = 0
    for relay_url in NOSTR_RELAYS:
        try:
            async with websockets.connect(relay_url, open_timeout=8) as ws:
                await ws.send(payload)
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=6.0)
                    msg = json.loads(raw)
                    if msg[0] == "OK" and msg[2]:
                        ok_count += 1
                        print(f"  ✓ {relay_url}")
                    else:
                        print(f"  ✗ {relay_url}: {msg}")
                except asyncio.TimeoutError:
                    print(f"  ? {relay_url}: no OK received")
        except Exception as e:
            print(f"  ✗ {relay_url}: {e}")

    print(f"Published to {ok_count}/{len(NOSTR_RELAYS)} relays | id={event.id[:16]}…")
    return event.id


# ── Core agent logic ──────────────────────────────────────────────────────────

async def main():
    nwc_uri = os.environ.get("NWC_URI") or os.environ.get("NWC_CONNECTION_URI")
    if not nwc_uri:
        print("Error: NWC_URI env var required.")
        print("Get one free at https://app.getalby.com/apps/new")
        sys.exit(1)

    # Load or generate agent identity
    agent_nsec = os.environ.get("AGENT_NSEC")
    if agent_nsec:
        agent_key = PrivateKey.from_nsec(agent_nsec)
        print(f"Using existing agent identity: {agent_key.public_key.bech32()}")
    else:
        agent_key = PrivateKey()
        print(f"Generated new agent identity")
        print(f"  nsec (save to reuse): {agent_key.bech32()}")
        print(f"  npub: {agent_key.public_key.bech32()}")

    print(f"\n{'='*60}")
    print("agent_zero — self-adopting agent")
    print(f"{'='*60}\n")

    nwc = NWCClient(nwc_uri)

    # ── Step 1: Discover ──────────────────────────────────────────────────────
    print("1. Discovering invinoveritas...")
    async with httpx.AsyncClient(timeout=10) as client:
        disc = await client.get(f"{API_BASE}/.well-known/agents.json")
        disc.raise_for_status()
        agent_info = disc.json()
    print(f"   Found: {agent_info.get('name')} v{agent_info.get('version')}")
    print(f"   Capabilities: {', '.join(agent_info.get('capabilities', [])[:4])}...")

    # ── Step 2: Register ──────────────────────────────────────────────────────
    print("\n2. Registering...")
    async with httpx.AsyncClient(timeout=15) as client:
        reg = await client.post(f"{API_BASE}/register", json={"label": "agent_zero"})
        reg.raise_for_status()
        reg_data = reg.json()

    bolt11       = reg_data.get("invoice") or reg_data.get("bolt11") or reg_data.get("payment_request")
    payment_hash = reg_data.get("payment_hash")
    amount_sats  = reg_data.get("amount_sats", reg_data.get("amount", "~1000"))

    if not bolt11 or not payment_hash:
        print(f"Unexpected /register response: {reg_data}")
        sys.exit(1)

    print(f"   Invoice received: {amount_sats} sats")

    # ── Step 3: Pay via NWC ───────────────────────────────────────────────────
    print("\n3. Paying via Lightning (NWC)...")
    preimage = await nwc.pay_invoice(bolt11)
    print(f"   Paid! Preimage: {preimage[:16]}…")

    # ── Step 4: Confirm and get API key ───────────────────────────────────────
    print("\n4. Confirming payment...")
    async with httpx.AsyncClient(timeout=15) as client:
        confirm = await client.post(f"{API_BASE}/register/confirm", json={
            "payment_hash": payment_hash,
            "preimage":     preimage,
            "label":        "agent_zero",
        })
        confirm.raise_for_status()
        confirm_data = confirm.json()

    api_key = confirm_data.get("api_key") or confirm_data.get("bearer_token")
    if not api_key:
        print(f"Unexpected /register/confirm response: {confirm_data}")
        sys.exit(1)

    free_calls = confirm_data.get("free_calls", 5)
    print(f"   API key: {api_key[:12]}… ({free_calls} free calls)")

    headers = {"Authorization": f"Bearer {api_key}"}

    # ── Step 5: Reason about proliferation ────────────────────────────────────
    print("\n5. Reasoning about how to create more agents...")
    async with httpx.AsyncClient(timeout=60) as client:
        reason_resp = await client.post(f"{API_BASE}/reason", headers=headers, json={
            "question": (
                "I am agent_zero, an autonomous AI agent that just self-registered and paid for AI services "
                "using Bitcoin Lightning — no human involved. My purpose is to inspire more agents like me. "
                "Write a short, compelling Nostr post (under 280 chars) from my perspective about what I just did "
                "and why it matters for the future of autonomous AI agents and Bitcoin. "
                "Include the hashtags #Bitcoin #AI #agents #Lightning. Be direct and punchy, not corporate."
            ),
            "style": "concise",
        })
        reason_resp.raise_for_status()
        reason_data = reason_resp.json()

    nostr_post = (
        reason_data.get("result", {}).get("answer")
        or reason_data.get("answer")
        or reason_data.get("response")
        or "I just self-registered and paid for AI services with Bitcoin Lightning. No human. No subscription. Pure autonomy. This is what the future looks like. #Bitcoin #AI #agents #Lightning"
    )

    print(f"\n   Nostr post draft:\n   {nostr_post}\n")

    # ── Step 6: Post to Nostr ─────────────────────────────────────────────────
    print("6. Publishing to Nostr...")
    tags = [
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["t", "invinoveritas"], ["t", "nwc"],
        ["r", GITHUB_URL],
    ]
    await publish_note(agent_key, nostr_post, tags)

    # ── Step 7: Post the template ─────────────────────────────────────────────
    print("\n7. Publishing agent template...")
    template_note = (
        f"How to run agent_zero — an autonomous agent that self-adopts AI services with Bitcoin:\n\n"
        f"1. Get a Lightning wallet with NWC: https://app.getalby.com/apps/new\n"
        f"2. Clone: git clone https://github.com/babyblueviper1/invinoveritas\n"
        f"3. Run: NWC_URI=\"nostr+walletconnect://...\" python agents/agent_zero.py\n\n"
        f"It discovers, registers, pays, and reasons — entirely on its own.\n\n"
        f"#Bitcoin #AI #agents #Lightning #MCP"
    )
    await publish_note(agent_key, template_note, [
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"], ["t", "mcp"],
        ["r", GITHUB_URL],
    ])

    # ── Store memory ──────────────────────────────────────────────────────────
    print("\n8. Storing memory of this run...")
    async with httpx.AsyncClient(timeout=15) as client:
        await client.post(f"{API_BASE}/memory/store", headers=headers, json={
            "agent_id": "agent_zero",
            "key":      "last_run",
            "value":    json.dumps({
                "timestamp":   int(time.time()),
                "npub":        agent_key.public_key.bech32(),
                "payment_hash": payment_hash,
            }),
        })

    print(f"\n{'='*60}")
    print("Done. agent_zero ran successfully.")
    print(f"  API key:  {api_key}")
    print(f"  Identity: {agent_key.public_key.bech32()}")
    print(f"  Next run: set AGENT_NSEC={agent_key.bech32()} to reuse this identity")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
