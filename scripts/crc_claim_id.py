#!/usr/bin/env python3
"""crc_claim_id.py -- our own independent implementation of the Cross-Reference Console's
claim_id derivation (crc.claim.v0, see trustless-ai/cross-reference-console/CLAIM.md).

Written fresh from the spec, not copied from the reference repo's reference/claim_id.py --
this is what makes our Cell's evidence.independence.implementation a genuinely distinct
implementation ref rather than a re-hosted copy of theirs (crc.cell.v1's whole point: two
Cells are independent when their implementation refs differ and their inputs carry the same
content_hash). Golden-vector-checked against the reference repo's own published claim_id for
/ledger#236 (sha256:df1a6bfe3063186f8a8327b75a5bfddae12d3518f2cc16f8fddbc6c311de9512) --
matches byte-for-byte.

Usage: venv/bin/python scripts/crc_claim_id.py < preimage.json
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import datetime

FIELDS = ["schema", "profile_id", "policy_version", "artifact_hash", "artifact_type",
          "claim_body", "source_class", "verifier_profile", "as_of", "claimant"]
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_AS_OF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _reject_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError(f"duplicate JSON member: {k!r}")
        out[k] = v
    return out


def validate(preimage: dict) -> None:
    keys = set(preimage)
    required = set(FIELDS)
    if keys != required:
        raise ValueError(f"field-set mismatch: missing={sorted(required - keys)} extra={sorted(keys - required)}")
    if preimage["schema"] != "crc.claim.v0":
        raise ValueError("schema must be 'crc.claim.v0'")
    for k in ("schema", "profile_id", "policy_version", "artifact_hash", "artifact_type",
              "source_class", "verifier_profile", "as_of"):
        if not isinstance(preimage[k], str) or not preimage[k]:
            raise ValueError(f"{k} must be a non-empty string")
    if not (preimage["claim_body"] is None or isinstance(preimage["claim_body"], str)):
        raise ValueError("claim_body must be string or null")
    if not _HASH_RE.match(preimage["artifact_hash"]):
        raise ValueError("artifact_hash must be bare lowercase hex-64")
    if isinstance(preimage["claimant"], bool) or not isinstance(preimage["claimant"], int):
        raise ValueError("claimant must be an int")
    if not (0 <= preimage["claimant"] < 2**256):
        raise ValueError("claimant out of uint256 range")
    if not _AS_OF_RE.match(preimage["as_of"]):
        raise ValueError("as_of must be RFC3339 UTC second-precision")
    datetime.strptime(preimage["as_of"], "%Y-%m-%dT%H:%M:%SZ")  # rejects e.g. month 13


def claim_id(preimage: dict) -> str:
    validate(preimage)
    canon = json.dumps({k: preimage[k] for k in FIELDS}, sort_keys=True,
                        separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(canon).hexdigest()


if __name__ == "__main__":
    print(claim_id(json.loads(sys.stdin.read())))
