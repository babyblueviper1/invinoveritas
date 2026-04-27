#!/usr/bin/env python3
"""
Fetch all kind 1 notes from our Nostr pubkey, sign kind 5 deletion events
for any that contain old version strings (not "v1.1.1"), and broadcast them.

Run once:
  cd /root/invinoveritas && venv/bin/python scripts/delete_old_nostr_notes.py
"""
import asyncio
import json
import sys
import time
sys.path.insert(0, "/root/invinoveritas")

import websockets
from nostr.event import Event
from nostr.key import PrivateKey

NSEC = "nsec1r0jktys2z3vqv7t8etkksduwdv0vpka8hry36ecgfz2pappes2zqh72xht"
PUBKEY = "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7"
CURRENT_VERSION = "v1.4.0"

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://nostr.oxtr.dev",
    "wss://nostr.bitcoiner.social",
    "wss://offchain.pub",
]

FETCH_TIMEOUT  = 12.0   # seconds to wait for events per relay
PUBLISH_TIMEOUT = 10.0


async def fetch_kind1_from_relay(relay_url: str) -> list[dict]:
    """Return all kind 1 events from our pubkey on this relay."""
    events = []
    sub_id = "del-fetch"
    req = json.dumps(["REQ", sub_id, {
        "kinds": [1],
        "authors": [PUBKEY],
        "limit": 500,
    }])
    try:
        async with websockets.connect(relay_url, open_timeout=8) as ws:
            await ws.send(req)
            deadline = time.time() + FETCH_TIMEOUT
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                    msg = json.loads(raw)
                    if msg[0] == "EVENT" and msg[1] == sub_id:
                        events.append(msg[2])
                    elif msg[0] == "EOSE":
                        break
                except asyncio.TimeoutError:
                    break
    except Exception as e:
        print(f"  fetch error {relay_url}: {e}")
    return events


async def publish_deletion(relay_url: str, del_event: Event) -> bool:
    payload = json.dumps(["EVENT", json.loads(del_event.to_json_object() if hasattr(del_event, 'to_json_object') else _event_dict(del_event))])
    try:
        async with websockets.connect(relay_url, open_timeout=8) as ws:
            await ws.send(payload)
            deadline = time.time() + PUBLISH_TIMEOUT
            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                    msg = json.loads(raw)
                    if msg[0] == "OK" and msg[1] == del_event.id:
                        return msg[2]  # True = accepted
                except asyncio.TimeoutError:
                    break
    except Exception as e:
        print(f"  publish error {relay_url}: {e}")
    return False


def _event_dict(event: Event) -> str:
    """Fallback serializer for the nostr lib's Event object."""
    return json.dumps({
        "id": event.id,
        "pubkey": event.public_key,
        "created_at": event.date_time if hasattr(event, 'date_time') else int(time.time()),
        "kind": event.kind,
        "tags": event.tags,
        "content": event.content,
        "sig": event.signature,
    })


def build_deletion_event(private_key: PrivateKey, event_ids: list[str]) -> Event:
    tags = [["e", eid] for eid in event_ids]
    event = Event(
        kind=5,
        content="Deleting outdated version announcements",
        tags=tags,
        public_key=private_key.public_key.hex(),
    )
    private_key.sign_event(event)
    return event


def is_old_version(content: str) -> bool:
    """True if the note is a version announcement that is NOT the current version."""
    markers = ["invinoveritas", "babyblueviper", "lightning-native", "pay-per-use"]
    if not any(m in content.lower() for m in markers):
        return False
    return CURRENT_VERSION not in content


async def main():
    private_key = PrivateKey.from_nsec(NSEC)

    # ── 1. Collect kind 1 events from all relays ─────────────────────────────
    print(f"Fetching kind 1 events from {len(RELAYS)} relays...")
    seen: dict[str, dict] = {}
    tasks = [fetch_kind1_from_relay(r) for r in RELAYS]
    results = await asyncio.gather(*tasks)
    for relay_events in results:
        for ev in relay_events:
            seen[ev["id"]] = ev

    print(f"Found {len(seen)} unique kind 1 events from our pubkey\n")

    # ── 2. Filter to old-version notes ───────────────────────────────────────
    to_delete = [ev for ev in seen.values() if is_old_version(ev.get("content", ""))]

    if not to_delete:
        print("No old-version notes found — nothing to delete.")
        return

    print(f"Found {len(to_delete)} old-version note(s) to delete:")
    for ev in to_delete:
        snippet = ev["content"][:80].replace("\n", " ")
        ts = time.strftime("%Y-%m-%d %H:%M", time.gmtime(ev.get("created_at", 0)))
        print(f"  [{ts}] {ev['id'][:12]}…  {snippet}")

    # ── 3. Sign one kind 5 deletion event covering all IDs ───────────────────
    ids_to_delete = [ev["id"] for ev in to_delete]
    del_event = build_deletion_event(private_key, ids_to_delete)
    print(f"\nSigned kind 5 deletion event: {del_event.id[:16]}…")

    # ── 4. Broadcast deletion to all relays ──────────────────────────────────
    print(f"Broadcasting to {len(RELAYS)} relays...")

    # Build the raw payload once
    ev_dict = {
        "id": del_event.id,
        "pubkey": del_event.public_key,
        "created_at": del_event.created_at if hasattr(del_event, 'created_at') else int(time.time()),
        "kind": del_event.kind,
        "tags": del_event.tags,
        "content": del_event.content,
        "sig": del_event.signature,
    }
    payload = json.dumps(["EVENT", ev_dict])

    async def send_to_relay(url: str) -> bool:
        try:
            async with websockets.connect(url, open_timeout=8) as ws:
                await ws.send(payload)
                deadline = time.time() + PUBLISH_TIMEOUT
                while time.time() < deadline:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=4.0)
                        msg = json.loads(raw)
                        if msg[0] == "OK" and msg[1] == del_event.id:
                            ok = msg[2]
                            print(f"  {'✓' if ok else '✗'} {url}")
                            return ok
                    except asyncio.TimeoutError:
                        break
        except Exception as e:
            print(f"  ✗ {url}: {e}")
        return False

    tasks2 = [send_to_relay(r) for r in RELAYS]
    results2 = await asyncio.gather(*tasks2)
    ok_count = sum(1 for r in results2 if r)
    print(f"\nDeletion confirmed on {ok_count}/{len(RELAYS)} relays.")
    print("Primal honors NIP-09 — old notes should disappear within a few minutes.")


if __name__ == "__main__":
    asyncio.run(main())
