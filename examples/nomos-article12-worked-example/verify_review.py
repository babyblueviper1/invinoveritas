#!/usr/bin/env python3
"""Independently confirm the signed /review proof via POST /verify-proof.

Free, no auth. Proves the verdict validates against the published key —
do not trust review_response.json's self-report alone.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
DEFAULT_REVIEW = HERE / "review_response.json"
DEFAULT_OUT = HERE / "verify_proof_response.json"
DEFAULT_API = "http://127.0.0.1:8000/verify-proof"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()

    record = json.loads(args.review.read_text(encoding="utf-8"))
    body = record.get("review_response") or record
    proof = body.get("proof") or {}
    event = proof.get("event")
    if not event:
        print("verify_review: no proof.event in the review record", file=sys.stderr)
        return 2

    print(f"POST {args.api}  event.id={event.get('id')}")
    r = httpx.post(args.api, json={"event": event}, timeout=30)
    try:
        result = r.json()
    except Exception:
        print(f"verify_review: non-JSON ({r.status_code})", file=sys.stderr)
        print(r.text[:800], file=sys.stderr)
        return 1
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    if r.status_code != 200 or not result.get("valid"):
        print("verify_review: proof did NOT independently validate", file=sys.stderr)
        return 1
    print(f"independently valid against published key; wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
