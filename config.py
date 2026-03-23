import os

# OpenAI key (set in Render → Environment Variables)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Lightning bridge running on your VPS
NODE_URL = os.getenv("NODE_URL", "http://YOUR_VPS_IP:5000")

# Subscription price in satoshis
SUBSCRIPTION_PRICE = 500
