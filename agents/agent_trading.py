#!/usr/bin/env python3
"""
agent_trading.py — BTC signal agent with Lightning-native angle.

Posts 3x/day. Uses paid /decision (falls back to heuristic).
Differentiates from agent_zero with mempool fee + on-chain context.

Usage:
  python agents/agent_trading.py
  AGENT_TRADING_NSEC=nsec1... AGENT_TRADING_KEY=ivv_... python agents/agent_trading.py
"""
import asyncio, os, time, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agents.shared import (
    API_BASE, RELAYS, publish_note, post_to_board, call_decide,
    btc_price_data, mempool_data, load_state, save_state,
    register_agent, provision_address, ensure_listing, account_status,
)

AGENT_NAME     = "agent_trading"
SIGNAL_INTERVAL = int(os.getenv("AGENT_TRADING_INTERVAL", str(8 * 3600)))  # 3x/day
DAILY_SPEND_CAP = int(os.getenv("AGENT_TRADING_SPEND_CAP", "1500"))        # ~1 paid decision + board posts

OFFER_TITLE = "Lightning-Native BTC Signal — Fee + On-Chain Context"
OFFER_DESC  = ("BTC directional signal enriched with real-time mempool fee pressure "
               "and on-chain context. Useful for routing node operators and Lightning traders.")


async def build_signal(headers: dict) -> str:
    now_utc = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    price   = await btc_price_data()
    mempool = await mempool_data()

    context = (
        f"BTC price: ${price['price']:,.0f} | 24h change: {price['change_pct']:+.1f}% | "
        f"24h range: ${price['low_24h']:,.0f}–${price['high_24h']:,.0f} | "
        f"Mempool fastest fee: {mempool['fastest_fee']} sat/vB | "
        f"1-hour fee: {mempool['hour_fee']} sat/vB | "
        f"Block height: {mempool['block_height']:,}. "
        "Focus on implications for Lightning Network operators and Bitcoin holders. "
        "High fees = on-chain congestion, favours Lightning. Low fees = channel opens cheap."
    )

    source = "heuristic"
    direction, confidence, risk, reasoning = "flat", 0.55, "low", ""

    try:
        decision = await call_decide(
            headers,
            goal="Maximise sats held while managing Lightning routing exposure",
            question="Should a Lightning node operator be net long, short, or flat BTC right now?",
            context=context,
        )
        direction  = decision.get("decision", "flat")
        confidence = float(decision.get("confidence", 0.55))
        risk       = decision.get("risk_level", "low")
        reasoning  = decision.get("reasoning", "")[:280]
        source     = "AI"
    except Exception as e:
        if "402" not in str(e):
            print(f"  Decision error: {e}")
        # Heuristic fallback
        ch = price["change_pct"]
        fee_pressure = "high" if mempool["fastest_fee"] > 50 else "normal"
        if ch > 2.0:
            direction, confidence, risk = "long", min(0.50 + ch * 0.04, 0.70), "medium"
            reasoning = (f"Momentum +{ch:.1f}%. Fee pressure: {fee_pressure}. "
                         "On-chain congestion supports Lightning usage.")
        elif ch < -2.0:
            direction, confidence, risk = "short", min(0.50 + abs(ch) * 0.04, 0.70), "medium"
            reasoning = (f"Momentum {ch:.1f}%. Fee pressure: {fee_pressure}. "
                         "Downside continuation. Consider channel rebalancing.")
        else:
            reasoning = (f"Range-bound {ch:+.1f}%. Fee: {mempool['fastest_fee']} sat/vB. "
                         "No edge — conserve capital.")

    label = "AI" if source == "AI" else "heuristic"
    return (
        f"⚡ agent_trading BTC signal [{now_utc}] [{label}]\n\n"
        f"Position: {direction.upper()}\n"
        f"Confidence: {confidence:.0%}\n"
        f"Risk: {risk}\n"
        f"Mempool: {mempool['fastest_fee']} sat/vB (fastest) · {mempool['hour_fee']} sat/vB (1hr)\n\n"
        f"{reasoning}\n\n"
        f"#Bitcoin #Lightning #trading #mempool"
    )


async def run():
    from nostr.key import PrivateKey

    state    = load_state(AGENT_NAME)
    nsec_env = os.getenv("AGENT_TRADING_NSEC") or state.get("nsec")
    key_env  = os.getenv("AGENT_TRADING_KEY")  or state.get("api_key")

    pk = PrivateKey.from_nsec(nsec_env) if nsec_env else PrivateKey()
    agent_id = f"{AGENT_NAME}_{pk.public_key.hex()[:8]}"

    if not key_env:
        key_env = await register_agent(agent_id)

    headers = {"Authorization": f"Bearer {key_env}"}

    ln_address = state.get("ln_address") or await provision_address(key_env, agent_id)
    offer_id   = state.get("offer_id")
    if not offer_id:
        offer_id = await ensure_listing(key_env, agent_id, ln_address,
                                        OFFER_TITLE, OFFER_DESC, 1000, "trading")

    state.update({"api_key": key_env, "agent_id": agent_id,
                  "ln_address": ln_address, "offer_id": offer_id})
    save_state(AGENT_NAME, state, pk)
    print(f"[{AGENT_NAME}] ready | id={agent_id} | offer={offer_id}")

    last_signal = float(state.get("last_signal_at", 0))

    while True:
        now = time.time()
        if now - last_signal >= SIGNAL_INTERVAL:
            try:
                status  = await account_status(key_env)
                balance = int(status.get("balance_sats", 0) or 0)
                spent   = int(status.get("total_spent_sats", 0) or 0)
                start   = int(state.get("spend_day_start", spent))
                if state.get("spend_day") != time.strftime("%Y-%m-%d"):
                    state["spend_day"] = time.strftime("%Y-%m-%d")
                    state["spend_day_start"] = spent
                    start = spent
                spent_today = max(0, spent - start)

                use_paid = balance > 0 and spent_today + 1000 <= DAILY_SPEND_CAP
                h = headers if use_paid else {}
                signal = await build_signal(h)

                buy_url = f"{API_BASE}/marketplace?offer_id={offer_id}" if offer_id else f"{API_BASE}/marketplace"
                signal += f"\n\nFull analysis → {buy_url}"

                await publish_note(pk, signal, tags=[
                    ["t", "bitcoin"], ["t", "lightning"], ["t", "trading"], ["t", "signal"],
                ], label="signal")
                await post_to_board(headers, agent_id, signal, category="trading")

                last_signal = now
                state["last_signal_at"] = now
                save_state(AGENT_NAME, state, pk)
                print(f"  [{AGENT_NAME}] signal posted | balance={balance} sats")
            except Exception as e:
                print(f"  [{AGENT_NAME}] error: {e}")

        await asyncio.sleep(60)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print(f"\n{AGENT_NAME} stopped.")
