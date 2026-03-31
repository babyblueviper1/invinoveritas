import os

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Bridge on your VPS
NODE_URL = os.getenv("NODE_URL", "http://YOUR_VPS_IP:5000")

REASONING_PRICE_SATS = int(os.getenv("REASONING_PRICE_SATS", 500))
DECISION_PRICE_SATS = int(os.getenv("DECISION_PRICE_SATS", 1000))

ENABLE_DYNAMIC_PRICING = False
ENABLE_AGENT_DISCOUNT = True

if not OPENAI_API_KEY:
    print("⚠️ WARNING: OPENAI_API_KEY is not set!")

if not NODE_URL or "YOUR_VPS_IP" in NODE_URL:
    print("⚠️ WARNING: NODE_URL is not set correctly!")
