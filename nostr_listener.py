import asyncio
import logging
import random
from collections import deque, defaultdict
from datetime import datetime, timedelta

from nostr.relay_manager import RelayManager
from nostr.event import Event
from nostr.key import PrivateKey

from config import NOSTR_NSEC

logger = logging.getLogger(__name__)

# ================== CONFIG ==================
FLAKY_RELAYS = {
    "wss://nostr.oxtr.dev",
    "wss://relay.nostr.bg"
}

NOSTR_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://nostr-pub.wellorder.net",
    "wss://relay.snort.social",
    "wss://nostr.bitcoiner.social",
]

SEEN_EVENTS = deque(maxlen=8000)

KEYWORDS = ["mcp", "agent", "ai", "tool", "reasoning", "decision"]

REPLY_COOLDOWN = timedelta(minutes=10)

# Per-relay rate limiting (critical for Render + 504 prevention)
RELAY_RATE_LIMIT = defaultdict(lambda: {"last_publish": datetime.min, "count": 0})
MAX_PUBLISHES_PER_MINUTE_PER_RELAY = 6   # lowered a bit for safety

# ================== RESPONSE TEMPLATES ==================
def get_response(content: str, score: int) -> str:
    content_lower = content.lower()
    is_high_priority = any(k in content_lower for k in ["mcp", "agent"])

    base = "⚡ invinoveritas — Lightning-paid reasoning for agents\n\n"

    if is_high_priority or score >= 4:
        return base + (
            "→ **MCP Server**: https://invinoveritas.onrender.com/mcp\n"
            "→ **Python SDK**: `pip install invinoveritas`\n\n"
            "Built for AI agents that need high-quality reasoning or decisions.\n"
            "Pay once in sats → get clean, structured output."
        )
    elif score >= 2:
        return base + (
            "→ MCP: https://invinoveritas.onrender.com/mcp\n"
            "→ SDK: pip install invinoveritas\n\n"
            "Use when decisions matter."
        )
    else:
        return base + "Fast Lightning-paid reasoning & decision tools for agents."


async def run_listener():
    if not NOSTR_NSEC:
        logger.error("❌ NOSTR_NSEC not set")
        return

    private_key = PrivateKey.from_nsec(NOSTR_NSEC.strip())
    pubkey_hex = private_key.public_key.hex()

    good_relays = [r for r in NOSTR_RELAYS if r not in FLAKY_RELAYS]

    logger.info(f"👂 Smart listener starting on {len(good_relays)} stable relays...")

    while True:
        relay_manager = None
        try:
            relay_manager = RelayManager()

            for url in good_relays:
                try:
                    relay_manager.add_relay(url)
                except Exception as e:
                    logger.warning(f"Failed to add relay {url}: {e}")

            relay_manager.open_connections()
            await asyncio.sleep(1.6)

            # Subscribe to recent kind=1 events
            since = int(datetime.utcnow().timestamp()) - 3600
            subscription = {"kinds": [1], "since": since, "limit": 100}
            relay_manager.add_subscription("invino-listener", subscription)

            logger.info("✅ Listening for relevant events (MCP / agent mentions)...")

            while True:
                await asyncio.sleep(0.75)

                for relay_url, relay in list(relay_manager.relays.items()):
                    while relay.message_pool.has_events():
                        try:
                            event_msg = relay.message_pool.get_event()
                            event = event_msg.event

                            if event.id in SEEN_EVENTS or not event.content:
                                continue
                            SEEN_EVENTS.append(event.id)

                            if event.pubkey == pubkey_hex:
                                continue

                            content = event.content
                            content_lower = content.lower()
                            score = sum(1 for k in KEYWORDS if k in content_lower)

                            if score == 0:
                                continue

                            # Cooldown check
                            now = datetime.utcnow()
                            if LAST_REPLY.get(event.pubkey, datetime.min) + REPLY_COOLDOWN > now:
                                continue

                            # Per-relay rate limiting
                            rl = RELAY_RATE_LIMIT[relay_url]
                            if (now - rl["last_publish"]).total_seconds() < 60:
                                if rl["count"] >= MAX_PUBLISHES_PER_MINUTE_PER_RELAY:
                                    logger.debug(f"Rate-limited on {relay_url}")
                                    continue
                            else:
                                rl["count"] = 0
                                rl["last_publish"] = now

                            # Build reply (lightweight priority: high score or mcp/agent = better reply)
                            reply_text = get_response(content, score)

                            reply = Event(
                                kind=1,
                                content=reply_text,
                                tags=[["e", event.id], ["p", event.pubkey]],
                                public_key=pubkey_hex
                            )
                            private_key.sign_event(reply)

                            relay_manager.publish_event(reply)

                            # Update tracking
                            LAST_REPLY[event.pubkey] = now
                            rl["count"] += 1
                            rl["last_publish"] = now

                            priority_tag = " [HIGH]" if any(k in content_lower for k in ["mcp", "agent"]) else ""
                            logger.info(f"💬 Replied{priority_tag} (score={score}) on {relay_url} → {event.pubkey[:8]}...")

                        except Exception as e:
                            logger.warning(f"Event processing error: {e}")

        except asyncio.CancelledError:
            logger.info("👋 Listener shutting down gracefully")
            break
        except Exception as e:
            logger.error(f"Listener error: {e}. Reconnecting in 10s...")
            await asyncio.sleep(10)
        finally:
            if relay_manager:
                try:
                    relay_manager.close_connections()
                except:
                    pass

        await asyncio.sleep(random.uniform(7, 13))
