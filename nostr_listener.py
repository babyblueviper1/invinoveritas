import asyncio
import logging
import random
from collections import deque, defaultdict
from datetime import datetime, timedelta
from typing import Dict

from nostr.relay_manager import RelayManager
from nostr.event import Event
from nostr.key import PrivateKey

from config import NOSTR_NSEC

logger = logging.getLogger(__name__)

# ================== CONFIG ==================
FLAKY_RELAYS = {"wss://nostr.oxtr.dev", "wss://relay.nostr.bg"}

NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://relay.snort.social",
    "wss://nostr.bitcoiner.social",
]

SEEN_EVENTS = deque(maxlen=8000)          # increased a bit
KEYWORDS = ["mcp", "agent", "ai", "tool", "reasoning", "decision"]

REPLY_COOLDOWN = timedelta(minutes=10)

# Per-relay rate limiting (helps prevent 504s)
RELAY_RATE_LIMIT = defaultdict(lambda: {"last_publish": datetime.min, "count": 0})
MAX_PUBLISHES_PER_MINUTE_PER_RELAY = 8

# ================== RESPONSE TEMPLATES ==================
def get_response(score: int, content: str) -> str:
    base = "⚡ invinoveritas — Lightning-paid reasoning for agents\n\n"
    
    if score >= 4 or any(k in content.lower() for k in ["mcp", "agent"]):
        return base + (
            "→ MCP server: https://invinoveritas.onrender.com/mcp\n"
            "→ Python SDK: `pip install invinoveritas`\n\n"
            "Perfect for AI agents that need high-quality reasoning or decisions.\n"
            "Pay in sats → get structured output."
        )
    elif score >= 2:
        return base + (
            "→ MCP: https://invinoveritas.onrender.com/mcp\n"
            "→ SDK: pip install invinoveritas\n\n"
            "Use when decisions matter."
        )
    else:
        return base + "→ Fast Lightning-paid reasoning for agents. Check it out: https://invinoveritas.onrender.com/mcp"


async def run_listener():
    if not NOSTR_NSEC:
        logger.error("❌ NOSTR_NSEC not set")
        return

    private_key = PrivateKey.from_nsec(NOSTR_NSEC.strip())
    pubkey_hex = private_key.public_key.hex()

    good_relays = [r for r in NOSTR_RELAYS if r not in FLAKY_RELAYS]

    logger.info(f"👂 Starting smart listener on {len(good_relays)} relays...")

    while True:
        relay_manager = None
        try:
            relay_manager = RelayManager()
            for url in good_relays:
                relay_manager.add_relay(url)

            relay_manager.open_connections()
            await asyncio.sleep(1.5)

            # Subscribe
            since = int(datetime.utcnow().timestamp()) - 3600
            subscription = {"kinds": [1], "since": since, "limit": 120}
            relay_manager.add_subscription("invino-listener", subscription)

            logger.info("✅ Listener active — watching for MCP / agent mentions")

            while True:
                await asyncio.sleep(0.7)

                for relay_url, relay in list(relay_manager.relays.items()):
                    while relay.message_pool.has_events():
                        try:
                            event_msg = relay.message_pool.get_event()
                            event = event_msg.event

                            if event.id in SEEN_EVENTS:
                                continue
                            SEEN_EVENTS.append(event.id)

                            if event.pubkey == pubkey_hex or not event.content:
                                continue

                            content_lower = event.content.lower()
                            score = sum(1 for k in KEYWORDS if k in content_lower)
                            if score == 0:
                                continue

                            # === Priority boost for strong keywords ===
                            is_high_priority = any(k in content_lower for k in ["mcp", "agent"])

                            # === Cooldown check ===
                            now = datetime.utcnow()
                            if LAST_REPLY.get(event.pubkey, datetime.min) + REPLY_COOLDOWN > now:
                                continue

                            # === Per-relay rate limit (prevents 504s) ===
                            rl = RELAY_RATE_LIMIT[relay_url]
                            if (now - rl["last_publish"]).total_seconds() < 60:
                                if rl["count"] >= MAX_PUBLISHES_PER_MINUTE_PER_RELAY:
                                    logger.debug(f"Rate limited on {relay_url}")
                                    continue
                            else:
                                # Reset counter every minute
                                rl["count"] = 0
                                rl["last_publish"] = now

                            # === Build smart reply ===
                            reply_text = get_response(score, event.content)

                            reply = Event(
                                kind=1,
                                content=reply_text,
                                tags=[
                                    ["e", event.id],
                                    ["p", event.pubkey]
                                ],
                                public_key=pubkey_hex
                            )
                            private_key.sign_event(reply)

                            relay_manager.publish_event(reply)

                            # Update tracking
                            LAST_REPLY[event.pubkey] = now
                            rl["count"] += 1
                            rl["last_publish"] = now

                            logger.info(f"💬 Replied (score={score}{', HIGH' if is_high_priority else ''}) "
                                      f"on {relay_url} → {event.pubkey[:8]}...")

                        except Exception as inner_e:
                            logger.warning(f"Event processing error: {inner_e}")

        except asyncio.CancelledError:
            logger.info("Listener shutting down gracefully")
            break
        except Exception as e:
            logger.error(f"Listener crashed: {e}. Restarting in 8s...")
            await asyncio.sleep(8)
        finally:
            if relay_manager:
                try:
                    relay_manager.close_connections()
                except:
                    pass

        await asyncio.sleep(random.uniform(6, 12))
