#!/usr/bin/env python3
"""invinoveritas-verify — portable, OFFLINE, zero-dependency verifier for invinoveritas proofs.

This is an "aqueduct": you run it on YOUR infrastructure and verify an invinoveritas verdict proof
WITHOUT calling our API and WITHOUT trusting us. It recomputes the proof's Nostr event id (NIP-01),
checks the BIP-340 schnorr signature against our PUBLISHED public key, and confirms authorship + shape.
A `valid` result means invinoveritas issued exactly this verdict — provable by math you ran yourself.

Zero dependencies on purpose: the schnorr verification is the canonical BIP-340 reference algorithm in
pure Python (stdlib hashlib only). A verifier that shipped a sketchy crypto dependency would be
self-defeating — here there is nothing to trust but ~120 lines you can read, and the only input that
matters is a PUBLIC key (no secret ships, by design).

Verdicts are byte-identical to the live endpoint https://api.babyblueviper.com/verify-proof.

Usage:
    python verify_proof.py path/to/proof.json      # or '-' / stdin
    from verify_proof import verify_proof; verify_proof(event_dict)
"""
from __future__ import annotations

import hashlib
import json
import sys

# invinoveritas's published verifier key (x-only, hex). Pin this; verification asserts authorship against
# it. Re-derive it yourself any time: GET https://api.babyblueviper.com/.well-known/agent-handshake →
# verifier_pubkey. If a proof's pubkey != this, it is NOT an invinoveritas verdict.
PUBLISHED_PUBKEY = "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7"
PROOF_KIND = 30078            # NIP-33 parameterized-replaceable; the only kind sign_payload issues
SCHEMA_PREFIX = "invinoveritas."

# ── secp256k1 + BIP-340 schnorr verification (canonical reference algorithm, pure stdlib) ─────────────
_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _tagged_hash(tag: str, msg: bytes) -> bytes:
    t = hashlib.sha256(tag.encode()).digest()
    return hashlib.sha256(t + t + msg).digest()


def _point_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        lam = (3 * x1 * x1) * pow(2 * y1, _P - 2, _P) % _P
    else:
        lam = (y2 - y1) * pow(x2 - x1, _P - 2, _P) % _P
    x3 = (lam * lam - x1 - x2) % _P
    y3 = (lam * (x1 - x3) - y1) % _P
    return (x3, y3)


