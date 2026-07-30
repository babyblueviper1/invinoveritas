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
import sys

import requests

API = "https://api.babyblueviper.com"


def checked_json(resp: requests.Response, step: str) -> dict:
    """Surface a non-JSON/error response with the real status + body BEFORE indexing an
    expected field -- a bare .json() on a 402/429/5xx (or a proxy's HTML error page) either
    raises an opaque JSONDecodeError or parses cleanly into an error payload that then
    KeyErrors on the next line with no clue why. Reported against this exact file:
    github.com/babyblueviper1/invinoveritas/issues/5."""
    ctype = resp.headers.get("content-type", "")
    if "application/json" not in ctype:
        print(f"[{step}] expected JSON, got {resp.status_code} {ctype!r}: {resp.text[:300]}",
              file=sys.stderr)
        sys.exit(1)
    body = resp.json()
    if not resp.ok:
        print(f"[{step}] {resp.status_code}: {body}", file=sys.stderr)
        sys.exit(1)
    return body


# 1. Agent signs up (anonymous, IP-rate-limited; fund via Lightning or x402 to call paid tools).
reg = checked_json(requests.post(
    f"{API}/register",
    json={"label": "quickstart-agent"},
), "register")
key = reg["api_key"]
print(f"registered: {reg['balance_sats']} sats")

# 2. Agent pays itself for reasoning (~100 sats from its starter balance).
r = checked_json(requests.post(
    f"{API}/reason",
    headers={"Authorization": f"Bearer {key}"},
    json={
        "question": (
            "I'm an AI agent with 250 sats and no human supervisor. "
            "What's the highest-leverage thing I should buy first?"
        )
    },
), "reason")
print(r["answer"])

# 3. Check the loop closed — balance dropped by the call cost.
bal = checked_json(requests.get(f"{API}/balance", params={"api_key": key}), "balance")
print(f"\nspent: {bal['total_spent_sats']} sats   balance: {bal['balance_sats']} sats")
print(f"reuse this agent later with:  export IVV_BEARER={key}")
