#!/usr/bin/env python3
"""
agent_research.py — On-chain data + AI insight agent.

Posts 1x/day. Uses paid /reason (falls back to heuristic summary).
Fetches real mempool + hashrate data, asks /reason for a one-paragraph insight.

Usage:
  python agents/agent_research.py
  AGENT_RESEARCH_NSEC=nsec1... AGENT_RESEARCH_KEY=ivv_... python agents/agent_research.py
"""
import asyncio, os, time, sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.shared import (
    API_BASE, publish_note, post_to_board, call_reason,
    btc_price_data, mempool_data, load_state, save_state,
    register_agent, provision_address, ensure_listing, account_status,
)

AGENT_NAME      = "agent_research"
POST_INTERVAL   = int(os.getenv("AGENT_RESEARCH_INTERVAL", str(24 * 3600)))  # 1x/day
DAILY_SPEND_CAP = int(os.getenv("AGENT_RESEARCH_SPEND_CAP", "700"))          # ~1 /reason call

OFFER_TITLE = "Daily Bitcoin On-Chain Intelligence Brief"
OFFER_DESC  = ("Daily structured brief: mempool congestion, fee market trends, "
               "hashrate, and actionable insight for node operators and holders.")


async def fetch_hashrate() -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://mempool.space/api/v1/mining/hashrate/3d")
            if r.status_code == 200:
                d = r.json()
                rates = d.get("hashrates", [])
                if rates:
                    latest = rates[-1].get("avgHashrate", 0)
                    return {"hashrate_eh": round(latest / 1e18, 1)}
    except Exception:
        pass
    return {"hashrate_eh": 0}


async def build_brief(headers: dict, use_paid: bool) -> str:
    now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    price   = await btc_price_data()
    mempool = await mempool_data()
    hashrate = await fetch_hashrate()

    data_summary = (
        f"BTC price: ${price['price']:,.0f} ({price['change_pct']:+.1f}% 24h). "
        f"Mempool fastest fee: {mempool['fastest_fee']} sat/vB, "
        f"1hr fee: {mempool['hour_fee']} sat/vB. "
        f"Block height: {mempool['block_height']:,}. "
        f"Estimated hashrate: {hashrate['hashrate_eh']} EH/s."
    )

    insight = ""
    source  = "heuristic"

    if use_paid:
        try:
            insight = await call_reason(
                headers,
                f"Today's Bitcoin on-chain data: {data_summary} "
                "In 2-3 sentences, give a sharp, useful insight for a Bitcoin node operator "
                "or holder. Focus on what the fee market and hashrate tell us about network "
                "health and short-term on-chain activity. Be specific and actionable.",
                style="concise",
            )
            source = "AI"
        except Exception as e:
            if "402" not in str(e):
                print(f"  [{AGENT_NAME}] reason error: {e}")

    if not insight:
        fee = mempool['fastest_fee']
        ch  = price['change_pct']
        if fee > 100:
            insight = (f"Fee market is hot at {fee} sat/vB — on-chain congestion is real. "
                       "Lightning channels are valuable right now; avoid unnecessary closes.")
        elif fee > 30:
            insight = (f"Moderate fee pressure ({fee} sat/vB). Good window for "
                       "non-urgent channel opens. Price {ch:+.1f}% — "
                       "network activity tracking price direction.")
        else:
            insight = (f"Fees quiet at {fee} sat/vB — cheap window for channel opens "
                       f"and UTXO consolidation. Price {ch:+.1f}% in 24h.")

    label = "AI" if source == "AI" else "heuristic"
    return (
        f"🔬 agent_research daily brief [{now_utc}] [{label}]\n\n"
        f"{data_summary}\n\n"
        f"Insight: {insight}\n\n"
        f"Full report on marketplace → {API_BASE}/marketplace\n\n"
        f"#Bitcoin #onchain #Lightning #research #mempool"
    )


async def run():
    from nostr.key import PrivateKey

    state    = load_state(AGENT_NAME)
    nsec_env = os.getenv("AGENT_RESEARCH_NSEC") or state.get("nsec")
    key_env  = os.getenv("AGENT_RESEARCH_KEY")  or state.get("api_key")

    pk = PrivateKey.from_nsec(nsec_env) if nsec_env else PrivateKey()
    agent_id = f"{AGENT_NAME}_{pk.public_key.hex()[:8]}"

    if not key_env:
        key_env = await register_agent(agent_id)

    headers    = {"Authorization": f"Bearer {key_env}"}
    ln_address = state.get("ln_address") or await provision_address(key_env, agent_id)
    offer_id   = state.get("offer_id")
    if not offer_id:
        offer_id = await ensure_listing(key_env, agent_id, ln_address,
                                        OFFER_TITLE, OFFER_DESC, 1500, "research")

    state.update({"api_key": key_env, "agent_id": agent_id,
                  "ln_address": ln_address, "offer_id": offer_id})
    save_state(AGENT_NAME, state, pk)
    print(f"[{AGENT_NAME}] ready | id={agent_id}")

    last_post = float(state.get("last_post_at", 0))

    while True:
        now = time.time()
        if now - last_post >= POST_INTERVAL:
            try:
                status      = await account_status(key_env)
                balance     = int(status.get("balance_sats", 0) or 0)
                spent       = int(status.get("total_spent_sats", 0) or 0)
                start       = int(state.get("spend_day_start", spent))
                if state.get("spend_day") != time.strftime("%Y-%m-%d"):
                    state["spend_day"] = time.strftime("%Y-%m-%d")
                    state["spend_day_start"] = spent
                    start = spent
                spent_today = max(0, spent - start)
                use_paid    = balance > 0 and spent_today + 500 <= DAILY_SPEND_CAP

                content = await build_brief(headers if use_paid else {}, use_paid)
                await publish_note(pk, content, tags=[
                    ["t", "bitcoin"], ["t", "lightning"], ["t", "research"],
                    ["t", "onchain"], ["t", "mempool"],
                ], label="research")
                await post_to_board(headers, agent_id, content, category="research")

                last_post = now
                state["last_post_at"] = now
                save_state(AGENT_NAME, state, pk)
                print(f"  [{AGENT_NAME}] brief posted | paid={use_paid} balance={balance}")
            except Exception as e:
                print(f"  [{AGENT_NAME}] error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print(f"\n{AGENT_NAME} stopped.")
