import os

# =====================================
# OpenAI
# =====================================
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# =====================================
# Lightning Node (LND) - gRPC Connection
# =====================================
LND_DIR = os.getenv("LND_DIR", "/root/.lnd")

# Your restricted invoice macaroon (the one you baked earlier)
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
# Warnings
# =====================================
if not OPENAI_API_KEY:
    print("⚠️  WARNING: OPENAI_API_KEY is not set!")

if not LND_MACAROON_HEX:
    print("⚠️  WARNING: LND_MACAROON_HEX is not set! Lightning invoice creation will fail.")

# Optional: Show config on startup (development only)
if os.getenv("ENVIRONMENT") == "development":
    print(f"✅ Config loaded - Reasoning: {REASONING_PRICE_SATS} sats | Decision: {DECISION_PRICE_SATS} sats")
    print(f"LND_DIR = {LND_DIR}")
