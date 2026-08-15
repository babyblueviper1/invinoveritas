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

`--supplements` is split into two categories:

  * policy / evidence (`environment`, `eval_evidence`, `rollback_plan`,
    `observability_requirements`, `python_version`) — may come from outside
    agents-cli and may fill honestly-absent fields.
  * execution inputs (`gcp_project`, `service_account`, `source_revision`,
    `resource_sizing`, `network_exposure`, and the other
    `EXECUTION_RELEVANT_FIELDS`) — must come from CLI flags / manifest so
    they can bind to `agents-cli deploy`. They are refused as supplements.

Deploy-time bind
----------------
A native `agents-cli deploy --plan-json` does not exist. This adapter's
substitute: take the already-approved plan, re-resolve a *fresh* plan from
the live flags/manifest immediately before deploy, and compare every
execution-relevant field. Any divergence refuses the deploy (fail closed).
That is "resolve effective plan -> approve that plan -> deploy consumes
the same resolved values", prototyped locally. Approving a projection
and then running a different flag set is the gap this closes.
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


_ABSENT = object()


class PlanDivergenceError(ValueError):
    """Approved plan and live re-resolve disagree on an execution-relevant field."""

    def __init__(self, report: dict[str, Any]):
        self.report = report
        fields = [d["field"] for d in report.get("divergences", [])]
        super().__init__(
            "deploy refused: approved plan diverges from a fresh re-resolve "
            f"on execution-relevant field(s) {fields}. "
            "The approval digest does not bind to what would execute."
        )


