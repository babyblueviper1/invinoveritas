#!/usr/bin/env python3
"""Offline, zero-dep checker for the VeraData AAT hash chain (x402-foundation/x402#2749).

Recomputes query_hash -> event_hash -> chain_hash independently from the fixture's own
declared inputs, so the chain is a runnable proof, not an assertion. Also checks the
risk_category overclaim boundary: a CLEAN result over a fixed list set must not be
machine-readable as a global "entity is clean" claim.

    python3 check_chain.py        # exit 0 iff the full chain recomputes and the
                                   # overclaim boundary holds
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _strip_prefix(h: str) -> str:
    return h[len("sha256:"):] if h.startswith("sha256:") else h


def recompute(fx: dict) -> dict:
    rc = fx["recompute_construction"]
    resp = fx["response"]
    aat = resp["aat"]

    genesis = _sha256_hex(rc["genesis_input"])
    query_hash = _sha256_hex(rc["query_hash_input"])
    # Load-bearing detail: inputs to the NEXT hash carry their own "sha256:" prefix.
    event_hash = _sha256_hex(
        f"sha256:{query_hash}|{resp['risk_score']:.4f}|{resp['checked_at']}|{aat['policy_ref']}"
    )
    chain_hash = _sha256_hex(f"sha256:{genesis}|sha256:{event_hash}")

    return {
        "genesis_recomputes": genesis == _strip_prefix(aat["prev_hash"]),
        "query_hash_recomputes": query_hash == _strip_prefix(aat["query_hash"]),
        "event_hash_recomputes": event_hash == _strip_prefix(aat["event_hash"]),
        "chain_hash_recomputes": chain_hash == _strip_prefix(aat["chain_hash"]),
    }


def check_overclaim_boundary(fx: dict) -> bool:
    """A CLEAN/0.0 result must be scoped to the checked lists, not a global claim.
    Structural check: risk_category alone (without lists_checked + matches present
    alongside it) would let a consumer silently overclaim. Fail if the scope fields
    aren't present next to the verdict."""
    resp = fx["response"]
    has_scope = "lists_checked" in resp and isinstance(resp["lists_checked"], list) and resp["lists_checked"]
    has_matches = "matches" in resp and isinstance(resp["matches"], list)
    return bool(has_scope and has_matches)


def main() -> int:
    fixtures = sorted(HERE.glob("sanctions_response_*.json"))
    if not fixtures:
        print("no fixtures found", file=sys.stderr)
        return 2
    ok = True
    for path in fixtures:
        fx = json.loads(path.read_text())
        got = recompute(fx)
        exp = fx["expected"]
        chain_ok = all(got[k] == exp[k] for k in got)
        overclaim_ok = check_overclaim_boundary(fx)
        passed = chain_ok and overclaim_ok
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {path.name}")
        for k, v in got.items():
            print(f"    {k}: {v} (expected {exp[k]})")
        print(f"    overclaim_boundary_holds: {overclaim_ok}")
    print("\nchain + overclaim boundary hold ✓" if ok else "\nFIXTURE BROKEN ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
