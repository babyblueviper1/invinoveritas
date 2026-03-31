import os

# =====================================
# OpenAI
# =====================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# =====================================
# Lightning Node (LND) - Direct Connection
# =====================================
LND_REST_URL = os.getenv("LND_REST_URL", "http://127.0.0.1:8080")

# Your baked macaroon (DO NOT put the value directly in os.getenv like this)
LND_MACAROON_HEX = os.getenv("LND_MACAROON_HEX")

# =====================================
# Pricing
# =====================================
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 500))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 1000))

# =====================================
# Optional Features
# =====================================
ENABLE_DYNAMIC_PRICING = False
ENABLE_AGENT_DISCOUNT = True

# =====================================
# Warnings (helpful during development)
# =====================================
if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY is not set!")

if not LND_MACAROON_HEX:
    print("⚠️  WARNING: LND_MACAROON_HEX is not set! Lightning payments will fail.")

# Optional: Show config on startup in development
if os.getenv("ENVIRONMENT") == "development":
    print(f"✅ Config loaded - Reasoning: {REASONING_PRICE_SATS} sats | Decision: {DECISION_PRICE_SATS} sats")
