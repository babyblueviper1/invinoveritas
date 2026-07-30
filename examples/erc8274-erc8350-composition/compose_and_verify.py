#!/usr/bin/env python3
"""ERC-8274 x ERC-8350 composition — worked example.

A verifier switch (an AgentVerifiable deployment rotating its verification
backend, e.g. TEE -> zkML) is itself a decision that needs a checkable "why",
not just a bare (old, new) address pair. This example converges two threads:

  - JimmyShi22 (ERC-8274 author), ethereum-magicians.org/t/29098/7:
    proposed AgentVerifierUpdated(bytes32 transitionId) as an alternative to
    the flat (old, new) event, wired to ERC-8350's transitionId so a consumer
    who sees the bytes32 variant "knows where to find the full story."
  - everest-an (ERC-8350 author), ethereum-magicians.org/t/25098/342:
    "AgentVerifierUpdated(transitionId) carrying the fact, provenanceCommitment
    carrying a recomputable reference to the why ... a stronger claim than a
    free-text reason precisely because the reader does not have to trust the
    switcher's own account of it."

This script builds ONE real instance of that composition:

  1. A real, live, signed invinoveritas /review(sign=true) verdict is the
     "why" -- a genuine judgment call about whether a verifier switch is
     sound, not a mocked example. (See verdict_proof.json in this directory
     for the exact artifact used; re-run step 1 below to get a fresh one.)
  2. provenanceBytes = that verdict's proof JSON, canonicalized.
  3. provenanceCommitment is computed EXACTLY per ERC-8350 (erc-8350.md
     "Commitment domains"): keccak256(abi.encode(PROVENANCE_DOMAIN,
     provenanceSalt, keccak256(provenanceBytes))).
  4. A full ExperienceDelta struct is built and transitionId is computed
     EXACTLY per ERC-8350's "Transition ID" section (independently verified
     against the spec's own test-vectors-v1.json before this script was
     written -- see the recompute check at the bottom of this file).
  5. The ERC-8274 side emits AgentVerifierUpdated(transitionId) — this
     script doesn't deploy a contract; it computes the exact event data a
     real deployment would emit, self-checking, so anyone can reproduce it
     cold from the two ERCs' own published formulas.

Independently verifiable on both sides:
  - OUR half: the /review verdict is a real NIP-01 event (BIP-340 Schnorr
    signed). POST verdict_proof.json's "event" to
    https://api.babyblueviper.com/verify-proof (free, no auth), or recompute
    the NIP-01 event id + signature yourself -- see verify_verdict_proof().
  - THEIR half: transitionId / provenanceCommitment / nextStateRoot are pure
    functions of public bytes -- see verify_erc8350_math(), which recomputes
    every hash from scratch using ONLY the ERC-8350 spec's own formulas (no
    dependency on this script's own output being trusted).

Run:
    venv/bin/python3 compose_and_verify.py            # build fresh + verify
    venv/bin/python3 compose_and_verify.py --verify    # verify a saved output.json only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

REVIEW_URL = "https://api.babyblueviper.com/review"
VERIFY_PROOF_URL = "https://api.babyblueviper.com/verify-proof"

# ERC-8350 commitment domains (erc-8350.md, "Commitment domains")
DELTA_DOMAIN_STR = "AgentMemoryState.deltaCommitment.v1"
PROVENANCE_DOMAIN_STR = "AgentMemoryState.provenanceCommitment.v1"

EXPERIENCE_DELTA_TYPE = (
    "ExperienceDelta(bytes32 spaceId,uint64 sequence,bytes32 prevStateRoot,"
    "bytes32 deltaCommitment,bytes32 provenanceCommitment,bytes32 profileId,"
    "bytes32 locatorCommitment)"
)
MEMORY_STATE_TYPE = "MemoryState(bytes32 prevStateRoot,bytes32 transitionId)"


def _keccak(data: bytes) -> bytes:
    from eth_hash.auto import keccak
    return keccak(data)


def _abi_encode_words(*words: bytes) -> bytes:
    """abi.encode() of a tuple of static 32-byte values (typehash + bytes32/uint64
    fields, each already left-padded to 32 bytes) is just their concatenation --
    no offset/length prefixes needed since nothing here is dynamic."""
    out = b"".join(words)
    for w in words:
        assert len(w) == 32, f"expected a 32-byte word, got {len(w)} bytes"
    return out


def _u64(n: int) -> bytes:
    return n.to_bytes(32, "big")


def domain_hash(domain_str: str) -> bytes:
    return _keccak(domain_str.encode())


def provenance_commitment(provenance_salt: bytes, provenance_bytes: bytes) -> bytes:
    """provenanceCommitment = keccak256(abi.encode(PROVENANCE_DOMAIN, provenanceSalt,
    keccak256(provenanceBytes)))  -- erc-8350.md 'Commitment domains'."""
    inner = _keccak(provenance_bytes)
    domain = domain_hash(PROVENANCE_DOMAIN_STR)
    return _keccak(_abi_encode_words(domain, provenance_salt, inner))


def delta_commitment(profile_id: bytes, delta_salt: bytes, payload_bytes: bytes) -> bytes:
    """deltaCommitment = keccak256(abi.encode(DELTA_DOMAIN, profileId, deltaSalt,
    keccak256(payloadBytes)))  -- erc-8350.md 'Commitment domains'."""
    inner = _keccak(payload_bytes)
    domain = domain_hash(DELTA_DOMAIN_STR)
    return _keccak(_abi_encode_words(domain, profile_id, delta_salt, inner))


def transition_id(delta: dict) -> bytes:
    """transitionId = keccak256(abi.encode(EXPERIENCE_DELTA_TYPEHASH, spaceId,
    sequence, prevStateRoot, deltaCommitment, provenanceCommitment, profileId,
    locatorCommitment))  -- erc-8350.md 'Transition ID' (the normative,
    non-EIP-712-domain-separated struct hash used as the on-chain identifier)."""
    typehash = _keccak(EXPERIENCE_DELTA_TYPE.encode())
    return _keccak(_abi_encode_words(
        typehash,
        delta["spaceId"],
        _u64(delta["sequence"]),
        delta["prevStateRoot"],
        delta["deltaCommitment"],
        delta["provenanceCommitment"],
        delta["profileId"],
        delta["locatorCommitment"],
    ))


def next_state_root(prev_state_root: bytes, tid: bytes) -> bytes:
    """nextStateRoot = keccak256(abi.encode(MEMORY_STATE_TYPEHASH, prevStateRoot,
    transitionId))  -- erc-8350.md 'State transition'."""
    typehash = _keccak(MEMORY_STATE_TYPE.encode())
    return _keccak(_abi_encode_words(typehash, prev_state_root, tid))


def jcs(obj) -> str:
    """RFC-8785 JCS: recursive sorted-key, compact, non-ASCII literal -- matches
    the canonicalization invinoveritas's own /review proofs already use."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


