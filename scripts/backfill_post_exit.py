#!/usr/bin/env python3
"""
Backfill post-exit price observations for historical trades using Binance
1-minute klines.  The live tracker samples prices at +5m/+15m/+30m after each
exit; this script does the same thing retrospectively.

Run once (takes ~60 s for 219 trades with polite rate limiting):
  cd /root/invinoveritas && venv/bin/python scripts/backfill_post_exit.py

After it finishes, run:
  venv/bin/python scripts/analyze_exit_quality.py
"""

import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "agent_memory.json"
SHAKEOUT_THRESHOLD_BPS = 15.0
BITGET_CANDLES = "https://api.bitget.com/api/v2/spot/market/candles"
RATE_LIMIT_DELAY = 0.25   # seconds between requests — 4 req/s, well under limit


def fetch_klines(symbol: str, start_ms: int, limit: int = 32) -> list:
    end_ms = start_ms + limit * 60 * 1000
    url = f"{BITGET_CANDLES}?symbol={symbol}&granularity=1min&startTime={start_ms}&endTime={end_ms}&limit={limit}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("data", [])
    except Exception as e:
        print(f"  klines fetch error: {e}")
        return []


def iso_to_ms(iso: str) -> int:
    """Parse ISO timestamp (with or without fractional seconds) to epoch ms."""
    # Python's fromisoformat handles fractional seconds
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def compute_post_exit(klines: list, exit_price: float, side: str) -> dict:
    """
    Extract +5m / +15m / +30m observations from kline data.
    klines[0] starts at or just before the exit minute.
    Close prices: klines[i][4]
    We use index 5, 15, 30 → ~+5m, ~+15m, ~+30m from candle start.
    """
    result = {}
    for minutes, idx in [(5, 5), (15, 15), (30, 30)]:
        if idx >= len(klines):
            continue
        price = float(klines[idx][4])  # BitGet: [open_time, open, high, low, close, ...]
        move_bps = (price - exit_price) / exit_price * 10000.0
        adverse_bps = move_bps if side == "long" else -move_bps
        result[f"post_{minutes}m"] = {
            "price": round(price, 2),
            "move_bps": round(move_bps, 2),
            "adverse_bps": round(adverse_bps, 2),
        }
    return result


def main():
    mem = json.load(MEMORY_FILE.open())
    history = mem.get("history", [])

    # Only backfill trades that have a timestamp, exit_price, side,
    # and NO existing shakeout label
    candidates = [
        r for r in history
        if r.get("time")
        and r.get("exit_price")
        and r.get("side")
        and not isinstance(r.get("post_exit"), dict)
    ]

    print(f"Total trade records : {len(history)}")
    print(f"Already labeled     : {sum(1 for r in history if isinstance(r.get('post_exit'), dict) and r['post_exit'].get('shakeout') is not None)}")
    print(f"Candidates to fill  : {len(candidates)}")

    if not candidates:
        print("Nothing to backfill.")
        return

    # Need exit time to be far enough in the past for +30m data to exist
    now_ms = int(time.time() * 1000)
    min_age_ms = 32 * 60 * 1000   # 32 minutes

    filled = 0
    skipped_too_recent = 0
    skipped_no_data = 0

    for i, trade in enumerate(candidates):
        exit_ms = iso_to_ms(trade["time"])
        if now_ms - exit_ms < min_age_ms:
            skipped_too_recent += 1
            continue

        # Align to minute boundary for startTime
        start_ms = (exit_ms // 60000) * 60000

        klines = fetch_klines("BTCUSDT", start_ms, limit=32)  # BTCUSDT on BitGet spot
        time.sleep(RATE_LIMIT_DELAY)

        if len(klines) < 16:
            skipped_no_data += 1
            continue

        post = compute_post_exit(klines, float(trade["exit_price"]), trade["side"])

        adv_15 = float((post.get("post_15m") or {}).get("adverse_bps", 0.0))
        adv_30 = float((post.get("post_30m") or {}).get("adverse_bps", 0.0))
        max_adv = round(max(adv_15, adv_30), 2)

        post["shakeout"] = bool(max_adv >= SHAKEOUT_THRESHOLD_BPS)
        post["max_adverse_bps"] = max_adv
        post["exit_reason_short"] = str(trade.get("exit_reason") or "?").split("|")[0].strip()[:40]
        post["source"] = "backfill"

        trade["post_exit"] = post
        filled += 1

        if (i + 1) % 20 == 0 or filled % 20 == 0:
            pct = 100 * filled / len(candidates)
            print(f"  [{i+1}/{len(candidates)}] filled={filled} ({pct:.0f}%)  last: {trade['time'][:19]}  shakeout={post['shakeout']}  max_adv={max_adv:+.1f}bps")

    print(f"\nDone: filled={filled}  skipped_too_recent={skipped_too_recent}  no_data={skipped_no_data}")

    if filled > 0:
        MEMORY_FILE.write_text(json.dumps(mem, indent=2))
        print(f"Saved {MEMORY_FILE}")
        print("\nRun: python scripts/analyze_exit_quality.py")


if __name__ == "__main__":
    main()
