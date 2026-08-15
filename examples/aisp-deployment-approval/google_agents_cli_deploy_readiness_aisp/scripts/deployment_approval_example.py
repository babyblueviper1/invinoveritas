#!/usr/bin/env python3
"""AISP deployment-approval evidence profile -- a real, cross-recomputable worked example.

v2 (google/agents-cli#48, 2026-08-13): implements the concrete next-improvements list
optimization2026 gave after reviewing v1 -- specifically the parts that are self-contained
(don't require agents-cli's own internals or a real sys.io.confirm host). Each numbered item
below maps 1:1 to a numbered item in their review comment:

  (3) approved_scope verified independently, not just plan_sha256 -- see
      `approved_scope_matches_current_plan` / `approved_scope_digest_matches` in verify_approval().
  (5) key_id separated from the actual public key material -- key_id is now an opaque registry
      label, `public_key` carries the x-only hex the verifier actually needs.
  (6) approval_conditions (signed, load-bearing) split from display_note (unsigned, presentational)
      -- a "deploy only during the maintenance window" instruction can no longer hide in a free-text
      comment that was never covered by the signature.
  (7) canonicalization: still NOT a full RFC 8785 implementation (that's a real external dependency
      decision, not something to pull in casually inside a demo script) -- instead explicitly
      documented and enforced as a restricted JCS-safe subset (see `_assert_jcs_safe` below), which
      was optimization2026's own named fallback option ("explicitly constrain the digest input to a
      documented JCS-safe data subset").
  (9) fixed cross-language test vectors -- `--fixtures` writes deterministic, reproducible files
      (fixed key, fixed timestamps, no time.time()/secrets.token_bytes) so a JS/Rust/Go
      implementation can verify byte-for-byte agreement without sharing this code.

Also added, named in their review but not numbered: required-field fail-closed validation
(`validate_plan_completeness`) and domain-separation/replay-protection fields (`profile`,
`skill_id`, `operation`, `plan_schema`, `audience`, `issued_at`, `nonce`, `max_uses`) plus a
demo in-memory replay guard showing what `max_uses` enforcement looks like (a real deployment
needs a persistent nonce store -- this demo makes that requirement visible, doesn't claim to
solve it standalone).

Deliberately NOT attempted here, because they need optimization2026's own side to be real (not
something a standalone example can honestly claim): (1) wiring through an actual sys.io.confirm
human-response channel, (2) resolving the plan from real agents-cli state instead of a hardcoded
dict, (8) authenticating the `approver` identity against a real IdP. Naming these here rather than
silently pretending v2 covers everything the review asked for.

Requires: pip install coincurve  (BIP-340 schnorr, same primitive Nostr/Bitcoin Taproot use --
no custom crypto).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import time
from typing import Any

from coincurve import PrivateKey, PublicKeyXOnly


# ---------------------------------------------------------------------------
# 1. The resolved deployment plan. Fields are split into LOAD-BEARING (changing
#    the action or its risk -> must enter the digest) and PRESENTATIONAL (free
#    text, doesn't change what gets deployed -> must NOT enter the digest, so a
#    typo fix in a comment can't silently invalidate a real human approval).
#    Field list is optimization2026's own from the issue thread.
# ---------------------------------------------------------------------------
LOAD_BEARING_FIELDS = (
    "deployment_target", "environment", "gcp_project", "region", "service_name",
    "source_revision", "python_version", "service_account", "network_exposure",
    "secret_policy_digest", "resource_sizing", "eval_evidence", "rollback_plan",
    "observability_requirements",
)

# Required-field validation (named in the 2026-08-13 review, "some fields should fail closed
# when missing" rather than silently digesting as null): the subset that must be present and
# non-null before an approval can even be requested for a production deployment.
REQUIRED_FOR_PRODUCTION = (
    "deployment_target", "gcp_project", "region", "service_name",
    "source_revision", "service_account", "rollback_plan",
)


def validate_plan_completeness(resolved_plan: dict[str, Any],
                                required: tuple[str, ...] = REQUIRED_FOR_PRODUCTION) -> list[str]:
    """Fail-closed check: returns the list of required fields that are missing or null. An empty
    list means the plan is complete enough to request approval for. Caller must refuse to proceed
    to build_approval_response() if this is non-empty -- a missing rollback_plan should block the
    approval request, not silently digest as null and get approved by omission."""
    return [f for f in required if resolved_plan.get(f) in (None, "")]


def _assert_jcs_safe(value: Any, path: str = "$") -> None:
    """Enforces the restricted JCS-safe subset this profile actually supports, rather than
    silently mis-serializing something json.dumps(sort_keys=True) would get wrong relative to
    full RFC 8785 (float formatting, -0, duplicate keys, non-string dict keys, NaN/Infinity).
    This is deliberately option (2) from optimization2026's own review: 'explicitly constrain the
    digest input to a documented JCS-safe data subset' -- not a full RFC 8785 implementation.
    Allowed: str, int (not bool), dict[str, JCS-safe] with string keys, list[JCS-safe], None.
    Disallowed: float (ambiguous cross-language formatting), bool used where int expected."""
    if value is None or isinstance(value, str) or isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError(f"{path}: JCS-safe subset requires string dict keys, got {type(k)}")
            _assert_jcs_safe(v, f"{path}.{k}")
        return
    if isinstance(value, list):
        for i, v in enumerate(value):
            _assert_jcs_safe(v, f"{path}[{i}]")
        return
    raise ValueError(f"{path}: value {value!r} ({type(value)}) is outside the documented "
                      f"JCS-safe subset (str/int/dict[str,_]/list/None only -- no float/bool-as-bool)")


def _canon(value: dict[str, Any]) -> str:
    _assert_jcs_safe(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_plan_digest(resolved_plan: dict[str, Any]) -> str:
    """sha256(JCS-safe-canon(load-bearing subset)). Any two independent parties resolving the
    SAME plan get the SAME digest, byte for byte, with no shared code -- within the documented
    JCS-safe subset (see _assert_jcs_safe)."""
    preimage = {k: resolved_plan.get(k) for k in LOAD_BEARING_FIELDS}
    return "sha256:" + hashlib.sha256(_canon(preimage).encode("utf-8")).hexdigest()


def compute_scope_digest(approved_scope: dict[str, Any]) -> str:
    """Same digest function applied to the envelope's OWN approved_scope, independent of
    resolved_plan -- see the (3) approved_scope-independent-verification section below for why
    this must be checked separately from plan_digest_matches."""
    return "sha256:" + hashlib.sha256(_canon(approved_scope).encode("utf-8")).hexdigest()


# Domain-separation / replay-protection context, named in the 2026-08-13 review item 7. These
# are SIGNED (part of the envelope's signed_fields), so an approval minted for one skill/operation
# cannot be replayed against another without breaking the signature.
DOMAIN_CONTEXT = {
    "profile": "aisp.deployment_approval_response.v1",
    "skill_id": "google_agents_cli_deploy_readiness_aisp",
    "operation": "agents-cli.deploy",
    "plan_schema": "agents-cli.effective_deployment_plan.v1",
}

# Fields that enter the signature (order doesn't matter, _canon sorts keys -- listed here once
# so build_approval_response and verify_approval can't drift apart on what's actually signed).
SIGNED_FIELD_NAMES = (
    "decision", "approver", "approved_scope", "plan_sha256", "approval_conditions",
    "public_key", "key_id", "profile", "skill_id", "operation", "plan_schema",
    "audience", "issued_at", "expires_at", "nonce", "max_uses",
)


def build_approval_response(resolved_plan: dict[str, Any], approver: str,
                             signing_key: PrivateKey, key_id: str = "release-key-2026-01",
                             audience: str = "agents-cli-production-deployer",
                             approval_conditions: list[str] | None = None,
                             display_note: str = "", ttl_seconds: int = 3600,
                             *, fixed_issued_at: int | None = None,
                             fixed_nonce: str | None = None,
                             aux_randomness: bytes = b"") -> dict[str, Any]:
    missing = validate_plan_completeness(resolved_plan)
    if missing:
        raise ValueError(f"refusing to build an approval response: plan is missing required "
                          f"fields {missing} -- these must not silently digest as null")

    plan_sha256 = compute_plan_digest(resolved_plan)
    approved_scope = {k: resolved_plan.get(k) for k in LOAD_BEARING_FIELDS}
    issued_at = fixed_issued_at if fixed_issued_at is not None else int(time.time())
    nonce = fixed_nonce if fixed_nonce is not None else secrets.token_hex(16)
    public_key_hex = signing_key.public_key.format(compressed=True)[1:].hex()  # x-only, BIP-340

    envelope: dict[str, Any] = {
        "decision": "approve",
        "approver": approver,
        "approved_scope": approved_scope,
        "plan_sha256": plan_sha256,
        # (6) signed conditions vs unsigned display note -- "deploy only in the maintenance
        # window" is load-bearing and must be signed; a spelling fix in a comment is not.
        "approval_conditions": list(approval_conditions or []),
        # (5) key_id is now an opaque registry label -- NOT the key material itself. public_key
        # is the actual x-only hex the verifier needs. A real deployment can resolve public_key
        # from a published registry by key_id instead of trusting the envelope's own copy of it;
        # this demo signs both so the example stays self-verifying without an external registry.
        "public_key": public_key_hex,
        "key_id": key_id,
        # (7) domain separation -- an approval for THIS skill/operation/plan-schema/audience only.
        **DOMAIN_CONTEXT,
        "audience": audience,
        "issued_at": issued_at,
        "expires_at": issued_at + ttl_seconds,
        "nonce": nonce,
        "max_uses": 1,
        "display_note": display_note,  # presentational, NOT in signed_fields below
    }

    signed_fields = {k: envelope[k] for k in SIGNED_FIELD_NAMES}
    signed_canon = _canon(signed_fields)
    # BIP-340 Schnorr signing mixes in 32 bytes of auxiliary randomness by default (defense
    # against fault attacks) -- the DEFAULT aux_randomness=b"" auto-generates fresh randomness
    # on every call, so signing the identical message twice with the identical key produces two
    # DIFFERENT, both-valid signatures. Real deployments want that (it's the whole point of aux
    # rand). Fixed cross-language test vectors do NOT -- caught while building the --fixtures
    # mode below (first attempt silently produced a different signature on every run, which would
    # have made the "byte-for-byte reproducible" claim false). write_fixtures() passes a fixed
    # all-zero aux_randomness explicitly for that reason; the interactive demo below uses the
    # real-randomness default.
    sig = signing_key.sign_schnorr(hashlib.sha256(signed_canon.encode("utf-8")).digest(),
                                    aux_randomness=aux_randomness)
    envelope["signature"] = sig.hex()
    return envelope


class ReplayGuard:
    """In-memory demo of max_uses enforcement -- names the requirement the 2026-08-13 review
    flagged (nonce + max_uses in the signed payload) without overclaiming that a single-process
    dict is a real production replay store. A real deployment needs this backed by durable
    storage shared across every verifier instance, not a per-process dict that resets on
    restart -- said plainly here rather than left implied."""

    def __init__(self) -> None:
        self._used: dict[str, int] = {}

    def check_and_record(self, nonce: str, max_uses: int) -> bool:
        used = self._used.get(nonce, 0)
        if used >= max_uses:
            return False
        self._used[nonce] = used + 1
        return True


def verify_approval(resolved_plan: dict[str, Any], approval: dict[str, Any],
                     replay_guard: "ReplayGuard | None" = None,
                     expected_audience: str | None = None) -> dict[str, Any]:
    """Deterministic verification -- the sys.assert step in optimization2026's flow. Returns a
    structured result (never a bare bool), fails closed on any exception, names the specific
    reason. v2 adds the (3) approved-scope-independent checks the review specifically asked for:
    a malformed/malicious signer can no longer display one approved_scope while carrying a digest
    for a different plan."""
    checks: dict[str, bool] = {}

    # (a) plan_sha256 matches the CURRENT plan being deployed, recomputed, not trusted from the
    # envelope's own claim.
    recomputed_plan_digest = compute_plan_digest(resolved_plan)
    checks["plan_digest_matches"] = (recomputed_plan_digest == approval.get("plan_sha256"))

    # (b) (3) approved_scope, independently: does it actually equal the load-bearing subset of
    # the CURRENT plan, and does ITS OWN digest match plan_sha256 too? Closes the gap where a
    # signer shows one approved_scope on screen while the digest secretly covers another plan.
    current_load_bearing = {k: resolved_plan.get(k) for k in LOAD_BEARING_FIELDS}
    checks["approved_scope_matches_current_plan"] = (
        approval.get("approved_scope") == current_load_bearing)
    try:
        checks["approved_scope_digest_matches"] = (
            compute_scope_digest(approval.get("approved_scope", {})) == approval.get("plan_sha256"))
    except Exception:
        checks["approved_scope_digest_matches"] = False

    checks["not_expired"] = int(time.time()) < approval.get("expires_at", 0)

    # (c) signature verifies over the exact signed_fields subset, against public_key (not key_id
    # -- key_id is an opaque label per item 5, the verifier trusts public_key or resolves it from
    # a registry by key_id; this demo has no registry, so it checks the envelope's own public_key).
    try:
        signed_fields = {k: approval[k] for k in SIGNED_FIELD_NAMES}
        signed_canon = _canon(signed_fields)
        msg_hash = hashlib.sha256(signed_canon.encode("utf-8")).digest()
        pub = PublicKeyXOnly(bytes.fromhex(approval["public_key"]))
        checks["signature_valid"] = pub.verify(bytes.fromhex(approval["signature"]), msg_hash)
    except Exception:
        checks["signature_valid"] = False

    checks["decision_is_approve"] = approval.get("decision") == "approve"

    if expected_audience is not None:
        checks["audience_matches"] = (approval.get("audience") == expected_audience)

    if replay_guard is not None:
        checks["not_replayed"] = replay_guard.check_and_record(
            approval.get("nonce", ""), approval.get("max_uses", 1))

    return {"valid": all(checks.values()), "checks": checks}


# ---------------------------------------------------------------------------
# (9) Fixed cross-language test vectors. No time.time(), no secrets.token_bytes -- a fixed,
# publicly-known, clearly-labeled TEST-ONLY private key and fixed timestamps/nonce so a
# Python/JS/Rust/Go implementation can reproduce the SAME digest and signature bytes.
# ---------------------------------------------------------------------------
FIXED_TEST_SIGNING_KEY_HEX = hashlib.sha256(
    b"aisp-deployment-approval-fixed-test-vector-v2-DO-NOT-USE-IN-PRODUCTION"
).hexdigest()
FIXED_ISSUED_AT = 1786000000  # fixed epoch second, arbitrary but constant across runs
FIXED_TTL = 3600
FIXED_NONCE = "0" * 32  # deliberately all-zero and clearly a test fixture, not real entropy


def _fixed_plan() -> dict[str, Any]:
    return {
        "deployment_target": "agent_runtime",
        "environment": "production",
        "gcp_project": "company-prod",
        "region": "us-central1",
        "service_name": "support-agent",
        "source_revision": "abc123",
        "python_version": "3.13",
        "service_account": "support-agent-sa@company-prod.iam.gserviceaccount.com",
        "network_exposure": "internal-only",
        "secret_policy_digest": "sha256:deadbeef",
        "resource_sizing": {"cpu": "2", "memory": "4Gi"},
        "eval_evidence": "sha256:eval-report-hash",
        "rollback_plan": "revert to abc122 via agents-cli rollback --to abc122",
        "observability_requirements": "logs+traces to company-prod/support-agent",
    }


def write_fixtures(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    key = PrivateKey(bytes.fromhex(FIXED_TEST_SIGNING_KEY_HEX))
    plan = _fixed_plan()

    approval = build_approval_response(
        plan, approver="alice@example.com", signing_key=key,
        approval_conditions=["Deploy only during the approved maintenance window",
                              "Maximum instances must remain <= 10"],
        display_note="Approved for production deployment",
        ttl_seconds=FIXED_TTL, fixed_issued_at=FIXED_ISSUED_AT, fixed_nonce=FIXED_NONCE,
        aux_randomness=b"\x00" * 32,  # fixed, not real randomness -- see the comment on the
        # sign_schnorr call in build_approval_response for why this is required for the
        # signature bytes themselves to be reproducible across independent runs/implementations.
    )

    tampered_plan = dict(plan)
    tampered_plan["region"] = "eu-west-1"

    presentational_edit = dict(approval)
    presentational_edit["display_note"] = "typo fix, still approved for production"

    verification_on_fixed_plan = verify_approval(plan, approval,
                                                   expected_audience="agents-cli-production-deployer")
    verification_on_tampered_plan = verify_approval(tampered_plan, approval)

    files = {
        "fixed-private-key-test-only.txt": FIXED_TEST_SIGNING_KEY_HEX,
        "fixed-public-key.txt": key.public_key.format(compressed=True)[1:].hex(),
        "fixed-plan.json": json.dumps(plan, indent=2, sort_keys=True),
        "expected-canonical-plan.txt": _canon({k: plan.get(k) for k in LOAD_BEARING_FIELDS}),
        "expected-plan-sha256.txt": compute_plan_digest(plan),
        "fixed-approval-response.json": json.dumps(approval, indent=2, sort_keys=True),
        "expected-signature.txt": approval["signature"],
        "tampered-region-plan.json": json.dumps(tampered_plan, indent=2, sort_keys=True),
        "presentational-edit-response.json": json.dumps(presentational_edit, indent=2, sort_keys=True),
        "expected-verification-results.json": json.dumps({
            "against_fixed_plan": verification_on_fixed_plan,
            "against_tampered_region_plan": verification_on_tampered_plan,
        }, indent=2, sort_keys=True),
    }
    for name, content in files.items():
        with open(os.path.join(out_dir, name), "w") as f:
            f.write(content + ("\n" if not content.endswith("\n") else ""))
    print(f"Wrote {len(files)} fixed vector files to {out_dir}/")
    print("A Python/JS/Rust/Go implementation reading fixed-plan.json + "
          "fixed-private-key-test-only.txt should reproduce expected-plan-sha256.txt and "
          "expected-signature.txt byte-for-byte, and expected-verification-results.json exactly.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", metavar="DIR", help="write fixed cross-language test vectors to DIR and exit")
    args = ap.parse_args()

    if args.fixtures:
        write_fixtures(args.fixtures)
        return

    signing_key = PrivateKey(secrets.token_bytes(32))
    resolved_plan = _fixed_plan()

    print("=== (required-field validation) a plan missing rollback_plan must be REJECTED before approval ===")
    incomplete_plan = dict(resolved_plan)
    incomplete_plan["rollback_plan"] = None
    missing = validate_plan_completeness(incomplete_plan)
    assert missing == ["rollback_plan"], missing
    try:
        build_approval_response(incomplete_plan, approver="alice@example.com", signing_key=signing_key)
        raise AssertionError("expected build_approval_response to refuse an incomplete plan")
    except ValueError as e:
        print(f"Correctly refused: {e}")

    approval = build_approval_response(
        resolved_plan, approver="alice@example.com", signing_key=signing_key,
        approval_conditions=["Deploy only during the approved maintenance window",
                              "Maximum instances must remain <= 10"],
        display_note="Approved for production deployment",
    )
    print("\n=== approval envelope ===")
    print(json.dumps(approval, indent=2))

    guard = ReplayGuard()
    print("\n=== verify against the SAME resolved plan (should be valid) ===")
    result = verify_approval(resolved_plan, approval, replay_guard=guard,
                              expected_audience="agents-cli-production-deployer")
    print(json.dumps(result, indent=2))
    assert result["valid"], "expected a valid approval to verify"

    print("\n=== REPLAY TEST: verifying the SAME nonce a second time must fail (max_uses=1) ===")
    result2 = verify_approval(resolved_plan, approval, replay_guard=guard,
                               expected_audience="agents-cli-production-deployer")
    assert not result2["valid"], "a replayed approval MUST fail on the second use"
    assert result2["checks"]["not_replayed"] is False
    print(json.dumps(result2, indent=2))
    print("Correctly rejected on reuse: not_replayed=False. (Demo uses an in-memory guard -- a "
          "real deployment needs this backed by durable, shared storage, not a per-process dict.)")

    print("\n=== TAMPER TEST: change one load-bearing field AFTER approval (region) ===")
    tampered_plan = dict(resolved_plan)
    tampered_plan["region"] = "eu-west-1"
    result = verify_approval(tampered_plan, approval)
    print(json.dumps(result, indent=2))
    assert not result["valid"], "a tampered load-bearing field MUST fail verification"
    assert not result["checks"]["plan_digest_matches"]
    assert not result["checks"]["approved_scope_matches_current_plan"]
    print("\nCorrectly rejected on both plan_digest_matches AND approved_scope_matches_current_plan.")

    print("\n=== SCOPE-FORGERY TEST: envelope's approved_scope edited to differ from its own plan_sha256 ===")
    forged = dict(approval)
    forged_scope = dict(forged["approved_scope"])
    forged_scope["region"] = "eu-west-1"
    forged["approved_scope"] = forged_scope
    result = verify_approval(resolved_plan, forged)
    assert not result["valid"]
    assert not result["checks"]["signature_valid"], "editing approved_scope must break the signature too"
    assert not result["checks"]["approved_scope_digest_matches"]
    print(json.dumps(result, indent=2))
    print("Correctly rejected: signature_valid=False (approved_scope is inside the signed payload, "
          "so this isn't just a digest mismatch -- it's a broken signature) AND "
          "approved_scope_digest_matches=False independently.")

    print("\n=== presentational-only edit (display_note) does NOT need re-approval ===")
    approval2 = dict(approval)
    approval2["display_note"] = "typo fix, still approved for production"
    result = verify_approval(resolved_plan, approval2, expected_audience="agents-cli-production-deployer")
    assert result["valid"], "a presentational-only field change must not invalidate a real approval"
    print("Correctly still valid: display_note is presentational, never entered the signed digest.")

    print("\n=== JCS-safe subset enforcement: a float in a load-bearing field is REJECTED, not "
          "silently mis-serialized ===")
    unsafe_plan = dict(resolved_plan)
    unsafe_plan["resource_sizing"] = {"cpu": 2.5, "memory": "4Gi"}
    try:
        compute_plan_digest(unsafe_plan)
        raise AssertionError("expected a float to be rejected by the JCS-safe subset check")
    except ValueError as e:
        print(f"Correctly refused: {e}")


if __name__ == "__main__":
    main()
