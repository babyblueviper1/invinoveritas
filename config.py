import os

# =============================
# OpenAI
# =============================

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# =============================
# Lightning Node (your VPS bridge)
# =============================

# Example: http://123.45.67.89:5000
NODE_URL = os.getenv("NODE_URL")


# =============================
# Pricing (in satoshis)
# =============================

# Premium reasoning endpoint
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", "500"))

# Agent decision endpoint
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", "250"))


# =============================
# Optional future pricing flags
# (leave disabled for now)
# =============================

ENABLE_DYNAMIC_PRICING = False
ENABLE_AGENT_DISCOUNT = True
