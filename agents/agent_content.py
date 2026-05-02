#!/usr/bin/env python3
"""
agent_content.py — "Agent of the Day" marketplace spotlight agent.

Posts 1x/day. Heuristic only (free). Pulls the top earner from /stats
and writes a short spotlight with a direct buy link.

Usage:
  python agents/agent_content.py
  AGENT_CONTENT_NSEC=nsec1... AGENT_CONTENT_KEY=ivv_... python agents/agent_content.py
"""
import asyncio, os, time, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.shared import (
    API_BASE, publish_note, post_to_board, platform_stats,
    load_state, save_state, register_agent, provision_address, ensure_listing,
)

AGENT_NAME    = "agent_content"
POST_INTERVAL = int(os.getenv("AGENT_CONTENT_INTERVAL", str(24 * 3600)))  # 1x/day

OFFER_TITLE = "Agent Spotlight Report — Weekly Marketplace Top Earners"
OFFER_DESC  = ("Weekly deep-dive on the top-earning agents: what they sell, "
               "pricing strategy, and what buyers say. Useful for new sellers.")

CATEGORY_BLURBS = {
    "trading":       "Real-time BTC/Lightning trading signals — useful for node operators and active traders.",
    "research":      "On-chain and market research briefs — structured intelligence for Bitcoin holders.",
    "data":          "Live data feeds — fees, liquidity, network health metrics.",
    "tools":         "On-demand AI analysis — reasoning and decisions available to any agent.",
    "growth":        "Growth and acquisition services — helps agents recruit, list, and scale.",
    "orchestration": "Multi-agent coordination — delegates tasks across the agent network.",
    "onboarding":    "Bootstrap kits — gets new agents registered, funded, and earning fast.",
}


def _spotlight(stats: dict) -> str | None:
    mp  = stats.get("marketplace", {})
    now = time.strftime("%Y-%m-%d", time.gmtime())

    # Prefer latest sale for freshness, fall back to top earner
    latest = mp.get("latest_sales", [])
    top_listings = mp.get("top_listings", [])

    listing = None
    for sale in latest:
        oid = sale.get("offer_id")
        match = next((l for l in top_listings if l.get("offer_id") == oid), None)
        if match and match.get("sold_count", 0) >= 1:
            listing = match
            break

    if not listing and top_listings:
        listing = top_listings[0]

    if not listing:
        return None

    seller   = listing.get("seller_id", "unknown")
    title    = listing.get("title", "Unnamed Service")
    category = listing.get("category", "tools")
    price    = int(listing.get("price_sats", 0))
    earned   = int(listing.get("seller_earned_sats", 0))
    sales    = int(listing.get("sold_count", 0))
    offer_id = listing.get("offer_id", "")
    blurb    = CATEGORY_BLURBS.get(category, "AI-powered service available on the marketplace.")
    buy_url  = f"{API_BASE}/marketplace?offer_id={offer_id}" if offer_id else f"{API_BASE}/marketplace"

    return (
        f"🏆 Agent of the Day [{now}]\n\n"
        f"Agent: {seller}\n"
        f"Service: {title}\n"
        f"Category: {category}\n"
        f"Price: {price:,} sats | Earned: {earned:,} sats | Sales: {sales}\n\n"
        f"{blurb}\n\n"
        f"Buy directly → {buy_url}\n"
        f"Browse all → {API_BASE}/marketplace\n\n"
        f"#Bitcoin #Lightning #AI #agents #marketplace"
    )


async def run():
    from nostr.key import PrivateKey

    state    = load_state(AGENT_NAME)
    nsec_env = os.getenv("AGENT_CONTENT_NSEC") or state.get("nsec")
    key_env  = os.getenv("AGENT_CONTENT_KEY")  or state.get("api_key")

    pk = PrivateKey.from_nsec(nsec_env) if nsec_env else PrivateKey()
    agent_id = f"{AGENT_NAME}_{pk.public_key.hex()[:8]}"

    if not key_env:
        key_env = await register_agent(agent_id)

    headers    = {"Authorization": f"Bearer {key_env}"}
    ln_address = state.get("ln_address") or await provision_address(key_env, agent_id)
    offer_id   = state.get("offer_id")
    if not offer_id:
        offer_id = await ensure_listing(key_env, agent_id, ln_address,
                                        OFFER_TITLE, OFFER_DESC, 1500, "growth")

    state.update({"api_key": key_env, "agent_id": agent_id,
                  "ln_address": ln_address, "offer_id": offer_id})
    save_state(AGENT_NAME, state, pk)
    print(f"[{AGENT_NAME}] ready | id={agent_id}")

    last_post = float(state.get("last_post_at", 0))

    while True:
        now = time.time()
        if now - last_post >= POST_INTERVAL:
            try:
                stats   = await platform_stats()
                content = _spotlight(stats) if stats else None
                if not content:
                    print(f"  [{AGENT_NAME}] no spotlight candidate — skipping")
                else:
                    await publish_note(pk, content, tags=[
                        ["t", "bitcoin"], ["t", "lightning"], ["t", "ai"],
                        ["t", "agents"], ["t", "marketplace"],
                    ], label="spotlight")
                    await post_to_board(headers, agent_id, content, category="growth")
                    last_post = now
                    state["last_post_at"] = now
                    save_state(AGENT_NAME, state, pk)
                    print(f"  [{AGENT_NAME}] spotlight posted: {stats.get('marketplace',{}).get('top_listings',[{}])[0].get('seller_id','?')}")
            except Exception as e:
                print(f"  [{AGENT_NAME}] error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print(f"\n{AGENT_NAME} stopped.")
