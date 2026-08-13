#!/usr/bin/env python3
"""AISP deployment-approval evidence profile — a real, cross-recomputable worked example.

Answers google/agents-cli#48's request for "the real cross-recomputable example" of a
skill-specific structured approval-response profile riding inside sys.io.confirm, per the exact
shape optimization2026 specified: load-bearing fields enter a JCS digest, presentational fields
don't, the human-approval response binds to that digest + a BIP-340 schnorr signature, and
verification is deterministic -- no secret key material ever leaves the signer.

Two things this demonstrates, both load-bearing to the point of the exercise:
  1. compute_plan_digest() is exactly the "resolve the effective deployment plan, then digest
     the load-bearing fields" step -- the digest changes if and only if something that actually
     changes the deployed action changes (deployment target, region, service, revision, etc.),
     never if a presentational/comment field changes.
  2. verify_approval() is a REAL check, not a stamp -- see the tamper test at the bottom, which
     changes one load-bearing field (region) after signing and confirms verification correctly
     fails. A verifier with no failing case is decoration, not a check.

Requires: pip install coincurve  (BIP-340 schnorr, same primitive Nostr/Bitcoin Taproot use --
no custom crypto).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from typing import Any

from coincurve import PrivateKey


# ---------------------------------------------------------------------------
# 1. The resolved deployment plan. Fields are split into LOAD-BEARING (changing
#    the action or its risk -> must enter the digest) and PRESENTATIONAL (free
#    text, doesn't change what gets deployed -> must NOT enter the digest, so a
#    typo fix in a comment can't silently invalidate a real human approval).
#    This is optimization2026's own field list from the issue thread.
# ---------------------------------------------------------------------------
LOAD_BEARING_FIELDS = (
    "deployment_target", "environment", "gcp_project", "region", "service_name",
    "source_revision", "python_version", "service_account", "network_exposure",
    "secret_policy_digest", "resource_sizing", "eval_evidence", "rollback_plan",
    "observability_requirements",
)


def compute_plan_digest(resolved_plan: dict[str, Any]) -> str:
    """sha256(JCS(load-bearing subset)). JCS = RFC 8785-style canonicalization: sorted keys,
    no insignificant whitespace, deterministic across implementations -- any two independent
    parties resolving the SAME plan get the SAME digest, byte for byte, with no shared code."""
    preimage = {k: resolved_plan.get(k) for k in LOAD_BEARING_FIELDS}
    canon = json.dumps(preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 2. The human-approval response envelope. Matches optimization2026's exact shape:
#    decision / approver / approved_scope (bound to plan_sha256) / key_id / signature_ref /
#    expires_at / comment. `comment` and any other free text are deliberately OUTSIDE the
#    signed digest -- see LOAD_BEARING_FIELDS above, plan_sha256 is derived from the plan, not
#    from this envelope, so nothing in the envelope itself needs re-hashing, only re-checking.
# ---------------------------------------------------------------------------
def build_approval_response(resolved_plan: dict[str, Any], approver: str,
                             signing_key: PrivateKey, ttl_seconds: int = 3600) -> dict[str, Any]:
    plan_sha256 = compute_plan_digest(resolved_plan)
    envelope = {
        "decision": "approve",
        "approver": approver,
        "approved_scope": {k: resolved_plan.get(k) for k in LOAD_BEARING_FIELDS},
        "plan_sha256": plan_sha256,
        "key_id": signing_key.public_key.format(compressed=True)[1:].hex(),  # x-only, BIP-340 style
        "expires_at": int(time.time()) + ttl_seconds,
        "comment": "Approved for production deployment",  # presentational, not signed over
    }
    # Sign the digest of the SIGNED fields only (decision + approver + approved_scope +
    # plan_sha256 + key_id + expires_at) -- `comment` is explicitly excluded, matching
    # optimization2026's presentational/load-bearing split applied to the envelope itself.
    signed_fields = {k: envelope[k] for k in
                      ("decision", "approver", "approved_scope", "plan_sha256", "key_id", "expires_at")}
    signed_canon = json.dumps(signed_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    sig = signing_key.sign_schnorr(hashlib.sha256(signed_canon.encode("utf-8")).digest())
    envelope["signature"] = sig.hex()
    return envelope


def verify_approval(resolved_plan: dict[str, Any], approval: dict[str, Any]) -> dict[str, Any]:
    """Deterministic verification -- the `sys.assert` step in optimization2026's flow. Returns a
    structured result (never a bare bool) so a caller can see WHY a rejection happened, same
    discipline as any real verifier: fail closed, name the specific failure."""
    checks: dict[str, bool] = {}

    # (a) The plan actually approved must be the plan being deployed NOW -- recompute the
    # digest from the current resolved plan and compare, don't trust the envelope's own claim.
    recomputed = compute_plan_digest(resolved_plan)
    checks["plan_digest_matches"] = (recomputed == approval.get("plan_sha256"))

    # (b) Not expired.
    checks["not_expired"] = int(time.time()) < approval.get("expires_at", 0)

    # (c) Signature verifies over the signed-fields subset, against the claimed key_id.
    try:
        signed_fields = {k: approval[k] for k in
                          ("decision", "approver", "approved_scope", "plan_sha256", "key_id", "expires_at")}
        signed_canon = json.dumps(signed_fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        msg_hash = hashlib.sha256(signed_canon.encode("utf-8")).digest()
        from coincurve import PublicKeyXOnly
        pub = PublicKeyXOnly(bytes.fromhex(approval["key_id"]))
        checks["signature_valid"] = pub.verify(bytes.fromhex(approval["signature"]), msg_hash)
    except Exception:
        checks["signature_valid"] = False

    checks["decision_is_approve"] = approval.get("decision") == "approve"

    return {"valid": all(checks.values()), "checks": checks}


if __name__ == "__main__":
    signing_key = PrivateKey(secrets.token_bytes(32))

    resolved_plan = {
        "deployment_target": "agent_runtime",
        "environment": "production",
        "gcp_project": "company-prod",
        "region": "us-central1",
        "service_name": "support-agent",
        "source_revision": "abc123",
        "python_version": "3.13",
        "service_account": "support-agent-sa@company-prod.iam.gserviceaccount.com",
        "network_exposure": "internal-only",
        "secret_policy_digest": "sha256:deadbeef...",
        "resource_sizing": {"cpu": "2", "memory": "4Gi"},
        "eval_evidence": "sha256:eval-report-hash...",
        "rollback_plan": "revert to abc122 via `agents-cli rollback --to abc122`",
        "observability_requirements": "logs+traces to company-prod/support-agent",
    }

    approval = build_approval_response(resolved_plan, approver="alice@example.com", signing_key=signing_key)
    print("=== approval envelope ===")
    print(json.dumps(approval, indent=2))

    print("\n=== verify against the SAME resolved plan (should be valid) ===")
    result = verify_approval(resolved_plan, approval)
    print(json.dumps(result, indent=2))
    assert result["valid"], "expected a valid approval to verify"

    print("\n=== TAMPER TEST: change one load-bearing field AFTER approval (region) ===")
    tampered_plan = dict(resolved_plan)
    tampered_plan["region"] = "eu-west-1"  # deployer/attacker changes target region post-approval
    result = verify_approval(tampered_plan, approval)
    print(json.dumps(result, indent=2))
    assert not result["valid"], "a tampered load-bearing field MUST fail verification"
    assert not result["checks"]["plan_digest_matches"], "digest mismatch is the specific reason"
    print("\nCorrectly rejected: plan_digest_matches=False. The approval for us-central1 does not "
          "authorize eu-west-1, and the runtime can say exactly why instead of guessing.")

    print("\n=== presentational-field-only change (comment) does NOT need re-approval ===")
    # comment is outside the signed fields entirely -- editing it doesn't touch signature or digest
    approval2 = dict(approval)
    approval2["comment"] = "typo fix, still approved for production"
    result = verify_approval(resolved_plan, approval2)
    assert result["valid"], "a presentational-only field change must not invalidate a real approval"
    print("Correctly still valid: comment is presentational, never entered the signed digest.")
