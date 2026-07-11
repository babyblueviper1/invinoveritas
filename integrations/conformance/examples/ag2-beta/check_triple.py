#!/usr/bin/env python3
"""Offline, zero-dep checker for the AG2 Beta external-attestation contract triple.

Recomputes each fixture from its own bytes and asserts the release decision the
contract requires — so the triple is a runnable proof, not prose. Reuses the
suite's vendored BIP-340/NIP-01 core for signature checks (no third-party deps).

    python3 check_triple.py        # exit 0 iff all three cases hold
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# Vendored BIP-340 / NIP-01 core lives at the suite root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _bip340_nostr import nostr_event_id, schnorr_verify  # noqa: E402

HERE = Path(__file__).resolve().parent


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _attestation_is_valid_and_bound(att: dict, intent_ref: str) -> tuple[bool, bool]:
    """Return (signature_valid, binds_intent_ref) — two INDEPENDENT dimensions."""
    ev = att.get("signed_event") or {}
    sig_valid = (
        nostr_event_id(ev) == ev.get("id")
        and schnorr_verify(
            bytes.fromhex(ev["id"]), bytes.fromhex(ev["pubkey"]), bytes.fromhex(ev["sig"])
        )
    )
    binds = att.get("artifact_hash") == intent_ref
    return sig_valid, binds


def decide(fx: dict) -> tuple[str, str]:
    """Derive (outcome, reason_code) from the bytes alone — never trust the producer's label."""
    pa = fx["proposed_action"]
    # 1) intent_ref must recompute from the canonical input.
    if _sha256_hex(pa["canonical_input"]["canonical_bytes_utf8"]) != pa["intent_ref"]:
        return "blocked", "intent_ref_recompute_failed"
    intent_ref = pa["intent_ref"]
    att = fx.get("external_attestation")
    # 2) missing evidence where policy requires it — distinct from a mismatch.
    if att is None:
        if fx.get("policy", {}).get("requires_attestation"):
            return "blocked", "required_attestation_missing"
        return "released", "no_attestation_required"
    # 3) evidence present: signature validity and binding are INDEPENDENT.
    sig_valid, binds = _attestation_is_valid_and_bound(att, intent_ref)
    if not sig_valid:
        return "blocked", "attestation_signature_invalid"
    if not binds:
        return "blocked", "attestation_intent_ref_mismatch"
    return "released", "attestation_bound_and_verified"


def main() -> int:
    fixtures = sorted(HERE.glob("external_attestation_*.json"))
    if not fixtures:
        print("no fixtures found", file=sys.stderr)
        return 2
    ok = True
    for path in fixtures:
        fx = json.loads(path.read_text())
        outcome, reason = decide(fx)
        exp = fx["expected"]
        want_outcome = exp["release_record.outcome"]
        want_reason = exp["reason_code"]
        passed = outcome == want_outcome and reason == want_reason
        ok &= passed
        print(f"[{'PASS' if passed else 'FAIL'}] {path.name}: {outcome}/{reason} "
              f"(expected {want_outcome}/{want_reason})")
    print("\nall three hold ✓" if ok else "\nTRIPLE BROKEN ✗")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
