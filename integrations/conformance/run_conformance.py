#!/usr/bin/env python3
"""
run_conformance.py — the conformance bar.

Asserts every fixture verifies to its DECLARED expectation:
  - the positive fixture passes all three joined suites end to end;
  - each negative fixture fails for EXACTLY ONE reason, and that reason matches its declared
    expected_failure_reason (and every other suite still passes — one broken join, not several).

Exit 0 iff the whole suite meets the bar. Run from anywhere:
    python3 run_conformance.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from verifier import verify_fixture  # noqa: E402

FIX = HERE / "fixtures"


def main() -> int:
    fixtures = sorted(p for p in FIX.glob("*.json")
                      if p.name not in ("trust_policy.json", "live_confirmed_anchor.json"))
    failures = []
    for path in fixtures:
        fx = json.loads(path.read_text())
        r = verify_fixture(fx)
        exp_pass = fx["expected_overall"] == "pass"
        exp_reason = fx.get("expected_failure_reason")

        # 1) overall verdict matches
        if r["overall_pass"] != exp_pass:
            failures.append(f"{path.name}: overall_pass={r['overall_pass']} expected {exp_pass}")
            continue
        if exp_pass:
            print(f"  ✓ {path.name}: PASS (all three suites join)")
            continue

        # 2) negative: fails for exactly the declared reason
        if r["failure_reason"] != exp_reason:
            failures.append(f"{path.name}: failed with {r['failure_reason']!r}, expected {exp_reason!r}")
            continue
        # 3) exactly ONE broken join (every other suite passes; not_assessable is a skip, not a break)
        broken = [name for name, s in r["suites"].items() if s["pass"] is False]
        if len(broken) != 1:
            failures.append(f"{path.name}: {len(broken)} broken suites {broken}, expected exactly 1")
            continue
        print(f"  ✓ {path.name}: FAIL ({exp_reason}) — exactly one broken join, others pass")

    print("-" * 64)
    if failures:
        print(f"CONFORMANCE BAR NOT MET — {len(failures)} issue(s):")
        for f in failures:
            print(f"    ✗ {f}")
        return 1
    print(f"CONFORMANCE BAR MET — {len(fixtures)} fixtures verify to their declared expectations.")
    print("Positive proves the five-invariant join end to end; each negative fails for exactly one reason.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
