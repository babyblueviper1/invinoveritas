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
NODE_URL = os.getenv("NODE_URL", "http://127.0.0.1:5000")

if not NODE_URL or "YOUR_VPS_IP" in NODE_URL:
    print("⚠️  WARNING: NODE_URL is not properly configured!")

# ======================
# Pricing Configuration
# ======================
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 500))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 1000))

# Agent pricing logic
ENABLE_AGENT_MULTIPLIER = os.getenv("ENABLE_AGENT_MULTIPLIER", "True").lower() in ("true", "1", "yes")
AGENT_PRICE_MULTIPLIER = float(os.getenv("AGENT_PRICE_MULTIPLIER", 1.2))

# Minimum price floor
MIN_PRICE_SATS = int(os.getenv("MIN_PRICE_SATS", 50))

# Rate limiting
RATE_LIMIT_SECONDS = int(os.getenv("RATE_LIMIT_SECONDS", 5))

# ======================
# Debug Info
# ======================
def print_config():
    print("=== invinoveritas Configuration Loaded ===")
    print(f"OPENAI_API_KEY          : {'✅ Set' if OPENAI_API_KEY else '❌ MISSING'}")
    print(f"NODE_URL                : {NODE_URL}")
    print(f"REASONING_PRICE         : {REASONING_PRICE_SATS} sats")
    print(f"DECISION_PRICE          : {DECISION_PRICE_SATS} sats")
    print(f"ENABLE_AGENT_MULTIPLIER : {ENABLE_AGENT_MULTIPLIER}")
    print(f"AGENT_PRICE_MULTIPLIER  : {AGENT_PRICE_MULTIPLIER}x")
    print(f"MIN_PRICE_SATS          : {MIN_PRICE_SATS} sats")
    print(f"RATE_LIMIT_SECONDS      : {RATE_LIMIT_SECONDS}s")
    print("========================================")


# Print on startup (very useful on Render)
print_config()
