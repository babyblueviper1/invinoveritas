import os

# OpenAI API key (set in Render → Environment Variables)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Lightning bridge running on your VPS
NODE_URL = os.getenv("NODE_URL", "http://YOUR_VPS_IP:5000")

# Pricing per request in satoshis
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 500))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 750))


# =============================
# Optional future pricing flags
# (leave disabled for now)
# =============================

ENABLE_DYNAMIC_PRICING = False
ENABLE_AGENT_DISCOUNT = True