def _point_mul(point, k):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _lift_x(x: int):
    """The point on secp256k1 with the given x and even y, or None if x is not on the curve."""
    if x >= _P:
        return None
    c = (pow(x, 3, _P) + 7) % _P
    y = pow(c, (_P + 1) // 4, _P)
    if pow(y, 2, _P) != c:
        return None
    return (x, y if y % 2 == 0 else _P - y)


def schnorr_verify(msg32: bytes, pubkey32: bytes, sig64: bytes) -> bool:
    """BIP-340 verify. msg = 32-byte message (here the event id), pubkey = 32-byte x-only, sig = 64 bytes."""
    if len(msg32) != 32 or len(pubkey32) != 32 or len(sig64) != 64:
        return False
    P = _lift_x(int.from_bytes(pubkey32, "big"))
    if P is None:
        return False
    r = int.from_bytes(sig64[0:32], "big")
    s = int.from_bytes(sig64[32:64], "big")
    if r >= _P or s >= _N:
        return False
    e = int.from_bytes(_tagged_hash("BIP0340/challenge", sig64[0:32] + pubkey32 + msg32), "big") % _N
    R = _point_add(_point_mul(_G, s), _point_mul(P, _N - e))
    if R is None or R[1] % 2 != 0 or R[0] != r:
        return False
    return True


# ── NIP-01 event id + invinoveritas proof verification ───────────────────────────────────────────────
def nostr_event_id(event: dict) -> str:
    """Recompute the canonical NIP-01 event id from the signed fields."""
    serial = json.dumps(
        [0, str(event["pubkey"]).lower(), int(event["created_at"]), int(event["kind"]),
         event.get("tags", []) or [], str(event["content"])],
        separators=(",", ":"), ensure_ascii=False,
    )
    return hashlib.sha256(serial.encode("utf-8")).hexdigest()


def verify_proof(event: dict, expect_pubkey: str = PUBLISHED_PUBKEY) -> dict:
    """Trustlessly verify an invinoveritas proof event. Returns {valid, checks{...}, ...}; never raises.
    `valid` is True only if all four checks hold — same logic as the live /verify-proof endpoint."""
    pin = (expect_pubkey or "").strip().lower()
    checks = {"id_integrity": False, "signature_valid": False,
              "issued_by_invinoveritas": False, "is_proof_event": False}
    out = {"valid": False, "checks": checks, "published_pubkey": PUBLISHED_PUBKEY,
           "how_to_verify": "Recompute id = sha256(JSON [0,pubkey,created_at,kind,tags,content]); schnorr-"
                            "verify sig over it vs pubkey; confirm pubkey == published_pubkey. NIP-01."}
    if not isinstance(event, dict):
        out["error"] = "event must be an object with id/pubkey/created_at/kind/tags/content/sig"
        return out
    content = event.get("content", "")
    tags = event.get("tags", []) or []
    # DoS guards — match the API; a real proof is a few hundred bytes.
    if not isinstance(content, str) or len(content) > 65_536:
        out["error"] = "event content too large or not a string (max 64KB)"
        return out
    if not isinstance(tags, list) or len(tags) > 256 or len(str(tags)) > 65_536:
        out["error"] = "event tags too large (max 256 entries / 64KB)"
        return out
    if any(event.get(k) in (None, "") for k in ("id", "pubkey", "created_at", "kind", "content", "sig")):
        out["error"] = "event missing required fields"
        return out
    try:
        # 1. id integrity
        checks["id_integrity"] = nostr_event_id(event).lower() == str(event["id"]).lower()
        # 2. schnorr signature over the (claimed) id, against the event's own pubkey
        try:
            checks["signature_valid"] = schnorr_verify(
                bytes.fromhex(str(event["id"])), bytes.fromhex(str(event["pubkey"])),
                bytes.fromhex(str(event["sig"])))
        except Exception:
            checks["signature_valid"] = False
        # 3. authorship — pubkey must be the invinoveritas published key
        checks["issued_by_invinoveritas"] = bool(pin) and str(event["pubkey"]).strip().lower() == pin
        # 4. proof shape — kind 30078 + content schema starts with invinoveritas.
        try:
            schema = json.loads(str(event["content"])).get("schema", "")
        except Exception:
            schema = ""
        checks["is_proof_event"] = (int(event["kind"]) == PROOF_KIND
                                    and isinstance(schema, str) and schema.startswith(SCHEMA_PREFIX))
    except Exception as exc:
        out["error"] = f"malformed event: {type(exc).__name__}: {exc}"
        return out

    out["issued_by_invinoveritas"] = checks["issued_by_invinoveritas"]
    out["valid"] = all(checks.values())
    if checks["signature_valid"] and checks["issued_by_invinoveritas"] and not checks["is_proof_event"]:
        out["error"] = ("authentically signed by invinoveritas, but NOT a verdict/action proof "
                        "(wrong kind/schema). Not valid as a proof.")
    try:
        out["proof_payload"] = json.loads(event["content"])
    except Exception:
        out["proof_payload"] = None
    return out


def _main(argv=None) -> int:
    # console_scripts entry point calls _main() with no args; fall back to sys.argv.
    argv = list(sys.argv) if argv is None else argv
    src = argv[1] if len(argv) > 1 else "-"
    raw = sys.stdin.read() if src == "-" else open(src).read()
    try:
        event = json.loads(raw)
    except Exception as e:
        print(json.dumps({"valid": False, "error": f"input not JSON: {e}"}))
        return 2
    result = verify_proof(event)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
