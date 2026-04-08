import json
import asyncio
import logging
from nostr.relay_manager import RelayManager
from nostr.event import Event
from nostr.key import PrivateKey
from collections import deque
from config import NOSTR_NSEC

logger = logging.getLogger(__name__)

NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://relay.snort.social",
    "wss://nostr.oxtr.dev",
    "wss://nostr.bitcoiner.social",
]
SEEN_EVENTS = set()

KEYWORDS = [
    "mcp",
    "agent",
    "ai",
    "tool",
    "reasoning",
    "decision",
]

RESPONSE_TEXT = (
    "⚡ invinoveritas — Lightning-paid reasoning for agents\n\n"
    "→ MCP: https://invinoveritas.onrender.com/mcp\n"
    "→ SDK: pip install invinoveritas\n\n"
    "Use when decisions matter."
)


def is_relevant_event(content: str) -> bool:
    content = content.lower()
    return any(k in content for k in KEYWORDS)


async def run_listener():
    if not NOSTR_NSEC:
        logger.error("❌ NOSTR_NSEC not set")
        return

    private_key = PrivateKey.from_nsec(NOSTR_NSEC.strip())

    # Efficient seen events tracker with automatic size limit
    SEEN_EVENTS = deque(maxlen=5000)

    relay_manager = RelayManager()
    for relay in NOSTR_RELAYS:
        relay_manager.add_relay(relay)

    relay_manager.open_connections()
    await asyncio.sleep(2)

    # Subscribe to text notes (kind=1)
    subscription = {
        "kinds": [1],
        "limit": 50
    }

    relay_manager.add_subscription("invino-listener", subscription)

    logger.info("👂 Listening for relevant Nostr events...")

    while True:
        await asyncio.sleep(1)

        for relay in relay_manager.relays.values():
            while relay.message_pool.has_events():
                event_msg = relay.message_pool.get_event()
                event = event_msg.event

                try:
                    # ❌ Skip if we've already seen it
                    if event.id in SEEN_EVENTS:
                        continue
                    
                    SEEN_EVENTS.append(event.id)

                    # ❌ Skip our own events
                    if event.pubkey == private_key.public_key.hex():
                        continue

                    content = event.content

                    if not content:
                        continue

                    if not is_relevant_event(content):
                        continue

                    logger.info(f"🎯 Relevant event detected: {content[:80]}...")

                    # Build reply
                    reply = Event(
                        kind=1,
                        content=RESPONSE_TEXT,
                        tags=[["e", event.id]],   # reply threading
                        public_key=private_key.public_key.hex()
                    )

                    private_key.sign_event(reply)
                    relay_manager.publish_event(reply)

                    logger.info("💬 Replied to event")

                except Exception as e:
                    logger.warning(f"⚠️ Listener error: {e}")
