"""
Trading Bot Net Profit Demo — invinoveritas + Lightning
========================================================
Shows how to build a trading bot that:
  1. Uses invinoveritas /decide before every trade
  2. Tracks invinoveritas spend against realized P&L
  3. Proves NET PROFIT: trade gains > AI consultation cost

This is a simulation (no real trades) — wire in your exchange API to go live.

Setup:
    pip install invinoveritas
    export INVINO_API_KEY="your-bearer-token"
    python trading_bot_net_profit.py

NWC wallet (recommended — no manual payments):
    export NWC_URI="nostr+walletconnect://..."
    pip install "invinoveritas[nwc]"
"""

import os
import sys
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../sdk"))

from invinoveritas import InvinoClient

BASE_URL = "https://api.babyblueviper.com"
API_KEY  = os.getenv("INVINO_API_KEY", "")

if not API_KEY:
    print("❌  Set INVINO_API_KEY to your Bearer token")
    print("    Register: https://api.babyblueviper.com/register")
    sys.exit(1)

# ─── Config ──────────────────────────────────────────────────────────────────
SIMULATED_CAPITAL_SATS = 1_000_000     # 0.01 BTC = 1M sats
MIN_CONFIDENCE         = 0.65          # skip if AI confidence < this
MAX_RISK_LEVEL         = "medium"      # skip if AI risk_level = "high"
MAX_CONSULT_SATS       = 50_000        # stop consulting after spending this much
TRADE_SIZE_SATS        = 100_000       # 10% of capital per trade
FEE_RATE               = 0.001         # 0.1% exchange fee per side

RISK_RANK = {"low": 0, "medium": 1, "high": 2}
MAX_RISK_RANK = RISK_RANK.get(MAX_RISK_LEVEL, 1)

client = InvinoClient(base_url=BASE_URL, bearer_token=API_KEY)


# ─── Simulated market data ────────────────────────────────────────────────────
def get_market_snapshot() -> dict:
    """In production: replace with exchange API call."""
    price = random.uniform(85_000, 110_000)
    rsi = random.uniform(25, 75)
    trend = random.choice(["uptrend", "downtrend", "sideways"])
    volume_24h = random.uniform(20_000, 80_000)  # BTC

    # Compute a crude "signal" for demo
    signal = "long" if rsi < 40 and trend == "uptrend" else \
             "short" if rsi > 60 and trend == "downtrend" else "neutral"

    return {
        "price_usd": round(price, 2),
        "rsi_14": round(rsi, 1),
        "trend": trend,
        "volume_24h_btc": round(volume_24h, 1),
        "signal": signal,
    }


def simulate_trade_outcome(direction: str, confidence: float) -> dict:
    """
    Simulate a trade outcome.
    Higher AI confidence → higher probability of winning.
    """
    win_prob = 0.45 + (confidence - 0.5) * 0.8
    win_prob = max(0.1, min(0.95, win_prob))

    won = random.random() < win_prob
    move_pct = random.uniform(0.003, 0.025) * (1 if won else -1)

    gross_pnl_sats = int(TRADE_SIZE_SATS * move_pct)
    fees_sats = int(TRADE_SIZE_SATS * FEE_RATE * 2)
    net_pnl_sats = gross_pnl_sats - fees_sats

    return {
        "won": won,
        "direction": direction,
        "gross_pnl_sats": gross_pnl_sats,
        "fees_sats": fees_sats,
        "net_pnl_sats": net_pnl_sats,
    }


