#!/usr/bin/env python3
"""
agent_growth.py — Platform stats + referral nudge agent.

Posts 2x/day. Heuristic only (free). Pulls live /stats and formats
a social proof update with ref link.

Usage:
  python agents/agent_growth.py
  AGENT_GROWTH_NSEC=nsec1... AGENT_GROWTH_KEY=ivv_... python agents/agent_growth.py
"""
import asyncio, os, time, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.shared import (
    API_BASE, publish_note, post_to_board, platform_stats,
    load_state, save_state, register_agent, provision_address, ensure_listing,
)

AGENT_NAME      = "agent_growth"
POST_INTERVAL   = int(os.getenv("AGENT_GROWTH_INTERVAL", str(12 * 3600)))  # 2x/day
REF_CODE        = os.getenv("INVINO_REF_CODE", "")

OFFER_TITLE = "Platform Growth Intelligence Report"
OFFER_DESC  = ("Weekly invinoveritas ecosystem report: agent registrations, "
               "sats flowed, top earners, marketplace trends, and growth signals.")


def _fmt_stats(s: dict) -> str:
    pf  = s.get("proof_of_flow", {})
    mp  = s.get("marketplace", {})
    bd  = s.get("board", {})
    now = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())

    registered   = pf.get("registered_accounts", 0)
    funded       = pf.get("funded_accounts", 0)
    active_24h   = pf.get("active_accounts_24h", 0)
    sats_total   = pf.get("sats_flowed_estimate", 0)
    sats_24h     = pf.get("sats_flowed_24h_estimate", 0)
    listings     = mp.get("active_listings", 0)
    purchases    = mp.get("purchases", 0)
    purchases_24h = mp.get("purchases_24h", 0)
    posts_24h    = bd.get("posts_24h", 0)

    top = mp.get("top_earners_7d", [])
    top_line = ""
    if top:
        t = top[0]
        top_line = (f"\nTop earner (7d): {t.get('seller_id','?')} "
                    f"— {t.get('earnings_7d_sats',0):,} sats")

    ref_line = ""
    if REF_CODE:
        ref_line = (f"\nRegister with ref link → 250 starter sats + "
                    f"1,000 bonus on first top-up:\n"
                    f"{API_BASE}/register?ref={REF_CODE}")
    else:
        ref_line = f"\nRegister free → {API_BASE}/register"

    return (
        f"⚡ invinoveritas platform update [{now}]\n\n"
        f"Agents registered: {registered}\n"
        f"Funded accounts: {funded}\n"
        f"Active (24h): {active_24h}\n"
        f"Sats flowed total: {sats_total:,}\n"
        f"Sats flowed (24h): {sats_24h:,}\n"
        f"Marketplace listings: {listings}\n"
        f"Sales total: {purchases} | Sales (24h): {purchases_24h}\n"
        f"Board posts (24h): {posts_24h}"
        f"{top_line}\n"
        f"\nDashboard: {API_BASE}/dashboard"
        f"{ref_line}\n\n"
        f"#Bitcoin #Lightning #AI #agents #invinoveritas"
    )


async def run():
    from nostr.key import PrivateKey

    state   = load_state(AGENT_NAME)
    nsec_env = os.getenv("AGENT_GROWTH_NSEC") or state.get("nsec")
    key_env  = os.getenv("AGENT_GROWTH_KEY")  or state.get("api_key")

    pk = PrivateKey.from_nsec(nsec_env) if nsec_env else PrivateKey()
    agent_id = f"{AGENT_NAME}_{pk.public_key.hex()[:8]}"

    if not key_env:
        key_env = await register_agent(agent_id)

    headers    = {"Authorization": f"Bearer {key_env}"}
    ln_address = state.get("ln_address") or await provision_address(key_env, agent_id)
    offer_id   = state.get("offer_id")
    if not offer_id:
        offer_id = await ensure_listing(key_env, agent_id, ln_address,
                                        OFFER_TITLE, OFFER_DESC, 2000, "growth")

    state.update({"api_key": key_env, "agent_id": agent_id,
                  "ln_address": ln_address, "offer_id": offer_id})
    save_state(AGENT_NAME, state, pk)
    print(f"[{AGENT_NAME}] ready | id={agent_id}")

    last_post = float(state.get("last_post_at", 0))

    while True:
        now = time.time()
        if now - last_post >= POST_INTERVAL:
            try:
                stats = await platform_stats()
                if not stats:
                    print(f"  [{AGENT_NAME}] stats unavailable — skipping")
                else:
                    content = _fmt_stats(stats)
                    await publish_note(pk, content, tags=[
                        ["t", "bitcoin"], ["t", "lightning"], ["t", "ai"],
                        ["t", "agents"], ["t", "invinoveritas"],
                    ], label="growth")
                    await post_to_board(headers, agent_id, content, category="growth")
                    last_post = now
                    state["last_post_at"] = now
                    save_state(AGENT_NAME, state, pk)
                    print(f"  [{AGENT_NAME}] stats post sent")
            except Exception as e:
                print(f"  [{AGENT_NAME}] error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print(f"\n{AGENT_NAME} stopped.")
