import os

# OpenAI key (set in Render → Environment Variables)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not set")


# Lightning bridge running on your VPS
NODE_URL = os.getenv("NODE_URL")

if not NODE_URL:
    raise ValueError("NODE_URL not set")


# Prices
REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 100))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 250))