def merge_supplements(
    result: resolver.ResolveResult,
    supplements: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return plan + out-of-band fills for honestly-absent *policy/evidence* fields.

    Execution-input keys are refused even when currently absent: they must
    arrive via CLI flags / manifest so a deploy-time re-resolve can see them.
    """
    plan = dict(result.plan)
    if not supplements:
        return plan
    execution = [
        k for k in supplements
        if k in resolver.EXECUTION_INPUT_SUPPLEMENT_FIELDS
    ]
    if execution:
        raise ValueError(
            f"--supplements tried to set execution-input field(s) {execution}. "
            "Those must come from CLI flags or the manifest so they flow into "
            "the deploy invocation, not just the approval record. "
            f"Policy/evidence supplements allowed: "
            f"{list(resolver.POLICY_EVIDENCE_SUPPLEMENT_FIELDS)}."
        )
    illegal = [k for k in supplements if k not in result.absent_fields]
    if illegal:
        sources = {k: result.coverage.get(k) for k in illegal}
        raise ValueError(
            f"--supplements tried to set {illegal}, but those fields already "
            f"have a real agents-cli source in this resolution (sources: {sources}). "
            f"Policy/evidence supplements may only fill absent_fields="
            f"{[f for f in result.absent_fields if f in resolver.POLICY_EVIDENCE_SUPPLEMENT_FIELDS]}."
        )
    unknown = [k for k in supplements if k not in dae.LOAD_BEARING_FIELDS]
    if unknown:
        raise ValueError(
            f"--supplements contains non-load-bearing keys {unknown}; "
            f"allowed policy/evidence fields are "
            f"{list(resolver.POLICY_EVIDENCE_SUPPLEMENT_FIELDS)}"
        )
    not_policy = [
        k for k in supplements
        if k not in resolver.POLICY_EVIDENCE_SUPPLEMENT_FIELDS
    ]
    if not_policy:
        raise ValueError(
            f"--supplements keys {not_policy} are not policy/evidence fields. "
            f"Allowed: {list(resolver.POLICY_EVIDENCE_SUPPLEMENT_FIELDS)}."
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


def _field_slice(plan: dict[str, Any]) -> dict[str, Any]:
    """Execution-relevant subset. Missing keys stay missing (not fabricated null)."""
    return {
        name: plan[name]
        for name in resolver.EXECUTION_RELEVANT_FIELDS
        if name in plan
    }


def compare_execution_fields(
    approved_plan: dict[str, Any],
    live_plan: dict[str, Any],
) -> list[dict[str, Any]]:
    """Field-by-field diffs on EXECUTION_RELEVANT_FIELDS, including both-absent."""
    diffs: list[dict[str, Any]] = []
    for name in resolver.EXECUTION_RELEVANT_FIELDS:
        approved_val = approved_plan[name] if name in approved_plan else _ABSENT
        live_val = live_plan[name] if name in live_plan else _ABSENT
        if approved_val != live_val:
            diffs.append({
                "field": name,
                "approved": None if approved_val is _ABSENT else approved_val,
                "approved_present": approved_val is not _ABSENT,
                "live": None if live_val is _ABSENT else live_val,
                "live_present": live_val is not _ABSENT,
            })
    return diffs


def check_deploy_binding(
    approved_plan: dict[str, Any],
    flags: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    *,
    defaults_mode: str = "create",
) -> dict[str, Any]:
    """Re-resolve live flags+manifest and compare to the already-approved plan.

    Does not apply supplements: execution inputs must come from flags/manifest,
    and policy/evidence fields are not in the comparison set.
    `bound` is True only when every execution-relevant field matches.
    """
    fresh = resolver.resolve_agents_cli_plan(
        flags, manifest, defaults_mode=defaults_mode
    )
    diffs = compare_execution_fields(approved_plan, fresh.plan)
    return {
        "bound": not diffs,
        "execution_relevant_fields": list(resolver.EXECUTION_RELEVANT_FIELDS),
        "divergences": diffs,
        "approved_execution_slice": _field_slice(approved_plan),
        "live_execution_slice": _field_slice(fresh.plan),
        "live_unmapped_cli_flags_present": fresh.unmapped_cli_flags_present,
    }


def assert_deploy_bound(
    approved_plan: dict[str, Any],
    flags: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    *,
    defaults_mode: str = "create",
) -> dict[str, Any]:
    """Fail closed: raise PlanDivergenceError unless the live re-resolve binds."""
    report = check_deploy_binding(
        approved_plan, flags, manifest, defaults_mode=defaults_mode
    )
    if not report["bound"]:
        raise PlanDivergenceError(report)
    return report


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


def _cmd_deploy_check(args: argparse.Namespace) -> int:
    """Fail closed unless the live re-resolve binds to the approved plan."""
    approved = _load_json(args.plan)
    flags = _load_json(args.flags) if args.flags else {}
    manifest = _load_manifest(args.manifest)
    report = check_deploy_binding(
        approved, flags, manifest, defaults_mode=args.defaults_mode
    )
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0 if report.get("bound") else 2


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

    print("\n=== execution-input supplements are refused (service_account) ===")
    try:
        merge_supplements(result, {
            "service_account": "other-sa@company-prod.iam.gserviceaccount.com",
        })
        raise AssertionError("expected execution-input supplement to fail")
    except ValueError as exc:
        print(f"Correctly refused: {exc}")

    print("\n=== deploy-time bind: live flags still match the approved plan ===")
    bind_ok = check_deploy_binding(plan, flags, None, defaults_mode="create")
    print(json.dumps({k: bind_ok[k] for k in (
        "bound", "divergences", "approved_execution_slice", "live_execution_slice",
    )}, indent=2, sort_keys=True))
    assert bind_ok["bound"], bind_ok
    assert_deploy_bound(plan, flags, None, defaults_mode="create")

    print("\n=== deploy-time bind: service_account drifted A -> B, refuse ===")
    drifted = dict(flags)
    drifted["--service-account"] = "other-sa@company-prod.iam.gserviceaccount.com"
    bind_bad = check_deploy_binding(plan, drifted, None, defaults_mode="create")
    print(json.dumps(bind_bad["divergences"], indent=2, sort_keys=True))
    assert not bind_bad["bound"], bind_bad
    sa_diff = next(d for d in bind_bad["divergences"] if d["field"] == "service_account")
    assert sa_diff["approved"] == flags["--service-account"]
    assert sa_diff["live"] == drifted["--service-account"]
    try:
        assert_deploy_bound(plan, drifted, None, defaults_mode="create")
        raise AssertionError("expected drifted service_account to refuse deploy")
    except PlanDivergenceError as exc:
        print(f"Correctly refused: {exc}")

    print("\n=== composition OK: resolver -> policy-supplements-only -> "
          "build_approval_response -> verify_approval (pass + tamper fail) -> "
          "deploy-bind (pass + service_account drift refuse) ===")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Resolve an agents-cli plan and/or verify a signed approval."
    )
    sub = ap.add_subparsers(dest="cmd")

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--flags", help="JSON object of cmd_deploy.py-style flags")
        p.add_argument("--manifest", help="Path to agents-cli-manifest.yaml or .json")
        p.add_argument(
            "--supplements",
            help="JSON object filling honestly-absent *policy/evidence* fields only "
                 "(environment, eval_evidence, rollback_plan, observability_requirements, "
                 "python_version). Execution inputs are refused.",
        )
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

    p_bind = sub.add_parser(
        "deploy-check",
        help="re-resolve live flags/manifest and refuse if they diverge "
             "from the already-approved plan on any execution-relevant field",
    )
    p_bind.add_argument("--plan", required=True, help="already-approved plan JSON")
    p_bind.add_argument("--flags", help="JSON object of current cmd_deploy.py-style flags")
    p_bind.add_argument("--manifest", help="Path to current agents-cli-manifest.yaml or .json")
    p_bind.add_argument(
        "--defaults-mode",
        choices=("create", "explicit_only"),
        default="create",
    )

    ap.add_argument("--demo", action="store_true",
                    help="run the composition: resolve, refuse-incomplete, "
                         "supplement, build, verify, tamper, deploy-bind")

    args = ap.parse_args()
    if args.demo or args.cmd is None:
        return _demo()
    if args.cmd == "resolve":
        return _cmd_resolve(args)
    if args.cmd == "verify":
        return _cmd_verify(args)
    if args.cmd == "build":
        return _cmd_build(args)
    if args.cmd == "deploy-check":
        return _cmd_deploy_check(args)
    ap.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
