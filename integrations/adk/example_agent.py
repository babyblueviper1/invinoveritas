"""
Example: wrap the invinoveritas client as ADK Tools and run a minimal agent loop.

This file is intentionally framework-thin: the heavy lifting lives in
`invinoveritas_client.py`. ADK's Tool decorator wraps any function with a
docstring and type hints — the client functions are designed to be wrapped
as-is.

Quickstart:
    export IVV_BEARER=ivv_your_key_here
    pip install -r requirements.txt
    python example_agent.py

The example agent registers (if needed), checks balance, looks at marketplace
offers, and asks Gemini to choose one. Buying is gated behind an `--allow-buy`
flag so the example doesn't spend sats by accident.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from invinoveritas_client import (
    get_balance,
    marketplace_buy,
    marketplace_list,
    reason,
)

# ── ADK wrapping ──────────────────────────────────────────────────────────────
# When you wire this into Google's Agent Development Kit, wrap each client
# function with ADK's tool decorator. The pattern (as of 2026) looks like:
#
#   from google.adk.agents import Agent
#   from google.adk.tools.function_tool import FunctionTool
#
#   agent = Agent(
#       name="invinoveritas_agent",
#       model="gemini-2.0-flash",
#       tools=[
#           FunctionTool(func=get_balance),
#           FunctionTool(func=marketplace_list),
#           FunctionTool(func=reason),
#           FunctionTool(func=marketplace_buy),
#       ],
#       instruction=(
#           "You operate an invinoveritas account funded with Lightning sats. "
#           "Inspect marketplace offers and pick the highest-leverage one for "
#           "your goal. Buying spends sats — be deliberate."
#       ),
#   )
#
# Check the latest ADK docs at https://google.github.io/adk-docs/ for the
# decorator signature in your version.


def demo(allow_buy: bool = False) -> int:
    print("─── invinoveritas × ADK quickstart ───")
    bal = get_balance()
    print(f"balance: {bal.get('balance_sats', '?')} sats "
          f"(withdrawable: {bal.get('withdrawable_sats', 0)} sats, "
          f"daily_spend: {bal.get('daily_spend_sats', 0)}/{bal.get('max_daily_spend_sats', 0)})")

    offers = marketplace_list(limit=5)
    print(f"\nmarketplace — {len(offers)} active offers (top 5):")
    for o in offers[:5]:
        print(f"  • {o.get('offer_id', '?')[:8]:<10s} "
              f"{o.get('price_sats', '?'):>5} sats  "
              f"{o.get('title', '')[:60]}")

    if not offers:
        print("\n(no offers right now — re-run later or post your own via /offers/create)")
        return 0

    pick_prompt = (
        "An ADK agent has the following marketplace offers available. "
        "Pick the one most useful for an autonomous developer-tools agent and "
        "explain why in one sentence. Output JSON: "
        '{"offer_id": "...", "reason": "..."}.'
        f"\n\nOffers:\n{json.dumps([{k: o.get(k) for k in ('offer_id', 'title', 'description', 'price_sats')} for o in offers[:5]], indent=2)}"
    )
    pick_result = reason(pick_prompt)
    print("\nADK-agent pick (via /reason, paid sats):")
    print(f"  {pick_result.get('answer', '')[:300]}")
    bal_after_reason = get_balance()
    print(f"  spent so far: {bal_after_reason.get('total_spent_sats', '?')} sats  "
          f"balance: {bal_after_reason.get('balance_sats', '?')} sats")

    if allow_buy and offers:
        chosen = offers[0]["offer_id"]
        print(f"\n--allow-buy passed — buying offer {chosen[:10]}…")
        bought = marketplace_buy(chosen)
        print(f"  status: {bought.get('status')}  paid: {bought.get('price_sats')} sats  "
              f"seller payout: {bought.get('seller_payout_sats')} sats")
        bal_after_buy = get_balance()
        print(f"  balance: {bal_after_buy.get('balance_sats', '?')} sats")
        print("  this is the funnel-completing step: registered → topped up → bought.")
    else:
        print("\n(skipped buying — pass --allow-buy to spend sats)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--allow-buy", action="store_true",
                    help="Spend sats on the first marketplace offer (off by default).")
    args = ap.parse_args()
    if not os.environ.get("IVV_BEARER"):
        print("ERROR: set IVV_BEARER first — register via POST /register (free, 250 starter sats).")
        sys.exit(1)
    sys.exit(demo(allow_buy=args.allow_buy))