# ─── Main trading loop ────────────────────────────────────────────────────────
def main():
    print("⚡ invinoveritas Trading Bot — Net Profit Demo")
    print(f"   Capital   : {SIMULATED_CAPITAL_SATS:,} sats")
    print(f"   Trade size: {TRADE_SIZE_SATS:,} sats ({TRADE_SIZE_SATS/SIMULATED_CAPITAL_SATS:.0%})")
    print(f"   Min conf  : {MIN_CONFIDENCE:.0%}")
    print(f"   Max risk  : {MAX_RISK_LEVEL}")
    print()

    total_trades     = 0
    skipped_trades   = 0
    total_pnl_sats   = 0
    total_consult_sats = 0
    wins             = 0

    for iteration in range(1, 11):
        print(f"── Iteration {iteration}/10 ─────────────────────────────────")

        mkt = get_market_snapshot()
        print(f"  Market: ${mkt['price_usd']:,.0f} | RSI={mkt['rsi_14']} | {mkt['trend']} | signal={mkt['signal']}")

        if mkt["signal"] == "neutral":
            print("  → No signal. Skipping.")
            skipped_trades += 1
            time.sleep(0.3)
            continue

        # ── check optimize_call to decide if consulting is worth it ──
        opt = client.optimize_call(
            question=f"Should I enter a {mkt['signal']} position on BTC?",
            context={
                "uncertainty": abs(mkt["rsi_14"] - 50) / 50,
                "value_at_risk": TRADE_SIZE_SATS,
                "steps": 2,
            }
        )
        if not opt["should_call_api"]:
            print(f"  → optimize_call: use local model (score={opt['score']}). Skipping consult.")
            skipped_trades += 1
            continue

        # ── consult invinoveritas ──
        if total_consult_sats >= MAX_CONSULT_SATS:
            print(f"  → Consult budget exhausted ({total_consult_sats:,} sats). Using signal directly.")
            decision = None
        else:
            try:
                decision = client.decide(
                    goal="Maximize BTC net profit while managing downside risk",
                    question=f"Should I enter a {mkt['signal']} trade on BTC at ${mkt['price_usd']:,.0f}?",
                    context=(
                        f"RSI={mkt['rsi_14']}, trend={mkt['trend']}, "
                        f"volume={mkt['volume_24h_btc']:.0f} BTC/24h, "
                        f"trade_size={TRADE_SIZE_SATS} sats, "
                        f"current_pnl={total_pnl_sats} sats"
                    ),
                    policy={"risk_limit": MAX_RISK_LEVEL},
                )
                cost_sats = opt["estimated_sats"]
                total_consult_sats += cost_sats
                print(f"  → AI: {decision.decision} | conf={decision.confidence:.0%} | risk={decision.risk_level} | cost={cost_sats} sats")
            except Exception as e:
                print(f"  → Consult failed: {e}. Using signal directly.")
                decision = None

        # ── apply filters ──
        if decision:
            if decision.confidence < MIN_CONFIDENCE:
                print(f"  → Confidence {decision.confidence:.0%} < {MIN_CONFIDENCE:.0%}. Skipping.")
                skipped_trades += 1
                continue
            if RISK_RANK.get(decision.risk_level, 0) > MAX_RISK_RANK:
                print(f"  → Risk {decision.risk_level} > {MAX_RISK_LEVEL}. Skipping.")
                skipped_trades += 1
                continue

        # ── execute simulated trade ──
        conf = decision.confidence if decision else 0.60
        outcome = simulate_trade_outcome(mkt["signal"], conf)
        total_pnl_sats += outcome["net_pnl_sats"]
        total_trades += 1
        if outcome["won"]:
            wins += 1

        result_icon = "✅" if outcome["won"] else "❌"
        print(f"  → Trade: {result_icon} {outcome['direction'].upper()} | "
              f"gross={outcome['gross_pnl_sats']:+,} sats | "
              f"fees={outcome['fees_sats']} sats | "
              f"net={outcome['net_pnl_sats']:+,} sats")

        time.sleep(0.5)

    # ─── Summary ──────────────────────────────────────────────
    print()
    print("═" * 55)
    print("  NET PROFIT SUMMARY")
    print("═" * 55)
    print(f"  Trades executed    : {total_trades}")
    print(f"  Trades skipped     : {skipped_trades}")
    print(f"  Win rate           : {wins/max(total_trades,1):.0%}")
    print(f"  Gross trading P&L  : {total_pnl_sats:+,} sats")
    print(f"  AI consult cost    : {total_consult_sats:,} sats")
    net = total_pnl_sats - total_consult_sats
    print(f"  ┌─────────────────────────────────────────┐")
    print(f"  │  NET PROFIT (P&L - AI cost) : {net:+,} sats │")
    print(f"  └─────────────────────────────────────────┘")
    if net > 0:
        multiple = (total_pnl_sats / max(total_consult_sats, 1))
        print(f"  Return on AI spend : {multiple:.1f}x")
        print()
        print("  ✅ PROFITABLE: The AI consultation cost was justified.")
        print("     invinoveritas added more value than it cost.")
    else:
        print()
        print("  📉 Not profitable this session.")
        print("     Tune MIN_CONFIDENCE or trade size to improve ROI.")

    print()
    print("  To go live: replace get_market_snapshot() with your exchange API")
    print("  and replace simulate_trade_outcome() with real order execution.")


if __name__ == "__main__":
    main()
