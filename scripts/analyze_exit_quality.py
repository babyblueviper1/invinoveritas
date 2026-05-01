#!/usr/bin/env python3
"""
Exit quality analyzer — reads agent_memory.json trade history and prints
shakeout rates, post-exit price movements, and learned exit biases.

A "shakeout" = price moved adversely >= 15 bps within 30 min after exit
(i.e., we exited and the trade would have recovered / continued profitably).

Run any time:
  python scripts/analyze_exit_quality.py
"""
import json
from collections import defaultdict
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "agent_memory.json"
SHAKEOUT_THRESHOLD_BPS = 15.0


def _pct(n: int, d: int) -> str:
    return f"{100*n/d:.0f}%" if d else "n/a"


def _stats(items: list[dict]) -> str:
    n = len(items)
    if not n:
        return "n=0"
    shakeouts = sum(1 for r in items if r.get("post_exit", {}).get("shakeout"))
    avg_adv = sum(float(r.get("post_exit", {}).get("max_adverse_bps", 0)) for r in items) / n
    avg_net = sum(float(r.get("net_pnl", 0) or 0) for r in items) / n
    return f"n={n:3d}  shakeout={_pct(shakeouts, n):5s}  avg_adv={avg_adv:+6.1f}bps  avg_net={avg_net:+7.1f}"


def main():
    with open(MEMORY_FILE) as f:
        mem = json.load(f)
    history = mem.get("history", [])

    tracked = [
        r for r in history
        if isinstance(r.get("post_exit"), dict)
        and r["post_exit"].get("shakeout") is not None
    ]
    untracked = [r for r in history if not isinstance(r.get("post_exit"), dict)]

    print(f"Total trade records: {len(history)}")
    print(f"  With post-exit data: {len(tracked)}")
    print(f"  Without (pre-feature or pending): {len(untracked)}")
    if not tracked:
        print("\nNo post-exit observations yet — data accumulates as bot trades.")
        print("Each exit fires 3 checks at +5m, +15m, +30m. Check back after ~10 trades.")
        return

    print(f"\nShakeout threshold: price moved adversely >= {SHAKEOUT_THRESHOLD_BPS:.0f} bps within 30 min\n")

    print(f"OVERALL: {_stats(tracked)}")

    # --- By exit reason ---
    print("\n=== BY EXIT REASON ===")
    reason_buckets: dict[str, list] = defaultdict(list)
    for r in tracked:
        raw = (r.get("post_exit") or {}).get("exit_reason_short") or (r.get("exit_reason") or "?")[:40]
        simplified = (
            "DET_THESIS_BREAK" if "THESIS_BREAK" in raw
            else "SL_HIT" if "SL_HIT" in raw
            else "DYN_REBALANCE" if "DYN_REBALANCE" in raw
            else "TP_HIT" if "TP_HIT" in raw
            else "OTHER"
        )
        reason_buckets[simplified].append(r)
    for key, items in sorted(reason_buckets.items(), key=lambda x: -len(x[1])):
        print(f"  {key:20s}  {_stats(items)}")

    # --- By close_alignment at exit ---
    print("\n=== BY CLOSE_ALIGNMENT AT EXIT ===")
    ca_buckets: dict[str, list] = defaultdict(list)
    for r in tracked:
        ca = float(r.get("close_alignment", 0.0) or 0.0)
        ca_buckets["high (>=0.60)" if ca >= 0.60 else "mid (0.35-0.60)" if ca >= 0.35 else "low (<0.35)"].append(r)
    for key in ["low (<0.35)", "mid (0.35-0.60)", "high (>=0.60)"]:
        items = ca_buckets.get(key, [])
        print(f"  {key:20s}  {_stats(items)}")

    # --- By side ---
    print("\n=== BY SIDE ===")
    for side in ("long", "short"):
        items = [r for r in tracked if r.get("side") == side]
        print(f"  {side:5s}  {_stats(items)}")

    # --- Post-exit price trajectories ---
    print("\n=== POST-EXIT PRICE MOVEMENT (avg bps, adverse direction) ===")
    for label in ("post_5m", "post_15m", "post_30m"):
        pts = [r for r in tracked if label in r.get("post_exit", {})]
        if not pts:
            continue
        adv = [float(r["post_exit"][label].get("adverse_bps", 0)) for r in pts]
        avg = sum(adv) / len(adv)
        reversal = sum(1 for a in adv if a >= SHAKEOUT_THRESHOLD_BPS)
        print(f"  {label}: n={len(pts)}  avg_adverse={avg:+.1f}bps  reversal_rate={_pct(reversal, len(pts))}")

    # --- DET_THESIS_BREAK deep dive ---
    det = reason_buckets.get("DET_THESIS_BREAK", [])
    if det:
        print(f"\n=== DET_THESIS_BREAK DEEP DIVE (n={len(det)}) ===")
        for label in ("post_5m", "post_15m", "post_30m"):
            pts = [r for r in det if label in r.get("post_exit", {})]
            if not pts:
                continue
            adv = [float(r["post_exit"][label].get("adverse_bps", 0)) for r in pts]
            avg = sum(adv) / len(adv)
            reversal = sum(1 for a in adv if a >= SHAKEOUT_THRESHOLD_BPS)
            print(f"  {label}: avg_adverse={avg:+.1f}bps  reversal_rate={_pct(reversal, len(pts))}")
        # Net PnL of shakeout vs confirmed DET exits
        shakeouts = [r for r in det if r.get("post_exit", {}).get("shakeout")]
        confirmed = [r for r in det if not r.get("post_exit", {}).get("shakeout")]
        if shakeouts:
            avg_sq = sum(float(r.get("net_pnl", 0) or 0) for r in shakeouts) / len(shakeouts)
            print(f"  Shakeout exits ({len(shakeouts)}): avg net_pnl={avg_sq:+.1f}  (we exited, it recovered)")
        if confirmed:
            avg_cf = sum(float(r.get("net_pnl", 0) or 0) for r in confirmed) / len(confirmed)
            print(f"  Confirmed exits ({len(confirmed)}): avg net_pnl={avg_cf:+.1f}  (we exited correctly)")

    # --- Learned biases ---
    bias = (mem.get("brain") or {}).get("exit_quality_bias") or {}
    if bias:
        print(f"\n=== LEARNED EXIT BIASES (last computed {bias.get('computed_at','?')[:19]}) ===")
        for k, v in (bias.get("biases") or {}).items():
            print(f"  {k:45s} = {v}")
    else:
        print("\n(exit_quality_bias not yet computed — needs >= 5 tracked exits)")


if __name__ == "__main__":
    main()
