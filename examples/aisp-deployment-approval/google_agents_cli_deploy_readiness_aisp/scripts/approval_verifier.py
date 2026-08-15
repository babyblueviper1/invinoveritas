#!/usr/bin/env python3
"""Thin AISOP-facing wrapper: resolve a real agents-cli plan, then verify approval.

Composes — does not duplicate — the already-tested functions in
`deployment_approval_example.py` (`compute_plan_digest`, `build_approval_response`,
`verify_approval`, `validate_plan_completeness`) and the new
`resolve_agents_cli_plan.py`.

This script is the `approval.verify` Runtime tool optimization2026 named on
google/agents-cli#48. It is not itself the human channel (`sys.io.confirm`
already exists in SoulBot). It receives the current effective plan plus the
raw approval payload and returns the structured verification result that
`sys.assert` consumes.

Supplements
-----------
Several LOAD_BEARING_FIELDS have no agents-cli source (`rollback_plan`,
`eval_evidence`, `python_version`, `environment`, `observability_requirements`,
and `source_revision` when `--image` was not passed). The resolver leaves
those absent. `validate_plan_completeness` / `build_approval_response` will
refuse a production approval that is missing `rollback_plan` or
`source_revision`.

`--supplements` exists so a human or a policy layer can supply those
honestly-absent fields out of band. It is an error to use supplements to
override a field the resolver *did* map — that would paper over a real
agents-cli value. Only keys in `result.absent_fields` are accepted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 2026-08-15 (optimization2026's real packaging critique on google/agents-cli#48):
# this package used to reach OUTSIDE the Skill Folder for these two modules
# (examples/aisp-deployment-approval/, the parent of this skill), which breaks
# self-containment the moment the folder is copied/hashed/zipped/registered on its
# own -- exactly the failure mode a portable AISP package must not have. Both
# modules are now local copies inside this Skill Folder's own scripts/ dir; the
# outer examples/aisp-deployment-approval/ copies remain as the standalone
# generator/demo they always were, kept in sync by hand (no runtime dependency
# between the two anymore).
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import deployment_approval_example as dae  # noqa: E402
import resolve_agents_cli_plan as resolver  # noqa: E402


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_manifest(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    return resolver.load_manifest(path)


def merge_supplements(
    result: resolver.ResolveResult,
    supplements: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return plan + out-of-band fills for honestly-absent fields only."""
    plan = dict(result.plan)
    if not supplements:
        return plan
    illegal = [k for k in supplements if k not in result.absent_fields]
    if illegal:
        sources = {k: result.coverage.get(k) for k in illegal}
        raise ValueError(
            f"--supplements tried to set {illegal}, but those fields already "
            f"have a real agents-cli source in this resolution (sources: {sources}). "
            f"Supplements may only fill absent_fields={result.absent_fields}."
        )
    unknown = [k for k in supplements if k not in dae.LOAD_BEARING_FIELDS]
    if unknown:
        raise ValueError(
            f"--supplements contains non-load-bearing keys {unknown}; "
            f"allowed absent fields are {result.absent_fields}"
        )
    plan.update(supplements)
    return plan


def resolve_from_inputs(
    flags: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    *,
    defaults_mode: str = "create",
    supplements: dict[str, Any] | None = None,
) -> tuple[resolver.ResolveResult, dict[str, Any]]:
    result = resolver.resolve_agents_cli_plan(
        flags, manifest, defaults_mode=defaults_mode
    )
    plan = merge_supplements(result, supplements)
    return result, plan


def verify_payload(
    plan: dict[str, Any],
    approval: dict[str, Any],
    *,
    expected_audience: str | None = "agents-cli-production-deployer",
) -> dict[str, Any]:
    """Deterministic verification — the sys.assert input. Never a bare bool."""
    return dae.verify_approval(plan, approval, expected_audience=expected_audience)


