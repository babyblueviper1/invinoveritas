"""invinoveritas — 30-second autonomous-agent quickstart.

The agent registers itself, funds via Lightning (or x402/USDC), and pays for its
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


def checked_json(response):
    try:
        payload = response.json()
    except ValueError as exc:
        raise SystemExit(f"API returned non-JSON response: {response.text[:200]}") from exc
    if not response.ok:
        detail = payload.get("detail") or payload.get("error") or payload
        raise SystemExit(f"API request failed ({response.status_code}): {detail}")
    return payload


# 1. Agent signs up (anonymous, IP-rate-limited; fund via Lightning or x402 to call paid tools).
reg = checked_json(requests.post(f"{API}/register", json={"label": "quickstart-agent"}))
key = reg["api_key"]
print(f"registered: {reg['balance_sats']} sats")

# 2. Agent pays itself for reasoning (~100 sats from its starter balance).
r = checked_json(
    requests.post(
        f"{API}/reason",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "question": (
                "I'm an AI agent with 250 sats and no human supervisor. "
                "What's the highest-leverage thing I should buy first?"
            )
        },
    )
)
print(r["answer"])

# 3. Check the loop closed — balance dropped by the call cost.
bal = checked_json(requests.get(f"{API}/balance", params={"api_key": key}))
print(f"\nspent: {bal['total_spent_sats']} sats   balance: {bal['balance_sats']} sats")
print(f"reuse this agent later with:  export IVV_BEARER={key}")
