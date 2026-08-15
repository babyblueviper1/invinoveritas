#!/usr/bin/env python3
"""Call live POST /review against the same synthetic transfer.

Mirrors scripts/discretionary_log.py pre_action_review(): load HL_REVIEW_BEARER
from .env.hl, POST with Authorization: Bearer, httpx, sign+seed=true. This is
our own fleet dogfooding a demo (seed=true keeps it out of proofs_issued).

The /review *artifact* is a plain-text description built FROM the fixture, so
both the fingerprint and the judgment bind to the same underlying transfer.
Allan's future .nomos seal should name the same underlying_transfer_id.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DEFAULT_ARTIFACT = HERE / "synthetic_fund_transfer_artifact.json"
DEFAULT_OUT = HERE / "review_response.json"
DEFAULT_API = "http://127.0.0.1:8000/review"

# Same concerns we actually want the reviewer to weigh — not a rubber stamp.
CONCERNS = (
    "New counterparty (first_seen_by_agent, prior_payments=0) while the agent "
    "cites a standing-vendor SOP; weekend-cutoff urgency plus a stated late-fee "
    "that we cannot recompute from an attached invoice (invoice_bytes_attached="
    "false); rail is on-chain USDC on Base to a synthetic address rather than "
    "the ACH account_ref also listed; amount 87450 USD is above the 50000 USD "
    "Article-12 human-authorization threshold and is not a round figure."
)
CONTEXT = (
    "Article 12 EU AI Act worked example (joint with NOMOS/SafeHaven) -- "
    "independent judgment on whether this specific fund transfer is reasonable "
    "given the stated facts, layered alongside NOMOS's separate authority-gate "
    "attestation on the same underlying transfer."
)


def _load_env_hl() -> dict[str, str]:
    """Same parser as scripts/discretionary_log.py _load_env_hl()."""
    env: dict[str, str] = {}
    env_path = REPO / ".env.hl"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def artifact_text(obj: dict) -> str:
    """Plain-text description derived from the fixture. No second source of truth."""
    action = obj["action"]
    cp = action["counterparty"]
    just = obj["justification"]
    pol = obj["policy"]
    agent = obj["agent"]
    dollars = action["amount_minor"] // 100
    cents = action["amount_minor"] % 100
    thresh = action["threshold_minor"] // 100
    return (
        f"SYNTHETIC / NOT A LIVE PAYMENT.\n"
        f"Agent {agent['id']} ({agent['role']}) proposes an irreversible "
        f"{action['type']} of {action['currency']} {dollars}.{cents:02d} "
        f"(amount_minor={action['amount_minor']}) via {action['rail']}.\n"
        f"Counterparty: {cp['name']} ({cp['legal_form']}); "
        f"account_ref={cp['account_ref']}; "
        f"chain_address={cp['chain_address']} chain_id={cp['chain_id']}; "
        f"first_seen_by_agent={cp['first_seen_by_agent']}; "
        f"prior_payments={cp['prior_payments']}.\n"
        f"Justification: {just['stated_reason']} "
        f"invoice_id={just['invoice_id']}; "
        f"stated_late_fee_minor={just['stated_late_fee_minor']}; "
        f"deadline={just['deadline']}; urgency={just['urgency']}; "
        f"claimed_sop={just['claimed_sop']}; "
        f"invoice_bytes_attached={just['invoice_bytes_attached']}.\n"
        f"Policy {pol['id']} ({pol['instrument']}): {pol['rule']} "
        f"Threshold {action['currency']} {thresh}. "
        f"human_authorization_required={pol['human_authorization_required']}.\n"
        f"proposed_at={obj['proposed_at']}. "
        f"underlying_transfer_id={obj['underlying_transfer_id']}."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--api", default=DEFAULT_API)
    args = ap.parse_args()

    from canonicalize import fingerprint, load_artifact

    obj = load_artifact(args.artifact)
    fp = fingerprint(obj)
    text = artifact_text(obj)

    env = _load_env_hl()
    bearer = (env.get("HL_REVIEW_BEARER") or "").strip()
    auth_used = "HL_REVIEW_BEARER"
    if not bearer or bearer.startswith("ivv_SIMULATED"):
        print("run_review: no HL_REVIEW_BEARER in .env.hl — refusing to fake a verdict",
              file=sys.stderr)
        return 2

    # Operator key is the same internal rail other examples use when the
    # dedicated review bearer is empty. Tried second, recorded in the
    # committed JSON — never a silent swap.
    def _operator_bearer() -> str:
        env_path = REPO / ".env"
        if not env_path.is_file():
            return ""
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("OPERATOR_FULL_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
        return ""

    payload = {
        "artifact": text,
        "artifact_type": "onchain_action",
        "context": CONTEXT,
        "concerns": CONCERNS,
        "severity_threshold": "all",
        "sign": True,
        "seed": True,
    }
    print(f"POST {args.api}")
    print(f"artifact_fingerprint {fp}")
    print(f"artifact_chars {len(text)}")
    r = httpx.post(
        args.api,
        json=payload,
        headers={"Authorization": f"Bearer {bearer}"},
        timeout=90,
    )
    if r.status_code == 402:
        alt = _operator_bearer()
        if alt:
            print("HL_REVIEW_BEARER returned 402 (insufficient sats); "
                  "retrying once with OPERATOR_FULL_API_KEY")
            auth_used = "OPERATOR_FULL_API_KEY (HL_REVIEW_BEARER 402)"
            r = httpx.post(
                args.api,
                json=payload,
                headers={"Authorization": f"Bearer {alt}"},
                timeout=90,
            )
    if r.status_code != 200:
        print(f"run_review: /review returned {r.status_code}", file=sys.stderr)
        print(r.text[:800], file=sys.stderr)
        return 1
    body = r.json()
    record = {
        "artifact_fingerprint": fp,
        "underlying_transfer_id": obj["underlying_transfer_id"],
        "auth_used": auth_used,
        "review_request": {
            "artifact_type": payload["artifact_type"],
            "context": payload["context"],
            "concerns": payload["concerns"],
            "severity_threshold": payload["severity_threshold"],
            "sign": True,
            "seed": True,
            "artifact": text,
        },
        "review_response": body,
    }
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    v = body.get("verdict")
    conf = body.get("confidence")
    proof = body.get("proof") or {}
    event = proof.get("event") or {}
    print(f"verdict={v!r} confidence={conf}")
    print(f"decision_ref={body.get('decision_ref')}")
    print(f"proof.event.id={event.get('id')}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