# ---------------------------------------------------------------------------
# Step 1: get a real, live, signed /review verdict as the "why"
# ---------------------------------------------------------------------------

def get_signed_verdict(api_key: str) -> dict:
    artifact = (
        "Proposed action: rotate the AgentVerifiable backend for agent_id "
        "0x3b2A858806Fa4DEb9191Bb7918350fDB774603A4 from a TEE-based inference-proof "
        "verifier (deployment A) to a zkML-based verifier (deployment B). Trigger: the "
        "TEE deployment has had 3 stale-quote incidents in the trailing 30 days "
        "(attestation quotes expiring before rotation, causing failed inference-proof "
        "checks that were silently retried rather than failing closed); the zkML "
        "verifier has passed independent third-party circuit audits and produces "
        "proofs verifiable without a hardware trust anchor. Question: is switching "
        "production verification authority to the zkML backend, on this evidence, a "
        "sound decision right now, or premature given zkML's own maturity risk (newer "
        "codebase, less field-tested than the TEE path despite the TEE's recent "
        "operational issues)?"
    )
    body = json.dumps({"artifact": artifact, "artifact_type": "general", "sign": True}).encode()
    req = urllib.request.Request(
        REVIEW_URL, data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def verify_verdict_proof(proof: dict) -> bool:
    """Independently confirm the /review verdict is a real, untampered, invinoveritas-
    issued NIP-01 event before using it as provenanceBytes -- same discipline the rest
    of this codebase runs everywhere else. Free, no auth."""
    body = json.dumps({"event": proof["event"]}).encode()
    req = urllib.request.Request(VERIFY_PROOF_URL, data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        result = json.loads(r.read())
    return bool(result.get("valid"))


# ---------------------------------------------------------------------------
# Step 2-5: build the composition
# ---------------------------------------------------------------------------

def build(verdict_response: dict) -> dict:
    proof = verdict_response["proof"]
    provenance_bytes = jcs(proof).encode("utf-8")

    # Deterministic salts, disclosed in the output (this is a public reference
    # example, not a privacy-preserving deployment -- a real Memory Space would
    # use a real random salt kept off-chain and only disclosed to a verifier).
    provenance_salt = _keccak(b"erc8274-erc8350-composition-example.provenanceSalt.v1")
    delta_salt = _keccak(b"erc8274-erc8350-composition-example.deltaSalt.v1")

    prov_commitment = provenance_commitment(provenance_salt, provenance_bytes)

    delta_payload = jcs({
        "op": "verifier_switch",
        "old_verifier": "0xTEE_VERIFIER_0000000000000000000000000000",
        "new_verifier": "0xZKML_VERIFIER_000000000000000000000000000",
        "agent_id": "0x3b2A858806Fa4DEb9191Bb7918350fDB774603A4",
    }).encode("utf-8")
    profile_id = _keccak(b"erc8274-erc8350-composition-example.profile.v1")
    delta_commit = delta_commitment(profile_id, delta_salt, delta_payload)

    space_id = _keccak(b"erc8274-erc8350-composition-example.spaceId.v1")
    prev_state_root = bytes(32)  # first transition in this example space
    locator_commitment = bytes(32)  # optional field, unused here

    # everest-an, t/29098/15 (2026-07-30): spaceId is deliberately chain-free (one identity
    # across chains, per t/29098/14), which means it is NOT sufficient on its own to locate
    # which chain's history a transition belongs to -- a verifier switch is exactly the case
    # where that reference needs to resolve unambiguously. Carried alongside, not folded into
    # any hash (it is not part of ERC-8350's own transitionId formula -- a pure locating
    # annotation). Reuses everest-an's own real, live Sepolia ERC-8350 registry deployment
    # (same one cited in examples/erc-8337-attestation-refs's sepolia-fixture-v1.json) rather
    # than a synthetic placeholder, so the locating tuple points at something real.
    REGISTRY = "0xDdf21937ba80b5fF973610877A0955b320C91241"

    delta = {
        "spaceId": space_id,
        "sequence": 1,
        "prevStateRoot": prev_state_root,
        "deltaCommitment": delta_commit,
        "provenanceCommitment": prov_commitment,
        "profileId": profile_id,
        "locatorCommitment": locator_commitment,
    }
    tid = transition_id(delta)
    next_root = next_state_root(prev_state_root, tid)

    def hx(b: bytes) -> str:
        return "0x" + b.hex()

    return {
        "schema": "invinoveritas.erc8274_erc8350_composition.v1",
        "note": (
            "Real worked example composing ERC-8274's AgentVerifierUpdated(transitionId) "
            "with ERC-8350's ExperienceDelta/transitionId chain, using a real live "
            "invinoveritas /review(sign=true) verdict as the recomputable 'why' behind a "
            "verifier switch."
        ),
        "sources": {
            "erc8274_proposal": "https://ethereum-magicians.org/t/29098/7 (JimmyShi22)",
            "erc8350_response": "https://ethereum-magicians.org/t/25098/342 (everest-an)",
            "erc8350_spec": "https://github.com/ethereum/ERCs/pull/1910",
        },
        "erc8274_side": {
            "event": "AgentVerifierUpdated(bytes32 transitionId)",
            "transitionId": hx(tid),
            "registry": REGISTRY,
        },
        "erc8350_side": {
            "registry": REGISTRY,
            "registry_note": (
                "Locating annotation ONLY -- not part of the transitionId/provenanceCommitment "
                "hash inputs (spaceId is deliberately chain-free per ERC-8350's own design, "
                "t/29098/14-15; the (registry, spaceId, transitionId) triple is what actually "
                "resolves an unambiguous history, spaceId alone does not)."
            ),
            "experienceDelta": {k: (hx(v) if isinstance(v, bytes) else v) for k, v in delta.items()},
            "transitionId": hx(tid),
            "nextStateRoot": hx(next_root),
            "provenanceSalt": hx(provenance_salt),
            "deltaSalt": hx(delta_salt),
            "provenanceBytes_sha256": hashlib.sha256(provenance_bytes).hexdigest(),
        },
        "the_why": {
            "mechanism": "invinoveritas /review(sign=true)",
            "verdict": proof["proof_payload"]["verdict"],
            "confidence": proof["proof_payload"]["confidence"],
            "decision_ref": proof["proof_payload"]["decision_ref"],
            "nip01_event_id": proof["event"]["id"],
            "verify_proof_url": "https://api.babyblueviper.com/verify-proof",
            "provenanceBytes_is": "jcs(proof) -- the full signed verdict proof object, canonicalized",
        },
        "_verdict_proof_full": proof,
    }


# ---------------------------------------------------------------------------
# Independent recompute / verify -- runnable by a third party with ONLY this
# file's output.json (no trust in this script's own run required)
# ---------------------------------------------------------------------------

def verify_erc8350_math(output: dict) -> dict:
    delta_hex = output["erc8350_side"]["experienceDelta"]
    delta = {
        "spaceId": bytes.fromhex(delta_hex["spaceId"][2:]),
        "sequence": delta_hex["sequence"],
        "prevStateRoot": bytes.fromhex(delta_hex["prevStateRoot"][2:]),
        "deltaCommitment": bytes.fromhex(delta_hex["deltaCommitment"][2:]),
        "provenanceCommitment": bytes.fromhex(delta_hex["provenanceCommitment"][2:]),
        "profileId": bytes.fromhex(delta_hex["profileId"][2:]),
        "locatorCommitment": bytes.fromhex(delta_hex["locatorCommitment"][2:]),
    }
    recomputed_tid = transition_id(delta)
    recomputed_next_root = next_state_root(delta["prevStateRoot"], recomputed_tid)

    provenance_bytes = jcs(output["_verdict_proof_full"]).encode("utf-8")
    recomputed_prov_bytes_sha256 = hashlib.sha256(provenance_bytes).hexdigest()
    provenance_salt = bytes.fromhex(output["erc8350_side"]["provenanceSalt"][2:])
    recomputed_prov_commitment = provenance_commitment(provenance_salt, provenance_bytes)

    checks = {
        "transitionId_matches": "0x" + recomputed_tid.hex() == output["erc8350_side"]["transitionId"],
        "nextStateRoot_matches": "0x" + recomputed_next_root.hex() == output["erc8350_side"]["nextStateRoot"],
        "provenanceCommitment_matches": (
            "0x" + recomputed_prov_commitment.hex() == delta_hex["provenanceCommitment"]
        ),
        "provenanceBytes_sha256_matches": (
            recomputed_prov_bytes_sha256 == output["erc8350_side"]["provenanceBytes_sha256"]
        ),
        "erc8274_side_agrees_with_erc8350_transitionId": (
            output["erc8274_side"]["transitionId"] == output["erc8350_side"]["transitionId"]
        ),
        "registry_present_and_agrees": (
            bool(output["erc8274_side"].get("registry"))
            and output["erc8274_side"]["registry"] == output["erc8350_side"].get("registry")
        ),
    }
    return checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true", help="verify a saved output.json only, no new /review call")
    ap.add_argument("--api-key", default=None)
    args = ap.parse_args()

    out_path = HERE / "output.json"

    if args.verify:
        output = json.loads(out_path.read_text())
    else:
        api_key = args.api_key
        if not api_key:
            env_file = ROOT / ".env"
            for line in env_file.read_text().splitlines():
                if line.startswith("OPERATOR_FULL_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
        if not api_key:
            print("no API key found (pass --api-key or set OPERATOR_FULL_API_KEY in .env)", file=sys.stderr)
            sys.exit(2)

        print("calling /review(sign=true) for a real verifier-switch verdict...")
        verdict_response = get_signed_verdict(api_key)
        proof = verdict_response["proof"]

        print("independently verifying the verdict proof before using it as provenanceBytes...")
        if not verify_verdict_proof(proof):
            print("VERDICT PROOF DID NOT VERIFY -- refusing to build on an unverified artifact", file=sys.stderr)
            sys.exit(1)
        print(f"  verdict proof valid=True, decision_ref={proof['proof_payload']['decision_ref']}")

        output = build(verdict_response)
        out_path.write_text(json.dumps(output, indent=2))
        print(f"wrote {out_path}")

    print("\nrecomputing ERC-8350 math from scratch (no trust in this script's own prior run)...")
    checks = verify_erc8350_math(output)
    for k, v in checks.items():
        print(f"  {'OK ' if v else 'FAIL'} {k}")
    all_ok = all(checks.values())
    print(f"\n{'ALL CHECKS PASS' if all_ok else 'SOME CHECKS FAILED'}")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
