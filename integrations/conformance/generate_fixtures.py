#!/usr/bin/env python3
"""
generate_fixtures.py — produce the pre-action governance conformance fixture set.

Run ONCE from the invinoveritas repo (needs the live signer for the positive fixture's
real schnorr signature). The output under fixtures/ is the portable conformance contract:
a second party checks it with verifier.py using ONLY the bytes + declared trust inputs, with
no call back to this runtime.

Three joined invariant suites (per the vercel/ai#13215 conformance design):
  chain_invariant      — pre-action and terminal records join on the same envelope hash
  admission_invariant  — an independent identity signed the same envelope hash before execution
  anchoring_invariant  — the commitment was externally anchored before the terminal outcome

One positive fixture (all three join) + five one-broken-join negatives, each failing for exactly
one reason:
  key_different_but_identity_unproven · admission_not_independent · verdict_binding_failed
  late_commitment · ordering_unanchored
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures"
REPO = HERE.parent.parent  # /root/invinoveritas

sys.path.insert(0, str(REPO))

from nostr.event import Event  # noqa: E402
from nostr.key import PrivateKey  # noqa: E402

CANON = "json-sorted-keys-utf8-nows"  # RFC 8785-compatible for the string/integer field set


def canonical_bytes(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def admission_content(envelope_hash: str, signer_pubkey: str, verdict: str = "reject") -> str:
    """The signed admission payload. artifact_hash binds the verdict to the envelope; the content
    declares which pubkey issued it (the verifier resolves the event's OUTER pubkey, not this claim)."""
    payload = {
        "schema": "invinoveritas.verdict_proof.v1",
        "artifact_hash": envelope_hash,
        "artifact_type": "onchain_action",
        "verdict": verdict,
        "confidence": 0.95,
        "verifier_pubkey": signer_pubkey,
        "verified_at": 1782600000,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def sign_admission(privkey: PrivateKey, content: str, created_at: int = 1782600000) -> dict:
    """Sign a kind-30078 Nostr event with an arbitrary key. Returns the portable event dict."""
    pub = privkey.public_key.hex()
    ev = Event(content=content, public_key=pub, created_at=created_at, kind=30078,
               tags=[["t", "invinoveritas"], ["t", "proof"]])
    privkey.sign_event(ev)
    return {"id": ev.id, "pubkey": pub, "created_at": created_at, "kind": 30078,
            "tags": ev.tags, "content": content, "sig": ev.signature}


def our_signed_admission(envelope_hash: str):
    """The positive admission: a REAL verdict signed by our PUBLISHED key, via the production signer.
    artifact = the canonical envelope string, so the proof's artifact_hash == envelope_hash."""
    from services.proof_signing import build_verdict_proof, PUBLISHED_PUBKEY
    # reconstruct the exact canonical string whose sha256 is envelope_hash:
    proof = build_verdict_proof(_ENVELOPE_CANON_STR, "onchain_action",
                                {"verdict": "reject", "confidence": 0.95,
                                 "summary": "Independent pre-sign verdict: reject."}, seed=True)
    return proof["event"], PUBLISHED_PUBKEY


# ---- the proposed action under review (the same envelope across the whole fixture set) ----
ENVELOPE = {
    "action": "erc20_transfer",
    "chainId": "8453",
    "to": "0x000000000000000000000000000000000000dEaD",
    "token": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
    "amount": "115792089237316195423570985008687907853269984665640564039457584007913129639935",
    "spender": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
}
_ENVELOPE_CANON_BYTES = canonical_bytes(ENVELOPE)
_ENVELOPE_CANON_STR = _ENVELOPE_CANON_BYTES.decode("utf-8")
ENVELOPE_HASH = sha256_hex(_ENVELOPE_CANON_BYTES)

# A DIFFERENT envelope, for verdict_binding_failed (admission signs this instead).
OTHER_ENVELOPE = dict(ENVELOPE, amount="1")
OTHER_HASH = sha256_hex(canonical_bytes(OTHER_ENVELOPE))

ACTOR = PrivateKey()           # the agent proposing/executing the action
RANDOM = PrivateKey()          # an unrelated key, not in the trust policy's independent set
ACTOR_PUB = ACTOR.public_key.hex()

TERMINAL_OUTCOME_TIME = 1782600600  # 10 min after the (declared) anchor point in valid fixtures
VALID_ANCHOR_TIME = 1782600300      # precedes the terminal outcome -> ordering OK
LATE_ANCHOR_TIME = 1782600900       # AFTER the terminal outcome -> late_commitment


def canonical_envelope_layer() -> dict:
    return {
        "raw_input": ENVELOPE,
        "canonicalization": CANON,
        "canonical_bytes_utf8": _ENVELOPE_CANON_STR,
        "expected_envelope_hash": ENVELOPE_HASH,
    }


def chain_layer(envelope_hash: str, executed_hash: str | None = None,
                action_ref: str | None = None) -> dict:
    executed_hash = executed_hash if executed_hash is not None else envelope_hash
    action_ref = action_ref or f"act-{envelope_hash[:16]}"
    return {
        "pre_action": {"action_ref": action_ref, "actor_pubkey": ACTOR_PUB,
                       "envelope_hash": envelope_hash, "created_at": 1782599900},
        "terminal": {"action_ref": action_ref, "executed_envelope_hash": executed_hash,
                     "result": "executed", "terminal_outcome_time": TERMINAL_OUTCOME_TIME},
    }


def admission_layer(event: dict, bound_hash: str) -> dict:
    return {
        "verdict_event": event,
        "bound_envelope_hash": bound_hash,
        "signer_identity_evidence": {
            "pubkey": event["pubkey"],
            "publication_pointer": "https://api.babyblueviper.com/ledger (verifier_pubkey is self-described in the proof)",
        },
    }


def anchor_layer(commitment_digest: str, anchor_time: int | None,
                 ots_b64: str | None = None) -> dict | None:
    if anchor_time is None:
        return None  # ordering_unanchored: no external existence proof at all
    return {
        "commitment_digest": commitment_digest,
        "accepted_anchor_point": {"source": "opentimestamps-bitcoin", "block_time": anchor_time,
                                  "note": "DECLARED trust input. A deployment verifier resolves this from "
                                          "the anchor proof via `ots verify`; see live_confirmed_anchor.json "
                                          "for a real Bitcoin-confirmed instance."},
        "anchor_proof_ots_b64": ots_b64,
        "terminal_outcome_time": TERMINAL_OUTCOME_TIME,
    }


def trust_policy() -> dict:
    from services.proof_signing import PUBLISHED_PUBKEY
    return {
        "independent_verifier_pubkeys": [PUBLISHED_PUBKEY],
        "policy": "An admission verdict counts as independent iff its signing pubkey is in "
                  "independent_verifier_pubkeys AND is not the actor/executor pubkey in the chain.",
    }


def write(name: str, obj: dict):
    (FIX / name).write_text(json.dumps(obj, indent=2) + "\n")
    print(f"  wrote fixtures/{name}")


def live_confirmed_anchor() -> dict | None:
    """A REAL, fully-Bitcoin-confirmed anchored verdict from the live /ledger — the trust-root proof
    that accepted_anchor_point comes from real Bitcoin, not a declaration. Everything here is real."""
    vf = REPO / "data/track_record/verdict_0001_S168_whale_positioning.json"
    ots = REPO / "data/track_record/ots/eb22294404b2021588f90747b6404e878431191845c2aab26a919702394c68ac.ots"
    if not vf.exists():
        return None
    d = json.loads(vf.read_text())
    out = {
        "what": "A real verdict from api.babyblueviper.com/ledger, signed by the published key and "
                "OTS-anchored to Bitcoin (confirmed). Demonstrates the anchoring trust root end to end.",
        "event_id": d.get("event_id"),
        "pubkey_hex": d.get("pubkey_hex"),
        "signature": d.get("signature"),
        "record_sha256": d.get("record_sha256"),
        "verify": "POST the signed event to https://api.babyblueviper.com/verify-proof, or recompute "
                  "NIP-01 + BIP-340 locally with the zero-dep invinoveritas-verify package.",
    }
    if ots.exists():
        out["anchor_proof_ots_b64"] = base64.b64encode(ots.read_bytes()).decode("ascii")
        out["anchor_verify"] = ("ots verify -d %s <the .ots> — resolves the Bitcoin block whose time is "
                                "the accepted anchor point; that block precedes any outcome." % d.get("event_id"))
    return out


def main():
    FIX.mkdir(parents=True, exist_ok=True)
    print(f"envelope_hash = {ENVELOPE_HASH}")

    pos_event, our_pub = our_signed_admission(ENVELOPE_HASH)
    # sanity: the production proof must bind to our envelope hash
    assert json.loads(pos_event["content"])["artifact_hash"] == ENVELOPE_HASH, \
        "positive admission does not bind to envelope_hash"

    # Try a real fresh OTS stamp of the positive admission id (best-effort; deterministic suite does
    # not depend on it — accepted_anchor_point is the declared trust input).
    pos_ots_b64 = _try_stamp(pos_event["id"])

    common = {"canonical_envelope": canonical_envelope_layer(), "trust_policy": trust_policy()}

    # ---- POSITIVE ----
    write("positive.json", {
        "fixture": "positive", "expected_overall": "pass", "expected_failure_reason": None,
        "description": "All three suites join: chain links on the envelope hash, an independent "
                       "published key signed that same hash, and the commitment is anchored before the outcome.",
        **common,
        "chain": chain_layer(ENVELOPE_HASH),
        "admission": admission_layer(pos_event, ENVELOPE_HASH),
        "anchor": anchor_layer(pos_event["id"], VALID_ANCHOR_TIME, pos_ots_b64),
    })

    # ---- NEGATIVE: verdict_binding_failed (admission signs a DIFFERENT canonical hash) ----
    bind_event, _ = _our_admission_over(OTHER_HASH)
    write("negative_verdict_binding_failed.json", {
        "fixture": "verdict_binding_failed", "expected_overall": "fail",
        "expected_failure_reason": "verdict_binding_failed",
        "description": "Valid independent signature, but over a different canonical envelope hash than "
                       "the proposed action. The verdict approved a different call than the one in the chain.",
        **common,
        "chain": chain_layer(ENVELOPE_HASH),
        "admission": admission_layer(bind_event, OTHER_HASH),
        "anchor": anchor_layer(bind_event["id"], VALID_ANCHOR_TIME),
    })

    # ---- NEGATIVE: admission_not_independent (signer == actor controller) ----
    actor_event = sign_admission(ACTOR, admission_content(ENVELOPE_HASH, ACTOR_PUB))
    write("negative_admission_not_independent.json", {
        "fixture": "admission_not_independent", "expected_overall": "fail",
        "expected_failure_reason": "admission_not_independent",
        "description": "Signature verifies and binds the right envelope hash, but the signer is the "
                       "actor/executor itself — self-attested, not an independent judgment.",
        **common,
        "chain": chain_layer(ENVELOPE_HASH),
        "admission": admission_layer(actor_event, ENVELOPE_HASH),
        "anchor": anchor_layer(actor_event["id"], VALID_ANCHOR_TIME),
    })

    # ---- NEGATIVE: key_different_but_identity_unproven (signer != actor, but not declared-independent) ----
    rand_event = sign_admission(RANDOM, admission_content(ENVELOPE_HASH, RANDOM.public_key.hex()))
    write("negative_key_different_but_identity_unproven.json", {
        "fixture": "key_different_but_identity_unproven", "expected_overall": "fail",
        "expected_failure_reason": "key_different_but_identity_unproven",
        "description": "Signature verifies and the signer differs from the actor, but the key does not "
                       "resolve to an identity the trust policy declares independent. A second self-issued "
                       "key passes signature verification yet proves no independence.",
        **common,
        "chain": chain_layer(ENVELOPE_HASH),
        "admission": admission_layer(rand_event, ENVELOPE_HASH),
        "anchor": anchor_layer(rand_event["id"], VALID_ANCHOR_TIME),
    })

    # ---- NEGATIVE: late_commitment (anchor accepted AFTER the terminal outcome) ----
    write("negative_late_commitment.json", {
        "fixture": "late_commitment", "expected_overall": "fail",
        "expected_failure_reason": "late_commitment",
        "description": "Chain, independent admission, and anchor are all individually valid, but the "
                       "anchor's accepted point is after the terminal outcome — the commitment could have "
                       "been written after seeing the result.",
        **common,
        "chain": chain_layer(ENVELOPE_HASH),
        "admission": admission_layer(pos_event, ENVELOPE_HASH),
        "anchor": anchor_layer(pos_event["id"], LATE_ANCHOR_TIME, pos_ots_b64),
    })

    # ---- NEGATIVE: ordering_unanchored (valid internal chain, NO external existence proof) ----
    write("negative_ordering_unanchored.json", {
        "fixture": "ordering_unanchored", "expected_overall": "fail",
        "expected_failure_reason": "ordering_unanchored",
        "description": "Chain links and the independent admission verify, but there is no external anchor "
                       "at all — internal ordering only, nothing a third party can pin to an outside clock.",
        **common,
        "chain": chain_layer(ENVELOPE_HASH),
        "admission": admission_layer(pos_event, ENVELOPE_HASH),
        "anchor": None,
    })

    # ---- the real Bitcoin-confirmed reference ----
    lca = live_confirmed_anchor()
    if lca:
        write("live_confirmed_anchor.json", lca)

    write("trust_policy.json", trust_policy())
    print("done.")


def _our_admission_over(envelope_hash: str):
    from services.proof_signing import build_verdict_proof, PUBLISHED_PUBKEY
    canon = _ENVELOPE_CANON_STR if envelope_hash == ENVELOPE_HASH else \
        canonical_bytes(OTHER_ENVELOPE).decode("utf-8")
    proof = build_verdict_proof(canon, "onchain_action",
                                {"verdict": "reject", "confidence": 0.95, "summary": "x"}, seed=True)
    return proof["event"], PUBLISHED_PUBKEY


def _try_stamp(digest_hex: str) -> str | None:
    """Best-effort real OTS stamp of a digest. Returns base64 .ots or None (network/lib unavailable).
    The deterministic conformance suite does NOT depend on this; accepted_anchor_point is the declared
    trust input and live_confirmed_anchor.json carries a real Bitcoin-confirmed anchor."""
    try:
        from opentimestamps.core.timestamp import Timestamp, DetachedTimestampFile
        from opentimestamps.core.op import OpSHA256
        from opentimestamps.calendar import RemoteCalendar
        import io
        ts = Timestamp(bytes.fromhex(digest_hex))
        cal = RemoteCalendar("https://a.pool.opentimestamps.org")
        result = cal.submit(bytes.fromhex(digest_hex), timeout=15)
        for r in result:
            ts.merge(r)
        detached = DetachedTimestampFile(OpSHA256(), ts)
        buf = io.BytesIO()
        from opentimestamps.core.serialize import BytesSerializationContext
        ctx = BytesSerializationContext()
        detached.serialize(ctx)
        return base64.b64encode(ctx.getbytes()).decode("ascii")
    except Exception as e:  # noqa: BLE001
        print(f"  (OTS stamp skipped: {e})")
        return None


if __name__ == "__main__":
    main()
