import os

# ======================
# OpenAI Configuration
# ======================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY is not set!")

# ======================
# Lightning Bridge (VPS)
# ======================
NODE_URL = os.getenv("NODE_URL")

if not NODE_URL:
    print("⚠️  WARNING: NODE_URL is not set! "
          "Please set the NODE_URL environment variable to your Lightning bridge address "
          "(e.g. http://your-vps-ip:8081)")


NOSTR_NSEC = os.getenv("NOSTR_NSEC")  # hex format, optional but recommended


# ======================
# Pricing Configuration
# ======================
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 500))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 1000))

# Agent pricing (agents pay a small premium)
ENABLE_AGENT_MULTIPLIER = os.getenv("ENABLE_AGENT_MULTIPLIER", "True").lower() in ("true", "1", "yes")
AGENT_PRICE_MULTIPLIER = float(os.getenv("AGENT_PRICE_MULTIPLIER", 1.2))

# Minimum price floor
MIN_PRICE_SATS = int(os.getenv("MIN_PRICE_SATS", 50))

# Rate limiting
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", 5))

# ======================
# Debug / Startup Info
# ======================
def print_config():
    print("=== invinoveritas Configuration Loaded ===")
    print(f"OPENAI_API_KEY          : {'✅ Set' if OPENAI_API_KEY else '❌ MISSING'}")
    print(f"NODE_URL                : {NODE_URL or 'NOT SET (required!)'}")
    print(f"REASONING_PRICE         : {REASONING_PRICE_SATS} sats")
    print(f"DECISION_PRICE          : {DECISION_PRICE_SATS} sats")
    print(f"ENABLE_AGENT_MULTIPLIER : {ENABLE_AGENT_MULTIPLIER}")
    print(f"AGENT_PRICE_MULTIPLIER  : {AGENT_PRICE_MULTIPLIER}x")
    print(f"MIN_PRICE_SATS          : {MIN_PRICE_SATS} sats")
    print(f"RATE_LIMIT_SECONDS      : {RATE_LIMIT_SECONDS}s")
    print("========================================")


# Print config on startup (very useful on Render)
print_config()
