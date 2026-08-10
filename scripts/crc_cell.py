#!/usr/bin/env python3
"""crc_cell.py -- reusable Cell-construction script for the Cross-Reference Console
(trustless-ai/cross-reference-console), implementing crc.cell.v2 (CELL-v2.md, merged
2026-08-07, PR #5) on our Nostr lane.

Closes a real gap named live in the trustless-ai group (2026-08-06 audit thread, msg
2343/2344): our one existing Cell (#236, data/crc_cell_236.json / crc_cell_236_v1_node1.json)
was built inline during a session, with no reusable script -- so every new Cell meant
hand-rebuilding the same construction from scratch. This generalizes that one-off into the
one place to build a Cell going forward, v2-shaped from the start (Merlini, msg 2344: "build
it straight against v2, skip v1 entirely").

v2's one real change over v1 (CELL-v1.md, still in force per CELL-v2.md section 5 -- result
semantics, edge rule, pre-hash gate, independence-evidence shape, as_of/recomputed_at
separation, boundary-in-payload are ALL UNCHANGED): registry_id becomes a signed field.
Per section 2.1, registry_id lives at the CELL layer ONLY -- it must never enter
crc.claim.v0's ClaimPreimage/claim_id derivation, so the SAME claim_id from crc_claim_id.py
stays byte-identical across cell schema versions. Per section 2.3 (our lane, Nostr, no
domain/salt concept at all): registry_id is just a top-level member of the signed content
object, covered by the NIP-01 event id + BIP-340 signature like every other field.

registry_id for THIS registry (frozen 2026-08-07, cross-checked byte-for-byte by two parties
independently before freeze -- CELL-v2.md section 1):
    sha256:9b871ba9cf05e9da7df78e0b15d44fc04059e6af4bda8037d6f456984598d157
    (= sha256 of JCS(genesis nodes.json) @ trustless-ai/cross-reference-console commit
    72b8804c4e85e6ec1530a3470a9af7a5fe47f238, the commit that ADDED the file)

Usage:
    venv/bin/python scripts/crc_cell.py --claim-preimage preimage.json --result GREEN \\
        --verifier 54848 --boundary "..." --evidence evidence.json [--dry]

Or import build_cell_v2() / sign_cell_v2() directly. --dry prints the constructed +
would-be-signed payload without touching NOSTR_NSEC or any relay.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REGISTRY_ID = "sha256:9b871ba9cf05e9da7df78e0b15d44fc04059e6af4bda8037d6f456984598d157"
SCHEMA = "crc.cell.v2"
SCHEMA_V3 = "crc.cell.v3"

# Same field order/shape as crc_cell_236_v1_node1.json's proof_payload, plus registry_id
# (section 2.2's EIP-712 struct field list, minus evidence_hash since our lane signs the
# full evidence object inline rather than a keccak256 digest of it -- carried over from v0/v1,
# unchanged per section 5. "Everything else carries over ... unchanged from CELL-v1.md.").
_TOP_FIELDS = ("schema", "claim_id", "result", "verifier", "registry_id", "boundary",
               "as_of", "recomputed_at", "evidence")


def build_cell_v2(claim_id: str, result: str, verifier: int, boundary: str, as_of: str,
                   evidence: dict, recomputed_at: str | None = None) -> dict:
    """Construct the crc.cell.v2 proof_payload dict (unsigned). `evidence` is the full
    evidence object (claim_preimage, independence, recipe, note, ...) -- same shape as v1,
    this function only adds registry_id at the Cell layer per section 2.1/2.3."""
    if result not in ("GREEN", "RED", "AMBER"):
        raise ValueError(f"result must be GREEN|RED|AMBER, got {result!r}")
    if not claim_id.startswith("sha256:") or len(claim_id) != 71:
        raise ValueError("claim_id must be 'sha256:' + 64 lowercase hex (CELL-v2.md section 3)")
    payload = {
        "schema": SCHEMA,
        "claim_id": claim_id,
        "result": result,
        "verifier": verifier,
        "registry_id": REGISTRY_ID,
        "boundary": boundary,
        "as_of": as_of,
        "recomputed_at": recomputed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "evidence": evidence,
    }
    return {k: payload[k] for k in _TOP_FIELDS}


def build_cell_v3(claim_id: str, result: str, verifier: int, boundary: str, as_of: str,
                   evidence: dict, recomputed_at: str | None = None) -> dict:
    """crc.cell.v3 (CELL-v3.md, activated 2026-08-10 per PR #10/#43-#46 -- crc.cell.v2 became
    RED after the activation commit) -- structurally identical to v2 (build_cell_v2) except
    `schema` and the required `evidence.independence.derived_from` field (LINEAGE-REF.md).
    `evidence["independence"]["derived_from"]` MUST already be set by the caller before calling
    this (build_cell_v2 predates the requirement and won't set it) -- this function only
    validates it's present with the right shape rather than injecting a value, since what
    belongs there is a real declaration about THIS implementation's real lineage, not a default
    this script should silently assume."""
    if result not in ("GREEN", "RED", "AMBER"):
        raise ValueError(f"result must be GREEN|RED|AMBER, got {result!r}")
    if not claim_id.startswith("sha256:") or len(claim_id) != 71:
        raise ValueError("claim_id must be 'sha256:' + 64 lowercase hex (CELL-v2.md section 3)")
    independence = evidence.get("independence") or {}
    derived_from = independence.get("derived_from")
    if not isinstance(derived_from, list):
        raise ValueError("evidence.independence.derived_from is required for crc.cell.v3 and "
                          "must be a list (CELL-v3.md section 1.1) -- pass [] for 'no known "
                          "derivation, written from spec', not omit the field")
    if len(set(derived_from)) != len(derived_from):
        raise ValueError("derived_from contains duplicate entries -- gate REJECT (CELL-v3.md 1.1)")
    payload = {
        "schema": SCHEMA_V3,
        "claim_id": claim_id,
        "result": result,
        "verifier": verifier,
        "registry_id": REGISTRY_ID,
        "boundary": boundary,
        "as_of": as_of,
        "recomputed_at": recomputed_at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "evidence": evidence,
    }
    return {k: payload[k] for k in _TOP_FIELDS}


def sign_cell_v2(payload: dict) -> dict:
    """Schnorr-sign the payload as a NIP-01/kind-30078 Nostr event, same key as /prove and
    every prior Cell (PUBLISHED_PUBKEY). Content is JCS-style canonical: sort_keys, compact
    separators, ensure_ascii=False -- same convention as crc_claim_id.py and every decision_ref
    in this stack."""
    from config import NOSTR_NSEC
    from nostr.event import Event
    from nostr.key import PrivateKey

    if not NOSTR_NSEC:
        raise RuntimeError("NOSTR_NSEC unset -- cannot sign")
    content = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    nsec = NOSTR_NSEC.strip()
    pk = PrivateKey.from_nsec(nsec) if nsec.startswith("nsec") else PrivateKey(bytes.fromhex(nsec))
    created_at = int(time.time())
    d_tag = f"invinoveritas-proof-proof-{created_at}-{uuid.uuid4().hex[:8]}"
    ev = Event(
        kind=30078,
        content=content,
        tags=[["d", d_tag], ["t", "invinoveritas"], ["t", "proof"], ["schema", payload["schema"]]],
        public_key=pk.public_key.hex(),
        created_at=created_at,
    )
    pk.sign_event(ev)
    return {"id": ev.id, "pubkey": ev.public_key, "created_at": ev.created_at,
            "kind": ev.kind, "tags": ev.tags, "content": ev.content, "sig": ev.signature}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--claim-preimage", required=True, help="path to a crc.claim.v0 preimage JSON")
    ap.add_argument("--result", required=True, choices=["GREEN", "RED", "AMBER"])
    ap.add_argument("--verifier", required=True, type=int)
    ap.add_argument("--boundary", required=True)
    ap.add_argument("--evidence", required=True, help="path to the full evidence-object JSON "
                     "(claim_preimage, independence, recipe, note, ... -- claim_preimage inside "
                     "it should match --claim-preimage)")
    ap.add_argument("--out", help="write the finished artifact (payload + signed event) here")
    ap.add_argument("--dry", action="store_true", help="build + print without signing/publishing")
    ap.add_argument("--v3", action="store_true", help="build crc.cell.v3 instead of v2 -- "
                     "requires evidence.independence.derived_from already set in --evidence")
    args = ap.parse_args()

    from crc_claim_id import claim_id as compute_claim_id  # sibling script, same dir on sys.path

    preimage = json.loads(Path(args.claim_preimage).read_text())
    evidence = json.loads(Path(args.evidence).read_text())
    cid = compute_claim_id(preimage)
    builder = build_cell_v3 if args.v3 else build_cell_v2
    payload = builder(claim_id=cid, result=args.result, verifier=args.verifier,
                       boundary=args.boundary, as_of=preimage["as_of"], evidence=evidence)

    if args.dry:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    event = sign_cell_v2(payload)
    artifact = {"proof_payload": payload, "signed": {"signature_type": "nostr_event", "event": event}}
    out = json.dumps(artifact, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(out)
        print(f"wrote {args.out} (event id {event['id']})")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main())
