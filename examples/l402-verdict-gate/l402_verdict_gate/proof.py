"""Offline verification of an invinoveritas verdict proof (a BIP-340 signed Nostr event, kind 30078).

No call to invinoveritas and no trust in whoever handed you the proof:
  id_integrity            sha256([0, pubkey, created_at, kind, tags, content]) == event.id      (NIP-01)
  signature_valid         BIP-340 signature over event.id by event.pubkey
  issued_by_invinoveritas event.pubkey == the pinned published key
  is_proof_event          kind 30078 and an invinoveritas.* schema
  decision_ref_recomputes sha256(JCS(preimage)) == content.decision_ref
  args_bound              sha256(JCS(args)) == content.action_binding_args_hash   (when args are given)
  tool_bound              sha256(tool) == content.action_binding_tool_hash        (when a tool is given)
Same checks as examples/qbtlabs-x402-verdict-gate/src/verdict/proof.ts.
"""
import hashlib
import json

from . import bip340
from .jcs import canonicalize

# Re-derive: GET https://api.babyblueviper.com/.well-known/agent-handshake
INVINOVERITAS_PUBKEY = "6786e18a864893a900bd9858e650f67ccc3513f248fed374b591e2ff6922fbb7"
PROOF_KIND = 30078


def sha256_hex(s) -> str:
    return hashlib.sha256(s.encode() if isinstance(s, str) else s).hexdigest()


def args_hash(args) -> str:
    return "sha256:" + sha256_hex(canonicalize(args))


def nostr_event_id(ev) -> str:
    ser = json.dumps([0, ev["pubkey"], ev["created_at"], ev["kind"], ev["tags"], ev["content"]],
                     separators=(",", ":"), ensure_ascii=False)
    return sha256_hex(ser)


def verify_verdict_proof(event, pubkey=None, args=None, tool=None) -> dict:
    pin = (pubkey or INVINOVERITAS_PUBKEY).lower()
    checks = {k: False for k in ("id_integrity", "signature_valid", "issued_by_invinoveritas", "is_proof_event",
                                 "decision_ref_recomputes")}
    out = {"valid": False, "checks": checks}
    if not isinstance(event, dict) or any(event.get(k) in (None, "") for k in ("id", "pubkey", "created_at", "kind", "content", "sig")):
        return {**out, "error": "missing event field"}
    try:
        checks["id_integrity"] = nostr_event_id(event) == str(event["id"]).lower()
        try:
            checks["signature_valid"] = bip340.verify(bytes.fromhex(event["pubkey"]), bytes.fromhex(event["id"]),
                                                      bytes.fromhex(event["sig"]))
        except ValueError:
            checks["signature_valid"] = False
        checks["issued_by_invinoveritas"] = event["pubkey"].lower() == pin
        content = json.loads(event["content"])
        checks["is_proof_event"] = event["kind"] == PROOF_KIND and str(content.get("schema", "")).startswith("invinoveritas.")
        fields = content.get("decision_ref_preimage_fields")
        if isinstance(fields, list) and isinstance(content.get("decision_ref"), str):
            pre = {f: content.get(f) for f in fields}
            checks["decision_ref_recomputes"] = "sha256:" + sha256_hex(canonicalize(pre)) == content["decision_ref"]
        if args is not None:
            checks["args_bound"] = args_hash(args) == content.get("action_binding_args_hash")
        if tool is not None:
            checks["tool_bound"] = "sha256:" + sha256_hex(tool) == content.get("action_binding_tool_hash")
    except Exception as e:  # malformed event: never valid
        return {**out, "error": f"malformed event: {e}"}
    out.update(valid=all(checks.values()), content=content, verdict=content.get("verdict"),
               decision_ref=content.get("decision_ref"), verified_at=content.get("verified_at"))
    return out
