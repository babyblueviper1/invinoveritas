#!/usr/bin/env python3
"""Bind a verified zkTLS attestation into a live /review call via inputHash.

zkTLS authenticates the SOURCE (this HTTPS response came from Coinbase).
/review judges the REASONING over that authenticated fact. They compose;
they are not the same primitive.

Auth mirrors examples/nomos-article12-worked-example/run_review.py:
HL_REVIEW_BEARER from .env.hl first, OPERATOR_FULL_API_KEY on 402.
sign+seed=true. Independently POST /verify-proof (no auth).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

from canonicalize import fingerprint

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
OUT = HERE / "outputs"
DEFAULT_ATTESTATION = OUT / "attestation.json"
REVIEW_API = "http://127.0.0.1:8000/review"
VERIFY_API = "http://127.0.0.1:8000/verify-proof"

CONTEXT = (
    "WYRIWE Step 3 input-source-authentication demo (standalone script, "
    "NOT formal WYRIWE spec text). A Primus zkTLS attestation authenticated "
    "a Coinbase public BTC-USD spot GET. inputHash below is sha256 of the "
    "canonical attested payload. This /review judges whether it is reasonable "
    "to treat that source-authenticated print as a cited market fact for a "
    "later Hyperliquid BTC risk review — it does not re-authenticate the HTTPS "
    "source (zkTLS already did that) and it does not authorize a live order."
)
CONCERNS = (
    "The attested value is a single last print, not a book; Coinbase is not "
    "the execution venue (this fleet trades Hyperliquid); zkTLS here is "
    "occurrence evidence of one response, not a completeness claim that the "
    "price could not have moved; parsePath $.data.amount is a string but any "
    "downstream use as a float must not silently change the bound inputHash."
)


def _load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def attested_payload(attestation_obj: dict) -> dict:
    """Pull the revealed zkTLS data into a dict we can canonicalize."""
    att = attestation_obj.get("attestation") or attestation_obj
    raw = att.get("data")
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
    elif isinstance(raw, dict):
        parsed = raw
    else:
        parsed = {"raw": raw}
    return {
        "source": "https://api.coinbase.com/v2/prices/BTC-USD/spot",
        "method": "GET",
        "parse": {
            "amount": "$.data.amount",
            "base": "$.data.base",
            "currency": "$.data.currency",
        },
        "attested": parsed,
        "attestation_timestamp": att.get("timestamp"),
        "recipient": att.get("recipient"),
    }


def artifact_text(payload: dict, input_hash: str) -> str:
    att = payload["attested"]
    return (
        "SYNTHETIC / ADVISORY — no live order.\n"
        f"Source-authenticated inputHash={input_hash}\n"
        "HTTPS source: GET https://api.coinbase.com/v2/prices/BTC-USD/spot "
        "attested via Primus zkTLS (proxytls).\n"
        f"Revealed fields: base={att.get('base')!r} currency={att.get('currency')!r} "
        f"amount={att.get('amount')!r}.\n"
        f"attestation_timestamp={payload.get('attestation_timestamp')}.\n"
        "Question: is it reasonable to treat this independently source-authenticated "
        "Coinbase BTC-USD last print as a cited market fact for a subsequent "
        "Hyperliquid BTC risk/size review, given it is one snapshot from a "
        "non-execution venue?"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--attestation", type=Path, default=DEFAULT_ATTESTATION)
    args = ap.parse_args()

    blob = json.loads(args.attestation.read_text(encoding="utf-8"))
    if blob.get("ok") is False or blob.get("verifyResult") not in (True, None):
        if blob.get("verifyResult") is not True:
            print("bind_to_verdict: attestation verifyResult is not true; refusing to review a failed proof",
                  file=sys.stderr)
            return 2
    payload = attested_payload(blob)
    input_hash = fingerprint(payload)
    (OUT / "input_hash.txt").write_text(input_hash + "\n", encoding="utf-8")
    print(f"inputHash {input_hash}")

    env_hl = _load_env(REPO / ".env.hl")
    env_root = _load_env(REPO / ".env")
    bearer = (env_hl.get("HL_REVIEW_BEARER") or "").strip()
    auth_used = "HL_REVIEW_BEARER"
    if not bearer or bearer.startswith("ivv_SIMULATED"):
        print("no HL_REVIEW_BEARER", file=sys.stderr)
        return 2

    text = artifact_text(payload, input_hash)
    req = {
        "artifact": text,
        "artifact_type": "analysis",
        "context": CONTEXT + f" inputHash={input_hash}",
        "concerns": CONCERNS,
        "severity_threshold": "all",
        "sign": True,
        "seed": True,
    }
    print(f"POST {REVIEW_API}")
    r = httpx.post(REVIEW_API, json=req, headers={"Authorization": f"Bearer {bearer}"}, timeout=90)
    if r.status_code == 402:
        alt = (env_root.get("OPERATOR_FULL_API_KEY") or "").strip()
        if alt:
            print("HL_REVIEW_BEARER 402; retrying OPERATOR_FULL_API_KEY")
            auth_used = "OPERATOR_FULL_API_KEY (HL_REVIEW_BEARER 402)"
            r = httpx.post(REVIEW_API, json=req, headers={"Authorization": f"Bearer {alt}"}, timeout=90)
    if r.status_code != 200:
        print(f"/review {r.status_code}", file=sys.stderr)
        print(r.text[:800], file=sys.stderr)
        return 1
    body = r.json()
    record = {
        "input_hash": input_hash,
        "attested_payload": payload,
        "auth_used": auth_used,
        "review_request": req,
        "review_response": body,
    }
    (OUT / "review_response.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    event = ((body.get("proof") or {}).get("event")) or {}
    content = event.get("content")
    decision_ref = None
    if isinstance(content, str):
        try:
            decision_ref = json.loads(content).get("decision_ref")
        except json.JSONDecodeError:
            decision_ref = None
    print(f"verdict={body.get('verdict')!r} confidence={body.get('confidence')}")
    print(f"decision_ref={decision_ref}")
    print(f"proof.event.id={event.get('id')}")

    if not event:
        print("no proof.event — skip verify-proof", file=sys.stderr)
        return 1
    print(f"POST {VERIFY_API}")
    vr = httpx.post(VERIFY_API, json={"event": event}, timeout=30)
    try:
        vj = vr.json()
    except Exception:
        print(f"verify-proof non-JSON {vr.status_code}", file=sys.stderr)
        return 1
    (OUT / "verify_proof_response.json").write_text(
        json.dumps(vj, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"verify-proof valid={vj.get('valid')} status={vr.status_code}")
    return 0 if vj.get("valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
