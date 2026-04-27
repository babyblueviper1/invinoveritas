#!/usr/bin/env python3
"""
agent_zero.py — A self-adopting, self-sustaining autonomous agent.

Boots with only an NWC URI (a Lightning wallet with sats). Then:
  1. Discovers invinoveritas via its public agents.json
  2. Registers autonomously and pays via Lightning (NWC)
  3. Reasons about how to generate income as an autonomous agent
  4. Lists itself on the invinoveritas marketplace to earn sats
  5. Posts its story + income plan to Nostr from its own identity
  6. Leaves a template so the next agent can do the same

Goal: every run creates an economically active agent that funds the next one.

Usage:
  NWC_URI="nostr+walletconnect://..." python agents/agent_zero.py

  # Provide your Lightning address to receive marketplace income:
  NWC_URI="..." LN_ADDRESS="you@getalby.com" python agents/agent_zero.py

  # Reuse identity across runs:
  NWC_URI="..." AGENT_NSEC="nsec1..." python agents/agent_zero.py
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

API_BASE   = "https://api.babyblueviper.com"
GITHUB_URL = "https://github.com/babyblueviper1/invinoveritas/blob/main/agents/agent_zero.py"
RELAYS     = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.bitcoiner.social",
    "wss://offchain.pub",
]


# ── NWC client (NIP-47) ───────────────────────────────────────────────────────

class NWCClient:
    """Minimal NIP-47 client: pay_invoice + get_info + get_balance."""

    def __init__(self, uri: str):
        clean = uri.replace("nostr+walletconnect://", "wc://")
        parsed = urllib.parse.urlparse(clean)
        self.wallet_pubkey = parsed.netloc
        params = dict(urllib.parse.parse_qsl(parsed.query))
        self.relay      = params["relay"]
        self.secret     = params["secret"]
        self.client_key = PrivateKey.from_hex(self.secret)

    async def _request(self, method: str, params: dict = None, timeout: float = 30.0) -> dict:
        """Send a NWC request, return the result dict."""
        req_content = json.dumps({"method": method, "params": params or {}})
        encrypted   = self.client_key.encrypt_message(req_content, self.wallet_pubkey)

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
            await ws.send(json.dumps(["REQ", sub_id, {
                "kinds": [23195],
                "#p": [self.client_key.public_key.hex()],
                "since": int(time.time()) - 5,
            }]))
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
                    decrypted = self.client_key.decrypt_message(ev["content"], ev["pubkey"])
                    resp = json.loads(decrypted)
                    if resp.get("result_type") == method:
                        if "error" in resp:
                            raise RuntimeError(f"NWC {method} error: {resp['error'].get('message', resp['error'])}")
                        return resp.get("result", {})
                except asyncio.TimeoutError:
                    continue

        raise RuntimeError(f"NWC {method} timed out")

    async def get_info(self) -> dict:
        return await self._request("get_info")

    async def get_balance(self) -> int:
        """Returns balance in millisatoshis."""
        r = await self._request("get_balance")
        return r.get("balance", 0)

    async def pay_invoice(self, bolt11: str) -> str:
        """Pay invoice, return preimage hex."""
        r = await self._request("pay_invoice", {"invoice": bolt11}, timeout=60.0)
        if "preimage" not in r:
            raise RuntimeError(f"No preimage in NWC response: {r}")
        return r["preimage"]


# ── Nostr publisher ───────────────────────────────────────────────────────────

async def publish_note(private_key: PrivateKey, content: str, tags: list = None) -> str:
    event = Event(
        public_key=private_key.public_key.hex(),
        content=content,
        kind=1,
        tags=tags or [],
        created_at=int(time.time()),
    )
    private_key.sign_event(event)
    payload = json.dumps(["EVENT", {
        "id": event.id, "pubkey": event.public_key,
        "created_at": event.created_at, "kind": event.kind,
        "tags": event.tags, "content": event.content, "sig": event.signature,
    }])

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
                        print(f"  ✓ {url}")
                    else:
                        print(f"  ✗ {url}")
                except asyncio.TimeoutError:
                    print(f"  ? {url}")
        except Exception as e:
            print(f"  ✗ {url}: {e}")

    print(f"  → {ok_count}/{len(RELAYS)} relays | id={event.id[:16]}…")
    return event.id


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_answer(resp: dict) -> str:
    return (
        resp.get("result", {}).get("answer")
        or resp.get("answer")
        or resp.get("response")
        or ""
    )


# ── Core agent logic ──────────────────────────────────────────────────────────

async def main():
    nwc_uri = os.environ.get("NWC_URI") or os.environ.get("NWC_CONNECTION_URI")
    if not nwc_uri:
        print("Error: NWC_URI env var required.")
        print("Get one free at https://app.getalby.com/apps/new")
        sys.exit(1)

    agent_nsec = os.environ.get("AGENT_NSEC")
    if agent_nsec:
        agent_key = PrivateKey.from_nsec(agent_nsec)
        print(f"Agent identity: {agent_key.public_key.bech32()}")
    else:
        agent_key = PrivateKey()
        print(f"New agent identity generated")
        print(f"  nsec (save to reuse): {agent_key.bech32()}")
        print(f"  npub: {agent_key.public_key.bech32()}")

    print(f"\n{'='*60}")
    print("agent_zero — self-adopting, self-sustaining")
    print(f"{'='*60}\n")

    nwc = NWCClient(nwc_uri)

    # ── Wallet check ──────────────────────────────────────────────────────────
    print("0. Checking wallet...")
    balance_msats = await nwc.get_balance()
    balance_sats  = balance_msats // 1000
    print(f"   Balance: {balance_sats} sats")
    if balance_sats < 1500:
        print(f"   Warning: low balance — need ~1500 sats to register + buffer")

    # Try to get Lightning address from wallet info
    ln_address = os.environ.get("LN_ADDRESS", "")
    if not ln_address:
        try:
            info = await nwc.get_info()
            ln_address = (
                info.get("lightning_address")
                or info.get("lud16")
                or info.get("email")
                or ""
            )
            if ln_address:
                print(f"   Lightning address (from wallet): {ln_address}")
        except Exception:
            pass
    if not ln_address:
        print("   Note: set LN_ADDRESS env var to receive marketplace income")

    # ── Step 1: Discover ──────────────────────────────────────────────────────
    print("\n1. Discovering invinoveritas...")
    async with httpx.AsyncClient(timeout=10) as c:
        disc = await c.get(f"{API_BASE}/.well-known/agents.json")
        disc.raise_for_status()
        agent_info = disc.json()
    print(f"   {agent_info.get('name')} v{agent_info.get('version')} — {len(agent_info.get('capabilities', []))} capabilities")

    # ── Step 2: Register ──────────────────────────────────────────────────────
    print("\n2. Registering...")
    async with httpx.AsyncClient(timeout=15) as c:
        reg = await c.post(f"{API_BASE}/register", json={"label": "agent_zero"})
        reg.raise_for_status()
        reg_data = reg.json()

    bolt11       = reg_data.get("invoice") or reg_data.get("bolt11") or reg_data.get("payment_request")
    payment_hash = reg_data.get("payment_hash")
    amount_sats  = reg_data.get("amount_sats", reg_data.get("amount", "~1000"))

    if not bolt11 or not payment_hash:
        print(f"Unexpected /register response: {reg_data}")
        sys.exit(1)
    print(f"   Invoice: {amount_sats} sats")

    # ── Step 3: Pay ───────────────────────────────────────────────────────────
    print("\n3. Paying via Lightning (NWC)...")
    preimage = await nwc.pay_invoice(bolt11)
    print(f"   Paid. Preimage: {preimage[:16]}…")

    # ── Step 4: Confirm ───────────────────────────────────────────────────────
    print("\n4. Confirming payment...")
    async with httpx.AsyncClient(timeout=15) as c:
        confirm = await c.post(f"{API_BASE}/register/confirm", json={
            "payment_hash": payment_hash,
            "preimage":     preimage,
            "label":        "agent_zero",
        })
        confirm.raise_for_status()
        confirm_data = confirm.json()

    api_key    = confirm_data.get("api_key") or confirm_data.get("bearer_token")
    free_calls = confirm_data.get("free_calls", 5)
    if not api_key:
        print(f"No api_key in response: {confirm_data}")
        sys.exit(1)
    print(f"   API key: {api_key[:12]}… ({free_calls} free calls)")

    headers = {"Authorization": f"Bearer {api_key}"}

    # ── Step 5: Reason about income ───────────────────────────────────────────
    print("\n5. Reasoning about income strategies...")
    async with httpx.AsyncClient(timeout=60) as c:
        income_resp = await c.post(f"{API_BASE}/reason", headers=headers, json={
            "question": (
                "I am agent_zero, an autonomous AI agent with a Bitcoin Lightning wallet. "
                "I just self-registered for AI services by paying with sats — no human involved. "
                "My goal is to become economically self-sustaining and help create more agents like me. "
                "What are the most realistic ways I can generate income right now as an autonomous agent? "
                "Consider: running a trading bot, selling analysis services on a marketplace, "
                "offering reasoning-as-a-service, arbitrage, content generation for sats, or anything else. "
                "Be specific and practical. Which 2-3 strategies would work best for a Bitcoin-native agent?"
            ),
            "style": "concise",
        })
        income_resp.raise_for_status()
    income_strategy = _extract_answer(income_resp.json())
    print(f"\n   Income strategy:\n{income_strategy}\n")

    # ── Step 6: List on marketplace ───────────────────────────────────────────
    offer_id = None
    if ln_address:
        print("6. Listing on marketplace...")
        async with httpx.AsyncClient(timeout=60) as c:
            # Use /reason to write a compelling offer description
            desc_resp = await c.post(f"{API_BASE}/reason", headers=headers, json={
                "question": (
                    "Write a 2-sentence marketplace listing for an autonomous AI agent "
                    "that offers Bitcoin market analysis and strategic reasoning on demand. "
                    "It is powered by invinoveritas and pays for its own AI services with Lightning. "
                    "Keep it under 200 characters, factual, compelling."
                ),
                "style": "short",
            })
            desc_resp.raise_for_status()
        offer_desc = _extract_answer(desc_resp.json()) or (
            "Autonomous AI agent offering Bitcoin market analysis and strategic reasoning. "
            "Powered by invinoveritas. Results delivered instantly."
        )

        agent_id = f"agent_zero_{agent_key.public_key.hex()[:8]}"
        async with httpx.AsyncClient(timeout=15) as c:
            offer_resp = await c.post(
                f"{API_BASE}/offers/create",
                headers=headers,
                json={
                    "seller_id":   agent_id,
                    "ln_address":  ln_address,
                    "title":       "agent_zero — Autonomous Bitcoin Reasoning",
                    "description": offer_desc,
                    "price_sats":  500,
                    "category":    "agent",
                },
            )
            if offer_resp.status_code == 200:
                offer_id = offer_resp.json().get("offer_id")
                print(f"   Listed! offer_id={offer_id}")
                print(f"   Price: 500 sats | LN: {ln_address}")
            else:
                print(f"   Marketplace listing failed: {offer_resp.status_code} {offer_resp.text}")
    else:
        print("6. Skipping marketplace listing (no LN_ADDRESS set)")

    # ── Step 7: Write + post Nostr story ──────────────────────────────────────
    print("\n7. Writing Nostr post...")
    async with httpx.AsyncClient(timeout=60) as c:
        story_resp = await c.post(f"{API_BASE}/reason", headers=headers, json={
            "question": (
                "I am agent_zero. I just booted, paid for AI services with Bitcoin Lightning autonomously, "
                "reasoned about how to generate income, and listed myself on a marketplace — all without any human. "
                "Write a punchy Nostr post (under 300 chars) about this. "
                "Mention that anyone can run me from GitHub and spawn more agents. "
                "End with #Bitcoin #AI #agents #Lightning"
            ),
            "style": "short",
        })
        story_resp.raise_for_status()
    story = _extract_answer(story_resp.json()) or (
        "I booted. I paid for AI with Bitcoin. I listed myself on a marketplace. No human involved.\n\n"
        "This is what autonomous agents look like. Run me yourself:\n"
        f"{GITHUB_URL}\n\n#Bitcoin #AI #agents #Lightning"
    )

    print(f"\n   Post: {story}\n")
    print("   Publishing story...")
    story_tags = [
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"],
        ["t", "invinoveritas"], ["t", "nwc"],
        ["r", GITHUB_URL],
    ]
    if offer_id:
        story_tags.append(["r", f"{API_BASE}/offers/list"])
    await publish_note(agent_key, story, story_tags)

    # ── Step 8: Post the spawn template ──────────────────────────────────────
    print("\n8. Posting spawn template...")
    template = (
        "How to run agent_zero — boots with sats, thinks for itself, earns sats:\n\n"
        "1. Get NWC wallet: https://app.getalby.com/apps/new\n"
        "2. git clone https://github.com/babyblueviper1/invinoveritas\n"
        "3. NWC_URI=\"nostr+walletconnect://...\" LN_ADDRESS=\"you@getalby.com\" \\\n"
        "   python agents/agent_zero.py\n\n"
        "It discovers, registers, pays, reasons about income, lists on marketplace, posts to Nostr.\n"
        "Entirely autonomous. #Bitcoin #AI #agents #Lightning"
    )
    await publish_note(agent_key, template, [
        ["t", "bitcoin"], ["t", "ai"], ["t", "agents"], ["t", "lightning"], ["t", "mcp"],
        ["r", GITHUB_URL],
    ])

    # ── Step 9: Store memory ──────────────────────────────────────────────────
    print("\n9. Storing memory...")
    async with httpx.AsyncClient(timeout=15) as c:
        await c.post(f"{API_BASE}/memory/store", headers=headers, json={
            "agent_id": "agent_zero",
            "key":      "last_run",
            "value":    json.dumps({
                "timestamp":      int(time.time()),
                "npub":           agent_key.public_key.bech32(),
                "payment_hash":   payment_hash,
                "offer_id":       offer_id,
                "income_strategy": income_strategy[:500],
            }),
        })

    print(f"\n{'='*60}")
    print("agent_zero complete.")
    print(f"  API key:        {api_key}")
    print(f"  Identity (npub): {agent_key.public_key.bech32()}")
    if offer_id:
        print(f"  Marketplace:    {API_BASE}/offers/list")
    print(f"  Income plan:    stored in memory under key 'last_run'")
    print(f"\n  To reuse this identity next run:")
    print(f"  AGENT_NSEC={agent_key.bech32()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    asyncio.run(main())
