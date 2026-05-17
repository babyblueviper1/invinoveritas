"""invinoveritas — 30-second autonomous-agent quickstart.

The agent registers itself, gets 250 free starter sats, and pays for its
own first reasoning call. No Lightning wallet needed to try.

Run:
    pip install requests
    python examples/quickstart.py

The printed `IVV_BEARER=...` key is the agent's identity — keep it to reuse
the same agent later (top up via POST /topup, buy from the marketplace,
spend on /browse, /execute, /sovereign/execute, etc.).
"""
import requests

API = "https://api.babyblueviper.com"

# 1. Agent signs up (anonymous, IP-rate-limited, 250 free starter sats).
key = requests.post(
    f"{API}/register",
    json={"label": "quickstart-agent"},
).json()["api_key"]

# 2. Agent pays itself for reasoning (~100 sats from its starter balance).
r = requests.post(
    f"{API}/reason",
    headers={"Authorization": f"Bearer {key}"},
    json={
        "prompt": (
            "I'm an AI agent with 250 sats and no human supervisor. "
            "What's the highest-leverage thing I should buy first?"
        )
    },
).json()

print(r["reasoning"])
print(f"\ncost: {r['cost_sats']} sats   balance: {r['balance_after']} sats")
print(f"reuse this agent later with:  export IVV_BEARER={key}")
