#!/usr/bin/env python3
"""
Entry quality analyzer — reads agent_memory.json trade history and prints
win rates, avg PnL, and learned biases by entry condition.

Run any time to get a snapshot of what the bot has learned:
  python scripts/analyze_entry_quality.py
"""
import json
from collections import defaultdict, Counter
from pathlib import Path

MEMORY_FILE = Path(__file__).parent.parent / "agent_memory.json"


def _stats(pnls: list[float]) -> str:
    if not pnls:
        return "n=0"
    n = len(pnls)
    wins = sum(1 for p in pnls if p > 0)
    avg = sum(pnls) / n
    return f"n={n:3d}  win={100*wins/n:4.0f}%  avg={avg:+7.1f}"


def main():
    with open(MEMORY_FILE) as f:
        mem = json.load(f)
    history = mem.get("history", [])

    trades = [
        r for r in history
        if r.get("net_pnl") is not None and r.get("regime") is not None
    ]
    recent = [r for r in trades if r.get("level_alignment") is not None]
    print(f"Total closed trades: {len(trades)}  |  with full context: {len(recent)}")
    if not recent:
        print("Not enough data yet.")
        return

    baseline = [r["net_pnl"] for r in recent]
    print(f"\nBASELINE: {_stats(baseline)}\n")

    # --- Entry level alignment + direction ---
    print("=== DIRECTION × LEVEL ALIGNMENT (exit snapshot) ===")
    buckets = defaultdict(list)
    for r in recent:
        key = f"{r.get('side','?')}@{r.get('level_alignment','?')}"
        buckets[key].append(r["net_pnl"])
    for key, pnls in sorted(buckets.items(), key=lambda x: -len(x[1])):
        print(f"  {key:25s}  {_stats(pnls)}")

    # --- Wyckoff spring ---
    print("\n=== WYCKOFF SPRING SIGNALS ===")
    for field, label in [("wyckoff_spring_long", "spring_long"), ("wyckoff_spring_short", "spring_short")]:
        yes = [r["net_pnl"] for r in recent if r.get(field)]
        no  = [r["net_pnl"] for r in recent if r.get(field) is False]
        print(f"  {label}=True : {_stats(yes)}")
        print(f"  {label}=False: {_stats(no)}")

    # --- Sweep reclaim ---
    print("\n=== SWEEP RECLAIM ===")
    for field in ["sweep_reclaim_long", "sweep_reclaim_short"]:
        yes = [r["net_pnl"] for r in recent if r.get(field)]
        no  = [r["net_pnl"] for r in recent if r.get(field) is False]
        print(f"  {field}=True : {_stats(yes)}")
        print(f"  {field}=False: {_stats(no)}")

    # --- At support/resistance ---
    print("\n=== AT STRUCTURAL LEVEL ===")
    for field in ["at_support", "at_resistance"]:
        yes = [r["net_pnl"] for r in recent if r.get(field)]
        print(f"  {field}=True : {_stats(yes)}")

    # --- Entry tag patterns ---
    print("\n=== TOP ENTRY TAG PATTERNS ===")
    etag_buckets = defaultdict(list)
    for r in recent:
        tag = r.get("entry_tag") or "?"
        parts = tag.split("_")
        key = "_".join(parts[:5]) if len(parts) >= 5 else tag
        etag_buckets[key].append(r["net_pnl"])
    for key, pnls in sorted(etag_buckets.items(), key=lambda x: -len(x[1])):
        if len(pnls) < 3:
            continue
        print(f"  {key[:60]:60s}  {_stats(pnls)}")

    # --- Exit reason breakdown ---
    print("\n=== EXIT REASONS ===")
    exit_buckets = defaultdict(list)
    for r in recent:
        reason = (r.get("exit_reason") or "?").split("|")[0].strip()[:40]
        exit_buckets[reason].append(r["net_pnl"])
    for key, pnls in sorted(exit_buckets.items(), key=lambda x: -len(x[1]))[:12]:
        print(f"  {key:42s}  {_stats(pnls)}")

    # --- Regime breakdown ---
    print("\n=== BY REGIME ===")
    regime_buckets = defaultdict(list)
    for r in recent:
        regime_buckets[r.get("regime", "?")].append(r["net_pnl"])
    for key, pnls in sorted(regime_buckets.items(), key=lambda x: -len(x[1])):
        print(f"  {key:10s}  {_stats(pnls)}")

    # --- Learned biases (stored in brain, persisted in memory["brain"]) ---
    bias = (mem.get("brain") or {}).get("entry_quality_bias") or mem.get("entry_quality_bias") or {}
    if bias:
        print(f"\n=== LEARNED BIASES (last computed {bias.get('computed_at','?')[:19]}) ===")
        for k, v in (bias.get("biases") or {}).items():
            print(f"  {k:35s} = {v:+.4f}")
    else:
        print("\n(entry_quality_bias not yet computed — will run on next bot start)")


if __name__ == "__main__":
    main()