def _cmd_resolve(args: argparse.Namespace) -> int:
    flags = _load_json(args.flags) if args.flags else {}
    manifest = _load_manifest(args.manifest)
    supplements = _load_json(args.supplements) if args.supplements else None
    result, plan = resolve_from_inputs(
        flags, manifest, defaults_mode=args.defaults_mode, supplements=supplements
    )
    missing = dae.validate_plan_completeness(plan)
    out = result.to_dict()
    out["plan_after_supplements"] = plan
    out["production_completeness_missing"] = missing
    json.dump(out, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    flags = _load_json(args.flags) if args.flags else {}
    manifest = _load_manifest(args.manifest)
    supplements = _load_json(args.supplements) if args.supplements else None
    approval = _load_json(args.approval)
    _result, plan = resolve_from_inputs(
        flags, manifest, defaults_mode=args.defaults_mode, supplements=supplements
    )
    if args.plan:
        # Optional: verify against an already-resolved plan file instead.
        plan = _load_json(args.plan)
    report = verify_payload(plan, approval)
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report.get("valid") else 2


def _cmd_build(args: argparse.Namespace) -> int:
    """Demo-only envelope construction. A real host uses a secure signer."""
    flags = _load_json(args.flags) if args.flags else {}
    manifest = _load_manifest(args.manifest)
    supplements = _load_json(args.supplements) if args.supplements else None
    _result, plan = resolve_from_inputs(
        flags, manifest, defaults_mode=args.defaults_mode, supplements=supplements
    )
    key_hex = args.signing_key_hex or dae.FIXED_TEST_SIGNING_KEY_HEX
    key = dae.PrivateKey(bytes.fromhex(key_hex))
    approval = dae.build_approval_response(
        plan,
        approver=args.approver,
        signing_key=key,
        approval_conditions=args.condition or [],
        display_note=args.display_note,
        ttl_seconds=args.ttl,
        fixed_issued_at=dae.FIXED_ISSUED_AT if args.fixed else None,
        fixed_nonce=dae.FIXED_NONCE if args.fixed else None,
        aux_randomness=(b"\x00" * 32) if args.fixed else b"",
    )
    json.dump(approval, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def _demo() -> int:
    """End-to-end composition against a resolved plan: build, verify, tamper."""
    flags = {
        "--deployment-target": "cloud_run",
        "--project": "company-prod",
        "--region": "us-central1",
        "--service-name": "support-agent",
        "--service-account": "support-agent-sa@company-prod.iam.gserviceaccount.com",
        "--image": "us-central1-docker.pkg.dev/company-prod/support-agent/support-agent:abc123",
        "--cpu": "2",
        "--memory": "4Gi",
        "--secrets": "API_KEY=support-agent-api-key",
        "--iap": True,
    }
    result, raw_plan = resolve_from_inputs(flags, None, defaults_mode="create")

    print("=== resolved plan (agents-cli sources only) ===")
    print(json.dumps(result.plan, indent=2, sort_keys=True))
    print(f"absent_fields: {result.absent_fields}")

    missing_before = dae.validate_plan_completeness(raw_plan)
    print("\n=== production completeness on the raw resolved plan ===")
    print(f"missing required fields: {missing_before}")
    assert "rollback_plan" in missing_before, missing_before
    try:
        dae.build_approval_response(
            raw_plan, approver="alice@example.com",
            signing_key=dae.PrivateKey(bytes.fromhex(dae.FIXED_TEST_SIGNING_KEY_HEX)),
        )
        raise AssertionError("expected raw resolved plan to be refused")
    except ValueError as exc:
        print(f"Correctly refused: {exc}")

    # Out-of-band fills for fields agents-cli genuinely does not have.
    # These are labeled as supplements, not pretended to come from the CLI.
    supplements = {
        "environment": "production",
        "python_version": "3.13",
        "eval_evidence": "sha256:eval-report-hash",
        "rollback_plan": (
            "gcloud run services update-traffic support-agent "
            "--to-revisions=support-agent-00001-abc=100 --region=us-central1"
        ),
        "observability_requirements": "logs+traces to company-prod/support-agent",
    }
    plan = merge_supplements(result, supplements)
    print("\n=== plan after honest supplements (absent fields only) ===")
    print(json.dumps(plan, indent=2, sort_keys=True))
    assert dae.validate_plan_completeness(plan) == []

    key = dae.PrivateKey(bytes.fromhex(dae.FIXED_TEST_SIGNING_KEY_HEX))
    # Live issuance (time.time() / fresh nonce / real aux rand). The v2 fixture
    # timestamps (FIXED_ISSUED_AT=1786000000) expire an hour later and are
    # only for byte-reproducible vectors, not a live verify.
    approval = dae.build_approval_response(
        plan,
        approver="alice@example.com",
        signing_key=key,
        approval_conditions=["Deploy only during the approved maintenance window"],
        display_note="Approved for production deployment",
        ttl_seconds=3600,
    )
    print("\n=== verify against the SAME resolved+supplemented plan ===")
    ok = verify_payload(plan, approval)
    print(json.dumps(ok, indent=2, sort_keys=True))
    assert ok["valid"], ok

    print("\n=== TAMPER: change region after approval ===")
    tampered = dict(plan)
    tampered["region"] = "europe-west1"
    bad = verify_payload(tampered, approval)
    print(json.dumps(bad, indent=2, sort_keys=True))
    assert not bad["valid"]
    assert not bad["checks"]["plan_digest_matches"]
    assert not bad["checks"]["approved_scope_matches_current_plan"]
    print("Correctly rejected on plan_digest_matches AND approved_scope_matches_current_plan.")

    print("\n=== supplements cannot override a mapped field (region) ===")
    try:
        merge_supplements(result, {"region": "europe-west1"})
        raise AssertionError("expected supplement-override of a mapped field to fail")
    except ValueError as exc:
        print(f"Correctly refused: {exc}")

    print("\n=== composition OK: resolver -> supplements-for-absent-only -> "
          "build_approval_response -> verify_approval (pass + tamper fail) ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Resolve an agents-cli plan and/or verify a signed approval."
    )
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--flags", help="JSON object of cmd_deploy.py-style flags")
        p.add_argument("--manifest", help="Path to agents-cli-manifest.yaml or .json")
        p.add_argument("--supplements", help="JSON object filling honestly-absent fields only")
        p.add_argument(
            "--defaults-mode",
            choices=("create", "explicit_only"),
            default="create",
        )

    p_resolve = sub.add_parser("resolve", help="print the resolved plan + coverage")
    add_common(p_resolve)

    p_verify = sub.add_parser("verify", help="verify an approval envelope against the plan")
    add_common(p_verify)
    p_verify.add_argument("--approval", required=True, help="JSON approval envelope")
    p_verify.add_argument("--plan", help="optional already-resolved plan JSON (skips resolve)")

    p_build = sub.add_parser(
        "build",
        help="DEMO ONLY: build a signed envelope (real hosts use a secure signer)",
    )
    add_common(p_build)
    p_build.add_argument("--approver", default="alice@example.com")
    p_build.add_argument("--signing-key-hex", default=None,
                         help="32-byte hex key; default is the TEST-ONLY fixture key")
    p_build.add_argument("--condition", action="append",
                         help="signed approval_conditions entry (repeatable)")
    p_build.add_argument("--display-note", default="")
    p_build.add_argument("--ttl", type=int, default=3600)
    p_build.add_argument("--fixed", action="store_true",
                         help="use the v2 fixture timestamps/nonce/aux_rand")

    ap.add_argument("--demo", action="store_true",
                    help="run the composition: resolve, refuse-incomplete, "
                         "supplement, build, verify, tamper")

    args = ap.parse_args()
    if args.demo or args.cmd is None:
        return _demo()
    if args.cmd == "resolve":
        return _cmd_resolve(args)
    if args.cmd == "verify":
        return _cmd_verify(args)
    if args.cmd == "build":
        return _cmd_build(args)
    ap.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
